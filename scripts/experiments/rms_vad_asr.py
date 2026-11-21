"""Paired acoustic lyrics experiment; planning/preparation never load an ASR model.

The primary comparison is mix-rms versus mix-native on all four fixed pilot
recordings. Both vocal-source arms are retained. No reference lyrics are read.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
PILOT = ("bad-bunny-amorfoda", "fito-paez-11-y-6",
         "jonathan-coulton-mr-fancy-pants", "northern-star")
ARMS = ("mix-native", "mix-rms", "vocals-native", "vocals-rms")
MODEL_REVISION = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
MODEL_SHA = "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da"
RATE = 16000


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def check(item):
    path = Path(item["path"])
    if digest(path) != item["sha256"]:
        raise ValueError(f"Input changed: {path}")
    return path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def json_scalar(value):
    import numpy as np
    if isinstance(value, np.generic):
        scalar = value.item()
        if type(scalar) in (bool, int, float, str):
            return scalar
    raise TypeError(f"Unsupported JSON scalar: {type(value).__module__}.{type(value).__name__}")


def save(path, value):
    # Validate every value before creating the immutable evidence file.
    serialized = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, default=json_scalar)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(serialized + "\n")


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def plan(args):
    if args.output.exists():
        raise ValueError("Use a new output directory")
    source = load(args.cuts / "plan.json")
    frozen = load(args.cuts / "frozen.json")
    if digest(args.cuts / "plan.json") != frozen["plan_sha256"]:
        raise ValueError("Changed segmentation plan")
    entries = {e["id"]: e for e in source["entries"]}
    rows = {r["id"]: r for r in frozen["rows"]}
    weights = [record(p) | {"bytes": p.stat().st_size}
               for p in sorted(args.model.iterdir()) if p.is_file()]
    if digest(args.model / "model.bin") != MODEL_SHA:
        raise ValueError("Expected the existing pinned Turbo weights")
    inputs = []
    for tag in PILOT:
        entry = entries[tag]
        check(entry["audio"])
        check(entry["stem"])
        cuts = args.cuts / tag / "cuts.json"
        if digest(cuts) != rows[tag]["cuts_sha256"]:
            raise ValueError("Changed frozen cuts")
        inputs.append({"id": tag, "language": entry["language"],
                       "audio": entry["audio"], "stem": entry["stem"],
                       "cuts": record(cuts), "stem_samples": entry["samples"],
                       "stem_rate": entry["sample_rate"]})
    code = {name: record(path) for name, path in {
        "adapter": __file__, "production": ROOT / "src/karaoke/generation_worker.py",
        "supervisor": ROOT / "scripts/experiments/yourmt3_notes.py",
        "memory_monitor": ROOT / "scripts/experiments/lead_vocals.py",
    }.items()}
    versions = {name: importlib.metadata.version(name) for name in
                ("numpy", "scipy", "soundfile", "faster-whisper", "ctranslate2")}
    settings = {"created_utc": datetime.now(timezone.utc).isoformat(), "code": code,
        "segmentation_plan": record(args.cuts / "plan.json"),
        "segmentation_freeze": record(args.cuts / "frozen.json"), "inputs": inputs,
        "model_directory": str(args.model.resolve()), "model_revision": MODEL_REVISION,
        "model_files": weights, "versions": versions, "python": sys.version,
        "primary": ["mix-rms", "mix-native"], "arms": ARMS,
        "planned_transcriptions": 16, "no_selection_by_song": True,
        "references_opened": False, "status": "planned; no ASR executed",
        "decode": {"device": "cpu", "compute_type": "int8", "cpu_threads": 3,
                   "beam_size": 5, "word_timestamps": True, "vad_filter": False,
                   "condition_on_previous_text": False, "batch": 1},
        "preparation": {"mix": "production ffmpeg 44100 Hz stereo FLOAT WAV",
            "mono_and_resample": "production float32 channel mean then scipy resample_poly to 16000 Hz",
            "shared_waveform_for_native_and_rms": True,
            "max_duration_seconds": 300, "max_channels": 2,
            "max_input_rate": 48000, "one_source_at_a_time_before_model": True,
            "ffmpeg_timeout_seconds": 120,
            "rms_clock": "round(original_sample * 16000 / original_rate); absolute output clock, no fitted shift",
            "length_discrepancy": "require prepared mix/vocal length difference <=2 samples; preserve complete native input; clip RMS final bound to each input and record delta",
            "words": "retain raw model words including punctuation and nonpositive duration; production filtering only in separate product_lines",
            "boundaries": "retain and flag crossing times; never string-deduplicate repeated words"},
        "resources": {"worker_rss_and_footprint_stop_bytes": args.memory_limit_mib * 1024**2,
            "sample_seconds": .05, "timeout_seconds_per_arm": 600,
            "synthetic_timeout_seconds": args.synthetic_timeout_seconds,
            "one_fresh_worker_per_song_and_arm": True,
            "synthetic_control_required_before_cohort": True,
            "load_feasibility": "unmeasured for this frozen budget; loading the 1.618 GB weights and int8 conversion may exceed it",
            "failure": "preserve partial evidence and stop cohort, never start an unconfirmed-reaped successor",
            "limit": "sampled stop threshold, not an OS allocation limit or peak guarantee"},
        "cost_estimate": {"minutes": [20, 30], "basis": "previous Turbo CPU timings roughly70–100s per recording; additional load/chunk overhead unknown",
                          "maximum_worker_minutes": 160}, "selftest": selftest()}
    if args.reuse_prepared is not None:
        settings["reuse_prepared"] = {
            "source_plan": record(args.reuse_prepared / "plan.json"),
            "source_audio_freeze": record(args.reuse_prepared / "audio-frozen.json")}
    if args.resource_review is not None:
        settings["budget_justification"] = {name: record(args.resource_review / name) for name in (
            "model-metadata-only.json", "import-only/frozen.json", "sources/manifest-extended.json")}
    save(args.output / "plan.json", settings)
    for name, item in code.items():
        target = args.output / "source-snapshot" / (name + ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(check(item).read_bytes())
    print(json.dumps({"plan_sha256": digest(args.output / "plan.json"), "transcriptions": 16}))


def verify_plan(output):
    settings = load(output / "plan.json")
    for item in settings["code"].values():
        check(item)
    for name, expected in settings["versions"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError("Dependency version changed: " + name)
    return settings


def resample_source(path):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    info = sf.info(path)
    if not 0 < info.duration <= 300 or not 0 < info.channels <= 2 or info.samplerate > 48000:
        raise ValueError("Source exceeds the predeclared preparation bounds")
    samples, rate = sf.read(path, dtype="float32", always_2d=True)
    if not np.isfinite(samples).all():
        raise ValueError("Non-finite audio")
    factor = math.gcd(RATE, rate)
    waveform = resample_poly(samples.mean(axis=1), RATE // factor, rate // factor)
    return waveform


def prepare(args):
    import resource
    import soundfile as sf
    started = time.monotonic()
    settings = verify_plan(args.output)
    if "reuse_prepared" in settings:
        origin = settings["reuse_prepared"]
        source_plan = load(check(origin["source_plan"]))
        source_audio = load(check(origin["source_audio_freeze"]))
        if source_audio["plan_sha256"] != origin["source_plan"]["sha256"]:
            raise ValueError("Reused audio belongs to another source plan")
        for key in ("inputs", "segmentation_plan", "segmentation_freeze", "decode", "preparation"):
            if source_plan[key] != settings[key]:
                raise ValueError("Changed audio or decoding assumptions: " + key)
        prepared = source_audio["prepared"]
        expected = {(r["id"], kind) for r in settings["inputs"] for kind in ("mix", "vocals")}
        if len(prepared) != 8 or {(r["id"], r["kind"]) for r in prepared} != expected:
            raise ValueError("Expected exactly eight previously prepared sources")
        for row in prepared:
            info = sf.info(check(row["audio"]))
            check(row["prepared_from"])
            if (info.samplerate, info.channels, info.frames) != (RATE, 1, row["samples"]):
                raise ValueError("Changed reused audio geometry")
        save(args.output / "audio-frozen.json", {"plan_sha256": digest(args.output / "plan.json"),
            "prepared": prepared, "reused_from": origin, "reencoded": False,
            "asr_executed": False, "references_opened": False,
            "verification_wall_seconds": time.monotonic() - started})
        print(json.dumps({"verified_reused_sources": len(prepared), "reencoded": False, "asr_executed": False}))
        return
    prepared = []
    for row in settings["inputs"]:
        folder = args.output / "audio" / row["id"]
        folder.mkdir(parents=True)
        decoded = folder / "mix-44100.wav"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(check(row["audio"])),
            "-map", "0:a:0", "-vn", "-ar", "44100", "-ac", "2", "-c:a", "pcm_f32le", str(decoded)],
            check=True, timeout=120)
        for kind, path in (("mix", decoded), ("vocals", check(row["stem"]))):
            waveform = resample_source(path)
            target = folder / (kind + "-16000.wav")
            sf.write(target, waveform, RATE, subtype="FLOAT")
            prepared.append({"id": row["id"], "kind": kind, "samples": len(waveform),
                             "audio": record(target), "prepared_from": record(path)})
            del waveform
        lengths = [r["samples"] for r in prepared if r["id"] == row["id"]]
        if abs(lengths[0] - lengths[1]) > 2:
            raise ValueError("Prepared source clocks differ by more than two samples")
    assert "torch" not in sys.modules and "faster_whisper" not in sys.modules
    maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    save(args.output / "audio-frozen.json", {"plan_sha256": digest(args.output / "plan.json"),
         "prepared": prepared, "asr_executed": False, "references_opened": False,
         "wall_seconds": time.monotonic() - started,
         "max_resident_bytes": maximum if sys.platform == "darwin" else maximum * 1024})
    print(json.dumps({"prepared_sources": len(prepared), "asr_executed": False}))


def slices(cuts, frames, native=False):
    if native:
        return [{"start": 0, "end": frames, "clipped_samples": 0}]
    result = []
    for segment in cuts["segments"]:
        first = round(segment["start_sample"] * RATE / cuts["sample_rate"])
        last = round(segment["end_sample"] * RATE / cuts["sample_rate"])
        if not 0 <= first < min(last, frames):
            raise ValueError("Empty or invalid mapped interval")
        result.append({"start": first, "end": min(last, frames),
                       "clipped_samples": max(0, last - frames)})
    if any(a["end"] > b["start"] for a, b in zip(result, result[1:])):
        raise ValueError("Mapped intervals overlap")
    return result


def absolute_word(word, start, end):
    item = dict(word)
    item["local_start"], item["local_end"] = item["start"], item["end"]
    item["start"] += start / RATE
    item["end"] += start / RATE
    item["crosses_input_boundary"] = item["local_start"] < 0 or item["local_end"] > (end - start) / RATE
    item["nonpositive_duration"] = item["local_end"] <= item["local_start"]
    return item


class RecordingModel:
    def __init__(self, model):
        self.model, self.raw = model, []

    def transcribe(self, *args, **kwargs):
        segments, detail = self.model.transcribe(*args, **kwargs)
        def capture():
            for segment in segments:
                self.raw.append(asdict(segment) if is_dataclass(segment) else segment._asdict())
                yield segment
        return capture(), detail


def worker(args):
    settings = verify_plan(args.output)
    for item in settings["model_files"]:
        check(item)
    import soundfile as sf
    if args.control:
        import numpy as np
        output = args.output / "synthetic-control"
        audio = output / "silence.wav"
        sf.write(audio, np.zeros(RATE, dtype=np.float32), RATE, subtype="FLOAT")
        source = {"audio": record(audio)}
        row = {"language": "es"}
        bounds = [{"start": 0, "end": RATE, "clipped_samples": 0}]
    else:
        prepared = load(args.output / "audio-frozen.json")
        if prepared["plan_sha256"] != digest(args.output / "plan.json"):
            raise ValueError("Changed preparation plan")
        row = next(r for r in settings["inputs"] if r["id"] == args.song)
        kind, segmentation = args.arm.split("-")
        source = next(r for r in prepared["prepared"] if r["id"] == args.song and r["kind"] == kind)
        audio = check(source["audio"])
        cuts = load(check(row["cuts"]))
        bounds = slices(cuts, source["samples"], native=segmentation == "native")
        output = args.output / "results" / args.song / args.arm
    production = module(check(settings["code"]["production"]), "rms_asr_production")
    save(output / "before-model.json", {"unix_time": time.time(), "model_sha256": MODEL_SHA})
    from faster_whisper import WhisperModel
    save(output / "after-import.json", {"unix_time": time.time()})

    model = RecordingModel(WhisperModel(settings["model_directory"], device="cpu", compute_type="int8", cpu_threads=3))
    save(output / "after-model.json", {"unix_time": time.time()})
    started = time.monotonic()
    all_words, all_lines = [], []
    with sf.SoundFile(audio) as stream:
        for index, interval in enumerate(bounds):
            first, last = interval["start"], interval["end"]
            stream.seek(first)
            values = stream.read(last - first, dtype="float32")
            temporary = output / "current-input.wav"
            sf.write(temporary, values, RATE, subtype="FLOAT")
            del values
            model.raw = []
            lines, detected = production.transcribe(temporary, settings["model_directory"], row["language"], model=model)
            raw_words = [absolute_word(w, first, last) for seg in model.raw for w in (seg["words"] or [])]
            absolute_lines = [[dict(w, start=w["start"] + first / RATE, end=w["end"] + first / RATE)
                               for w in line] for line in lines]
            save(output / f"part-{index:03d}.json", {"interval": interval, "language": detected,
                 "raw_segments_local": model.raw, "raw_words_absolute": raw_words,
                 "product_lines_absolute": absolute_lines})
            all_words.extend(raw_words)
            all_lines.extend(absolute_lines)
            temporary.unlink()
    save(output / "prediction.json", {"id": "synthetic-silence" if args.control else args.song, "arm": args.arm,
        "plan_sha256": digest(args.output / "plan.json"), "audio": source["audio"],
        "intervals": bounds, "raw_words": all_words, "product_lines": all_lines,
        "seconds_after_model_load": time.monotonic() - started, "references_opened": False})


def controller(args):
    settings = verify_plan(args.output)
    monitor = module(check(settings["code"]["memory_monitor"]), "rms_asr_monitor")
    supervisor = module(check(settings["code"]["supervisor"]), "rms_asr_supervisor")
    if settings["code"]["memory_monitor"]["sha256"] != supervisor.MONITOR_SHA:
        raise ValueError("Supervisor's recorded monitor hash differs")
    sampler = monitor.memory_sampler()
    environment = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", OMP_NUM_THREADS="3",
        OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="3", HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    return settings, supervisor, sampler, environment


def run_planned_worker(settings, supervisor, command, output, sampler, environment, *, control):
    resources = settings["resources"]
    limit = resources["worker_rss_and_footprint_stop_bytes"]
    timeout = resources["synthetic_timeout_seconds"] if control else resources["timeout_seconds_per_arm"]
    if limit not in (2048 * 1024**2, 4096 * 1024**2) or not 0 < timeout <= 600:
        raise ValueError("Unsupported frozen resource budget")
    return supervisor.run_bounded(command, output, limit, timeout, sampler, environment)


def synthetic(args):
    settings, supervisor, sampler, environment = controller(args)
    output = args.output / "synthetic-control"
    output.mkdir()
    command = [sys.executable, str(Path(__file__).resolve()), "worker", "--output", str(args.output), "--control"]
    resources = run_planned_worker(settings, supervisor, command, output, sampler, environment, control=True)
    if not resources["reaped"]:
        raise RuntimeError("Synthetic worker was not confirmed reaped")
    save(args.output / "synthetic-frozen.json", {"plan_sha256": digest(args.output / "plan.json"),
         "prediction": record(output / "prediction.json"), "resources": record(output / "resources.json"),
         "model_sha256": MODEL_SHA, "reaped": True,
         "scope": "one second silence tests loading and API only; not song peak memory or lyric quality"})


def execute(args):
    settings, supervisor, sampler, environment = controller(args)
    control = load(args.output / "synthetic-frozen.json")
    if control["plan_sha256"] != digest(args.output / "plan.json") or not control["reaped"]:
        raise ValueError("A successful supervised synthetic control of this plan is required")
    check(control["prediction"])
    check(control["resources"])
    results = []
    for row in settings["inputs"]:
        for arm in ARMS:
            output = args.output / "results" / row["id"] / arm
            output.mkdir(parents=True)
            command = [sys.executable, str(Path(__file__).resolve()), "worker", "--output",
                       str(args.output), "--song", row["id"], "--arm", arm]
            resources = run_planned_worker(settings, supervisor, command, output, sampler, environment, control=False)
            if not resources["reaped"]:
                raise RuntimeError("Worker was not confirmed reaped")
            results.append({"id": row["id"], "arm": arm,
                "prediction": record(output / "prediction.json"), "resources": record(output / "resources.json")})
    save(args.output / "frozen.json", {"plan_sha256": digest(args.output / "plan.json"),
        "prepared_sha256": digest(args.output / "audio-frozen.json"), "results": results,
        "present": len(results), "planned": 16, "references_opened": False})


def selftest():
    cuts = {"sample_rate": 44100, "segments": [
        {"start_sample": 0, "end_sample": 10001},
        {"start_sample": 10001, "end_sample": 22051}]}
    result = slices(cuts, 8001)
    assert result[0]["end"] == result[1]["start"]
    assert sum(r["end"] - r["start"] for r in result) == round(22051 * RATE / 44100)
    assert slices(cuts, 8001, True) == [{"start": 0, "end": 8001, "clipped_samples": 0}]
    raw = {"word": "la", "start": -.01, "end": 1.01, "probability": .9}
    left = absolute_word(raw, 16000, 32000)
    right = absolute_word(raw, 32000, 48000)
    assert left["crosses_input_boundary"] and right["crosses_input_boundary"]
    assert [left["word"], right["word"]] == ["la", "la"]
    assert left["start"] == .99 and right["end"] == 3.01
    assert raw["start"] == -.01
    assert absolute_word({"word": "!", "start": .5, "end": .5}, 0, 16000)["nonpositive_duration"]
    product_check = product_control()
    budget_check = budget_control()
    serialization_check = serialization_control()
    assert "torch" not in sys.modules and "faster_whisper" not in sys.modules
    return {"integer_clock_shared_boundary": True, "native_full_input": True,
            "crossing_words_retained": True, "repetitions_preserved": True,
            "nonpositive_duration_retained": True, "production_call_and_raw_capture": product_check,
            "plan_budget_reaches_supervisor": budget_check,
            "numpy_scalars_nested_json_without_rounding": serialization_check}


def serialization_control():
    from dataclasses import make_dataclass
    import tempfile
    import numpy as np

    Word = make_dataclass("Word", [("word", str), ("start", float), ("end", float), ("probability", float)])
    Segment = make_dataclass("Segment", [("words", list), ("tokens", list)])
    precise = np.nextafter(np.float64(.12345678901234567), np.float64(1))
    word = Word("synthetic", precise, np.float64(.23456789012345678), np.float32(.9375))
    segment = Segment([word], [np.int64(17)])
    raw = asdict(segment)
    absolute = absolute_word(raw["words"][0], 7, 16000)
    payload = {"raw_segments_local": [raw], "raw_words_absolute": [absolute], "numpy_flag": np.bool_(True)}
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "valid.json"
        save(target, payload)
        decoded = load(target)
        assert set(decoded) == set(payload)
        stored = decoded["raw_words_absolute"][0]
        assert set(stored) == set(absolute)
        assert stored["local_start"] == float(precise)
        assert stored["start"] == float(precise + 7 / RATE)
        assert decoded["raw_segments_local"][0]["words"][0]["probability"] == float(word.probability)
        assert decoded["raw_segments_local"][0]["tokens"] == [17]
        assert type(decoded["numpy_flag"]) is bool
        assert type(stored["crosses_input_boundary"]) is bool
        assert type(stored["nonpositive_duration"]) is bool
        json.dumps(decoded, allow_nan=False)
        for index, bad in enumerate((np.float64(np.nan), np.float32(np.inf), np.float64(-np.inf))):
            invalid = Path(tmp) / f"invalid-{index}.json"
            try:
                save(invalid, {"value": bad})
            except ValueError:
                assert not invalid.exists()
            else:
                raise AssertionError("Non-finite number accepted")
        try:
            save(Path(tmp) / "unsupported.json", {"value": object()})
        except TypeError:
            assert not (Path(tmp) / "unsupported.json").exists()
        else:
            raise AssertionError("Unsupported object silently converted to text")
    return True


def budget_control():
    from types import SimpleNamespace
    observed = []
    def fake_runner(command, output, limit, timeout, sampler, environment):
        observed.append((limit, timeout))
        return {"reaped": True}
    supervisor = SimpleNamespace(run_bounded=fake_runner)
    for mib in (2048, 4096):
        settings = {"resources": {"worker_rss_and_footprint_stop_bytes": mib * 1024**2,
                    "synthetic_timeout_seconds": 120, "timeout_seconds_per_arm": 600}}
        for control in (True, False):
            result = run_planned_worker(settings, supervisor, [], Path("unused"), None, {}, control=control)
            assert result["reaped"]
    assert observed == [(2048 * 1024**2, 120), (2048 * 1024**2, 600),
                        (4096 * 1024**2, 120), (4096 * 1024**2, 600)]
    return True


def product_control():
    """Exercise the real production function with a fake recognizer, never ASR."""
    from dataclasses import make_dataclass
    import tempfile
    from types import SimpleNamespace
    import numpy as np
    import soundfile as sf

    Word = make_dataclass("Word", [("word", str), ("start", float), ("end", float), ("probability", float)])
    Segment = make_dataclass("Segment", [("words", list)])
    class Fake:
        def transcribe(self, waveform, **kwargs):
            assert kwargs == {"language": "es", "beam_size": 5, "word_timestamps": True,
                              "vad_filter": False, "condition_on_previous_text": False}
            assert waveform.dtype == np.float32 and len(waveform) == RATE
            return iter([Segment([Word(" la ", 0, .2, .9), Word("!", .2, .2, .5),
                                  Word(" la ", .3, .5, .8)])]), SimpleNamespace(language="es")
    assert "faster_whisper" not in sys.modules
    sys.modules["faster_whisper"] = SimpleNamespace(WhisperModel=None)
    try:
        production = module(ROOT / "src/karaoke/generation_worker.py", "rms_asr_test_production")
        recorder = RecordingModel(Fake())
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.wav"
            sf.write(audio, np.zeros(RATE, dtype=np.float32), RATE, subtype="FLOAT")
            lines, language = production.transcribe(audio, "unused", "es", model=recorder)
        assert language == "es" and [w["word"] for w in lines[0]] == ["la", "la"]
        assert [w["word"] for w in recorder.raw[0]["words"]] == [" la ", "!", " la "]
    finally:
        del sys.modules["faster_whisper"]
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "prepare", "selftest", "synthetic", "execute", "worker"))
    parser.add_argument("--output", type=Path, default=ROOT / "build/generation-next/rms-vad-asr/v1")
    parser.add_argument("--cuts", type=Path, default=ROOT / "build/generation-next/rms-vad/v1")
    parser.add_argument("--model", type=Path, default=Path.home() / ".cache/huggingface/hub" /
        "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots" / MODEL_REVISION)
    parser.add_argument("--song", choices=PILOT)
    parser.add_argument("--arm", choices=ARMS)
    parser.add_argument("--control", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--memory-limit-mib", type=int, choices=(2048, 4096), default=2048,
                        help="Plan only: RSS and physical footprint stop threshold")
    parser.add_argument("--synthetic-timeout-seconds", type=int, default=600,
                        help="Plan only: supervised synthetic control deadline")
    parser.add_argument("--reuse-prepared", type=Path,
                        help="Plan only: previous directory whose eight prepared WAVs will be verified and reused")
    parser.add_argument("--resource-review", type=Path,
                        help="Plan only: fixed metadata/import/source evidence supporting the proposed budget")
    args = parser.parse_args()
    if not 0 < args.synthetic_timeout_seconds <= 600:
        parser.error("Synthetic control deadline must be in 1..600 seconds")
    if args.command == "worker" and not args.control and (args.song is None or args.arm is None):
        parser.error("worker requires --song and --arm")
    if args.command == "selftest":
        print(json.dumps(selftest(), indent=2))
    else:
        {"plan": plan, "prepare": prepare, "synthetic": synthetic, "execute": execute, "worker": worker}[args.command](args)
