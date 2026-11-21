"""Freeze phoneme-informed note boundaries with FCPE pitch, without reading gold charts.

Run CPU inference in bounded windows, join frame logits on the original clock, then
decode once. Existing FCPE contours are accepted only for the identical vocal WAV.
Output events and pitch/events charts follow melody_compare's frozen file format.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np
import soundfile as sf
import soxr

from melody_compare import transform
from timing_predict import parse, serialize


SOURCE_COMMIT = "b2fcd9ea0f7898a8989c7e65781052d1ffc81094"
MODEL_SHA = "e56d1c7438f10afb61bbfe54a856a0355d4556fca6038dc67567fe68930ade17"
FCPE_SHA = "09c5717de92ddd5e4efc5177104f973d205102b2b5596ba91eeb19711cb90d12"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def load_model(args):
    import torch

    if digest(args.model) != MODEL_SHA:
        raise ValueError("Unexpected phoneme checkpoint")
    revision = subprocess.check_output(
        ["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True
    ).strip()
    changed = subprocess.check_output(
        ["git", "-C", str(args.source), "diff", "--name-only", "HEAD"], text=True
    ).strip()
    if revision != SOURCE_COMMIT or changed:
        raise ValueError("Phoneme source must match the unmodified pinned revision")
    sys.path.insert(0, str(args.source.resolve()))
    from phn_ast.model import TranscriptionModel
    from phn_ast.decoding import FramewiseDecoder

    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    # The upstream release includes a plain config as well as tensor parameters.
    state = torch.load(args.model, map_location="cpu", weights_only=False)
    config = state["config"]
    if (config["sample_rate"], config["hop_length"]) != (16000, 320):
        raise ValueError("Unexpected phoneme inference clock")
    model = TranscriptionModel(config).cpu().eval()
    model.load_state_dict(state["model_state_dict"])
    source_hashes = {
        str(path.relative_to(args.source)): digest(path)
        for path in sorted((args.source / "phn_ast").glob("*.py"))
    }
    versions = {name: importlib.metadata.version(name) for name in
                ("torch", "torchaudio", "nnAudio", "wquantiles", "numpy", "librosa", "soxr")}
    return model, FramewiseDecoder(config), config, source_hashes, versions


def windows(path, core, pad, target_rate=16000):
    """Yield mono audio and core clocks without retaining a whole song in memory."""
    with sf.SoundFile(path) as stream:
        rate, length = stream.samplerate, len(stream)
        for start in range(0, length, core * rate):
            end = min(length, start + core * rate)
            left, right = max(0, start - pad * rate), min(length, end + pad * rate)
            stream.seek(left)
            signal = stream.read(right - left, dtype="float32", always_2d=True).mean(axis=1)
            if rate != target_rate:
                signal = soxr.resample(signal, rate, target_rate, quality="HQ")
            yield start / rate, end / rate, left / rate, signal


def infer_logits(path, model, core, pad):
    import torch

    step = 0.02
    duration = sf.info(path).duration
    count = math.ceil(duration / step - 1e-8)
    combined = np.empty((count, 3), dtype=np.float32)
    written = np.zeros(count, dtype=bool)
    with torch.inference_mode():
        for start, end, left, signal in windows(path, core, pad):
            logits = model(torch.from_numpy(signal.copy())[None]).cpu().numpy()[0]
            a = round(start / step)
            b = min(count, math.ceil(end / step - 1e-8))
            offset = round((start - left) / step)
            selected = logits[offset:offset + b - a]
            if selected.shape != (b - a, 3) or not np.isfinite(selected).all():
                raise ValueError("Incomplete or non-finite phoneme window")
            if written[a:b].any():
                raise ValueError("Phoneme windows duplicated a core frame")
            combined[a:b], written[a:b] = selected, True
    if not written.all():
        raise ValueError("Phoneme windows left a gap")
    return combined, duration


def fcpe_track(tag, stem, stem_sha, args):
    candidates = [args.output / "fcpe" / (tag + ".npz"),
                  args.fcpe_cache / tag / "observations.npz"]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        with np.load(candidate, allow_pickle=False) as values:
            if str(values["source_sha"]) == stem_sha and str(values["model_sha"]) == FCPE_SHA:
                return values["raw"].copy(), candidate, "cached-identical-vocal"
    if args.fcpe_model is None:
        raise ValueError(f"No identical-vocal FCPE cache for {tag}; supply --fcpe-model")
    import onnxruntime as ort

    if digest(args.fcpe_model) != FCPE_SHA:
        raise ValueError("Unexpected FCPE checkpoint")
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    net = ort.InferenceSession(str(args.fcpe_model), sess_options=options,
                              providers=["CPUExecutionProvider"])
    parts = []
    started = time.monotonic()
    for start, end, left, signal in windows(stem, args.core, args.pad):
        raw = net.run(["f0"], {"audio": signal[None]})[0][0]
        offset = round((start - left) / 0.01)
        count = math.ceil((end - start) / 0.01 - 1e-8)
        selected = raw[offset:offset + count]
        if len(selected) != count or not np.isfinite(selected).all():
            raise ValueError("Incomplete or non-finite FCPE window")
        parts.append(selected)
    raw = np.concatenate(parts)
    path = candidates[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.npz")
    np.savez_compressed(temporary, raw=raw, source_sha=stem_sha, model_sha=FCPE_SHA,
                        seconds=round(time.monotonic() - started, 3))
    temporary.replace(path)
    return raw, path, "regenerated-identical-vocal"


def align_f0(raw, count):
    """The model's 20 ms frames coincide with even FCPE 10 ms frames.

    Do not interpolate across unvoiced gaps or invent the missing tail of a contour.
    """
    track = np.asarray(raw, dtype=np.float32)[::2][:count].copy()
    if len(track) != count or not np.isfinite(track).all():
        raise ValueError("FCPE and phoneme clocks disagree")
    track[track <= 0] = np.nan
    return track


def decode_events(logits, raw, decoder, duration):
    import torch

    f0 = align_f0(raw, len(logits))
    pitches, intervals = decoder.decode(torch.from_numpy(logits)[None], f0=f0)
    result = []
    for pitch, (start, end) in zip(pitches, intervals, strict=True):
        a, b = max(0, start * 0.02), min(duration, end * 0.02)
        if math.isfinite(pitch) and 0 < pitch <= 127 and b > a:
            if result and a < result[-1][1] - 1e-6:
                raise ValueError("Decoded notes overlap")
            result.append([round(a, 6), round(b, 6), round(pitch)])
    return result


def boundary_chart(chart, events, logits, raw):
    """Move existing boundaries at most 80 ms, with one-to-one voiced evidence.

    Preserve every pitch, lyric and note type, including repeated equal pitches.
    Reject competing movements instead of shortening a note to resolve a clash.
    """
    headers, rows = parse(chart)
    proposed = [replace(row) for row in rows]
    f0 = align_f0(raw, len(logits))
    voiced = np.isfinite(f0) & (logits[:, 2] >= 0)
    # One candidate boundary cannot attract two neighboring notes of equal pitch.
    used = {0: set(), 1: set()}
    for side in (0, 1):
        choices = []
        for i, row in enumerate(rows):
            if row.kind not in ":*":
                continue
            point = (row.start if side == 0 else row.end) / 60
            for j, event in enumerate(events):
                candidate = event[side]
                overlap = min(row.end / 60, event[1]) - max(row.start / 60, event[0])
                if abs(candidate - point) > 0.08 or overlap < 0.035:
                    continue
                a, b = (candidate, candidate + 0.04) if side == 0 else (candidate - 0.04, candidate)
                begin = max(0, math.ceil(a / 0.02 - 1e-8))
                end = min(len(voiced), math.ceil(b / 0.02 - 1e-8))
                if end <= begin or np.mean(voiced[begin:end]) < 0.5:
                    continue
                tick = round(candidate * 60)
                original = row.start if side == 0 else row.end
                if abs(tick - original) / 60 <= 0.08:
                    choices.append((abs(candidate - point), i, j, tick))
        assigned = set()
        for _, i, j, tick in sorted(choices):
            if i in assigned or j in used[side]:
                continue
            assigned.add(i)
            used[side].add(j)
            if side == 0:
                proposed[i].start = tick
            else:
                proposed[i].end = tick
    # A rejected movement restores original times. Re-run because restoration
    # can conflict with the adjacent movement that was previously valid.
    while True:
        rejected = set()
        for i, (old, new) in enumerate(zip(rows, proposed, strict=True)):
            if (new.start, new.end) != (old.start, old.end) and new.end - new.start < 3:
                rejected.add(i)
            if i and proposed[i - 1].end > new.start:
                if rows[i - 1].end > old.start:
                    raise ValueError("Baseline chart already overlaps")
                rejected.update((i - 1, i))
        changed = [i for i in rejected if proposed[i] != rows[i]]
        if not changed:
            break
        for i in changed:
            proposed[i] = replace(rows[i])
    return serialize(headers, proposed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "model", "stems", "charts", "fcpe-cache", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--fcpe-model", type=Path)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--core", type=int, default=18)
    parser.add_argument("--pad", type=int, default=2)
    parser.add_argument("--check-load", action="store_true")
    args = parser.parse_args()
    if args.threads < 1 or args.core < 1 or args.pad < 0:
        parser.error("Invalid threads or window duration")
    model, decoder, model_config, source_hashes, versions = load_model(args)
    if args.check_load:
        print(json.dumps({"model_loaded": True, "config": model_config, "versions": versions}))
        return
    stems, charts = (json.loads(p.read_text()) for p in (args.stems, args.charts))
    if set(stems) != set(charts):
        raise ValueError("Vocal and predicted-chart cohorts differ")
    ids = args.ids or sorted(stems)
    if not set(ids).issubset(stems):
        raise ValueError("Requested song is outside the frozen cohort")
    for tag in ids:
        if Path(tag).name != tag or tag in (".", ".."):
            raise ValueError("Invalid song identity")
        stem, chart = Path(stems[tag]), Path(charts[tag])
        stem_sha, chart_sha = digest(stem), digest(chart)
        events_path = args.output / "events" / (tag + ".json")
        destination = args.output / "variants" / tag
        settings = dict(family="phoneme-fcpe", model_sha256=MODEL_SHA, device="cpu",
                        source=str(stem), core=args.core, pad=args.pad, threads=args.threads)
        provenance = dict(stem_sha256=stem_sha, baseline_sha256=chart_sha,
                          implementation_sha256=digest(__file__), source_commit=SOURCE_COMMIT,
                          source_hashes=source_hashes, versions=versions,
                          fcpe_model_sha256=FCPE_SHA, model_config=model_config,
                          host=platform.platform(), machine=platform.machine())
        frozen_path = destination / "frozen.json"
        if frozen_path.exists():
            frozen = json.loads(frozen_path.read_text())
            old = json.loads(events_path.read_text())
            if frozen["provenance"] != provenance or old["settings"] != settings:
                raise ValueError(f"Incompatible frozen prediction for {tag}")
            if digest(events_path) != frozen["events_sha256"] or any(
                digest(destination / (name + ".txt")) != sha
                for name, sha in frozen["charts"].items()
            ):
                raise ValueError(f"Frozen output changed for {tag}")
            print(tag, "cached", flush=True)
            continue
        started = time.monotonic()
        raw, fcpe_path, origin = fcpe_track(tag, stem, stem_sha, args)
        logits, duration = infer_logits(stem, model, args.core, args.pad)
        events = decode_events(logits, raw, decoder, duration)
        seconds = round(time.monotonic() - started, 3)
        candidates = transform(chart, events, duration)
        candidates["boundaries"] = boundary_chart(chart, events, logits, raw)
        destination.mkdir(parents=True, exist_ok=True)
        hashes = {}
        for name, text in candidates.items():
            path = destination / (name + ".txt")
            path.write_text(text, encoding="utf-8")
            hashes[name] = digest(path)
        frame_path = args.output / "logits" / (tag + ".npz")
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(frame_path, logits=logits, step_s=0.02)
        write_json(events_path, dict(events=events, settings=settings, seconds=seconds,
                   provenance={**provenance, "duration_s": duration,
                               "fcpe_path": str(fcpe_path), "fcpe_sha256": digest(fcpe_path),
                               "fcpe_origin": origin, "logits_sha256": digest(frame_path)}))
        write_json(frozen_path, dict(provenance=provenance, charts=hashes,
                   events_sha256=digest(events_path), baseline_sha256=chart_sha,
                   secondary_sha256=None, seconds=seconds, duration_s=duration))
        print(tag, len(events), seconds, origin, flush=True)
    for method in ("pitch", "events", "boundaries"):
        mapping = {path.parent.name: str(path.resolve()) for path in
                   sorted((args.output / "variants").glob("*/" + method + ".txt"))}
        write_json(args.output / (method + "-charts.json"), mapping)


if __name__ == "__main__":
    main()
