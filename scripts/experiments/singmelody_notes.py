"""Test released SingMelody weights with the structurally matching public GAME code.

This is an experimental reconstruction, not the unavailable SingMelody runner.
The model card specifies a single pass but omits its constant t and decoding
settings. Predeclare t=0 and t=1, free/predicted-word boundaries, and GAME's CLI
decoding defaults; never select them from a reference chart. No gold input exists.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np
import soundfile as sf
import yaml

from melody_compare import transform
from timing_predict import parse
from timing_neural import lyric_words


MODEL_REVISION = "c0ba47cf22a1fe4de9b3d8e480415a9e53c67869"
GAME_REVISION = "69ba01ded0ddda5495e51ba373685f1be1a67ea2"
FILES = {
    "model.ckpt": "8553ef3bdac2ee0b27ab427c1f727fea62dcbb58c528562c6cab8ec4a389ff53",
    "config.yaml": "fd08c314d9436aff350b807db8d22cbf424732be4a04a66553102c1c926af2e1",
    "lang_map.json": "612e6bd14e3c0d9c1cfc368143a83ac8717fe4f80f0c04b9d64b918b579dad7a",
}
ARMS = {"free-t0": ("free", 0.0), "words-t0": ("words", 0.0),
        "free-t1": ("free", 1.0), "words-t1": ("words", 1.0)}
BOUNDARY_THRESHOLD = 0.2
BOUNDARY_RADIUS = 2  # GAME CLI default: 20 ms at the checkpoint's 10 ms hop.
PRESENCE_THRESHOLD = 0.2


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def load_model(args):
    import torch

    for name, expected in FILES.items():
        if digest(args.model_dir / name) != expected:
            raise ValueError(f"Unexpected SingMelody file: {name}")
    revision = subprocess.check_output(
        ["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True
    ).strip()
    changes = subprocess.check_output(
        ["git", "-C", str(args.source), "diff", "--name-only", "HEAD"], text=True
    ).strip()
    if revision != GAME_REVISION or changes:
        raise ValueError("GAME must match its unmodified pinned revision")
    sys.path.insert(0, str(args.source.resolve()))
    from lib.config.schema import ModelConfig, InferenceConfig
    from inference.me_infer import SegmentationEstimationInferenceModel

    config = yaml.safe_load((args.model_dir / "config.yaml").read_text())
    remap = {}
    for section in ("encoder", "segmenter", "estimator"):
        original = config["model"][section]["cls"]
        replacement = original.replace("singmelody.game.upstream._modules.", "modules.")
        if original == replacement:
            raise ValueError("Unexpected SingMelody namespace")
        remap[original] = replacement
        config["model"][section]["cls"] = replacement
    model_config = ModelConfig.model_validate(config["model"])
    inference_config = InferenceConfig.model_validate(config["inference"])
    if inference_config.features.audio_sample_rate != 44100 or inference_config.features.hop_size != 441:
        raise ValueError("Unexpected feature clock")
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    model = SegmentationEstimationInferenceModel(model_config, inference_config).cpu().eval()
    checkpoint = torch.load(args.model_dir / "model.ckpt", map_location="cpu",
                            weights_only=True, mmap=True)
    # This strict check has been verified: 671 matching names and shapes. It
    # establishes structural compatibility, not the missing original settings.
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    del checkpoint
    language_map = json.loads((args.model_dir / "lang_map.json").read_text())
    versions = {name: importlib.metadata.version(name) for name in
                ("torch", "numpy", "librosa", "pydantic", "einops")}
    return model, language_map, remap, versions


def known_durations(words, mode, left, right):
    cuts = {0.0, right - left}
    if mode == "words":
        for word in words:
            for point in (word.start, word.end):
                if left < point < right:
                    cuts.add(point - left)
    points = sorted(cuts)
    return [b - a for a, b in zip(points, points[1:]) if b > a]


def stitch(chunks):
    """Use each event's core midpoint and reconcile only window seam overlaps."""
    result = []
    # The network's clock is 10 ms. Remove sub-microsecond float accumulation
    # before comparing windows, so touching equal-pitch reattacks cannot merge.
    normalized = [(round(a, 6), round(b, 6), pitch) for a, b, pitch in chunks]
    for start, end, pitch in sorted(normalized):
        if result and start < result[-1][1]:
            if pitch == result[-1][2]:
                result[-1][1] = max(result[-1][1], end)
                continue
            seam = (start + result[-1][1]) / 2
            if seam <= result[-1][0] or seam >= end:
                continue
            result[-1][1] = start = seam
        if end > start:
            result.append([start, end, pitch])
    return [[round(a, 6), round(b, 6), p] for a, b, p in result]


