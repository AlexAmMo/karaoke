"""Evaluate production song charting on independent human charts, optionally using fixed audio excerpts.

Input JSON: list of {tag, language, title, artist, audio, reference} or a dictionary
of such lists by language. Paths can be absolute or relative to the working directory.
Run in the generation environment with this project's source tree available. The private
scratch directory contains audio, lyrics and metrics. Only the metrics are intended to share.
"""

import argparse
import gc
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from karaoke.generation_metrics import passes, score  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/karaoke"))
import generation_worker as worker  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE_SCHEMA = 1


def save(path, obj):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(obj, indent=2, ensure_ascii=False))
    temp.replace(path)


def seconds(media):
    result = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(media),
        ],
        text=True,
    )
    return float(result.strip())


def record_time(d, stage, fn):
    start = time.perf_counter()
    value = fn()
    d[stage] = round(time.perf_counter() - start, 2)
    return value


def payload_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def seal(value):
    return {**value, "payload_sha256": payload_hash(value)}


def intact(value):
    return value.get("payload_sha256") == payload_hash(
        {key: item for key, item in value.items() if key != "payload_sha256"}
    )


def versions(names):
    result = {}
    for name in names:
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def generation_code(args):
    files = [ROOT / "src/karaoke/generation_worker.py"]
    files.extend(sorted((ROOT / "src/karaoke/generation_assets").glob("*.py")))
    engine = args.cache.resolve() / f"creator-{worker.CREATOR_REV}"
    files.extend(engine / name for name in worker.ENGINE_FILES if (engine / name).is_file())
    custom_model = None
    if args.model_dir:
        if not args.model_dir.is_dir():
            raise ValueError("The custom ASR model directory does not exist")
        custom_model = {"path": str(args.model_dir.resolve()), "files": {
            str(path.relative_to(args.model_dir)): worker.digest(path)
            for path in sorted(args.model_dir.rglob("*")) if path.is_file()
        }}
    return {
        "files": {str(path): worker.digest(path) for path in files},
        "benchmark_generation": payload_hash([
            inspect.getsource(fn) for fn in (inputs_for, generate_predictions, record_time)
        ]),
        "packages": versions(("torch", "faster-whisper", "ctranslate2", "onnxruntime",
                              "numpy", "soundfile", "demucs", "librosa", "transformers")),
        "environment": {name: value for name, value in os.environ.items()
                        if name.startswith("ULTRASTAR_") or name in
                        ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")},
        "custom_asr_model": custom_model,
    }


def evaluation_code():
    return {
        "files": {name: worker.digest(ROOT / "src/karaoke" / name)
                  for name in ("generation_metrics.py", "songs.py")},
        "benchmark_evaluation": payload_hash(inspect.getsource(evaluate_prediction)),
        "packages": versions(("numpy",)),
    }


def inputs_for(row, args, code):
    audio = Path(row["audio"]).resolve()
    audio_hash = worker.digest(audio)
    if row.get("audio_sha") and row["audio_sha"] != audio_hash:
        raise ValueError(f"{row['tag']} audio hash mismatch")
    full = seconds(audio)
    duration = min(args.clip_seconds, full) if args.clip_seconds else full
    offset = max(0.0, (full - duration) * 0.4) if args.clip_seconds else 0
    voice = Path(row["voice"]).resolve() if row.get("voice") and not args.clip_seconds else None
    captions = Path(row["captions"]) if row.get("captions") and args.lookup_lyrics else None
    return {
        "schema": CACHE_SCHEMA, "id": row["tag"], "audio_sha256": audio_hash,
        "offset_s": offset, "window_s": duration, "clip_seconds": args.clip_seconds,
        "language": row["language"], "title": row["title"], "artist": row["artist"],
        "lookup_lyrics": args.lookup_lyrics,
        "voice_sha256": worker.digest(voice) if voice else None,
        "captions_sha256": worker.digest(captions) if captions else None,
        "video_id": row.get("video_id") if captions else None, "generation_code": code,
    }


def cached_prediction(folder, signature):
    frozen = folder / "prediction.json"
    if not frozen.exists():
        if (folder / "metrics.json").exists():
            raise ValueError(f"{folder.name} has an unversioned cache; use a new work directory")
        return None
    prediction = json.loads(frozen.read_text())
    if not intact(prediction) or prediction.get("signature") != signature:
        raise ValueError(f"{folder.name} prediction inputs or code changed; use a new work directory")
    draft_hash = prediction["result"].get("draft_sha256")
    draft = folder / "draft.txt"
    if draft_hash and (not draft.is_file() or worker.digest(draft) != draft_hash):
        raise ValueError(f"{folder.name} frozen draft changed; use a new work directory")
    return prediction


def evaluate_prediction(row, folder, prediction, code):
    # The prediction is already frozen. Gold is opened only by this stage.
    reference = Path(row["reference"])
    reference_hash = worker.digest(reference)
    if row.get("chart_sha") and reference_hash != row["chart_sha"]:
        raise ValueError(f"The evaluation reference changed for {row['tag']}")
    identity = {"prediction_sha256": prediction["payload_sha256"],
                "chart_sha256": reference_hash, "evaluation_code": code}
    report = folder / "metrics.json"
    if report.exists():
        try:
            previous = json.loads(report.read_text())
        except (ValueError, UnicodeError):
            previous = {}
        if previous.get("cache_identity") == identity and intact(previous):
            return previous
    result = {**prediction["result"], "chart_sha256": reference_hash}
    if "failure" not in result:
        signature = prediction["signature"]
        try:
            result["metrics"] = score(reference, folder / "draft.txt", signature["offset_s"],
                                      prediction["duration_seconds"], signature["clip_seconds"])
            result["meets_thresholds"] = passes(result["metrics"])
        except ValueError as exc:
            result.update(failure=str(exc), meets_thresholds=False)
    result = seal({**result, "cache_identity": identity})
    save(report, result)
    print("scored", row["tag"], result.get("metrics", result.get("failure")), flush=True)
    return result


def generate_predictions(pending, args):
    import soundfile as sf
    import torch
    from faster_whisper import WhisperModel

    torch.set_num_threads(3)
    whisper, separator, _ = worker.prepare(args.cache.resolve(), "quality", args.model_dir)
    # prepare may have installed the pinned engine source for this first run.
    code = generation_code(args)
    tasks = []
    waiting = []
    for row, signature, folder in pending:
        tag = row["tag"]
        signature["generation_code"] = code
        audio = Path(row["audio"]).resolve()
        offset, duration = signature["offset_s"], signature["window_s"]
        checkpoint = folder / "acoustics.json"
        stage = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        if stage and (not intact(stage) or stage.get("signature") != signature):
            raise ValueError(f"{tag} needs a new work directory")
        stage.pop("payload_sha256", None)
        timing = stage.get("seconds", {})
        if args.clip_seconds or not row.get("voice"):
            voice = folder / "vocals.wav"
        else:
            # Optional private stem from the exact same recording and separator revision.
            voice = Path(row["voice"]).resolve()
        if voice == folder / "vocals.wav" and voice.exists() and not stage:
            raise ValueError(f"{tag} has an unversioned vocal stem; use a new work directory")
        if not voice.exists():
            with TemporaryDirectory(dir=folder) as tmp:
                tmp = Path(tmp)
                mix = audio
                if args.clip_seconds:
                    mix = tmp / "excerpt.wav"
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-loglevel",
                            "error",
                            "-ss",
                            str(offset),
                            "-i",
                            str(audio),
                            "-t",
                            str(duration),
                            "-vn",
                            "-ar",
                            "44100",
                            "-ac",
                            "2",
                            "-c:a",
                            "pcm_s24le",
                            str(mix),
                        ],
                        check=True,
                    )
                local, _ = record_time(
                    timing, "separate", lambda: worker.split_vocals(mix, tmp, separator)
                )
                local.replace(voice)
        voice_hash = worker.digest(voice)
        if stage.get("voice_sha256", voice_hash) != voice_hash:
            raise ValueError(f"{tag} vocal stem changed; use a new work directory")
        stage["voice_sha256"] = voice_hash
        stage.setdefault("signature", signature)
        stage.setdefault("seconds", timing)
        save(checkpoint, seal(stage))
        if "words" not in stage:
            waiting.append((voice, row["language"], stage, checkpoint))
        tasks.append((row, voice, offset, stage, folder))
    # Keep the ASR weights out of memory while separating full recordings.
    model = (
        WhisperModel(str(whisper), device="cpu", compute_type="int8", cpu_threads=3)
        if waiting
        else None
    )
    for voice, language, stage, checkpoint in waiting:
        spans, language = record_time(
            stage["seconds"],
            "asr",
            lambda: worker.transcribe(voice, whisper, language, model=model),
        )
        stage.update(words=spans, language=language)
        save(checkpoint, seal(stage))
        print("transcribed", checkpoint.parent.name, stage["seconds"], flush=True)
    model = None
    gc.collect()
    for row, voice, offset, stage, folder in tasks:
        transcript = "\n".join(" ".join(w["word"] for w in line) for line in stage["words"])
        language = stage["language"]
        duration = sf.info(voice).duration
        lyr, src = transcript, {"kind": "asr"}
        # Full-track lyrics cannot be used as if they were lyrics for a 24 s excerpt.
        if args.lookup_lyrics and not args.clip_seconds:
            selected = None
            if row.get("captions") and row.get("video_id"):
                from generation_assets.captions import matching_lyrics

                tracks = json.loads(Path(row["captions"]).read_text(encoding="utf-8"))
                exact_tracks = [t for t in tracks if t["video_id"] == row["video_id"]]
                selected = matching_lyrics(exact_tracks, stage["words"], language)
            if selected is None:
                selected = worker.lookup(
                    transcript,
                    row["artist"],
                    row["title"],
                    duration,
                    rescue=lambda: worker.recover_transcript(voice, whisper, language),
                )
            if selected:
                lyr, src = selected
        timing = dict(stage["seconds"])
        result = {
            "id": row["tag"],
            "language": language,
            "offset_s": round(offset, 4),
            "duration_s": round(duration, 3),
            "lyrics_source": src,
            "seconds": timing,
            "audio_sha256": stage["signature"]["audio_sha256"],
        }
        try:
            notes, evidence = record_time(
                timing,
                "chart",
                lambda: worker.chart_quality(voice, lyr, language, args.cache.resolve()),
            )
            draft = folder / "draft.txt"
            text = worker.chart_text(notes, row["title"], row["artist"], language, duration)
            if src["kind"] == "lrclib" and language == "en":
                from generation_assets.spelling import restore_spelling

                text, evidence["spelling_corrections"] = restore_spelling(
                    text, stage["words"], row["title"], language
                )
            draft.write_text(text, encoding="utf-8")
            result["draft_sha256"] = worker.digest(draft)
            result["diagnostics"] = {k: v for k, v in evidence.items() if k != "review_regions"}
        except ValueError as exc:
            result.update(failure=str(exc), meets_thresholds=False)
        # Finish and fingerprint every prediction before any reference chart is opened.
        save(folder / "prediction.json", seal({"signature": stage["signature"], "result": result,
                                               "duration_seconds": duration}))
        if args.clip_seconds and voice == folder / "vocals.wav" and not args.keep_stems:
            voice.unlink()


