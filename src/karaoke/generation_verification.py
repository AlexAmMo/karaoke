"""Check a completed prediction against the independent chart for its exact recording."""

import hashlib
import math
from pathlib import Path
import tempfile

import requests

from . import acoustic, allkaraoke
from .generation_metrics import compare_notes, compare_words, extract, passes
from .songs import SongError


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


def verify_generated(chart, media, seconds, video, catalogues):
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
            gold = _mono_timeline(reference, seconds)
            found = _mono_timeline(chart, seconds)
            if gold is None or found is None:
                return None
            notes, words = gold
            generated_notes, generated_words = found
            if not any(n.pitch is not None for n in notes):
                return None
            metrics = {
                **compare_words(words, generated_words),
                **compare_notes(notes, generated_notes),
            }
            if not passes(metrics):
                return None
            acoustic.require_alignment(reference, media)
            with media.open("rb") as stream:
                media_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            return {
                "audio_sha256": media_hash,
                "method": "independent-chart-and-recording-v1",
                "source": candidate["source"],
                "catalogue_revision": allkaraoke.REVISION,
                "video_id": video,
                "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
                "chart_sha256": hashlib.sha256(chart.read_bytes()).hexdigest(),
                "metrics": metrics,
            }
    except (OSError, SongError, ValueError, OverflowError, requests.RequestException):
        return None
