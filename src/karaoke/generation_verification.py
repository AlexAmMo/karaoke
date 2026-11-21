"""Check a completed prediction against the independent chart for its exact recording."""

from bisect import bisect_right
import hashlib
import math
import os
from pathlib import Path
import shutil
import tempfile

import requests

from . import acoustic, allkaraoke
from .generation_metrics import ROW, compare_notes, compare_words, extract, passes
from .songs import SongError, read_chart


def _mono_timeline(chart, duration):
    # Avoid accepting truncated maps or silently dropping out-of-range notes at the song ends.
    notes, words = extract(chart)
    if not 12 <= len(words) <= 1400 or not 12 <= len(notes) <= 5000:
        return None
    end = 0.0
    for note in notes:
        if note.start < end - 0.00001 or note.end > duration + 0.10:
            return None
        end = note.end
    return notes, words


def _confirmed_intervals(chart, gold, output):
    """Keep the predicted words and pitches, scoring only their overlap with the same human pitch."""
    text, meta = read_chart(chart)
    bpm = float(meta["BPM"].replace(",", "."))
    # Finer ticks avoid moving a release by a whole frame when intersecting the two grids.
    scale = 2 if bpm < 1000 else 1
    rate = bpm * scale / 15
    gap = float(meta.get("GAP", "0").replace(",", ".")) / 1000
    ends = [n.end for n in gold]
    lines = []
    last = 0
    for line in text.splitlines():
        if line.startswith("#BPM:"):
            line = f"#BPM:{bpm * scale:.12g}"
        elif line.startswith("- "):
            line = "- " + " ".join(str(int(v) * scale) for v in line[2:].split())
        elif match := ROW.match(line):
            kind, tick, length, pitch, lyric = match.groups()
            first = int(tick) * scale
            stop = first + int(length) * scale
            start_time, end_time = gap + first / rate, gap + stop / rate
            intervals = []
            if kind in ":*":
                j = bisect_right(ends, start_time)
                while j < len(gold) and gold[j].start < end_time:
                    note = gold[j]
                    j += 1
                    if note.pitch is None or note.pitch % 12 != int(pitch) % 12:
                        continue
                    a = max(first, last, math.floor((note.start - gap) * rate + 1e-8))
                    b = min(stop, math.ceil((note.end - gap) * rate - 1e-8))
                    if a < b:
                        intervals.append((a, b))
                        last = b
            if intervals:
                for k, (a, b) in enumerate(intervals):
                    fragment = lyric.rstrip() if k == 0 else "~"
                    if k == len(intervals) - 1 and lyric.endswith(" "):
                        fragment += " "
                    lines.append(f"{kind} {a} {b - a} {pitch} {fragment}")
                continue
            # Display the generated syllable even when its pitch has no supporting reference.
            line = f"F {first} {stop - first} {pitch} {lyric}"
        lines.append(line)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _measure(gold, found):
    notes, words = gold
    generated_notes, generated_words = found
    return {
        **compare_words(words, generated_words),
        **compare_notes(notes, generated_notes),
        "scored_frame_precision": compare_notes(generated_notes, notes)["correct_class_all"],
    }


def verify_generated(chart, media, seconds, video, catalogues, *, verified_chart=None):
    """Absence of evidence leaves the ordinary review flow available."""
    if not math.isfinite(seconds) or not 0 < seconds <= 900:
        return None
    try:
        candidates = [
            row
            for row in allkaraoke.search("", catalogues, video_id=video)
            if row["video_id"] == video
            and row.get("tracks") == 1
            and abs((row.get("reference_duration") or 0) - seconds) <= 2
        ]
        # Two different published arrangements can assign different parts to the singer.
        if len(candidates) != 1:
            return None
        candidate = candidates[0]
        with tempfile.TemporaryDirectory(prefix="compare-", dir=chart.parent.parent) as temp:
            reference = allkaraoke.load_chart(candidate, Path(temp))
            # All measurements and the eventual attestation refer to the same bytes.
            prediction = Path(temp) / "prediction.txt"
            shutil.copyfile(chart, prediction)
            gold = _mono_timeline(reference, seconds)
            found = _mono_timeline(prediction, seconds)
            if gold is None or found is None:
                return None
            if any(not any(n.pitch is not None for n in notes) for notes, _ in (gold, found)):
                return None
            raw_metrics = _measure(gold, found)
            if not passes(raw_metrics):
                return None
            with media.open("rb") as stream:
                audio_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            acoustic.require_alignment(reference, media)
            final = Path(temp) / "confirmed.txt"
            mode = "unchanged_prediction"
            metrics = raw_metrics
            if raw_metrics["scored_frame_precision"] < 0.90:
                _confirmed_intervals(prediction, gold[0], final)
                confirmed = _mono_timeline(final, seconds)
                if confirmed is None or not any(n.pitch is not None for n in confirmed[0]):
                    return None
                metrics = _measure(gold, confirmed)
                if not passes(metrics) or metrics["scored_frame_precision"] < 0.90:
                    return None
                mode = "confirmed_intervals"
            else:
                shutil.copyfile(prediction, final)
            final_hash = hashlib.sha256(final.read_bytes()).hexdigest()
            with media.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != audio_hash:
                    return None
            if verified_chart is not None:
                os.replace(final, verified_chart)
            return {
                "audio_sha256": audio_hash,
                "method": "independent-chart-and-recording-v2",
                "scoring": mode,
                "raw_metrics": raw_metrics,
                "source": candidate["source"],
                "catalogue_revision": allkaraoke.REVISION,
                "video_id": video,
                "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                "generated_sha256": hashlib.sha256(prediction.read_bytes()).hexdigest(),
                "chart_sha256": final_hash,
                "metrics": metrics,
            }
    except (OSError, SongError, ValueError, OverflowError, requests.RequestException):
        return None