def run(args):
    if not math.isfinite(args.clip_seconds) or args.clip_seconds < 0:
        raise ValueError("Clip duration must be finite and nonnegative")
    raw = json.loads(args.manifest.read_text())
    cases = sum(raw.values(), []) if isinstance(raw, dict) else raw
    tags = [row["tag"] for row in cases]
    if len(set(tags)) != len(tags) or any(
        Path(tag).name != tag or tag in (".", "..") for tag in tags
    ):
        raise ValueError("Invalid or duplicate corpus ID")
    # Interleave languages deterministically. An interrupted run still exercises both.
    cases.sort(key=lambda row: (hashlib.sha256(row["tag"].encode()).hexdigest(), row["tag"]))
    args.output.mkdir(exist_ok=True, parents=True)
    code = generation_code(args)
    tasks, pending = [], []
    for row in cases:
        folder = args.output / row["tag"]
        folder.mkdir(exist_ok=True)
        signature = inputs_for(row, args, code)
        prediction = cached_prediction(folder, signature)
        if prediction is None:
            checkpoint = folder / "acoustics.json"
            if checkpoint.exists():
                stage = json.loads(checkpoint.read_text())
                if not intact(stage) or stage.get("signature") != signature:
                    raise ValueError(f"{row['tag']} acoustics changed; use a new work directory")
            pending.append((row, signature, folder))
        tasks.append((row, signature, folder))
    # Valid charts and metric-only changes never prepare or load inference models.
    if pending:
        generate_predictions(pending, args)
    evaluator = evaluation_code()
    results = []
    for row, signature, folder in tasks:
        prediction = cached_prediction(folder, signature)
        results.append(evaluate_prediction(row, folder, prediction, evaluator))
    # Include precisely this manifest, never abandoned reports from sibling runs.
    results.sort(key=lambda result: result["id"])
    save(args.output / "results.json", results)


if __name__ == "__main__":
    from generation_assets.runtime import configure_intel_openmp

    configure_intel_openmp()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, default=worker.default_cache())
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--clip-seconds", type=float, default=0)
    parser.add_argument("--lookup-lyrics", action="store_true")
    parser.add_argument("--keep-stems", action="store_true")
    run(parser.parse_args())
