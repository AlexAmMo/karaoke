"""Isolate each GAME window in one CPU worker; freeze both arms before evaluation.

This is a new RNG configuration: seed 113 restarts for every window. It does not
claim numerical equivalence with historical GAME runs using a continuous RNG.
Window/context selection, ownership, stitching and chart projection are reused.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lead_vocals as guard

ROOT = Path(__file__).resolve().parents[2]
GUARD_SHA = "5cc80cefe57a4088701dc3ea1e9bfa2be3ee5120754c4d6a702ccf184ed3ef97"
SEED = 113
WINDOW_TIMEOUT = 30
ARM_TIMEOUT = 900
RNG_POLICY = "Reset ONNX seed 113 before creating the segmenter in every fresh window worker"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def freeze(path, value):
    if path.exists():
        if read_json(path) != value:
            raise ValueError(f"Frozen data changed: {path}")
    else:
        guard.write_new(path, value)


def freeze_text(path, text):
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError("Frozen chart changed")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sources():
    names = ("scripts/experiments/windowed_game.py", "scripts/experiments/conditioned_notes.py",
             "scripts/experiments/melody_compare.py", "scripts/experiments/lead_vocals.py",
             "src/karaoke/generation_worker.py", "src/karaoke/songs.py",
             "src/karaoke/generation_metrics.py")
    hashes = {name: guard.digest(ROOT / name) for name in names}
    if hashes["scripts/experiments/lead_vocals.py"] != GUARD_SHA:
        raise ValueError("Resource supervisor differs from the fixed v3 guard")
    return hashes


def game_metadata(cache):
    sys.path.insert(0, str(ROOT / "src"))
    from karaoke.generation_worker import CREATOR_REV
    source = cache / ("creator-" + CREATOR_REV) / "services/game_notes.py"
    spec = importlib.util.spec_from_file_location("window_game_metadata", source)
    game = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(game)  # Definitions and NumPy only, no sessions or model loads.
    return {"adapter_sha256": guard.digest(source),
            "model_sha256": {name: value[1] for name, value in game.MODEL_FILES.items()},
            "model_folder": str(Path(game.model_folder(str(cache))).resolve())}


def prepare_plan(args):
    charts, stems = read_json(args.charts), read_json(args.stems)
    if set(charts) != set(stems) or not set(args.ids).issubset(charts):
        raise ValueError("Selected recordings must belong to both frozen manifests")
    settings = {"schema": 1, "arm": args.arm, "cohort_ids": list(charts), "selected_ids": args.ids,
                "mode": "free", "seed": SEED, "rng_policy": RNG_POLICY,
                "cache": str(args.cache.resolve()), "threads": args.threads,
                "onnx_memory_policy": "no-arena", "window_timeout_seconds": WINDOW_TIMEOUT,
                "arm_timeout_seconds": ARM_TIMEOUT, "worker_memory_stop_bytes": guard.WORKER_MEMORY_STOP,
                "window_policy": "Unchanged conditioned_notes.infer: 12s core, 1.5s context each side",
                "source_sha256": sources(), "game": game_metadata(args.cache.resolve()),
                "onnxruntime": importlib.metadata.version("onnxruntime"),
                "manifests_sha256": {"charts": guard.digest(args.charts), "stems": guard.digest(args.stems)},
                "inputs": {tag: {"stem": str(Path(stems[tag]).resolve()),
                                 "stem_sha256": guard.digest(Path(stems[tag])),
                                 "chart": str(Path(charts[tag]).resolve()),
                                 "chart_sha256": guard.digest(Path(charts[tag]))} for tag in args.ids},
                "reference_input": None, "historical_numerical_equivalence": False}
    path = args.output / "plan.json"
    if not path.exists() and args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a new empty output directory")
    freeze(path, settings)
    return settings


@contextmanager
def arm_deadline(seconds):
    """A wall-clock timer interrupts the inner supervisor, which reaps its child."""
    if not hasattr(signal, "setitimer"):
        raise RuntimeError("This experiment requires POSIX interval timers")
    def timeout(_signum, _frame):
        raise TimeoutError("Global arm deadline expired; no further windows started")
    def interrupted(_signum, _frame):
        raise InterruptedError("Parent terminated; stop and reap the active window")
    previous_alarm = signal.signal(signal.SIGALRM, timeout)
    previous_term = signal.signal(signal.SIGTERM, interrupted)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_alarm)
        signal.signal(signal.SIGTERM, previous_term)


def freeze_waveform(path, waveform):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        np.save(stream, waveform, allow_pickle=False)
    try:
        if path.exists():
            if guard.digest(path) != guard.digest(temporary):
                raise ValueError("Frozen window samples changed")
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_response(folder, request):
    execution = read_json(folder / "execution.json")
    response = read_json(folder / "response.json")
    if execution["state"] != "complete" or execution["returncode"] != 0:
        raise ValueError("Window did not complete successfully")
    if response["request_sha256"] != guard.digest(folder / "request.json"):
        raise ValueError("Window response belongs to another request")
    if response["rng_policy"] != RNG_POLICY or response["seed"] != SEED:
        raise ValueError("Window RNG policy changed")
    events = response["events"]
    for event in events:
        if len(event) != 4 or not all(math.isfinite(event[i]) for i in (0, 1, 3)):
            raise ValueError("Nonfinite or malformed raw event")
    freeze(folder / "frozen.json", {"request_sha256": guard.digest(folder / "request.json"),
                                   "response_sha256": guard.digest(folder / "response.json"),
                                   "execution_sha256": guard.digest(folder / "execution.json"),
                                   "resources_sha256": guard.digest(folder / "execution.resources.jsonl"),
                                   "waveform_sha256": request["waveform_sha256"]})
    return events


class WindowBackend:
    SAMPLE_RATE = 44100

    def __init__(self, output, plan, tag, runner=guard.run_worker):
        self.output, self.plan, self.tag, self.runner = output, plan, tag, runner
        self.windows = []

    def extract(self, _folder, waveform, known, language):
        if waveform.dtype != np.float32 or waveform.ndim != 1 or not np.isfinite(waveform).all():
            raise ValueError("Expected the unchanged finite mono float32 window")
        folder = self.output / "window-workers" / self.tag / f"{len(self.windows) + 1:04d}"
        array_path = folder / "waveform.npy"
        freeze_waveform(array_path, waveform)
        request = {"plan": self.plan, "tag": self.tag, "window_index": len(self.windows) + 1,
                   "waveform": str(array_path.resolve()), "waveform_sha256": guard.digest(array_path),
                   "sample_count": len(waveform), "known": list(known), "language": language,
                   "seed": SEED, "rng_policy": RNG_POLICY}
        freeze(folder / "request.json", request)
        if not (folder / "response.json").exists():
            if (folder / "execution.json").exists():
                raise RuntimeError("Previous window attempt is incomplete; do not retry in the same directory")
            command = [sys.executable, str(Path(__file__).resolve()), "worker", "--request",
                       str((folder / "request.json").resolve()), "--result",
                       str((folder / "response.json").resolve())]
            self.runner(command, folder / "worker.log", folder / "execution.json", WINDOW_TIMEOUT)
        events = validate_response(folder, request)
        self.windows.append({"folder": str(folder.resolve()), "frozen_sha256": guard.digest(folder / "frozen.json")})
        return events


def single_extract(runtime, game, make_options, folder, waveform, known, language, threads):
    """One session group and one extraction; the fresh process owns all buffers."""
    options = make_options(threads, "no-arena")
    def session(name):
        return runtime.InferenceSession(str(Path(folder) / (name + ".onnx")),
                                        sess_options=options, providers=["CPUExecutionProvider"])
    game._sessions[folder] = {name: session(name) for name in ("encoder", "estimator", "dur2bd", "bd2dur")}
    runtime.set_seed(SEED)
    game._sessions[folder]["segmenter"] = session("segmenter")
    return game.extract(folder, waveform, known, language)


def worker(request_path, result_path):
    request = read_json(request_path)
    plan = request["plan"]
    if sources() != plan["source_sha256"] or request["seed"] != SEED or request["rng_policy"] != RNG_POLICY:
        raise ValueError("Worker code or random policy differs from the plan")
    waveform = np.load(request["waveform"], allow_pickle=False)
    if (guard.digest(Path(request["waveform"])) != request["waveform_sha256"] or
        waveform.dtype != np.float32 or waveform.shape != (request["sample_count"],) or
        not np.isfinite(waveform).all()):
        raise ValueError("Window samples changed")
    import conditioned_notes as existing
    existing.load_engine(Path(plan["cache"]))
    from services import game_notes
    folder = game_notes.model_folder(plan["cache"])
    if guard.digest(Path(game_notes.__file__)) != plan["game"]["adapter_sha256"]:
        raise ValueError("Pinned GAME adapter changed")
    for name, sha in plan["game"]["model_sha256"].items():
        if guard.digest(Path(folder) / name) != sha:
            raise ValueError("Pinned GAME weights changed")
    if existing.ort.__version__ != plan["onnxruntime"]:
        raise ValueError("ONNX Runtime differs from the plan")
    started = time.monotonic()
    events = single_extract(existing.ort, game_notes, existing.session_options, folder, waveform,
                            request["known"], request["language"], plan["threads"])
    guard.write_new(result_path, {"request_sha256": guard.digest(request_path),
                                 "seed": SEED, "rng_policy": RNG_POLICY,
                                 "events": [[float(a), float(b), bool(v), float(m)] for a, b, v, m in events],
                                 "seconds": time.monotonic() - started})


def run_arm(args):
    import resource
    sampler = guard.memory_sampler()
    record = {"pid": os.getpid(), "started_at_unix": time.time(), "state": "running",
              "deadline_seconds": ARM_TIMEOUT, "parent_initial_memory": sampler(os.getpid())}
    plan_ready = False
    try:
        with arm_deadline(ARM_TIMEOUT):
            plan = prepare_plan(args)
            plan_ready = True
            import conditioned_notes as existing
            for tag in plan["selected_ids"]:
                source = plan["inputs"][tag]
                chart, stem = Path(source["chart"]), Path(source["stem"])
                spans, words, meta = existing.predicted_anchors(chart)
                if not spans:
                    raise ValueError("No predicted syllables")
                language = meta.get("LANGUAGE", "").lower()
                language = {"english": "en", "spanish": "es"}.get(language, language)
                backend = WindowBackend(args.output, plan, tag)
                windows = []
                events, duration = existing.infer(stem, spans, words, "free", language, backend, "unused", windows)
                target = args.output / "free" / tag
                target.mkdir(parents=True, exist_ok=True)
                freeze(target / "events.json", {"events": events, "provenance": plan})
                freeze(target / "windows.json", {"windows": windows, "provenance": plan})
                charts = {}
                for method, text in existing.transform(chart, events, duration).items():
                    path = target / (method + ".txt")
                    freeze_text(path, text)
                    charts[method] = guard.digest(path)
                freeze(target / "frozen.json", {"provenance": plan, "charts": charts,
                                               "events_sha256": guard.digest(target / "events.json"),
                                               "windows_sha256": guard.digest(target / "windows.json"),
                                               "window_workers": backend.windows, "duration_s": duration})
            record["state"] = "complete"
    except BaseException as exc:
        record.update(state="failed", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        record.update(finished_at_unix=time.time(), parent_final_memory=sampler(os.getpid()),
                      parent_max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      memory_scope="Parent max RSS from macOS rusage; footprint only at initial/final checkpoints")
        if plan_ready:
            guard.write_checkpoint(args.output / "parent-execution.json", record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("plan", "run", "worker"))
    for name in ("charts", "stems", "cache", "output", "request", "result"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--arm", choices=("original", "lead"))
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    if args.stage == "worker":
        if not args.request or not args.result:
            parser.error("worker requires --request and --result")
        worker(args.request, args.result)
    else:
        if not all((args.charts, args.stems, args.cache, args.output, args.ids, args.arm)) or args.threads != 2:
            parser.error("plan/run require manifests, cache, output, IDs, arm and exactly two threads")
        if args.stage == "plan":
            prepare_plan(args)
        else:
            run_arm(args)


if __name__ == "__main__":
    main()
