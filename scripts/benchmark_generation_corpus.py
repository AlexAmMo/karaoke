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
import math
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import soundfile as sf
import torch
from faster_whisper import WhisperModel

from benchmark_chart_generation import compare_notes, compare_words, extract

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


def score(reference, draft, offset, duration, clip):
    # This is the first time the human chart is opened. Discard boundary words whose
    # syllables may extend beyond the excerpt, with the same margin for both charts.
    notes, words = extract(reference)
    found, recognized = extract(draft)
    lo, hi = (0.5, duration - 0.5) if clip else (0, duration)
    golden = [
        replace(n, start=n.start - offset, end=min(n.end - offset, hi))
        for n in notes
        if lo <= n.start - offset < hi
    ]
    vocal = [(word, t - offset) for word, t in words if lo <= t - offset < hi]
    found = [replace(n, end=min(n.end, hi)) for n in found if lo <= n.start < hi]
    recognized = [(word, t) for word, t in recognized if lo <= t < hi]
    metric = compare_words(vocal, recognized) if vocal else {"ref_words": 0, "wer": None}
    scored = any(n.pitch is not None for n in golden)
    if found and golden and scored:
        metric.update(compare_notes(golden, found))
    else:
        metric.update(
            reference_notes=sum(n.pitch is not None for n in golden),
            correct_class_all=0.0 if scored else None,
            onset_pitch_f1_100ms=0.0 if scored else None,
        )
    return metric


def record_time(d, stage, fn):
    start = time.perf_counter()
    value = fn()
    d[stage] = round(time.perf_counter() - start, 2)
    return value


def run(args):
    torch.set_num_threads(3)
    raw = json.loads(args.manifest.read_text())
    cases = sum(raw.values(), []) if isinstance(raw, dict) else raw
    # Interleave languages deterministically. An interrupted run still exercises both.
    cases.sort(key=lambda r: (hashlib.sha256(r["tag"].encode()).hexdigest(), r["tag"]))
    args.output.mkdir(exist_ok=True, parents=True)
    whisper, separator, _ = worker.prepare(args.cache.resolve(), "quality", args.model_dir)
    model = WhisperModel(str(whisper), device="cpu", compute_type="int8", cpu_threads=3)
    tasks = []
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
        if not stage:
            spans, lang = record_time(
                timing,
                "asr",
                lambda: worker.transcribe(voice, whisper, row["language"], model=model),
            )
            stage = {"words": spans, "language": lang, "signature": signature, "seconds": timing}
            save(checkpoint, stage)
            print("transcribed", tag, timing, flush=True)
        tasks.append((row, voice, offset, stage, folder))
    model = None
    gc.collect()
    for row, voice, offset, stage, folder in tasks:
        transcript = "\n".join(" ".join(w["word"] for w in line) for line in stage["words"])
        language = stage["language"]
        duration = sf.info(voice).duration
        lyr, src = transcript, {"kind": "asr"}
        # Full-track lyrics cannot be used as if they were lyrics for a 24 s excerpt.
        if args.lookup_lyrics and not args.clip_seconds:
            selected = worker.lookup(transcript, row["artist"], row["title"], duration)
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
            "chart_sha256": worker.digest(row["reference"]),
        }
        try:
            notes, evidence = record_time(
                timing,
                "chart",
                lambda: worker.chart_quality(voice, lyr, language, args.cache.resolve()),
            )
            draft = folder / "draft.txt"
            draft.write_text(
                worker.chart_text(notes, row["title"], row["artist"], language, duration)
            )
            result["metrics"] = score(
                Path(row["reference"]), draft, offset, duration, args.clip_seconds
            )
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


def passes(m):
    p90 = m.get("word_mae_p50_p90_s", [])
    return bool(
        len(p90) == 2
        and p90[1] <= 0.12
        and m.get("wer", math.inf) <= 0.05
        and (m.get("correct_class_all") or 0) >= 0.9
        and (m.get("onset_pitch_f1_100ms") or 0) >= 0.85
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, default=worker.default_cache())
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--clip-seconds", type=float, default=0)
    parser.add_argument("--lookup-lyrics", action="store_true")
    parser.add_argument("--keep-stems", action="store_true")
    run(parser.parse_args())
