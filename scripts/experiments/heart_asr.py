"""Fixed four-song Heart ASR comparison; planning and tests never load a model.

The converted model must already be frozen by heart_conversion.py. Synthetic
control and cohort are separate supervised commands, with no automatic retry.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import signal
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HELPERS = ROOT / "scripts/experiments/rms_vad_asr.py"
SPEC = importlib.util.spec_from_file_location("heart_asr_shared", HELPERS)
shared = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shared)
check, digest, load, record, save, module = (
    shared.check, shared.digest, shared.load, shared.record, shared.save, shared.module)
PILOT, RATE = shared.PILOT, 16000
ARM = "heart-native"
LIMIT = 4 * 1024**3
PROPOSAL_SHA = "d8e8951e071720bb741d6f19aeb0aeb59fb666f588041a8aa3367780cb013d15"
BASELINE_PLAN_SHA = "0a9e4d81a2462977c8b21871f9cc3fe5451db48ead5d6cb853d2e902e6bf183c"
BASELINE_FREEZE_SHA = "c88bf5aa82893d41a018a88e65f03db8bd6182a092da3f51df79f9f17a253e12"
AUDIO_FREEZE_SHA = "07b4c792c70fba8dba50d399a70edfed88c3ed31d93f4f168ffcbf59d84e0659"
HELPERS_SHA = "2b4b95d80638188c750d506dfbac68e5011d153a32aecc5b84026eefa8a8583a"
SUPERVISOR_SHA = "0a36facfe0b49da79a4b8ac24c79bce2fa34f28854891d45f13890ffb9d84cc8"
MONITOR_SHA = "5cc80cefe57a4088701dc3ea1e9bfa2be3ee5120754c4d6a702ccf184ed3ef97"
SOURCE_SHA = "9e09145b687c26330da96ad2d7ca1fe542d46247700a43a3156b924a6b6e6a07"
VERSIONS = {"faster-whisper": "1.2.1", "ctranslate2": "4.9.0",
            "numpy": "2.5.5", "scipy": "1.18.1", "soundfile": "0.14.0"}
DECODE = {"beam_size": 2, "best_of": 1, "temperature": [0, .1, .2, .4],
          "compression_ratio_threshold": 1.8, "log_prob_threshold": -1.,
          "no_speech_threshold": .4, "condition_on_previous_text": False,
          "word_timestamps": True, "vad_filter": False, "task": "transcribe",
          "max_new_tokens": 256, "chunk_length": 30}
MODEL = {"device": "cpu", "compute_type": "int8", "cpu_threads": 2,
         "num_workers": 1, "local_files_only": True, "files": None}
RESOURCES = {"worker_rss_and_footprint_stop_bytes": LIMIT,
             "synthetic_timeout_seconds": 120, "timeout_seconds_per_song": 900,
             "sample_seconds": .05, "fresh_process_per_song": True,
             "on_failure": "stop and reap; preserve partial evidence; no retries or quota increases"}
CONTROL = {"sample_rate": RATE, "samples": 2 * RATE, "language": "es",
           "waveform": "float32: .15 * envelope * (sin(2*pi*440*t) + .3*sin(2*pi*880*t))",
           "envelope": "clip(min((t-.2)/.01, (1.6-t)/.01), 0, 1)",
           "scope": "nonzero synthetic runtime control; no playback or lyric correctness claim"}


def successful(resources):
    if (not resources["reaped"] or resources["exit_code"] != 0
            or resources["stopped_reason"]):
        raise ValueError("A successful worker with confirmed reap is required")


def checked_conversion(path):
    """Check frozen evidence and model bytes, without loading runtime or tensors."""
    frozen = load(path)
    plan = load(check(frozen["plan"]))
    successful(load(check(frozen["resources"])))
    complete = load(check(frozen["worker_complete"]))
    if (not frozen["reaped"] or frozen["transcription_executed"]
            or frozen["source_sha256"] != SOURCE_SHA
            or complete["plan_sha256"] != frozen["plan"]["sha256"]):
        raise ValueError("Incomplete or different Heart conversion")
    options = plan["conversion"]
    if (options["quantization"] != "int8" or not options["load_as_float16"]
            or options["device"] != "cpu"
            or options["reader"] != "transformers.modeling_utils.safe_open: backend=pread"):
        raise ValueError("Expected the distinct FP16/pread/int8 conversion")
    directory = Path(frozen["model_directory"])
    files = frozen["model_files"]
    required = {"model.bin", "config.json", "tokenizer.json", "preprocessor_config.json", "vocabulary.json"}
    if not required <= files.keys() or {p.name for p in directory.iterdir()} != files.keys():
        raise ValueError("Converted model file inventory differs")
    for name, sha in files.items():
        check({"path": str(directory / name), "sha256": sha})
    evidence_directory = Path(frozen["worker_complete"]["path"]).parent
    for name, sha in complete["files"].items():
        # Converter renames ct2-staging after the validated worker exits.
        relative = Path(name)
        if relative.parts[0] == "ct2-staging":
            candidate = directory.joinpath(*relative.parts[1:])
        else:
            candidate = evidence_directory / relative
        check({"path": str(candidate), "sha256": sha})
    return {"freeze": record(path), "plan": frozen["plan"],
            "resources": frozen["resources"], "worker_complete": frozen["worker_complete"],
            "model_directory": str(directory.resolve()), "model_files": files,
            "source_sha256": SOURCE_SHA}


def baseline_inputs(directory, proposal):
    paths = {"plan": directory / "plan.json", "freeze": directory / "frozen.json",
             "prepared": directory / "audio-frozen.json"}
    for key, sha in (("plan", BASELINE_PLAN_SHA), ("freeze", BASELINE_FREEZE_SHA),
                     ("prepared", AUDIO_FREEZE_SHA)):
        if digest(paths[key]) != sha:
            raise ValueError("Expected the completed RMS v3 baseline")
    plan, frozen, prepared = (load(paths[k]) for k in ("plan", "freeze", "prepared"))
    if frozen["present"] != 16 or frozen["plan_sha256"] != BASELINE_PLAN_SHA:
        raise ValueError("Incomplete baseline")
    selected = {row["id"]: row for row in frozen["results"] if row["arm"] == "vocals-native"}
    proposed = {row["id"]: row for row in proposal["inputs"]}
    inputs = []
    for row in plan["inputs"]:
        tag = row["id"]
        source = next(r for r in prepared["prepared"] if r["id"] == tag and r["kind"] == "vocals")
        if (row["stem"] != proposed[tag]["source_stem"]
                or source["audio"] != {k: proposed[tag]["prepared_audio"][k] for k in ("path", "sha256")}):
            raise ValueError("Proposal and baseline must identify the same vocal bytes")
        for item in (row["audio"], row["stem"], source["audio"],
                     selected[tag]["prediction"], selected[tag]["resources"]):
            check(item)
        successful(load(check(selected[tag]["resources"])))
        # Identity only: baseline lyric content is neither inspected nor selected.
        prediction = load(check(selected[tag]["prediction"]))
        if (prediction["id"] != tag or prediction["arm"] != "vocals-native"
                or prediction["plan_sha256"] != BASELINE_PLAN_SHA
                or prediction["audio"] != source["audio"]):
            raise ValueError("Baseline prediction identity differs")
        inputs.append({"id": tag, "language": row["language"], "original_audio": row["audio"],
                       "source_stem": row["stem"], "prepared_audio": source["audio"],
                       "samples": source["samples"], "sample_rate": RATE,
                       "baseline": selected[tag]})
    if tuple(row["id"] for row in inputs) != PILOT:
        raise ValueError("Expected all four fixed identities in their original order")
    return inputs, {key: record(path) for key, path in paths.items()}


def own_sources():
    records = {key: record(path) for key, path in {
        "adapter": Path(__file__), "helpers": HELPERS,
        "production": ROOT / "src/karaoke/generation_worker.py",
        "supervisor": ROOT / "scripts/experiments/yourmt3_notes.py",
        "memory_monitor": ROOT / "scripts/experiments/lead_vocals.py"}.items()}
    for key, sha in (("helpers", HELPERS_SHA), ("supervisor", SUPERVISOR_SHA),
                     ("memory_monitor", MONITOR_SHA)):
        if records[key]["sha256"] != sha:
            raise ValueError("Reviewed helper or resource guard changed")
    return records


def plan(args):
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use an empty output; prior plans and attempts are immutable")
    if digest(args.proposal) != PROPOSAL_SHA:
        raise ValueError("Expected the fixed FP16/pread/beam2 proposal")
    conversion = checked_conversion(args.conversion_freeze)
    proposal = load(args.proposal)
    for key, value in DECODE.items():
        if proposal["inference"][key] != value:
            raise ValueError("Decoding differs from the predeclared Heart proposal")
    inputs, baseline = baseline_inputs(args.baseline, proposal)
    for row in inputs:
        audio_values(row["prepared_audio"], row["samples"])
    payload = {"schema": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
        "proposal": record(args.proposal), "code": own_sources(), "conversion": conversion,
        "baseline": baseline, "inputs": inputs, "arm": ARM, "planned_transcriptions": 4,
        "denominator": 40, "references_opened": False, "model": MODEL, "decode": DECODE,
        "rng_seed": 113, "versions": VERSIONS, "python": str(args.python.absolute()),
        "resources": RESOURCES, "synthetic": CONTROL,
        "filtering": "production transcribe, windowed=False; explicit Heart recognizer kwargs override all production decoding kwargs; raw captured before filters",
        "comparison_scope": proposal["comparison_warning"],
        "historical_proposal_links": "Proposal v2 baseline links retained as history; this plan explicitly binds completed RMS v3 and identical WAV bytes",
        "cost_estimate": "Unmeasured for Heart; four 900s deadlines total 60min plus a 120s control. No runtime estimate inferred from Turbo results."}
    save(args.output / "plan.json", payload)
    for name, item in payload["code"].items():
        destination = args.output / "source-snapshot" / (name + ".py")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(check(item).read_bytes())
    print(shared.json.dumps({"plan": str(args.output / "plan.json"), "planned": 4,
                             "model_loaded": False, "references_opened": False}))


def verify_plan(output):
    settings = load(output / "plan.json")
    if (settings["code"] != own_sources() or settings["decode"] != DECODE
            or settings["model"] != MODEL or settings["resources"] != RESOURCES
            or settings["synthetic"] != CONTROL or settings["versions"] != VERSIONS
            or settings["rng_seed"] != 113 or settings["arm"] != ARM
            or settings["planned_transcriptions"] != 4 or settings["references_opened"]):
        raise ValueError("Source or fixed experiment settings changed")
    check(settings["proposal"])
    if checked_conversion(check(settings["conversion"]["freeze"])) != settings["conversion"]:
        raise ValueError("Changed conversion evidence")
    inputs, baseline = baseline_inputs(Path(settings["baseline"]["plan"]["path"]).parent,
                                      load(check(settings["proposal"])))
    if inputs != settings["inputs"] or baseline != settings["baseline"]:
        raise ValueError("Changed fixed audio or baseline")
    return settings


def audio_values(item, samples):
    import numpy as np
    import soundfile as sf
    with sf.SoundFile(check(item)) as stream:
        if stream.samplerate != RATE or stream.channels != 1 or len(stream) != samples:
            raise ValueError("Prepared audio geometry changed")
        values = stream.read(dtype="float32")
    if not np.isfinite(values).all() or not values.any() or not 0 < samples <= 300 * RATE:
        raise ValueError("Audio must be finite, nonzero and no longer than300seconds")
    return values


class HeartRecordingModel(shared.RecordingModel):
    """Keep production filtering while making every Heart decode option explicit."""

    def __init__(self, model, language):
        super().__init__(model)
        self.language, self.calls = language, []

    def transcribe(self, waveform, **kwargs):
        expected = {"language": self.language, "beam_size": 5, "word_timestamps": True,
                    "vad_filter": False, "condition_on_previous_text": False}
        if kwargs != expected:
            raise ValueError("Production call contract changed; review before running")
        effective = dict(DECODE, language=self.language)
        self.calls.append({"production_kwargs": kwargs, "effective_kwargs": effective,
                           "samples": len(waveform)})
        return super().transcribe(waveform, **effective)


def synthetic_audio():
    import numpy as np
    times = np.arange(2 * RATE, dtype=np.float32) / RATE
    envelope = np.clip(np.minimum((times - .2) / .01, (1.6 - times) / .01), 0, 1)
    return (.15 * envelope * (np.sin(2 * np.pi * 440 * times)
                              + .3 * np.sin(2 * np.pi * 880 * times))).astype(np.float32)


def worker(args):
    if os.environ.get("HEART_ASR_SUPERVISED") != "1":
        raise ValueError("Worker requires its resource supervisor")
    settings = verify_plan(args.output)
    observed = {name: importlib.metadata.version(name) for name in VERSIONS}
    if observed != VERSIONS:
        raise ValueError("Runtime versions differ from plan")
    destination = args.output / "synthetic-control" if args.control else args.output / "results" / args.song
    with (destination / "worker.log").open("x", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
        import soundfile as sf
        if args.control:
            audio = destination / "nonzero-2s.wav"
            sf.write(audio, synthetic_audio(), RATE, subtype="FLOAT")
            row = {"id": "synthetic-nonzero-2s", "language": "es", "samples": 2 * RATE,
                   "prepared_audio": record(audio)}
        else:
            row = next(r for r in settings["inputs"] if r["id"] == args.song)
            audio = check(row["prepared_audio"])
        values = audio_values(row["prepared_audio"], row["samples"])
        del values
        production = module(check(settings["code"]["production"]), "heart_asr_production")
        save(destination / "before-model.json", {"unix_time": time.time(), "versions": observed})
        import ctranslate2
        from faster_whisper import WhisperModel
        ctranslate2.set_random_seed(settings["rng_seed"])
        save(destination / "after-import.json", {"unix_time": time.time()})
        model_directory = settings["conversion"]["model_directory"]
        model = HeartRecordingModel(WhisperModel(model_directory, **settings["model"]), row["language"])
        save(destination / "after-model.json", {"unix_time": time.time()})
        started = time.monotonic()
        lines, language = production.transcribe(audio, model_directory, row["language"], model=model)
        if len(model.calls) != 1 or model.calls[0]["samples"] != row["samples"]:
            raise ValueError("Expected one complete native waveform with unchanged sample clock")
        interval = {"start": 0, "end": row["samples"], "clipped_samples": 0}
        raw = [shared.absolute_word(w, 0, row["samples"]) for seg in model.raw for w in (seg["words"] or [])]
        save(destination / "part-000.json", {"interval": interval, "language": language,
             "calls": model.calls, "raw_segments_local": model.raw,
             "raw_words_absolute": raw, "product_lines_absolute": lines})
        save(destination / "prediction.json", {"id": row["id"], "arm": ARM,
             "plan_sha256": digest(args.output / "plan.json"), "audio": row["prepared_audio"],
             "intervals": [interval], "raw_words": raw, "product_lines": lines,
             "seconds_after_model_load": time.monotonic() - started, "references_opened": False})
        save(destination / "after-prediction.json", {"unix_time": time.time()})


@contextmanager
def catch_termination():
    def stopped(_signum, _frame):
        raise InterruptedError("Heart ASR controller terminated")
    previous = signal.signal(signal.SIGTERM, stopped)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def controller(output):
    settings = verify_plan(output)
    monitor = module(check(settings["code"]["memory_monitor"]), "heart_asr_monitor")
    supervisor = module(check(settings["code"]["supervisor"]), "heart_asr_supervisor")
    if supervisor.MONITOR_SHA != MONITOR_SHA:
        raise ValueError("Supervisor monitor differs from plan")
    sampler = monitor.memory_sampler()
    environment = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", OMP_NUM_THREADS="2",
        MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="1", HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
        HEART_ASR_SUPERVISED="1")
    environment.pop("PYTHONPATH", None)
    return settings, supervisor, sampler, environment


def run_one(args, state, *, control, tag=None):
    settings, supervisor, sampler, environment = state
    destination = args.output / "synthetic-control" if control else args.output / "results" / tag
    destination.mkdir(parents=True)  # Existing attempts are never resumed or overwritten.
    command = [settings["python"], str(Path(__file__).resolve()), "_worker", "--output", str(args.output.resolve())]
    command += ["--control"] if control else ["--song", tag]
    timeout = settings["resources"]["synthetic_timeout_seconds" if control else "timeout_seconds_per_song"]
    save(destination / "launch.json", {"command": command, "timeout_seconds": timeout,
         "rss_and_footprint_stop_bytes": LIMIT, "plan_sha256": digest(args.output / "plan.json")})
    with catch_termination():
        resources = supervisor.run_bounded(command, destination, LIMIT, timeout, sampler, environment)
    successful(resources)
    return {"id": "synthetic-nonzero-2s" if control else tag, "arm": ARM,
            "prediction": record(destination / "prediction.json"),
            "resources": record(destination / "resources.json"),
            "partial_evidence": [record(p) for p in sorted(destination.iterdir())
                                 if p.is_file() and p.name not in ("prediction.json", "resources.json")]}


def synthetic(args):
    row = run_one(args, controller(args.output), control=True)
    save(args.output / "synthetic-frozen.json", {"plan_sha256": digest(args.output / "plan.json"),
         **row, "reaped": True, "scope": CONTROL["scope"]})


def execute(args):
    state = controller(args.output)
    control = load(args.output / "synthetic-frozen.json")
    if control["plan_sha256"] != digest(args.output / "plan.json") or not control["reaped"]:
        raise ValueError("Successful control of this exact plan is required")
    check(control["prediction"])
    successful(load(check(control["resources"])))
    for item in control["partial_evidence"]:
        check(item)
    results = []
    for row in state[0]["inputs"]:
        results.append(run_one(args, state, control=False, tag=row["id"]))
    save(args.output / "frozen.json", {"plan_sha256": digest(args.output / "plan.json"),
         "results": results, "present": len(results), "planned": 4, "references_opened": False})


def selftest():
    """Small tests using a fake recognizer and real audio/filter/scalar types."""
    from dataclasses import dataclass
    from types import SimpleNamespace
    import numpy as np
    import soundfile as sf
    production = module(ROOT / "src/karaoke/generation_worker.py", "heart_asr_test_production")

    @dataclass
    class Word:
        start: object
        end: object
        word: str
        probability: object

    @dataclass
    class Segment:
        words: list
        tokens: list

    class Fake:
        def transcribe(self, values, **kwargs):
            assert kwargs == dict(DECODE, language="es")
            assert kwargs["beam_size"] == 2 and kwargs["best_of"] == 1
            assert len(values) == 2 * RATE and np.array_equal(values, synthetic_audio())
            words = [Word(np.float64(.1), np.float64(.2), " hola ", np.float32(.8)),
                     Word(np.float64(.2), np.float64(.2), "cero", np.float32(.5)),
                     Word(np.float64(.3), np.float64(.4), ".", np.float32(.5)),
                     Word(np.float64(.5), np.float64(.6), " hola ", np.float32(.7)),
                     Word(np.float64(1.9), np.float64(2.1), "fin", np.float32(.6))]
            return iter([Segment(words, [np.int64(17)])]), SimpleNamespace(language="es")

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "probe.wav"
        samples = synthetic_audio()
        assert len(samples) == 2 * RATE and np.isfinite(samples).all() and samples.any()
        sf.write(path, samples, RATE, subtype="FLOAT")
        assert np.array_equal(audio_values(record(path), len(samples)), samples)
        recorder = HeartRecordingModel(Fake(), "es")
        lines, language = production.transcribe(path, "unused", "es", model=recorder)
        assert language == "es" and [w["word"] for w in lines[0]] == ["hola", "hola", "fin"]
        raw = [shared.absolute_word(w, 0, len(samples)) for w in recorder.raw[0]["words"]]
        assert len(raw) == 5 and raw[1]["nonpositive_duration"] and raw[-1]["crosses_input_boundary"]
        target = Path(temporary) / "payload.json"
        save(target, {"segments": recorder.raw, "words": raw, "lines": lines})
        restored = load(target)
        assert type(restored["words"][1]["nonpositive_duration"]) is bool
        assert restored["words"][-1]["end"] == float(np.float64(2.1))
        assert len(restored["segments"][0]["words"]) == 5
        try:
            recorder.transcribe(samples, language="es", beam_size=2)
        except ValueError:
            pass
        else:
            raise AssertionError("Unexpected production contract accepted")
        for value in (np.float64(float("nan")), np.float32(float("inf")), object()):
            invalid = Path(temporary) / "invalid.json"
            try:
                save(invalid, {"value": value})
            except (ValueError, TypeError):
                assert not invalid.exists()
            else:
                raise AssertionError("Invalid scalar accepted")
    if "torch" in sys.modules or "faster_whisper" in sys.modules or "ctranslate2" in sys.modules:
        raise AssertionError("Lightweight control imported a model runtime")
    return {"checks": ["two-second finite nonzero audio", "exact waveform clock",
        "explicit Heart kwargs override production beam5", "production filters and repetitions",
        "nested dataclass and NumPy JSON", "boundary flags retained", "invalid scalars rejected",
        "production contract drift rejected", "no model runtimes imported"], "model_loaded": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "selftest", "synthetic", "execute", "_worker"))
    parser.add_argument("--output", type=Path, default=ROOT / "build/generation-next/heart-asr/v1")
    parser.add_argument("--proposal", type=Path, default=ROOT / "build/generation-next/heart-cpu-research/execution-proposal-fp16-pread-v2.json")
    parser.add_argument("--baseline", type=Path, default=ROOT / "build/generation-next/rms-vad-asr/v3")
    parser.add_argument("--conversion-freeze", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--song", choices=PILOT)
    parser.add_argument("--control", action="store_true")
    args = parser.parse_args()
    if args.command == "plan" and args.conversion_freeze is None:
        parser.error("plan requires an existing --conversion-freeze")
    if args.command == "_worker" and not args.control and args.song is None:
        parser.error("worker requires --song or --control")
    if args.command == "selftest":
        print(shared.json.dumps(selftest(), indent=2))
    else:
        {"plan": plan, "synthetic": synthetic, "execute": execute, "_worker": worker}[args.command](args)
