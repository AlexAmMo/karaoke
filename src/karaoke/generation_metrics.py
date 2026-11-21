"""Compare two fixed absolute UltraStar timelines, without transposition or fitting the clock."""

from dataclasses import dataclass, replace
import math
import re
import unicodedata

import numpy as np

from .songs import read_chart


@dataclass
class Note:
    start: float
    end: float
    pitch: int | None
    text: str


TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
ROW = re.compile(r"^([:*FRG])\s+(-?\d+)\s+(\d+)\s+(-?\d+) (.*)$")


def extract(chart):
    text, meta = read_chart(chart)
    tick = 15 / float(meta["BPM"].replace(",", "."))
    gap = float(meta.get("GAP", "0").replace(",", ".")) / 1000
    notes, chars, onsets = [], [], []
    for line in text.splitlines():
        m = ROW.match(line)
        if m:
            kind, s, d, p, lyric = m.groups()
            start = gap + int(s) * tick
            note = Note(start, start + int(d) * tick, int(p) if kind in ":*" else None, lyric)
            notes.append(note)
            clean = unicodedata.normalize("NFKC", lyric.casefold()).replace("~", "")
            chars.append(clean)
            onsets.extend([start] * len(clean))
        elif line.startswith("-"):
            chars.append(" ")
            onsets.append(0)
    words = [(w.group(), onsets[w.start()]) for w in TOKEN.finditer("".join(chars))]
    return notes, words


def compare_words(ref, hyp):
    # Sequence alignment, never estimating a time shift from the reference.
    a, b = len(ref), len(hyp)
    cost = np.empty((a + 1, b + 1), dtype=int)
    cost[:, 0], cost[0, :] = np.arange(a + 1), np.arange(b + 1)
    for i in range(1, a + 1):
        for j in range(1, b + 1):
            c = ref[i - 1][0] != hyp[j - 1][0]
            cost[i, j] = min(cost[i - 1, j] + 1, cost[i, j - 1] + 1, cost[i - 1, j - 1] + c)
    i, j = a, b
    errors, matched_times = [], []
    while i or j:
        equal = i and j and ref[i - 1][0] == hyp[j - 1][0]
        if i and j and cost[i, j] == cost[i - 1, j - 1] + (not equal):
            if equal:
                delta = hyp[j - 1][1] - ref[i - 1][1]
                errors.append(abs(delta))
                matched_times.append((ref[i - 1][1], delta))
            i, j = i - 1, j - 1
        elif i and cost[i, j] == cost[i - 1, j] + 1:
            i -= 1
        else:
            j -= 1
    # Per-third medians expose time drift hidden by aggregate percentiles.
    bounds = np.linspace(ref[0][1], ref[-1][1] + 1e-6, 4)
    thirds = [[d for t, d in matched_times if lo <= t < hi] for lo, hi in zip(bounds, bounds[1:])]
    return dict(
        ref_words=a,
        hyp_words=b,
        edits=int(cost[a, b]),
        wer=round(cost[a, b] / a, 4),
        exact=len(errors),
        word_mae_p50_p90_s=np.round(np.percentile(errors, [50, 90]), 3).tolist() if errors else [],
        signed_word_p50_by_third_s=[
            round(float(np.median(ds)), 3) if ds else None for ds in thirds
        ],
    )


def compare_notes(ref, hyp):
    # Reference frames with a scored melody provide the denominator, including missed frames.
    frames = np.arange(0, max(ref[-1].end, hyp[-1].end) + 0.01, 0.01)

    def paint(notes):
        track = np.full(len(frames), -1)
        for n in notes:
            if n.pitch is not None:
                a, b = np.searchsorted(frames, [n.start, n.end])
                track[a:b] = n.pitch % 12
        return track

    gold, found = paint(ref), paint(hyp)
    scored = gold >= 0
    overlap = scored & (found >= 0)
    distance = abs(gold - found)
    exact = scored & (found == gold)
    within = overlap & (np.minimum(distance, 12 - distance) <= 1)
    # Count each onset at most once. Matching requires both a 100 ms window and
    # the same pitch class. Within each class the onsets are chronological.
    matches = 0
    for pitch_class in range(12):

        def starts(notes):
            return [n.start for n in notes if n.pitch is not None and n.pitch % 12 == pitch_class]

        reference, generated = starts(ref), starts(hyp)
        i = j = 0
        while i < len(reference) and j < len(generated):
            if reference[i] < generated[j] - 0.1:
                i += 1
            elif generated[j] < reference[i] - 0.1:
                j += 1
            else:
                i += 1
                j += 1
                matches += 1
    total = sum(n.pitch is not None for n in ref) + sum(n.pitch is not None for n in hyp)
    return dict(
        reference_notes=sum(n.pitch is not None for n in ref),
        generated_scored=sum(n.pitch is not None for n in hyp),
        generated_freestyle=sum(n.pitch is None for n in hyp),
        covered_frames=round(overlap.sum() / scored.sum(), 4),
        correct_class_all=round(exact.sum() / scored.sum(), 4),
        within_one_semitone_all=round(within.sum() / scored.sum(), 4),
        correct_when_covered=round(exact.sum() / overlap.sum(), 4) if overlap.any() else None,
        matching_onsets=matches,
        onset_pitch_f1_100ms=round(2 * matches / total, 4) if total else None,
    )


def score(reference, draft, offset, duration, clip):
    # This is where the human notes and words are decoded. Discard boundary words whose
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


def passes(m):
    p90 = m.get("word_mae_p50_p90_s", [])
    return bool(
        len(p90) == 2
        and p90[1] <= 0.12
        and m.get("wer", math.inf) <= 0.05
        and (m.get("correct_class_all") or 0) >= 0.9
        and (m.get("onset_pitch_f1_100ms") or 0) >= 0.85
    )
