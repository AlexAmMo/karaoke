"""Explain frozen chart errors; references are used for diagnosis only, never prediction.

Reproduce the existing 10 ms metric, partition its denominator, and compare it
with continuous interval integration and an independent rational tick parser.
No audio is opened, no chart is written, no offset/threshold is fitted.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from karaoke.generation_metrics import Note, compare_notes, extract  # noqa: E402
from karaoke.songs import read_chart  # noqa: E402

ABSENT = -999
EXAMPLES = ("bad-bunny-amorfoda", "northern-star", "31-minutos-la-senora-interesante", "abba-estoy-sonando")
NOTE_ROW = re.compile(r"^([:*FRG])\s+(-?\d+)\s+(\d+)\s+(-?\d+)(?:\s|$)")
PARTITION = ("same_pitch_number", "same_class_other_octave", "wrong_pitch_class",
             "reference_freestyle", "reference_rap", "unannotated_before", "unannotated_between", "unannotated_after")


@dataclass
class Interval:
    start: float
    end: float
    pitch: int
    kind: str


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_intervals(path):
    path = Path(path)
    text, metadata = read_chart(path)
    # Independent rational conversion: UltraStar has four ticks per quarter.
    step = Fraction(15) / Fraction(metadata["BPM"].replace(",", "."))
    gap = Fraction(metadata.get("GAP", "0").replace(",", ".")) / 1000
    rows, kinds = [], Counter()
    for line in text.splitlines():
        match = NOTE_ROW.match(line)
        if not match:
            continue
        kind, start, length, pitch = match.groups()
        a = gap + int(start) * step
        rows.append(Interval(a, a + int(length) * step, int(pitch), kind))
        kinds[kind] += 1
    extracted, _ = extract(path)
    assert len(rows) == len(extracted)
    clock_error = max(abs(float(t) - u) for a, b in zip(rows, extracted, strict=True)
                      for t, u in ((a.start, b.start), (a.end, b.end)))
    canonical = [Interval(b.start, b.end, a.pitch, a.kind) for a, b in zip(rows, extracted, strict=True)]
    return canonical, extracted, {
        "bpm": float(Fraction(metadata["BPM"].replace(",", "."))),
        "gap_seconds": float(gap), "tick_seconds": float(step),
        "kinds": dict(kinds), "rational_parser_max_error_seconds": clock_error,
        "relative": metadata.get("RELATIVE", "NO").upper() == "YES",
        "variable_bpm_rows": len(re.findall(r"^B\s", text, re.M)),
        "duet_rows": len(re.findall(r"^P\s*[23]", text, re.M)),
        "start_header": metadata.get("START"), "end_header": metadata.get("END"),
    }, rows


def rational_grid_pitch(rows, length):
    """Exact ceil(time / 10 ms), independent of binary floating-point ties."""
    result = np.full(length, ABSENT, dtype=np.int16)
    for row in rows:
        if row.kind in ":*":
            result[max(0, math.ceil(row.start * 100)):max(0, math.ceil(row.end * 100))] = row.pitch
    return result


def paint(rows, points):
    pitch = np.full(len(points), ABSENT, dtype=np.int16)
    kind = np.full(len(points), "", dtype="U1")
    index = np.full(len(points), -1, dtype=np.int32)
    for i, note in enumerate(rows):
        a, b = np.searchsorted(points, [note.start, note.end])
        kind[a:b], index[a:b] = note.kind, i
        if note.kind in ":*":
            pitch[a:b] = note.pitch
    return pitch, kind, index


def proportions(gold, found, weights=None):
    ref, pred = gold != ABSENT, found != ABSENT
    correct = ref & pred & (gold % 12 == found % 12)
    overlap = ref & pred
    weights = np.ones(len(gold)) if weights is None else weights

    def total(mask):
        return float(weights[mask].sum())

    r, p, c = total(ref), total(pred), total(correct)
    return {"correct_class_all": c / r, "scored_frame_precision": c / p,
            "covered_frames": total(overlap) / r, "predicted_reference_ratio": p / r,
            "perfect_pitch_precision_upper_bound_fixed_intervals": total(overlap) / p}


def matched_attacks(reference, candidate):
    result = {}
    for pitch in range(12):
        ref = [(i, n) for i, n in enumerate(reference) if n.kind in ":*" and n.pitch % 12 == pitch]
        hyp = [(i, n) for i, n in enumerate(candidate) if n.kind in ":*" and n.pitch % 12 == pitch]
        i = j = 0
        while i < len(ref) and j < len(hyp):
            a, b = ref[i][1], hyp[j][1]
            if a.start < b.start - .1:
                i += 1
            elif b.start < a.start - .1:
                j += 1
            else:
                result[hyp[j][0]] = ref[i][0]
                i += 1
                j += 1
    return result


def frame_diagnosis(reference, candidate, duration):
    points = np.arange(0, max(reference[-1].end, candidate[-1].end) + .01, .01)
    gold, kind, _ = paint(reference, points)
    found, _, found_index = paint(candidate, points)
    ref, pred = gold != ABSENT, found != ABSENT
    correct = ref & pred & (gold % 12 == found % 12)
    unsupported = pred & ~ref
    empty = unsupported & (kind == "")
    between = empty & (points >= reference[0].start) & (points < reference[-1].end)
    masks = {
        "same_pitch_number": correct & (gold == found),
        "same_class_other_octave": correct & (gold != found),
        "wrong_pitch_class": ref & pred & ~correct,
        "reference_freestyle": unsupported & (kind == "F"),
        "reference_rap": unsupported & np.isin(kind, ["R", "G"]),
        "unannotated_before": empty & (points < reference[0].start),
        "unannotated_between": between,
        "unannotated_after": empty & (points >= reference[-1].end),
    }
    counts = {key: int(value.sum()) for key, value in masks.items()}
    counts.update(reference_frames=int(ref.sum()), predicted_frames=int(pred.sum()),
                  correct_class_frames=int(correct.sum()), overlap_frames=int((ref & pred).sum()),
                  reference_missed_frames=int((ref & ~pred).sum()),
                  predicted_outside_audio_frames=int((pred & ((points < 0) | (points >= duration))).sum()))
    assert sum(counts[key] for key in PARTITION) == counts["predicted_frames"]
    gap_bins = {"up_to_50ms": 0, "50_to_150ms": 0, "150_to_500ms": 0, "500_to_2000ms": 0, "over_2000ms": 0}
    for left, right in zip(reference, reference[1:]):
        gap = right.start - left.end
        if gap <= 0:
            continue
        bucket = next(name for upper, name in zip((.05, .15, .5, 2, float("inf")), gap_bins, strict=True) if gap <= upper)
        gap_bins[bucket] += int((between & (points >= left.end) & (points < right.start)).sum())
    assert sum(gap_bins.values()) == counts["unannotated_between"]
    leading = trailing = 0
    matches = matched_attacks(reference, candidate)
    overhang_examples = []
    for ci, ri in matches.items():
        c, r = candidate[ci], reference[ri]
        bad = pred & ~correct & (found_index == ci)
        before = int((bad & (points < r.start)).sum())
        after = int((bad & (points >= r.end)).sum())
        leading += before
        trailing += after
        if before + after:
            overhang_examples.append({"candidate_note_index": ci, "reference_note_index": ri,
                                      "candidate_start_end_s": [c.start, c.end],
                                      "reference_start_end_s": [r.start, r.end],
                                      "pitch_class": c.pitch % 12,
                                      "incorrect_leading_frames": before, "incorrect_trailing_frames": after})
    counts.update(matched_attack_incorrect_leading_frames=leading,
                  matched_attack_incorrect_trailing_frames=trailing,
                  matched_attack_count=len(matches))
    metrics = proportions(gold, found)
    assert abs(metrics["scored_frame_precision"] * metrics["predicted_reference_ratio"] - metrics["correct_class_all"]) < 1e-12
    # Independent continuous integration across all interval edges; no 10 ms grid.
    boundaries = np.unique([0, *[p for note in [*reference, *candidate] for p in (note.start, note.end)]])
    midpoints = (boundaries[:-1] + boundaries[1:]) / 2
    continuous = proportions(paint(reference, midpoints)[0], paint(candidate, midpoints)[0], np.diff(boundaries))
    shifted_grid = np.arange(.005, max(reference[-1].end, candidate[-1].end) + .01, .01)
    shifted = proportions(paint(reference, shifted_grid)[0], paint(candidate, shifted_grid)[0])
    return counts, gap_bins, metrics, continuous, shifted, sorted(overhang_examples, key=lambda x: x["incorrect_trailing_frames"], reverse=True)[:3]


def mathematical_probes():
    # Half-open intervals share a boundary without counting that instant twice.
    ref = [Note(0, .5, 60, ""), Note(.5, 1, 62, "")]
    assert compare_notes(ref, ref)["correct_class_all"] == 1
    gold, _, _ = paint([Interval(0, .5, 60, ":"), Interval(.5, 1, 62, ":")], np.array([0, .5, 1]))
    assert gold.tolist() == [60, 62, ABSENT]
    # Perfect coverage/class recall can coexist with 50% precision when a bar
    # extends into an unannotated interval; the octave difference is accepted.
    ref, hyp = [Note(0, .5, 60, "")], [Note(0, 1, 72, "")]
    assert compare_notes(ref, hyp)["correct_class_all"] == 1
    assert compare_notes(ref, hyp)["covered_frames"] == 1
    assert compare_notes(hyp, ref)["correct_class_all"] == .5
    return {"half_open_boundary": "passed", "octave_equivalence": "passed",
            "100_percent_recall_50_percent_precision_example": "passed"}


def run(args):
    frozen = json.loads(args.frozen.read_text(encoding="utf-8"))
    evaluation_path = args.frozen.with_name("evaluation.json")
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    assert evaluation["frozen_manifest_sha256"] == digest(args.frozen)
    assert len(frozen["entries"]) == frozen["cohort_size"] == 40
    official = {row["id"]: row for row in evaluation["recordings"]}
    identities = {r["tag"]: r for r in json.loads((ROOT / "docs/validation/generacion-muestra.json").read_text(encoding="utf-8"))}
    assert set(official) == set(identities) == {row["id"] for row in frozen["entries"]}
    rows, examples = [], {}
    for entry in frozen["entries"]:
        tag = entry["id"]
        assert entry["reference"]["sha256"] == identities[tag]["chart_sha"]
        assert entry["audio"]["sha256"] == identities[tag]["audio_sha"]
        for name in ("audio", "reference", "candidate"):
            assert digest(entry[name]["path"]) == entry[name]["sha256"]
        reference, gold, ref_meta, rational_ref = read_intervals(entry["reference"]["path"])
        candidate, hyp, hyp_meta, rational_hyp = read_intervals(entry["candidate"]["path"])
        for notes, metadata in ((reference, ref_meta), (candidate, hyp_meta)):
            assert not metadata["relative"] and not metadata["variable_bpm_rows"] and not metadata["duet_rows"], tag
            assert all(0 <= note.start < note.end <= entry["duration_seconds"] + 1e-9 for note in notes), tag
            assert all(a.end <= b.start + 1e-9 for a, b in zip(notes, notes[1:])), tag
        counts, gaps, measured, continuous, shifted, overhangs = frame_diagnosis(reference, candidate, entry["duration_seconds"])
        actual = {**compare_notes(gold, hyp), "scored_frame_precision": compare_notes(hyp, gold)["correct_class_all"]}
        for key in ("correct_class_all", "scored_frame_precision", "covered_frames"):
            assert round(measured[key], 4) == actual[key] == official[tag]["metrics"][key], (tag, key)
        length = math.ceil(max(rational_ref[-1].end, rational_hyp[-1].end) * 100) + 1
        exact_grid = proportions(rational_grid_pitch(rational_ref, length), rational_grid_pitch(rational_hyp, length))
        row = {"id": tag, "language": entry["language"], "duration_seconds": entry["duration_seconds"],
               "reference_sha256": entry["reference"]["sha256"], "candidate_sha256": entry["candidate"]["sha256"],
               "counts_10ms": counts, "unannotated_internal_gap_frames": gaps,
               "metrics_10ms": measured, "continuous_interval_metrics": continuous,
               "rational_clock_grid_metrics": exact_grid,
               "grid_origin_5ms_metrics": shifted, "reference_clock": ref_meta, "candidate_clock": hyp_meta}
        rows.append(row)
        if tag in EXAMPLES:
            examples[tag] = {**row, "matched_overhang_examples_without_lyrics": overhangs}
    groups = {}
    for language in ("all", "es", "en"):
        subset = [r for r in rows if language == "all" or r["language"] == language]
        totals = {key: sum(r["counts_10ms"][key] for r in subset) for key in rows[0]["counts_10ms"]}
        p, r, c = (totals[key] for key in ("predicted_frames", "reference_frames", "correct_class_frames"))
        groups[language] = {"songs": len(subset), "counts_10ms": totals,
            "pooled_metrics": {"correct_class_all": c/r, "scored_frame_precision": c/p,
                               "covered_frames": totals["overlap_frames"]/r, "predicted_reference_ratio": p/r,
                               "perfect_pitch_precision_upper_bound_fixed_intervals": totals["overlap_frames"]/p},
            "median_per_song_metrics": {key: statistics.median(row["metrics_10ms"][key] for row in subset) for key in rows[0]["metrics_10ms"]},
            "predicted_frame_partition_fractions": {key: totals[key]/p for key in PARTITION},
            "unannotated_internal_gap_frames": {key: sum(row["unannotated_internal_gap_frames"][key] for row in subset) for key in rows[0]["unannotated_internal_gap_frames"]}}
    result = {"scope": "Post-hoc error diagnosis only. Gold is opened here; outputs are not predictions, admission decisions, or parameter tuning.",
        "frozen_manifest_sha256": digest(args.frozen), "evaluation_sha256": digest(evaluation_path),
        "implementation_sha256": digest(__file__), "probes": mathematical_probes(),
        "definitions": {"reference_frames": "R: scored :/* reference frames", "predicted_frames": "P: scored :/* candidate frames",
            "correct_class_frames": "C: overlap with same pitch modulo12", "class_recall": "C/R", "scored_frame_precision": "C/P",
            "coverage": "overlap/R, regardless of pitch", "identity": "precision * (P/R) = class_recall per song and when pooling counts",
            "perfect_pitch_precision_upper_bound_fixed_intervals": "overlap/P: diagnostic oracle, even allowing a perfect independently chosen pitch in every scored candidate frame; no interval or scored/free-style status changes. Not a prediction or an achievable measured model.",
            "unannotated": "No reference row at this instant. Does not establish physical silence or missing backing vocals/repetitions.",
            "reference_rap": "Explicit R/G reference rows, excluded from pitch scoring by the existing metric",
            "same_class_other_octave": "Different chart pitch integer, same modulo12; accepted by the existing class metric, not an error",
            "overhangs": "Incorrect frames before/after the reference bar matched once by same-class attack within100ms; a diagnostic subset, not an extra disjoint category"},
        "groups": groups, "rows": rows,
        "discretization_checks": {"maximum_rational_clock_difference_seconds": max(row[side]["rational_parser_max_error_seconds"] for row in rows for side in ("reference_clock", "candidate_clock")),
            "maximum_precision_difference_from_continuous_pp": max(abs(row["metrics_10ms"]["scored_frame_precision"]-row["continuous_interval_metrics"]["scored_frame_precision"])*100 for row in rows),
            "maximum_precision_difference_from_rational_grid_pp": max(abs(row["metrics_10ms"]["scored_frame_precision"]-row["rational_clock_grid_metrics"]["scored_frame_precision"])*100 for row in rows),
            "maximum_precision_difference_from_5ms_grid_origin_pp": max(abs(row["metrics_10ms"]["scored_frame_precision"]-row["grid_origin_5ms_metrics"]["scored_frame_precision"])*100 for row in rows)}}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "diagnosis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (args.output / "examples.json").write_text(json.dumps(examples, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    flat = [{"id": row["id"], "language": row["language"], **row["metrics_10ms"], **row["counts_10ms"]} for row in rows]
    with (args.output / "frames.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)
    print(json.dumps({"songs": len(rows), "groups": groups, "discretization_checks": result["discretization_checks"], "probes": result["probes"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, default=ROOT / "build/generation-next/swift/common-evaluation/baseline/frozen.json")
    parser.add_argument("--output", type=Path, default=ROOT / "build/generation-next/error-diagnosis")
    run(parser.parse_args())
