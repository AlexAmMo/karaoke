"""Freeze a paired lead-vocal separation experiment without reading reference charts.

The pinned public BS Roformer and upstream demix implement separation. A separate
process runs the existing GAME experiment on both the original and separated WAV.
This research script does not distribute weights or modify the application's models.
"""

from __future__ import annotations

import argparse
from contextlib import suppress
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import numpy as np

REVISION = "1523206d12a521bdb20673726562524cf0f9635b"
MODEL_REVISION = "0d66103c6b79c0dd0e9efd38ca70db7042f6f695"
MODEL_SHA = "eb90ee24c1154d83fbcfd27e96182f19e061557cc6e4746953125e08c29389f9"
CONFIG_SHA = "1d3b58b473025183d0d3c91e7a444cb5f1418d9f34e8f46b8d2fb10d2cc8ab34"
PILOT = ("bad-bunny-amorfoda", "fito-paez-11-y-6",
         "jonathan-coulton-mr-fancy-pants", "northern-star")
MEMORY_LIMIT = 2 * 1024 ** 3
SAMPLE_RATE = 44100
STFT_HOP = 512
ATTENTION_BANDS = 62
ATTENTION_HEADS = 8


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_new(path, value):
    """Publish complete immutable JSON, or leave no target if serialization fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic create, never replace an earlier freeze.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_checkpoint(path, value):
    """Only execution status is replaceable; predictions and plans stay immutable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def attention_estimate(chunk_samples):
    """Conservative preflight estimate, not a measured or guaranteed peak bound."""
    frames = chunk_samples // STFT_HOP + 1
    matrix = ATTENTION_BANDS * ATTENTION_HEADS * frames * frames * 4
    # Scores, probabilities/workspace, two parameter-sized buffers and other work.
    estimated = 3 * matrix + 2 * 204436907 + 256 * 1024 ** 2
    return {"frames": frames, "dense_attention_bytes": matrix,
            "estimated_bytes": estimated, "limit_bytes": MEMORY_LIMIT}


def preflight(args):
    # This must run before importing torch, reading weights or starting a worker.
    if args.device != "cpu":
        raise ValueError("MPS is disabled for this experiment after a Mac restart; use CPU in a new v2 directory")
    if not 0 < args.chunk_seconds <= 120 or not 0 < args.timeout_seconds <= 3600:
        raise ValueError("Expected positive finite window and timeout (at most 120s / 3600s)")
    estimate = attention_estimate(round(args.chunk_seconds * SAMPLE_RATE))
    if estimate["estimated_bytes"] > MEMORY_LIMIT:
        raise ValueError("Window exceeds the 2 GiB preflight estimate; the v2 default is 4 seconds")
    return estimate


def run_settings(args):
    estimate = preflight(args)
    return {"schema": 2, "adapter_sha256": digest(__file__), "device": "cpu",
            "chunk_samples": round(args.chunk_seconds * SAMPLE_RATE), "overlap": 4,
            "batch_size": 1, "amp": False, "cpu_threads": 2,
            "timeout_seconds": args.timeout_seconds, "memory_preflight": estimate,
            "model_sha256": MODEL_SHA, "config_sha256": CONFIG_SHA,
            "source_revision": REVISION, "model_revision": MODEL_REVISION,
            "stems_manifest_sha256": digest(args.stems),
            "charts_manifest_sha256": digest(args.charts)}


def prepare_plan(args):
    settings = run_settings(args)
    selected = args.ids or list(PILOT)
    path = args.output / "plan-v2.json"
    if path.exists():
        plan = json.loads(path.read_text(encoding="utf-8"))
        if plan["settings"] != settings:
            raise ValueError("Changed v2 settings: use a new output directory")
        if (args.worker and not set(selected).issubset(plan["ids"])) or (
            not args.worker and selected != plan["ids"]
        ):
            raise ValueError("Changed v2 cohort: use a new output directory")
    else:
        if args.worker or (args.output.exists() and any(args.output.iterdir())):
            raise ValueError("v2 requires a new empty directory; keep the previous probe and plan unchanged")
        plan = {"settings": settings, "ids": selected,
                "created_at_unix": time.time(), "reference_input": None,
                "scope": "CPU research only; shorter windows differ from the published 20s configuration; no inference yet",
                "safety_limit": "The memory estimate and process timeout do not guarantee OS or driver stability"}
        write_new(path, plan)
    return plan