def infer(stem, words, language, model, arms, core, pad):
    import torch
    from modules.decoding import decode_soft_boundaries
    from modules.functional import format_boundaries, boundaries_to_regions, regions_to_durations

    chunks = {arm: [] for arm in arms}
    elapsed = {arm: 0.0 for arm in arms}
    encoder_seconds = 0.0
    with sf.SoundFile(stem) as stream, torch.inference_mode():
        rate, length = stream.samplerate, len(stream)
        if rate != 44100:
            raise ValueError("Frozen vocal stems must be 44100 Hz")
        duration = length / rate
        core_samples, context_samples = round(core * rate), round(pad * rate)
        for start in range(0, length, core_samples):
            end = min(length, start + core_samples)
            left, right = max(0, start - context_samples), min(length, end + context_samples)
            stream.seek(left)
            signal = stream.read(right - left, dtype="float32", always_2d=True).mean(axis=1)
            if not np.isfinite(signal).all():
                raise ValueError("Non-finite vocal samples")
            started = time.monotonic()
            waveform = torch.from_numpy(signal.copy())[None]
            window_duration = torch.tensor([(right - left) / rate], dtype=torch.float32)
            x_seg, x_est, mask = model.forward_encoder(waveform, window_duration)
            encoder_seconds += time.monotonic() - started
            if not torch.isfinite(x_seg).all() or not torch.isfinite(x_est).all():
                raise ValueError("Non-finite encoder outputs")
            for arm in arms:
                mode, constant_t = ARMS[arm]
                started = time.monotonic()
                lengths = known_durations(words, mode, left / rate, right / rate)
                known = format_boundaries(torch.tensor([lengths], dtype=torch.float32),
                                          x_seg.shape[1], model.timestep) & mask
                # Fixed word-tier mask; no D3PM sampling or random corruption.
                noise = boundaries_to_regions(known, mask=mask)
                logits, _ = model.model.forward_segmentation(
                    x_seg, noise=noise, t=torch.tensor([constant_t]),
                    language=torch.tensor([language]), mask=mask,
                )
                if not torch.isfinite(logits).all():
                    raise ValueError("Non-finite boundary logits")
                boundaries = decode_soft_boundaries(logits.sigmoid(), barriers=known, mask=mask,
                                                    threshold=BOUNDARY_THRESHOLD,
                                                    radius=BOUNDARY_RADIUS)
                regions = boundaries_to_regions(boundaries, mask=mask)
                max_notes = regions.max()
                frame_counts = regions_to_durations(regions, max_n=max_notes)
                presence, pitches = model.forward_estimator(
                    x_est, regions, mask, max_notes, torch.tensor(PRESENCE_THRESHOLD)
                )
                if not torch.isfinite(pitches).all() or not torch.isfinite(frame_counts).all():
                    raise ValueError("Non-finite note values")
                position_frame = 0
                for frames, sounding, pitch in zip(frame_counts[0].tolist(), presence[0].tolist(),
                                                   pitches[0].tolist(), strict=True):
                    position = left / rate + position_frame * model.timestep
                    stop = min(duration, left / rate + (position_frame + frames) * model.timestep)
                    midpoint = (position + stop) / 2
                    if sounding and 0 < pitch <= 127 and stop > position and start / rate <= midpoint < end / rate:
                        chunks[arm].append([max(0, position), stop, round(pitch)])
                    position_frame += frames
                elapsed[arm] += time.monotonic() - started
    # Shared encoder cost is recorded explicitly and apportioned for comparisons.
    elapsed = {name: round(value + encoder_seconds / len(arms), 3)
               for name, value in elapsed.items()}
    return {name: stitch(value) for name, value in chunks.items()}, duration, elapsed, encoder_seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model-dir", "source", "stems", "charts", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--core", type=float, default=12.0)
    parser.add_argument("--pad", type=float, default=1.5)
    parser.add_argument("--check-load", action="store_true")
    args = parser.parse_args()
    if args.threads < 1 or args.core <= 0 or args.pad < 0 or len(args.arms) != len(set(args.arms)):
        parser.error("Invalid threads, window duration or duplicate arm")
    model, language_map, namespace_remap, versions = load_model(args)
    if args.check_load:
        print(json.dumps({"strict_load": True, "tensors": len(model.state_dict()),
                          "languages": language_map, "versions": versions}))
        return
    stems, charts = (json.loads(p.read_text()) for p in (args.stems, args.charts))
    if set(stems) != set(charts) or not set(args.ids or []).issubset(stems):
        raise ValueError("Prediction and vocal cohorts differ")
    project = Path(__file__).resolve().parents[2]
    helper_paths = [Path(__file__).resolve(), Path(transform.__code__.co_filename).resolve(),
                    Path(parse.__code__.co_filename).resolve(),
                    Path(lyric_words.__code__.co_filename).resolve(),
                    *(project / "src/karaoke" / name for name in
                      ("generation_worker.py", "generation_metrics.py", "songs.py"))]
    helpers = {str(path.relative_to(project)): digest(path) for path in helper_paths}
    for tag in args.ids or sorted(stems):
        if Path(tag).name != tag or tag in (".", ".."):
            raise ValueError("Invalid song identity")
        stem, chart = Path(stems[tag]), Path(charts[tag])
        headers, rows = parse(chart)
        metadata = dict(line[1:].split(":", 1) for line in headers)
        language = metadata.get("LANGUAGE", "").lower()
        language = {"english": "en", "spanish": "es"}.get(language, language)
        if language not in language_map:
            raise ValueError(f"Unsupported language: {language}")
        words = lyric_words(rows)
        if not words:
            raise ValueError("Predicted chart contains no word intervals")
        base_provenance = dict(stem_sha256=digest(stem), baseline_sha256=digest(chart),
                               model_revision=MODEL_REVISION, model_files=FILES,
                               game_revision=GAME_REVISION, namespace_remap=namespace_remap,
                               implementation_hashes=helpers, versions=versions,
                               host=platform.platform(), machine=platform.machine(),
                               language=language, language_id=language_map[language],
                               word_intervals=[[w.start, w.end] for w in words],
                               reconstructed_runner=True, unknown_official_t=True)
        pending, settings_by_arm = [], {}
        for arm in args.arms:
            settings = dict(family="singmelody-" + arm, model_sha256=FILES["model.ckpt"],
                            source=str(stem), device="cpu", threads=args.threads,
                            core=args.core, pad=args.pad, mode=ARMS[arm][0], t=ARMS[arm][1],
                            boundary_threshold=BOUNDARY_THRESHOLD, boundary_radius=BOUNDARY_RADIUS,
                            presence_threshold=PRESENCE_THRESHOLD)
            settings_by_arm[arm] = settings
            destination = args.output / arm / "variants" / tag
            frozen_path = destination / "frozen.json"
            events_path = args.output / arm / "events" / (tag + ".json")
            if not frozen_path.exists():
                pending.append(arm)
                continue
            frozen = json.loads(frozen_path.read_text())
            previous = json.loads(events_path.read_text())
            if frozen["provenance"] != base_provenance or previous["settings"] != settings:
                raise ValueError(f"Incompatible cached SingMelody result: {tag}/{arm}")
            if digest(events_path) != frozen["events_sha256"] or any(
                digest(destination / (method + ".txt")) != sha
                for method, sha in frozen["charts"].items()
            ):
                raise ValueError(f"Frozen SingMelody result changed: {tag}/{arm}")
        if not pending:
            print(tag, "cached", flush=True)
            continue
        started = time.monotonic()
        events, duration, elapsed, encoder_seconds = infer(stem, words, language_map[language],
                                                         model, pending, args.core, args.pad)
        for arm in pending:
            destination = args.output / arm / "variants" / tag
            destination.mkdir(parents=True, exist_ok=True)
            events_path = args.output / arm / "events" / (tag + ".json")
            candidates = transform(chart, events[arm], duration)
            hashes = {}
            for method, text in candidates.items():
                path = destination / (method + ".txt")
                path.write_text(text, encoding="utf-8")
                hashes[method] = digest(path)
            write_json(events_path, dict(events=events[arm], settings=settings_by_arm[arm],
                       seconds=elapsed[arm], provenance={**base_provenance, "duration_s": duration,
                       "shared_encoder_seconds": round(encoder_seconds, 3),
                       "encoder_cost_divisor": len(pending)}))
            write_json(destination / "frozen.json", dict(provenance=base_provenance,
                       events_sha256=digest(events_path), baseline_sha256=base_provenance["baseline_sha256"],
                       charts=hashes, secondary_sha256=None, duration_s=duration, seconds=elapsed[arm]))
        print(tag, {arm: len(events[arm]) for arm in pending},
              round(time.monotonic() - started, 3), flush=True)
    for arm in args.arms:
        for method in ("pitch", "events"):
            mapping = {path.parent.name: str(path.resolve()) for path in
                       sorted((args.output / arm / "variants").glob("*/" + method + ".txt"))}
            write_json(args.output / arm / (method + "-charts.json"), mapping)


if __name__ == "__main__":
    main()
