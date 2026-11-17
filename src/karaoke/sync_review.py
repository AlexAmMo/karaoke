"""Audition the same map locations against the chosen recording, before importing."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .songs import SongError, read_chart


@dataclass(frozen=True)
class ReviewPoint:
    start: float
    onset: float
    caption: str


def review_points(chart: Path) -> tuple[ReviewPoint, ...]:
    """Use the first, middle and last sung phrases, excluding instrumental passages."""
    text, meta = read_chart(chart)
    beat = 60 / (4 * float(meta["BPM"].replace(",", ".")))
    gap = float(meta.get("GAP", "0").replace(",", ".")) / 1000
    phrases = []
    phrase = []
    for line in text.splitlines() + ["E"]:
        note = re.match(r"^[:*FRG]\s+(-?\d+)\s+\d+\s+-?\d+\s?(.*)$", line)
        if note:
            onset = gap + int(note[1]) * beat
            phrase.append((onset, note[2]))
        elif line.startswith(("-", "E")) and phrase:
            phrases.append(phrase)
            phrase = []
    # Long maps occasionally omit line breaks. Build three cues from notes in that case.
    if len(phrases) == 1:
        notes = [note for phrase in phrases for note in phrase]
        locations = sorted({0, len(notes) // 2, max(0, len(notes) - 1)})
        phrases = [notes[i : i + 7] for i in locations]
    points = []
    for i in sorted({0, len(phrases) // 2, len(phrases) - 1}):
        phrase = phrases[i]
        audible = next(
            (j for j, (t, syllable) in enumerate(phrase) if t >= 0 and syllable.strip(" ~")), None
        )
        if audible is None:
            continue
        onset = phrase[audible][0]
        caption = "".join(s for _, s in phrase[audible:]).replace("~", "").strip()
        points.append(ReviewPoint(max(0, onset - 1.2), onset, caption))
    if not points:
        raise SongError("Este mapa no tiene frases audibles para revisar la sincronía.")
    return tuple(points)


def play_review(audio: Path, point: ReviewPoint, *, player="ffplay"):
    # Put the tone in the audio stream so GUI refresh and device latency cannot
    # shift the reference relative to the song. All filter parameters are numeric.
    delay = point.onset - point.start
    audio_filter = (
        "aformat=channel_layouts=mono,asetpts=PTS-STARTPTS,"
        f"aeval=val(0)*0.82+0.18*sin(2*PI*880*t)*between(t\\,{delay:.6f}\\,{delay + 0.070:.6f})"
    )
    return subprocess.Popen(
        [
            player,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "error",
            "-volume",
            "40",
            "-ss",
            f"{point.start:.6f}",
            "-t",
            "7",
            "-af",
            audio_filter,
            str(audio),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
