"""Evaluate production song charting on independent human charts, optionally using fixed audio excerpts.

Input JSON: list of {tag, language, title, artist, audio, reference} or a dictionary
of such lists by language. Paths can be absolute or relative to the working directory.
Run in the generation environment with this project's source tree available. The private
scratch directory contains audio, lyrics and metrics. Only the metrics are intended to share.
"""

import argparse
import gc
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from karaoke.generation_metrics import passes, score  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/karaoke"))
import generation_worker as worker  # noqa: E402


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


def run(args):
    import soundfile as sf
    import torch
    from faster_whisper import WhisperModel

    torch.set_num_threads(3)
    raw = json.loads(args.manifest.read_text())
    cases = sum(raw.values(), []) if isinstance(raw, dict) else raw
    # Interleave languages deterministically. An interrupted run still exercises both.
    cases.sort(key=lambda r: (hashlib.sha256(r["tag"].encode()).hexdigest(), r["tag"]))
    args.output.mkdir(exist_ok=True, parents=True)
    whisper, separator, _ = worker.prepare(args.cache.resolve(), "quality", args.model_dir)
    tasks = []
    waiting = []
    for row in cases:
        tag = row["tag"]
        if Path(tag).name != tag or tag in (".", ".."):
            raise ValueError("Invalid corpus ID")
        folder = args.output / tag
        folder.mkdir(exist_ok=True)
        report = folder / "metrics.json"
        if report.exists():
            continue
        audio = Path(row["audio"]).resolve()
        audio_hash = worker.digest(audio)
        if row.get("audio_sha") and row["audio_sha"] != audio_hash:
            raise ValueError(f"{tag} audio hash mismatch")
        full = seconds(audio)
        duration = min(args.clip_seconds, full) if args.clip_seconds else full
        offset = max(0.0, (full - duration) * 0.4) if args.clip_seconds else 0
        signature = [audio_hash, round(offset, 4), round(duration, 4), row["language"]]
        checkpoint = folder / "acoustics.json"
        stage = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        if stage and stage["signature"] != signature:
            raise ValueError(f"{tag} needs a new work directory")
        timing = stage.get("seconds", {})
        if args.clip_seconds or not row.get("voice"):
            voice = folder / "vocals.wav"
        else:
            # Optional private stem from the exact same recording and separator revision.
            voice = Path(row["voice"]).resolve()
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
        stage.setdefault("signature", signature)
        stage.setdefault("seconds", timing)
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
        save(checkpoint, stage)
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
            "audio_sha256": stage["signature"][0],
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
            # Finish and fingerprint the prediction before opening the gold chart.
            # Only the evaluator receives its path; neither model nor text resolver does.
            result["draft_sha256"] = worker.digest(draft)
            reference = Path(row["reference"])
            result["chart_sha256"] = worker.digest(reference)
            if row.get("chart_sha") and result["chart_sha256"] != row["chart_sha"]:
                raise RuntimeError(f"The evaluation reference changed for {row['tag']}")
            result["metrics"] = score(reference, draft, offset, duration, args.clip_seconds)
            result["diagnostics"] = {k: v for k, v in evidence.items() if k != "review_regions"}
            result["meets_thresholds"] = passes(result["metrics"])
        except ValueError as exc:
            result.update(failure=str(exc), meets_thresholds=False)
        save(folder / "metrics.json", result)
        print("scored", row["tag"], result.get("metrics", result.get("failure")), flush=True)
        if args.clip_seconds and voice == folder / "vocals.wav" and not args.keep_stems:
            voice.unlink()
    results = [json.loads(p.read_text()) for p in sorted(args.output.glob("*/metrics.json"))]
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
