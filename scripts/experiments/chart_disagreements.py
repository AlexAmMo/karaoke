"""Explain frame and timing errors after predictions are frozen. The offset sweep is diagnostic only."""

import argparse
import csv
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import compare_notes, extract, passes, score  # noqa: E402


def chroma_errors(ref, hyp, duration):
    timeline = np.arange(0, duration, 0.01)

    def paint(notes):
        out = np.full(timeline.size, -999)
        for n in notes:
            if n.pitch is not None:
                a, b = np.searchsorted(timeline, [n.start, n.end])
                out[a:b] = n.pitch
        return out

    gold, found = paint(ref), paint(hyp)
    is_gold = gold != -999
    overlap = is_gold & (found != -999)
    distance = (found[overlap] - gold[overlap]) % 12
    distances = np.minimum(distance, 12 - distance)
    errors = np.bincount(distances, minlength=7)
    duration = int(is_gold.sum())
    return {
        "voiced_frames": duration,
        "missed_frames": int((is_gold & (found == -999)).sum()),
        **{f"chroma_distance_{n}": int(v) for n, v in enumerate(errors)},
        "octave_equivalents": int(((distance == 0) & (found[overlap] != gold[overlap])).sum()),
    }


def releases(gold, found):
    """Measure the far end of a bar after a unique same-class attack match."""
    ends = []
    duration_errors = []
    matching_ends = 0
    for pitch in range(12):
        reference = [n for n in gold if n.pitch is not None and n.pitch % 12 == pitch]
        predicted = [n for n in found if n.pitch is not None and n.pitch % 12 == pitch]
        i = j = 0
        while i < len(reference) and j < len(predicted):
            a, b = reference[i], predicted[j]
            if a.start < b.start - 0.1:
                i += 1
            elif b.start < a.start - 0.1:
                j += 1
            else:
                ends.append(1000 * abs(b.end - a.end))
                duration = a.end - a.start
                duration_errors.append(1000 * (b.end - b.start - duration))
                matching_ends += abs(b.end - a.end) <= max(0.05, 0.2 * duration)
                i += 1
                j += 1
    total = sum(n.pitch is not None for n in gold) + sum(n.pitch is not None for n in found)
    return dict(
        matched_ends=matching_ends,
        end_p50_ms=round(float(np.median(ends)), 1) if ends else None,
        end_p90_ms=round(float(np.percentile(ends, 90)), 1) if ends else None,
        duration_bias_p50_ms=round(float(np.median(duration_errors)), 1) if ends else None,
        onset_pitch_offset_f1=round(2 * matching_ends / total, 4) if total else None,
    )


def run(args):
    paths = json.loads(args.charts.read_text())
    corpus = {r["tag"]: r for group in json.loads(args.corpus.read_text()).values() for r in group}
    manifest = {r["tag"]: r for r in json.loads(args.manifest.read_text())}
    if set(manifest) != set(paths) or len(paths) != 40:
        raise ValueError("Expected exactly the frozen 40-song manifest.")
    output = []
    for tag, name in sorted(paths.items()):
        r, pred = corpus[tag], Path(name)
        reference = Path(r["reference"])
        if hashlib.sha256(reference.read_bytes()).hexdigest() != manifest[tag]["chart_sha"]:
            raise ValueError(f"Wrong reference for {tag}")
        gold = extract(reference)[0]
        hyp = extract(pred)[0]
        metric = score(reference, pred, 0, r["duration"], False)
        raw = compare_notes(gold, hyp)
        sweep = []
        for shift_ms in (-150, -100, -50, 0, 50, 100, 150):
            delta = shift_ms / 1000
            moved = []
            for n in hyp:
                if n.end + delta > 0:
                    moved.append(replace(n, start=max(0, n.start + delta), end=n.end + delta))
            if not moved:
                continue
            # Select only with respect to attack F1. No shift is used to generate or qualify a chart.
            sweep.append(
                (compare_notes(gold, moved)["onset_pitch_f1_100ms"], -abs(delta), shift_ms)
            )
        best_f1, _, shift_ms = max(sweep)
        output.append(
            {
                "id": tag,
                "language": r["language"],
                "master_sha256": r["audio_sha"],
                "generated_sha256": hashlib.sha256(pred.read_bytes()).hexdigest(),
                "wer": metric["wer"],
                "word_p90_s": metric["word_mae_p50_p90_s"][1],
                "pitch": metric["correct_class_all"],
                "onset_f1": metric["onset_pitch_f1_100ms"],
                "passes": passes(metric),
                "human_bars": raw["reference_notes"],
                "generated_bars": raw["generated_scored"],
                "matched_bars": raw["matching_onsets"],
                "best_fixed_shift_ms": shift_ms,
                "best_fixed_shift_f1": best_f1,
                **chroma_errors(gold, hyp, min(900, math.ceil(r["duration"]))),
                **releases(gold, hyp),
            }
        )
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, default=Path("docs/validation/generacion-muestra.json"))
    for name in ("charts", "corpus", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    run(p.parse_args())
