"""Freeze YourMT3+ vocal note events without reading human reference charts.

The inspected upstream code and one checkpoint live outside the product in
build/generation-next/yourmt3. `inspect` and `selftest` do not import Torch.
`synthetic`/`generate` run one supervised CPU worker, never a web demo or GPU.
Both raw program-100 and program-100+101 outputs remain independent diagnostics;
no pitch-ranking rule silently converts polyphony to a monophonic chart.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


SOURCE_REVISION = "5e66c1ea173a8186e0d20432b841d3180cc015b5"
SOURCE_MANIFEST_SHA = "0b2e70c3195441d75b7138d1d78d76a2ecb7c558d6d665daabde5b06d5508c09"
MODEL_REVISION = "e45ebd70398682d54b7bb1901a5216e18f3b1824"
MODEL_SHA = "ae38e415c79efd5592dcb9b658cdb99ddb11d4c4e1eaa364cab04a052473fc25"
MONITOR_SHA = "5cc80cefe57a4088701dc3ea1e9bfa2be3ee5120754c4d6a702ccf184ed3ef97"
EVALUATION_PLAN_SHA = "13bf73193782abefd6bd77971e3445e097a7eaa869c5bded5f168081dada34c1"
SAMPLE_SECONDS = .05
EXPERIMENT = "mc13_256_g4_all_v7_mt3f_sqr_rms_moe_wf4_n8k2_silu_rope_rp_b36_nops"
PILOT = (
    "bad-bunny-amorfoda", "fito-paez-11-y-6",
    "jonathan-coulton-mr-fancy-pants", "northern-star",
)
ARMS = {"lead": [100], "lead-and-chorus": [100, 101]}
UPSTREAM_ARGS = [
    EXPERIMENT + "@last.ckpt", "-p", "2024", "-tk", "mc13_full_plus_256",
    "-dec", "multi-t5", "-nl", "26", "-enc", "perceiver-tf", "-sqr", "1",
    "-ff", "moe", "-wf", "4", "-nmoe", "8", "-kmoe", "2", "-act", "silu",
    "-epe", "rope", "-rp", "1", "-ac", "spec", "-hop", "300", "-atc", "1",
    "-pr", "32", "-wb", "disabled",
]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"Refusing to overwrite evidence: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    def scalar(item):
        if isinstance(item, set):
            return sorted(item)
        if hasattr(item, "item"):
            return item.item()
        raise TypeError(f"Not a JSON scalar: {type(item).__name__}")

    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                    allow_nan=False, default=scalar) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_source(root):
    manifest = root / "source-manifest.json"
    if digest(manifest) != SOURCE_MANIFEST_SHA:
        raise ValueError("Source manifest differs from inspected snapshot")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data["revision"] != SOURCE_REVISION:
        raise ValueError("Unexpected source revision")
    for row in data["files"]:
        if digest(root / "source" / row["path"]) != row["sha256"]:
            raise ValueError(f"Changed upstream source: {row['path']}")
    if digest(root / "last.ckpt") != MODEL_SHA:
        raise ValueError("Unexpected checkpoint")
    return data


def official_arguments(root):
    """Run only the inspected argparse statements, without importing upstream ML.

    The upstream helper otherwise creates a Lightning Trainer, whose default
    accelerator is automatic. Its parser is reused verbatim; its trainer is not.
    """
    path = root / "source/model_helper.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "load_model_checkpoint")
    statements = []
    for node in function.body:
        statements.append(node)
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "parse_args"):
            break
    else:
        raise ValueError("Upstream parser boundary was not found")
    scope = {"argparse": argparse, "args": list(UPSTREAM_ARGS),
             "str2bool": lambda value: str(value).lower() in ("1", "true", "yes")}
    exec(compile(ast.Module(body=statements, type_ignores=[]), str(path), "exec"), scope)
    return scope["args"]


def note_diagnostics(notes, duration):
    invalid = []
    edges = []
    for i, row in enumerate(notes):
        a, b = row["onset"], row["offset"]
        if (not all(math.isfinite(v) for v in (a, b)) or not 0 <= a < b <= duration
                or not 0 <= row["pitch"] <= 127):
            invalid.append(i)
            continue
        edges.extend(((a, 1), (b, -1)))
    active = 0
    previous = 0.0
    overlap = 0.0
    maximum = 0
    for at, change in sorted(edges):
        if active > 1:
            overlap += at - previous
        active += change
        maximum = max(maximum, active)
        previous = at
    return {"invalid_note_indices": invalid, "overlap_seconds": overlap,
            "maximum_simultaneous_notes": maximum,
            "already_monophonic": maximum <= 1 and not invalid}


def input_rows(args):
    identities = json.loads(args.manifest.read_text(encoding="utf-8"))
    if len(identities) != 40 or len({r["tag"] for r in identities}) != 40:
        raise ValueError("Expected the fixed cohort of 40 recordings")
    identities = {r["tag"]: r for r in identities}
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    sources = {r["tag"]: r for rows in corpus.values() for r in rows}
    selected = []
    for tag in PILOT:
        source, identity = sources[tag], identities[tag]
        path = Path(source["audio"])
        sha = digest(path)
        if sha != identity["audio_sha"] or sha != source["audio_sha"]:
            raise ValueError(f"Master identity mismatch: {tag}")
        # In particular, do not open source['reference'].
        selected.append({"tag": tag, "language": identity["language"],
                         "audio": str(path.resolve()), "audio_sha256": sha})
    return selected


def audio_tool(name):
    executable = shutil.which(name)
    if not executable:
        raise ValueError(f"Missing audio preparation tool: {name}")
    path = Path(executable).resolve()
    version = subprocess.check_output([str(path), "-version"], text=True, encoding="utf-8")
    return {"path": str(path), "sha256": digest(path), "version": version}


def probe_audio(path, ffprobe):
    command = [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_streams",
               "-of", "json", str(path)]
    value = json.loads(subprocess.check_output(command, text=True, encoding="utf-8"))
    if len(value.get("streams", [])) != 1:
        raise ValueError("Expected exactly one selected audio stream")
    return value["streams"][0]


def audio_blocks(path, block_size):
    """Read bounded mono blocks; no whole-song decoding/resampling in the model worker."""
    import soundfile as sf

    with sf.SoundFile(path) as stream:
        if stream.samplerate != 16000 or stream.channels != 1 or stream.subtype != "FLOAT":
            raise ValueError("Expected a prepared mono float32/16-kHz WAV")
        while True:
            block = stream.read(block_size, dtype="float32", always_2d=False)
            if not len(block):
                return
            yield block


def prepare_audio(args):
    """Prepare the fixed four mixtures before a model exists, with independent limits."""
    import numpy as np
    import soundfile as sf
    from lead_vocals import memory_sampler

    monitor_spec()
    sample_memory = memory_sampler()
    if args.output.exists():
        raise ValueError("Use a new audio cache directory")
    inputs = input_rows(args)
    ffmpeg, ffprobe = audio_tool("ffmpeg"), audio_tool("ffprobe")
    commands = []
    for row in inputs:
        metadata = probe_audio(row["audio"], ffprobe["path"])
        channels = int(metadata["channels"])
        if channels not in (1, 2):
            raise ValueError("Only mono/stereo arithmetic-mean downmix was predeclared")
        pan = "pan=mono|c0=c0" if channels == 1 else "pan=mono|c0=0.5*c0+0.5*c1"
        resample = "aresample=16000:resampler=swr:filter_size=64:phase_shift=10:exact_rational=1:cutoff=0.95"
        destination = (args.output / f"{row['tag']}.wav").resolve()
        command = [ffmpeg["path"], "-nostdin", "-v", "error", "-n", "-threads", "1",
                   "-filter_threads", "1", "-i", row["audio"], "-map", "0:a:0", "-vn",
                   "-sn", "-dn", "-map_metadata", "-1", "-af", pan + "," + resample,
                   "-c:a", "pcm_f32le", "-threads", "1", str(destination)]
        commands.append({**row, "source_metadata": metadata, "prepared_audio": str(destination),
                         "command": command})
    args.output.mkdir(parents=True)
    preparation = {"created_utc": datetime.now(timezone.utc).isoformat(),
                   "script_sha256": digest(Path(__file__)), "ffmpeg": ffmpeg, "ffprobe": ffprobe,
                   "inputs": commands, "references_opened": False,
                   "policy": "complete original mix; arithmetic channel mean; fixed SWR resampling; no trim or normalization",
                   "resampler_matches_original_torchaudio": False,
                   "memory_monitor": monitor_spec(), "ffmpeg_limit_mib": 256,
                   "ffmpeg_timeout_seconds_per_song": 120}
    save(args.output / "plan.json", preparation)
    prepared = []
    for row in commands:
        if digest(row["audio"]) != row["audio_sha256"]:
            raise ValueError("Source changed after preparation plan")
        resources = args.output / "resources" / row["tag"]
        resources.mkdir(parents=True)
        run_bounded(row["command"], resources, 256 * 1024**2, 120, sample_memory)
        path = Path(row["prepared_audio"])
        metadata = sf.info(path)
        frames = 0
        for block in audio_blocks(path, 32767):
            if not np.isfinite(block).all():
                raise ValueError("Non-finite prepared audio")
            frames += len(block)
        if frames <= 0 or frames != metadata.frames:
            raise ValueError("Incomplete/empty prepared audio")
        prepared.append({**row, "prepared_sha256": digest(path), "frames": frames,
                         "duration_s": frames / 16000, "sample_rate": 16000,
                         "channels": 1, "subtype": "FLOAT", "finite": True,
                         "bytes": path.stat().st_size})
    save(args.output / "manifest.json", {"plan_sha256": digest(args.output / "plan.json"),
                                        "inputs": prepared, "references_opened": False})
    save(args.output / "frozen.json", {"files": {
        str(p.relative_to(args.output)): digest(p) for p in sorted(args.output.rglob("*"))
        if p.is_file()}, "references_opened": False})
    assert "torch" not in sys.modules
    print(f"Prepared {len(prepared)} complete mixtures; no Torch/model imported", flush=True)


def prepared_rows(args):
    current = input_rows(args)
    path = args.audio_cache / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    frozen = json.loads((args.audio_cache / "frozen.json").read_text(encoding="utf-8"))
    for relative, sha in frozen["files"].items():
        if digest(args.audio_cache / relative) != sha:
            raise ValueError(f"Prepared cache changed: {relative}")
    if manifest["plan_sha256"] != digest(args.audio_cache / "plan.json"):
        raise ValueError("Audio preparation plan mismatch")
    rows = manifest["inputs"]
    if [r["tag"] for r in rows] != list(PILOT):
        raise ValueError("Prepared audio differs from fixed pilot")
    for row, original in zip(rows, current, strict=True):
        if any(row[k] != original[k] for k in original):
            raise ValueError("Prepared cache master identity mismatch")
        if digest(row["prepared_audio"]) != row["prepared_sha256"]:
            raise ValueError("Prepared audio hash mismatch")
    return rows


def monitor_spec():
    path = Path(__file__).with_name("lead_vocals.py")
    if digest(path) != MONITOR_SHA:
        raise ValueError("Memory monitor changed; review it before declaring another plan")
    return {"module": str(path.resolve()), "sha256": MONITOR_SHA,
            "api": "proc_pid_rusage/RUSAGE_INFO_V0", "sample_seconds": SAMPLE_SECONDS,
            "worker_only": True, "fields": ["rss_bytes", "physical_footprint_bytes"],
            "stop_action": "SIGKILL, then confirmed wait/reap",
            "limit": "sampled values; not an allocation or absolute peak guarantee"}


def environment_record(root):
    names = sorted({d.metadata["Name"].lower().replace("_", "-")
                    for d in importlib.metadata.distributions()})
    packages = {name: importlib.metadata.version(name) for name in names}
    encoded = json.dumps(packages, sort_keys=True).encode("utf-8")
    return {"python": sys.version, "executable": sys.executable,
            "visible_packages": packages,
            "visible_packages_sha256": hashlib.sha256(encoded).hexdigest(),
            "overlay_requirements_sha256": digest(root / "requirements-overlay.txt")}


def plan(args):
    verify_source(args.root)
    evaluation = args.root / "map-evaluation-plan-v1.json"
    if args.command == "generate" and digest(evaluation) != EVALUATION_PLAN_SHA:
        raise ValueError("Predeclared evaluation plan changed")
    return {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_revision": SOURCE_REVISION, "source_manifest_sha256": SOURCE_MANIFEST_SHA,
        "model_revision": MODEL_REVISION, "model_sha256": MODEL_SHA,
        "script_sha256": digest(Path(__file__)), "upstream_arguments": UPSTREAM_ARGS,
        "parsed_arguments": vars(official_arguments(args.root)),
        "device": "cpu", "dtype": "float32", "threads": 2, "batch_size": 1,
        "arms": ARMS, "primary": "lead", "cohort_denominator": 40,
        "pilot_ids": list(PILOT),
        "map_policy": "No polyphony reduction. Lead eligible only when already monophonic; "
                      "lead-and-chorus always diagnostic. No maps created by this script.",
        "references_opened": False,
        "evaluation_plan": {"path": str(evaluation.resolve()), "sha256": EVALUATION_PLAN_SHA}
        if args.command == "generate" else None,
        "mode": args.command,
        "inputs": prepared_rows(args) if args.command == "generate" else [],
        "prepared_cache_manifest_sha256": digest(args.audio_cache / "manifest.json")
        if args.command == "generate" else None,
        "audio_loading": "prepared mono float32 16-kHz WAV streamed in 32767-frame blocks",
        "limits": {"rss_and_footprint_mib": args.max_rss_mib,
                   "timeout_seconds": args.timeout_seconds,
                   "timeout_scope": "whole sequence including all fresh workers"},
        "worker_lifetime": "fresh CPU model process per song; serial, confirmed reap before next; stop on first failure"
        if args.command == "generate" else "one synthetic worker",
        "memory_monitor": monitor_spec(),
        "environment": environment_record(args.root),
    }


def load_model(args, mark):
    import torch

    mark("after_torch_import")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.set_default_device("cpu")
    torch.set_float32_matmul_precision("high")
    torch.manual_seed(0)
    sys.path.insert(0, str((args.root / "source/amt/src").resolve()))
    from config.config import shared_cfg
    from model.init_train import update_config
    from model.ymt3 import YourMT3
    from utils.task_manager import TaskManager

    mark("after_model_imports")
    cli = official_arguments(args.root)
    shared, audio, model_config = update_config(cli, deepcopy(shared_cfg), stage="test")
    if (audio["sample_rate"], audio["input_frames"], shared["TOKENIZER"]["shift_step_ms"]) != (
            16000, 32767, 10):
        raise ValueError("Unexpected inference clock")
    manager = TaskManager(task_name=cli.task,
                          max_shift_steps=int(shared["TOKENIZER"]["max_shift_steps"]),
                          debug_mode=False)
    model = YourMT3(audio_cfg=audio, model_cfg=model_config, shared_cfg=shared,
                   task_manager=manager, eval_subtask_key=cli.eval_subtask_key)
    mark("after_model_construction")
    checkpoint = torch.load(args.root / "last.ckpt", map_location="cpu",
                            mmap=True, weights_only=False)
    mark("after_checkpoint_mapping")
    state = checkpoint["state_dict"]
    ignored = sorted(k for k in state if "pitchshift" in k)
    state = {k: v for k, v in state.items() if "pitchshift" not in k}
    model.load_state_dict(state, strict=True)
    mark("after_strict_state_load")
    model = model.cpu().float().eval()
    shapes = {k: list(v.shape) for k, v in state.items()}
    del checkpoint, state
    mark("after_checkpoint_release")

    def finite_logits(_module, _inputs, outputs):
        if not torch.isfinite(outputs).all():
            raise ValueError("Non-finite prediction logits")

    model.lm_head.register_forward_hook(finite_logits)
    details = {"parameters": sum(p.numel() for p in model.parameters()),
               "state_shapes": shapes, "ignored_training_keys": ignored,
               "audio_config": audio, "model_config": model_config,
               "task_channels": manager.num_decoding_channels,
               "max_tokens": model.max_total_token_length,
               "versions": {p: importlib.metadata.version(p) for p in
                            ("torch", "torchaudio", "transformers", "pytorch-lightning",
                             "numpy", "torchmetrics", "wandb", "mir_eval")}}
    suffix = f"-{args.song_id}" if args.song_id else ""
    save(args.output / f"architecture{suffix}.json", details)
    return model


def transcribe(model, blocks, frame_count, tag, output, mark):
    import numpy as np
    import torch
    from utils.event2note import merge_zipped_note_events_and_ties_to_notes

    duration = frame_count / 16000
    block_size = model.audio_cfg["input_frames"]
    tokens, starts = [], []
    before = time.monotonic()
    token_dir = output / "tokens" / tag
    token_dir.mkdir(parents=True, exist_ok=False)
    mark("before_song_inference", tag=tag, frames=frame_count)
    observed_frames = 0
    with torch.inference_mode():
        for index, tail in enumerate(blocks):
            begin = index * block_size
            expected = min(block_size, frame_count - begin)
            if len(tail) != expected or expected <= 0 or not np.isfinite(tail).all():
                raise ValueError("Invalid or non-finite input block")
            observed_frames += len(tail)
            block = np.zeros(block_size, dtype=np.float32)
            block[:len(tail)] = tail
            prediction = model.inference(torch.from_numpy(block[None, None, :])).cpu().numpy()
            if prediction.ndim != 3 or prediction.shape[:2] != (
                    1, model.task_manager.num_decoding_channels):
                raise ValueError(f"Unexpected token shape: {prediction.shape}")
            if not np.issubdtype(prediction.dtype, np.integer):
                raise ValueError("Predicted tokens are not integers")
            np.save(token_dir / f"{index:05d}.npy", prediction, allow_pickle=False)
            tokens.append(prediction)
            starts.append(begin / 16000)
            if index == 0 or (index + 1) % 25 == 0:
                mark("after_inference_block", tag=tag, block_index=index)
    if observed_frames != frame_count:
        raise ValueError("Incomplete song stream")
    mark("after_song_tokens", tag=tag, block_count=len(tokens))
    all_notes, channels = [], []
    repairs = Counter()
    for channel in range(model.task_manager.num_decoding_channels):
        zipped, _events, decode_errors = model.task_manager.detokenize_list_batches(
            [arr[:, channel, :] for arr in tokens], starts, return_events=True)
        notes, merge_errors = merge_zipped_note_events_and_ties_to_notes(zipped)
        records = [asdict(n) | {"channel": channel} for n in notes]
        all_notes.extend(records)
        repairs.update(decode_errors)
        repairs.update(merge_errors)
        channels.append({"channel": channel, "decode_errors": dict(decode_errors),
                         "merge_errors": dict(merge_errors),
                         "segments": [
                             {"events": [asdict(e) for e in events],
                              "ties": [asdict(e) for e in ties],
                              "last_activity": sorted(last_activity), "start": start}
                             for events, ties, last_activity, start in zipped]})
    all_notes.sort(key=lambda n: (n["onset"], n["offset"], n["program"], n["pitch"], n["channel"]))
    save(output / "raw" / f"{tag}.json",
         {"notes": all_notes, "channels": channels, "repair_counts": dict(repairs),
          "duration_s": duration, "seconds": time.monotonic() - before})
    for arm, programs in ARMS.items():
        selected = [n for n in all_notes if not n["is_drum"] and n["program"] in programs]
        diagnostics = note_diagnostics(selected, duration)
        eligible = arm == "lead" and bool(selected) and diagnostics["already_monophonic"]
        save(output / "arms" / arm / f"{tag}.json",
             {"events": [[n["onset"], n["offset"], n["pitch"]] for n in selected],
              "notes": selected, "diagnostics": diagnostics, "programs": programs,
              "eligible_for_monophonic_map": eligible, "chart_created": False,
              "repair_counts_all_channels": dict(repairs), "duration_s": duration})
    mark("after_song_decode", tag=tag, notes=len(all_notes))
    print(f"{tag}: {len(all_notes)} notes across all instruments, "
          f"{time.monotonic() - before:.2f}s", flush=True)


def worker(args):
    frozen_plan = json.loads((args.output / "plan.json").read_text(encoding="utf-8"))
    verify_source(args.root)
    if monitor_spec() != frozen_plan["memory_monitor"]:
        raise ValueError("Memory monitor differs from frozen plan")
    if environment_record(args.root) != frozen_plan["environment"]:
        raise ValueError("Environment differs from frozen plan")
    if digest(Path(__file__)) != frozen_plan["script_sha256"]:
        raise ValueError("Adapter changed after plan freeze")
    if args.command == "generate":
        if args.song_id not in [r["tag"] for r in frozen_plan["inputs"]]:
            raise ValueError("A generation worker must own exactly one predeclared song")
        expected = frozen_plan["evaluation_plan"]
        if digest(expected["path"]) != expected["sha256"]:
            raise ValueError("Evaluation protocol changed during prediction")
    from lead_vocals import memory_sampler

    sample_memory = memory_sampler()
    started = time.monotonic()
    suffix = f"-{args.song_id}" if args.song_id else ""

    def mark(label, **detail):
        with (args.output / f"phases{suffix}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"phase": label, "elapsed_seconds": time.monotonic() - started,
                                     **sample_memory(os.getpid()), **detail}) + "\n")

    mark("before_model_imports")
    model = load_model(args, mark)
    if args.command == "synthetic":
        import numpy as np
        import soundfile as sf

        times = np.arange(32000, dtype=np.float32) / 16000
        envelope = np.clip(np.minimum((times - .2) / .01, (1.6 - times) / .01), 0, 1)
        samples = (.15 * envelope * (np.sin(2 * np.pi * 440 * times)
                                   + .3 * np.sin(2 * np.pi * 880 * times))).astype(np.float32)
        sf.write(args.output / "synthetic.wav", samples, 16000, subtype="FLOAT")
        transcribe(model, [samples], len(samples), "synthetic-2s", args.output, mark)
    else:
        for row in [r for r in frozen_plan["inputs"] if r["tag"] == args.song_id]:
            if digest(row["audio"]) != row["audio_sha256"]:
                raise ValueError(f"Changed audio: {row['tag']}")
            if digest(row["prepared_audio"]) != row["prepared_sha256"]:
                raise ValueError(f"Changed prepared audio: {row['tag']}")
            transcribe(model, audio_blocks(row["prepared_audio"], model.audio_cfg["input_frames"]),
                       row["frames"], row["tag"], args.output, mark)
    mark("before_prediction_freeze")
    if args.song_id:
        owned = [args.output / name for name in
                 ("plan.json", f"architecture{suffix}.json", f"phases{suffix}.jsonl",
                  f"raw/{args.song_id}.json", *(f"arms/{arm}/{args.song_id}.json" for arm in ARMS))]
        owned.extend(sorted((args.output / "tokens" / args.song_id).glob("*.npy")))
    else:
        owned = [p for p in sorted(args.output.rglob("*"))
                 if p.is_file() and p.name not in ("resources.jsonl", "resources.json")]
    files = {str(p.relative_to(args.output)): digest(p) for p in owned}
    freeze_name = f"worker-frozen{suffix}.json" if args.song_id else "frozen.json"
    save(args.output / freeze_name, {"files": files,
         "frozen_utc": datetime.now(timezone.utc).isoformat(), "references_opened": False,
         "present": 1 if args.song_id else 0, "denominator": 40, "arms": ARMS,
         "song_id": args.song_id,
         "memory_monitor_sha256": MONITOR_SHA})


def run_bounded(command, output, limit_bytes, timeout, sample_memory, environment=None):
    """Observe one worker; stop immediately if either memory counter or telemetry fails."""
    started = time.monotonic()
    reason = None
    process = subprocess.Popen(command, env=environment)
    record = {"pid": process.pid, "sample_seconds": SAMPLE_SECONDS,
              "sampled_max_rss_bytes": 0, "sampled_max_physical_footprint_bytes": 0,
              "resource_samples": 0, "signals": [], "reaped": False,
              "memory_monitor_sha256": MONITOR_SHA, "stop_bytes": limit_bytes,
              "limit_is_sampled_not_a_hard_memory_guarantee": True}
    status = None
    try:
        with (output / "resources.jsonl").open("x", encoding="utf-8") as stream:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= timeout:
                    reason = "time_budget_exceeded"
                    break
                try:
                    sample = sample_memory(process.pid)
                    values = [sample[k] for k in ("rss_bytes", "physical_footprint_bytes")]
                    if any(not isinstance(v, int) or v < 0 for v in values):
                        raise ValueError("Invalid worker memory telemetry")
                except Exception as error:
                    if process.poll() is not None:
                        break
                    reason = "memory_telemetry_lost"
                    record["telemetry_error"] = repr(error)
                    break
                record["resource_samples"] += 1
                for field in ("rss_bytes", "physical_footprint_bytes"):
                    key = "sampled_max_" + field
                    record[key] = max(record[key], sample[field])
                stream.write(json.dumps({"elapsed_seconds": elapsed, **sample}) + "\n")
                stream.flush()
                if max(values) >= limit_bytes:
                    reason = "memory_budget_exceeded"
                    break
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=min(SAMPLE_SECONDS, max(.001, timeout - elapsed)))
        if reason and process.poll() is None:
            record["signals"].append("SIGKILL")
            with suppress(ProcessLookupError):
                process.kill()
        status = process.wait(timeout=5)
        record["reaped"] = True
    except BaseException:
        reason = reason or "controller_interrupted"
        if process.poll() is None:
            record["signals"].append("SIGKILL")
            with suppress(ProcessLookupError):
                process.kill()
        try:
            status = process.wait(timeout=5)
            record["reaped"] = True
        except subprocess.TimeoutExpired:
            reason += "_unreaped"
        raise
    finally:
        record.update(exit_code=status, stopped_reason=reason,
                      wall_seconds=time.monotonic() - started)
        save(output / "resources.json", record)
    if status or reason:
        raise SystemExit(f"Worker failed: status={status}, reason={reason}")
    return record


def run_sequence(jobs, output, limit_bytes, timeout, sample_memory, environment=None):
    """One fresh process per job, no next spawn until confirmed successful reap."""
    started = time.monotonic()
    records = []
    complete = False
    try:
        for tag, command in jobs:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise SystemExit("Whole-sequence time budget exceeded before next worker")
            destination = output / "resources" / tag
            destination.mkdir(parents=True)
            try:
                record = run_bounded(command, destination, limit_bytes, remaining,
                                     sample_memory, environment)
            except BaseException:
                if (destination / "resources.json").exists():
                    record = json.loads((destination / "resources.json").read_text(encoding="utf-8"))
                    records.append({"tag": tag, **record})
                raise
            if not record["reaped"] or record["exit_code"] != 0:
                raise RuntimeError("Worker did not finish successfully; do not start another")
            records.append({"tag": tag, **record})
        complete = True
    finally:
        save(output / "resources.json", {
            "status": "complete" if complete else "incomplete",
            "whole_sequence_wall_seconds": time.monotonic() - started,
            "requested_jobs": len(jobs), "started_jobs": len(records), "workers": records,
            "all_started_workers_reaped": all(r["reaped"] for r in records),
            "sampled_max_rss_bytes": max((r["sampled_max_rss_bytes"] for r in records), default=0),
            "sampled_max_physical_footprint_bytes": max(
                (r["sampled_max_physical_footprint_bytes"] for r in records), default=0),
            "stop_bytes": limit_bytes, "sample_seconds": SAMPLE_SECONDS,
            "memory_monitor_sha256": MONITOR_SHA})
    return records


def supervise(args):
    monitor_spec()
    from lead_vocals import memory_sampler

    sample_memory = memory_sampler()  # Verify telemetry works before spawning a model.
    if args.output.exists():
        raise ValueError("Use a new output directory; existing evidence is never overwritten")
    args.output.mkdir(parents=True)
    frozen_plan = plan(args)
    save(args.output / "plan.json", frozen_plan)
    (args.output / "source-at-generation.py").write_bytes(Path(__file__).read_bytes())
    environment = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", OMP_NUM_THREADS="2",
                       OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="2", WANDB_MODE="disabled",
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
    if args.command == "generate":
        jobs = [(r["tag"], command + ["--song-id", r["tag"]]) for r in frozen_plan["inputs"]]
        try:
            run_sequence(jobs, args.output, args.max_rss_mib * 1024**2,
                         args.timeout_seconds, sample_memory, environment)
        except BaseException:
            save(args.output / "partial-frozen.json", {
                "status": "incomplete", "references_opened": False,
                "completed_ids": [r["tag"] for r in frozen_plan["inputs"]
                                  if (args.output / f"worker-frozen-{r['tag']}.json").exists()],
                "pilot_denominator": len(PILOT), "cohort_denominator": 40,
                "files": {str(p.relative_to(args.output)): digest(p)
                          for p in sorted(args.output.rglob("*")) if p.is_file()}})
            raise
        save(args.output / "frozen.json", {
            "files": {str(p.relative_to(args.output)): digest(p)
                      for p in sorted(args.output.rglob("*")) if p.is_file()},
            "references_opened": False, "completed_ids": list(PILOT),
            "present": len(PILOT), "denominator": 40, "arms": ARMS,
            "memory_monitor_sha256": MONITOR_SHA})
        save(args.output / "execution-frozen.json", {
            "prediction_freeze_sha256": digest(args.output / "frozen.json"),
            "resources_sha256": digest(args.output / "resources.json"),
            "memory_monitor_sha256": MONITOR_SHA, "all_workers_reaped": True})
        return
    run_bounded(command, args.output, args.max_rss_mib * 1024**2,
                args.timeout_seconds, sample_memory, environment)
    save(args.output / "execution-frozen.json", {
        "prediction_freeze_sha256": digest(args.output / "frozen.json"),
        "resources_sha256": digest(args.output / "resources.json"),
        "resource_samples_sha256": digest(args.output / "resources.jsonl"),
        "memory_monitor_sha256": MONITOR_SHA, "worker_reaped": True})


def guardtest():
    """Small-process lifecycle checks; simulated limits never allocate large buffers."""
    monitor_spec()
    from lead_vocals import memory_sampler

    child = [sys.executable, "-c", "import time; time.sleep(5)"]

    def valid(_pid):
        return {"rss_bytes": 1024, "physical_footprint_bytes": 2048}

    def lost(_pid):
        raise OSError("simulated lost memory telemetry")

    cases = [
        ("rss", lambda _pid: {"rss_bytes": 8192, "physical_footprint_bytes": 1024}, 2),
        ("footprint", lambda _pid: {"rss_bytes": 1024, "physical_footprint_bytes": 8192}, 2),
        ("telemetry", lost, 2), ("timeout", valid, .06),
    ]
    records = []
    with tempfile.TemporaryDirectory(prefix="karaoke-yourmt3-guard-") as temporary:
        root = Path(temporary)
        for name, sample, timeout in cases:
            output = root / name
            output.mkdir()
            try:
                run_bounded(child, output, 4096, timeout, sample)
            except SystemExit:
                pass
            else:
                raise AssertionError("Expected a bounded failure")
            record = json.loads((output / "resources.json").read_text(encoding="utf-8"))
            assert record["signals"] == ["SIGKILL"] and record["reaped"]
            assert record["exit_code"] == -9
            records.append({"case": name, **record})
        output = root / "native"
        output.mkdir()
        record = run_bounded([sys.executable, "-c", "import time; time.sleep(.2)"],
                             output, 64 * 1024**2, 2, memory_sampler())
        assert record["exit_code"] == 0 and record["reaped"]
        assert record["sampled_max_physical_footprint_bytes"] > 0
        assert record["sampled_max_rss_bytes"] > 0
        records.append({"case": "native", **record})
    assert "torch" not in sys.modules
    print(json.dumps(records, indent=2))


def sequence_guardtest():
    """Four tiny processes and a third-worker limit; no model or large buffers."""
    monitor_spec()
    from lead_vocals import memory_sampler

    native_memory = memory_sampler()
    with tempfile.TemporaryDirectory(prefix="karaoke-yourmt3-sequence-") as directory:
        root = Path(directory)
        normal = root / "normal"
        normal.mkdir()
        jobs = [(str(i), [sys.executable, "-c", "import time; time.sleep(.06)"]) for i in range(4)]
        records = run_sequence(jobs, normal, 64 * 1024**2, 5, native_memory)
        assert len(records) == 4 and all(r["reaped"] and r["exit_code"] == 0 for r in records)
        pids = [r["pid"] for r in records]
        assert len(set(pids)) == 4
        for pid in pids:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            else:
                raise AssertionError("Expected a previously reaped child")
        failed = root / "failed"
        failed.mkdir()
        observed = []

        def third_exceeds(pid):
            if pid not in observed:
                observed.append(pid)
            return {"rss_bytes": 8192 if len(observed) == 3 else 1024,
                    "physical_footprint_bytes": 1024}

        try:
            run_sequence(jobs, failed, 4096, 5, third_exceeds)
        except SystemExit:
            pass
        else:
            raise AssertionError("Expected the third worker to stop the sequence")
        failure = json.loads((failed / "resources.json").read_text(encoding="utf-8"))
        assert failure["started_jobs"] == 3 and failure["all_started_workers_reaped"]
        assert failure["workers"][-1]["signals"] == ["SIGKILL"]
        assert failure["workers"][-1]["exit_code"] == -9
        assert not (failed / "resources" / "3").exists()
        result = {"four_fresh_workers": records, "third_worker_failure": failure,
                  "fourth_worker_not_started_after_failure": True}
    assert "torch" not in sys.modules
    print(json.dumps(result, indent=2))


def selftest(args):
    import numpy as np
    import soundfile as sf

    cli = official_arguments(args.root)
    assert cli.encoder_type == "perceiver-tf" and cli.decoder_type == "multi-t5"
    assert cli.task == "mc13_full_plus_256" and cli.precision == "32"
    assert cli.moe_num_experts == 8 and cli.moe_topk == 2
    rows = [{"onset": 0., "offset": 1., "pitch": 60},
            {"onset": 1., "offset": 2., "pitch": 62}]
    assert note_diagnostics(rows, 2.)["already_monophonic"]
    rows[1]["onset"] = .75
    assert note_diagnostics(rows, 2.)["overlap_seconds"] == .25
    assert not note_diagnostics(rows, 2.)["already_monophonic"]
    rows[1]["offset"] = 2.1
    assert note_diagnostics(rows, 2.)["invalid_note_indices"] == [1]
    with tempfile.TemporaryDirectory(prefix="karaoke-yourmt3-stream-") as directory:
        path = Path(directory) / "mono.wav"
        samples = np.arange(23, dtype=np.float32) / 23
        sf.write(path, samples, 16000, subtype="FLOAT")
        blocks = list(audio_blocks(path, 7))
        assert [len(block) for block in blocks] == [7, 7, 7, 2]
        assert np.array_equal(np.concatenate(blocks), samples)
        sf.write(path, samples, 44100, subtype="FLOAT")
        try:
            list(audio_blocks(path, 7))
        except ValueError:
            pass
        else:
            raise AssertionError("Unprepared audio should be rejected")
    assert "torch" not in sys.modules
    print("Parser, polyphony and streaming checks passed; no Torch/model imported")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "selftest", "guardtest", "sequence-guardtest", "prepare-audio", "synthetic", "generate"))
    parser.add_argument("--root", type=Path, default=Path("build/generation-next/yourmt3"))
    parser.add_argument("--manifest", type=Path, default=Path("docs/validation/generacion-muestra.json"))
    parser.add_argument("--corpus", type=Path, default=Path("build/generation-v2/corpus.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audio-cache", type=Path, default=Path("build/generation-next/yourmt3/audio-v1"))
    parser.add_argument("--max-rss-mib", type=int, default=2048,
                        help="Stop if either worker RSS or physical footprint reaches this limit")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--song-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.max_rss_mib <= 0 or args.max_rss_mib > 2560 or args.timeout_seconds <= 0:
        parser.error("RSS budget must be in 1..2560 MiB; timeout must be positive")
    if args.command == "selftest":
        selftest(args)
    elif args.command == "guardtest":
        guardtest()
    elif args.command == "sequence-guardtest":
        sequence_guardtest()
    elif args.command == "inspect":
        print(json.dumps(plan(args), indent=2))
    elif args.output is None:
        parser.error("prepare-audio/synthetic/generate require a new --output directory")
    elif args.command == "prepare-audio":
        prepare_audio(args)
    elif args.worker:
        worker(args)
    else:
        supervise(args)


if __name__ == "__main__":
    main()
