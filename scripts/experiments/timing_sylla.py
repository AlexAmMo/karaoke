"""Align sung graphemes to the fixed syllables, comparing Sylla's lead and pooled heads."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import numpy as np

from timing_neural import batches
from timing_predict import apply_offsets, parse, serialize
from timing_sylla_emissions import LEAD_SHA, BG_SHA

METHODS = (
    "sylla-principal",
    "sylla-dos-voces",
    "sylla-acuerdo",
    "sylla-vocal",
    "sylla-intervalo",
)


@dataclass
class Word:
    text: str
    rows: list[int]
    start: float
    end: float


def words_with_rows(rows):
    text, owners = [], []
    for i, row in enumerate(rows):
        if i and rows[i - 1].line != row.line:
            text.append(" ")
            owners.append(i)
        normalized = (
            unicodedata.normalize("NFKC", row.lyric.casefold()).replace("~", "").replace("’", "'")
        )
        text.extend(normalized)
        owners.extend([i] * len(normalized))
    tokens = list(re.finditer(r"[^\W_]+(?:'[^\W_]+)*", "".join(text)))
    result = []
    for i, token in enumerate(tokens):
        selected = owners[token.start() : token.end()]
        next_row = owners[tokens[i + 1].start()] if i + 1 < len(tokens) else len(rows)
        end = max(selected[-1], next_row - 1)
        result.append(
            Word(token.group(), selected, rows[selected[0]].start / 60, rows[end].end / 60)
        )
    return result


def path_starts(logp, targets):
    # CTC states alternate blank and literal. Non-identical adjacent letters can
    # skip one blank; identical letters need a blank separating their two spans.
    t, n = len(logp), len(targets)
    if n == 0 or t < n + sum(a == b for a, b in zip(targets[1:], targets[:-1])):
        return None
    sequence = np.zeros(2 * n + 1, dtype=int)
    sequence[1::2] = targets
    skip = np.zeros(len(sequence), dtype=bool)
    skip[2:] = (sequence[2:] != 0) & (sequence[2:] != sequence[:-2])
    prev = np.full(len(sequence), -np.inf, dtype="float32")
    prev[:2] = logp[0, sequence[:2]]
    way = np.zeros((t, len(sequence)), dtype="uint8")
    for i in range(1, t):
        step = np.r_[-np.inf, prev[:-1]].astype("float32")
        jump = np.r_[-np.inf, -np.inf, prev[:-2]].astype("float32")
        jump[~skip] = -np.inf
        take = step > prev
        best = np.where(take, step, prev)
        two = jump > best
        way[i] = np.where(two, 2, take)
        prev = np.maximum(best, jump) + logp[i, sequence]
    state = len(prev) - 1 if prev[-1] >= prev[-2] else len(prev) - 2
    if not np.isfinite(prev[state]):
        return None
    path = np.zeros(t, dtype=int)
    for i in range(t - 1, -1, -1):
        path[i] = state
        state -= int(way[i, state])
    # State order is monotone; searchsorted finds the first and last frame of each symbol.
    states = np.arange(1, len(sequence), 2)
    starts, stops = np.searchsorted(path, states), np.searchsorted(path, states + 1)
    peaks = [
        float(logp[a:b, symbol].max()) if b > a else -np.inf
        for a, b, symbol in zip(starts, stops, targets)
    ]
    return starts, stops, peaks


def anchors(rows, words, logp, labels):
    result, spans = {}, []
    vowel_ids = {labels[ch] for ch in "aeiouyáéíóúü" if ch in labels}
    for batch in batches(words):
        a = max(0, int((batch[0].start - 0.8) * 50))
        b = min(len(logp), int((batch[-1].end + 0.8) * 50) + 1, a + 32 * 50)
        targets, owners = [labels["|"]], [None]
        for word in batch:
            for ch, owner in zip(word.text, word.rows, strict=True):
                if ch in labels:
                    targets.append(labels[ch])
                    owners.append(owner)
            targets.append(labels["|"])
            owners.append(None)
        aligned = path_starts(logp[a:b], targets)
        if aligned is None:
            continue
        starts, stops, peaks = aligned
        measured = {}
        for target, owner, frame, stop, peak in zip(
            targets, owners, starts, stops, peaks, strict=True
        ):
            if owner is not None:
                spans.append(
                    [
                        owner,
                        int(frame + a),
                        int(stop + a),
                        bool(target in vowel_ids),
                        round(peak, 3),
                    ]
                )
            if owner is not None and owner not in measured:
                measured[owner] = ((frame + a) * 0.02 - rows[owner].start / 60, peak)
        # A phoneme that can be forced onto arbitrary noise supplies weak support.
        # This guard is independent of the human annotation and fixed for both heads.
        supported = {i: d for i, (d, p) in measured.items() if abs(d) <= 0.25 and p >= -4.6}
        if len(supported) >= max(1, 0.65 * len(measured)):
            result.update(supported)
    return result, spans


def nucleus_intervals(spans, supported):
    # Orthographic vowels approximate a syllable nucleus. Reject long gaps and
    # weak tokens; English spelling and backing singers can make this uncertain.
    per_row = defaultdict(list)
    for row, first, _, vowel, peak in spans:
        if row in supported:
            per_row[row].append((first * 0.02, vowel, peak))
    result = {}
    for row, tokens in per_row.items():
        onset, _, onset_peak = tokens[0]
        vowel = next((t for t in tokens if t[1]), None)
        if vowel and onset_peak >= -4.6 and vowel[2] >= -4.6 and 0 <= vowel[0] - onset <= 0.18:
            result[row] = (onset, vowel[0])
    return result


def interval_offsets(rows, lead, both):
    nucleus, cautious = {}, {}
    for row, (onset, vowel) in lead.items():
        seed = rows[row].start / 60
        if abs(vowel - seed) <= 0.25:
            nucleus[row] = vowel - seed
        if row not in both:
            continue
        other_onset, other_vowel = both[row]
        if max(abs(onset - other_onset), abs(vowel - other_vowel)) > 0.04:
            continue
        # A chart may follow the consonant or the ensuing vowel. Preserve any
        # start licensed by either head, and otherwise move only halfway.
        left, right = min(onset, other_onset), max(vowel, other_vowel)
        correction = min(max(seed, left), right) - seed
        if abs(correction) <= 0.16:
            cautious[row] = correction * 0.5
    return nucleus, cautious


def predict(rows, evidence):
    labels = {c: i for i, c in enumerate(evidence["labels"].tolist())}
    words = words_with_rows(rows)
    main, lead_spans = anchors(rows, words, evidence["lead"], labels)
    both, pooled_spans = anchors(rows, words, evidence["pooled"], labels)
    agree = {
        i: (main[i] + both[i]) * 0.25
        for i in main.keys() & both.keys()
        if abs(main[i] - both[i]) <= 0.04 and abs(main[i]) <= 0.16
    }
    nucleus, interval = interval_offsets(
        rows, nucleus_intervals(lead_spans, main), nucleus_intervals(pooled_spans, both)
    )
    estimated = dict(zip(METHODS, (main, both, agree, nucleus, interval), strict=True))
    return {
        name: apply_offsets(rows, [offsets.get(i, 0.0) for i in range(len(rows))])
        for name, offsets in estimated.items()
    }, {
        "lead": lead_spans,
        "pooled": pooled_spans,
        "hop_ms": 20,
        "columns": [
            "row",
            "start_frame",
            "end_frame_exclusive",
            "orthographic_vowel",
            "peak_log_probability",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("charts", type=Path)
    parser.add_argument("emissions", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for tag, file in json.loads(args.charts.read_text()).items():
        path = args.emissions / (tag + ".npz")
        if not path.is_file():
            continue
        chart = Path(file)
        headers, rows = parse(chart)
        with np.load(path) as data:
            recording = json.loads((chart.parent / "metrics.json").read_text())["audio_sha256"]
            if (str(data["audio_sha256"]), str(data["model_sha256"]), str(data["bg_sha256"])) != (
                recording,
                LEAD_SHA,
                BG_SHA,
            ):
                raise ValueError(f"Wrong recording or model for {tag}")
            alternatives, spans = predict(rows, data)
        dest = args.output / tag
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "grapheme-bounds.json").write_text(json.dumps(spans, separators=(",", ":")))
        hashes = {}
        for name, changed in alternatives.items():
            out = dest / (name + ".txt")
            out.write_text(serialize(headers, changed))
            hashes[name] = hashlib.sha256(out.read_bytes()).hexdigest()
        temp = dest / "hashes.tmp"
        temp.write_text(json.dumps(hashes))
        temp.replace(dest / "hashes.json")
        print(tag, flush=True)


if __name__ == "__main__":
    main()