def run_worker(command, log, checkpoint, timeout):
    """Bound one CPU song; never continue to another if termination is uncertain."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=stream, start_new_session=True)
        record = {"pid": process.pid, "command": command, "started_at_unix": time.time(),
                  "state": "running", "timeout_seconds": timeout}
        def terminate(state):
            record["signals"] = ["terminate"]
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                record["signals"].append("kill")
                with suppress(ProcessLookupError):
                    process.kill()
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    record["state"] = state + "-unreaped"
                    write_checkpoint(checkpoint, record)
                    raise RuntimeError(f"Worker {process.pid} did not terminate; no further songs started") from None
            record.update(state=state, returncode=code, finished_at_unix=time.time())
            write_checkpoint(checkpoint, record)

        try:
            write_checkpoint(checkpoint, record)
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate("timed-out")
            raise TimeoutError(f"CPU song exceeded {timeout}s; no further songs started") from None
        except BaseException:
            terminate("interrupted")
            raise
        record.update(state="complete" if code == 0 else "failed", returncode=code,
                      finished_at_unix=time.time())
        write_checkpoint(checkpoint, record)
        if code:
            raise RuntimeError(f"CPU song failed with exit code {code}; see {log}")


def load_model(args):
    preflight(args)
    import torch
    import yaml
    from ml_collections import ConfigDict

    if digest(args.model_dir / "model.ckpt") != MODEL_SHA:
        raise ValueError("Unexpected BS Roformer checkpoint")
    if digest(args.model_dir / "config.yaml") != CONFIG_SHA:
        raise ValueError("Unexpected published configuration")
    source = args.model_dir / "source"
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(source), "diff", "--name-only", "HEAD"], text=True).strip()
    if revision != REVISION or dirty:
        raise ValueError("Source must equal the unmodified pinned revision")
    sys.path.insert(0, str(source.resolve()))
    from models.bs_roformer import BSRoformer
    from utils.model_utils import demix

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(113)
    raw = yaml.load((args.model_dir / "config.yaml").read_text(), Loader=yaml.FullLoader)
    config = ConfigDict(raw)
    # v2 uses shorter CPU windows; the published 20s configuration is not resumed.
    config.audio.chunk_size = round(args.chunk_seconds * SAMPLE_RATE)
    config.inference.batch_size = 1
    config.training.use_amp = False
    model = BSRoformer(**raw["model"]).cpu().eval()
    state = torch.load(args.model_dir / "model.ckpt", map_location="cpu", weights_only=True, mmap=True)
    model.load_state_dict(state, strict=True)

    def validate_output(module, inputs, output):
        if output.shape[-1] != inputs[0].shape[-1] or not torch.isfinite(output).all():
            raise ValueError("Nonfinite or truncated separator window")
    model.register_forward_hook(validate_output)
    return model, config, demix


def provenance(args, source):
    return {"source": str(source.resolve()), "source_sha256": digest(source),
            "model_sha256": MODEL_SHA, "model_revision": MODEL_REVISION,
            "config_sha256": CONFIG_SHA, "source_revision": REVISION,
            "adapter_sha256": digest(__file__), "device": args.device,
            "sample_rate": 44100, "chunk_samples": round(args.chunk_seconds * SAMPLE_RATE), "overlap": 4,
            "batch_size": 1, "amp": False, "normalize": False, "cpu_threads": 2,
            "output": "mono mean of float32 lead channels; original sample count",
            "versions": {name: importlib.metadata.version(name) for name in
                         ("torch", "numpy", "librosa", "beartype", "rotary-embedding-torch", "ml-collections")},
            "host": platform.platform(), "machine": platform.machine()}


def probe(args):
    import torch

    model, config, demix = load_model(args)
    rng = np.random.default_rng(113)
    t = np.arange(round(args.chunk_seconds * SAMPLE_RATE), dtype=np.float32) / SAMPLE_RATE
    signal = (0.10 * np.sin(2 * np.pi * 220 * t) +
              0.04 * np.sin(2 * np.pi * 330 * t) +
              0.003 * rng.standard_normal(t.shape)).astype(np.float32)
    audio = np.stack((signal, signal * 0.9))[None]
    outputs, times = {}, {}
    with torch.inference_mode():
        for device in ("cpu",):
            started = time.monotonic()
            model.to(device)
            outputs[device] = model(torch.from_numpy(audio).to(device)).cpu().numpy()
            times[device] = time.monotonic() - started
            model.cpu()
    result = {"input": f"fixed synthetic {args.chunk_seconds:g}-second configured window; no reference chart",
              "times_seconds": times, "shape": list(outputs["cpu"].shape),
              "adapter_sha256": digest(__file__)}
    write_new(args.output / "cpu-probe-v2.json", result)
    print(json.dumps(result), flush=True)


def separate(args):
    import torch
    import soundfile as sf

    model, config, demix = load_model(args)
    model.to(args.device)
    stems, charts = (json.loads(p.read_text()) for p in (args.stems, args.charts))
    ids = args.ids or list(PILOT)
    if not set(ids).issubset(stems) or not set(ids).issubset(charts):
        raise ValueError("Pilot missing from source manifests")
    lead, original, selected_charts = {}, {}, {}
    for tag in ids:
        source = Path(stems[tag])
        expected = provenance(args, source)
        destination = args.output / "audio" / (tag + ".wav")
        record = args.output / "separation" / (tag + ".json")
        if record.exists():
            previous = json.loads(record.read_text())
            if previous["provenance"] != expected or digest(destination) != previous["output_sha256"]:
                raise ValueError(f"Changed frozen separation: {tag}")
        else:
            audio, rate = sf.read(source, dtype="float32", always_2d=True)
            if rate != 44100 or audio.shape[1] != 2 or not np.isfinite(audio).all():
                raise ValueError("Need finite stereo HTDemucs at 44.1 kHz")
            started = time.monotonic()
            result = demix(config, model, audio.T, torch.device(args.device), "bs_roformer", pbar=False)["Vocals"]
            if result.shape != audio.T.shape or not np.isfinite(result).all():
                raise ValueError("Separator changed sample clock or returned nonfinite output")
            mono = result.mean(axis=0).astype(np.float32)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp.wav")
            try:
                sf.write(temporary, mono, rate, subtype="FLOAT")
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
            payload = {"provenance": expected, "output_sha256": digest(destination),
                       "samples": len(audio), "seconds": time.monotonic() - started,
                       "rms_input": float(np.sqrt(np.mean(audio ** 2))),
                       "rms_output": float(np.sqrt(np.mean(mono ** 2)))}
            write_new(record, payload)
            print(tag, json.dumps({k:payload[k] for k in ("samples", "seconds", "rms_output")}), flush=True)
        lead[tag], original[tag], selected_charts[tag] = str(destination.resolve()), str(source.resolve()), charts[tag]
    if args.worker:
        return
    for name, value in (("lead-stems.json", lead), ("original-stems.json", original),
                        ("predicted-charts.json", selected_charts)):
        target = args.output / name
        if target.exists():
            if json.loads(target.read_text()) != value:
                raise ValueError("Use a new output directory for a different cohort")
        else:
            write_new(target, value)


def worker_command(args, stage, ids):
    return [sys.executable, str(Path(__file__).resolve()), stage, "--worker",
            "--model-dir", str(args.model_dir.resolve()), "--output", str(args.output.resolve()),
            "--stems", str(args.stems.resolve()), "--charts", str(args.charts.resolve()),
            "--device", "cpu", "--chunk-seconds", str(args.chunk_seconds),
            "--timeout-seconds", str(args.timeout_seconds), "--ids", *ids]


def bounded_probe(args):
    plan = prepare_plan(args)
    run_worker(worker_command(args, "probe", plan["ids"]), args.output / "logs" / "probe.log",
               args.output / "execution" / "probe.json", args.timeout_seconds)
    if not (args.output / "cpu-probe-v2.json").is_file():
        raise RuntimeError("CPU probe exited without its result")


def bounded_separation(args):
    plan = prepare_plan(args)
    stems = json.loads(args.stems.read_text(encoding="utf-8"))
    charts = json.loads(args.charts.read_text(encoding="utf-8"))
    if not set(plan["ids"]).issubset(stems) or not set(plan["ids"]).issubset(charts):
        raise ValueError("Pilot missing from source manifests")
    for tag in plan["ids"]:
        record = args.output / "separation" / (tag + ".json")
        output = args.output / "audio" / (tag + ".wav")
        if record.exists():
            previous = json.loads(record.read_text(encoding="utf-8"))
            if previous["provenance"] != provenance(args, Path(stems[tag])) or (
                digest(output) != previous["output_sha256"]
            ):
                raise ValueError(f"Changed frozen separation: {tag}")
            continue
        run_worker(worker_command(args, "separate", [tag]), args.output / "logs" / (tag + ".log"),
                   args.output / "execution" / (tag + ".json"), args.timeout_seconds)
        if not record.is_file():
            raise RuntimeError(f"Worker exited without a frozen separation: {tag}")
    manifests = {
        "lead-stems.json": {tag: str((args.output / "audio" / (tag + ".wav")).resolve()) for tag in plan["ids"]},
        "original-stems.json": {tag: str(Path(stems[tag]).resolve()) for tag in plan["ids"]},
        "predicted-charts.json": {tag: charts[tag] for tag in plan["ids"]},
    }
    for name, value in manifests.items():
        path = args.output / name
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != value:
                raise ValueError("Changed frozen manifest")
        else:
            write_new(path, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("plan", "probe", "separate"))
    for name in ("model-dir", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--stems", type=Path)
    parser.add_argument("--charts", type=Path)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    parser.add_argument("--chunk-seconds", type=float, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        preflight(args)
        if args.stems is None or args.charts is None:
            raise ValueError("v2 stages need --stems and --charts, even when only preparing a plan")
        prepare_plan(args)
    except ValueError as exc:
        parser.error(str(exc))
    if args.stage == "plan":
        print(args.output / "plan-v2.json")
    elif args.stage == "probe":
        if args.worker:
            probe(args)
        else:
            bounded_probe(args)
    elif args.worker:
        separate(args)
    else:
        bounded_separation(args)


if __name__ == "__main__":
    main()
