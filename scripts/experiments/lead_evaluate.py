"""Score paired, already frozen numeric predictions on their original UltraStar bars.

The input directory contains one folder per exact master with provenance.json, the three
SOME event lists (all_vocals/center/mdx.json), and both FCPE contours in observations.npz.
The artifact contains no lyrics or inference input taken from a gold chart.
"""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import extract, compare_notes, passes  # noqa: E402

SOME_SHA = "aa710fce920b4dae281b0e6cc2acba83345d82ee62d51f7bafeb29636f28f97c"
FCPE_SHA = "09c5717de92ddd5e4efc5177104f973d205102b2b5596ba91eeb19711cb90d12"
HARMONIC_INTERVALS = (3, 4, 5, 7, 8, 9)


def midi_from_hz(hz):
    midi = np.full(len(hz), np.nan)
    voiced = (hz >= 50) & (hz <= 2000)
    midi[voiced] = 69 + 12 * np.log2(hz[voiced] / 440)
    return midi


def judge_contour(contour, note):
    # Test the central voiced part of the original printed syllable, in 10ms steps.
    first = max(0, int(np.ceil((note.start + 0.015) * 100)))
    stop = min(len(contour), int(np.ceil((note.end - 0.015) * 100)))
    section = contour[first:stop]
    voiced = section[np.isfinite(section)]
    if len(voiced) < 6 or len(voiced) < 0.75 * len(section):
        return None
    mc = np.rint(voiced).astype(int)
    counts = np.bincount(mc, minlength=128)
    candidate = int(np.argmax(counts))
    if counts[candidate] < 0.8 * len(voiced):
        return None
    if abs(float(np.median(voiced)) - candidate) > 0.28:
        return None
    return candidate - 60


def event_votes(data, notes):
    events = data["events"]
    start = [e[0] for e in events]
    end = [e[1] for e in events]
    answer = []
    for n in notes:
        counts = Counter()
        for a, b, p in events[bisect_right(end, n.start) : bisect_left(start, n.end)]:
            counts[int(p)] += min(b, n.end) - max(a, n.start)
        if counts:
            pitch, weight = counts.most_common(1)[0]
            if weight >= 0.5 * (n.end - n.start):
                answer.append(pitch - 60)
                continue
        answer.append(None)
    return answer


def freeze(inputs, chart, expected_stem):
    notes, _ = extract(chart)
    out = {"shipped": [n.pitch for n in notes]}
    for method in ("all_vocals", "center", "mdx"):
        pred = json.loads((inputs / (method + ".json")).read_text())
        settings = pred["settings"]
        if (
            settings["stem_sha256"] != expected_stem
            or settings["some_sha256"] != SOME_SHA
            or settings["model"] != method
        ):
            raise ValueError("Mismatched SOME stem, weights or treatment")
        out["some_" + method] = event_votes(pred, notes)
    with np.load(inputs / "observations.npz") as obs:
        if str(obs["model_sha"]) != FCPE_SHA or str(obs["source_sha"]) != expected_stem:
            raise ValueError("Mismatched FCPE weights or stem")
        for method in ("raw", "center"):
            track = midi_from_hz(obs[method])
            out["fcpe_" + method] = [judge_contour(track, n) for n in notes]
    out["fcpe_agreement"] = [
        a if a is not None and b is not None and a % 12 == b % 12 else None
        for a, b in zip(out["fcpe_raw"], out["fcpe_center"])
    ]
    out["fcpe_center_rescue"] = [
        b if a is None else None for a, b in zip(out["fcpe_raw"], out["fcpe_center"])
    ]
    for second_vote in ("some_center", "fcpe_center"):
        out["uvr_harmony_" + second_vote] = [
            lead
            if None not in (original, all_voices, lead, corroboration)
            and original % 12 == all_voices % 12
            and lead % 12 == corroboration % 12
            and (lead - original) % 12 in HARMONIC_INTERVALS
            else None
            for original, all_voices, lead, corroboration in zip(
                out["shipped"], out["some_all_vocals"], out["some_mdx"], out[second_vote]
            )
        ]
    return {
        key: [
            replace(n, pitch=v) if v is not None and n.pitch is not None else n
            for n, v in zip(notes, votes)
        ]
        for key, votes in out.items()
    }


def classes(notes, frames):
    pitched = np.full(len(frames), -1, dtype=np.int16)
    for n in notes:
        if n.pitch is not None:
            left, right = np.searchsorted(frames, [n.start, n.end])
            pitched[left:right] = n.pitch % 12
    return pitched


def ceilings(reference, original, frames):
    """Upper bounds with perfect knowledge of the reference and unchanged game bars."""
    expected = classes(reference, frames)
    owner = np.full(len(frames), -1, dtype=int)
    for index, note in enumerate(original):
        if note.pitch is not None:
            start, end = np.searchsorted(frames, (note.start, note.end))
            owner[start:end] = index
    covered = (expected >= 0) & (owner >= 0)
    counts = np.bincount(
        owner[covered] * 12 + expected[covered], minlength=len(original) * 12
    ).reshape(-1, 12)
    pitch = float(counts.max(axis=1).sum() / (expected >= 0).sum())

    # For equal onset tolerances the earliest feasible chronological pairing achieves
    # the maximum cardinality. Labels can be assigned freely for this separate bound.
    starts = sorted(n.start for n in original if n.pitch is not None)
    truth = sorted(n.start for n in reference if n.pitch is not None)
    first = second = matches = 0
    while first < len(starts) and second < len(truth):
        a, b = starts[first], truth[second]
        if a < b - 0.1:
            first += 1
        elif b < a - 0.1:
            second += 1
        else:
            matches += 1
            first += 1
            second += 1
    return round(pitch, 4), round(2 * matches / (len(starts) + len(truth)), 4)


def run(args):
    manifest = {r["tag"]: r for r in json.loads(args.manifest.read_text())}
    paths = json.loads(args.charts.read_text())
    corpus = {r["tag"]: r for g in json.loads(args.corpus.read_text()).values() for r in g}
    metrics = {r["id"]: r for r in csv.DictReader(args.text_scores.open())}
    result = []
    for tag, case in sorted(manifest.items()):
        folder = args.inputs / tag
        status = folder / "provenance.json"
        if not status.is_file():
            if args.partial:
                continue
            raise ValueError("Missing numeric predictions for " + tag)
        meta = json.loads(status.read_text())
        if meta["master_pcm_sha256"] != case["pcm_sha256"] or meta["tag"] != tag:
            raise ValueError("Master identity mismatch " + tag)
        base = Path(paths[tag])
        with base.open("rb") as f:
            sha = hashlib.file_digest(f, "sha256").hexdigest()
        if metrics[tag]["generated_sha256"] != sha:
            raise ValueError("Word and timing scores refer to a different fixed chart")
        frozen = freeze(folder, base, meta["stem_sha256"])
        reference_path = Path(corpus[tag]["reference"])
        with reference_path.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != case["chart_sha"]:
                raise ValueError("Gold map mismatch for " + tag)
        ref, _ = extract(reference_path)
        dur = corpus[tag]["duration"]
        gt = [replace(n, end=min(n.end, dur)) for n in ref if 0 <= n.start < dur]

        def bound(notes):
            return [replace(n, end=min(n.end, dur)) for n in notes if 0 <= n.start < dur]

        frames = np.arange(0, dur, 0.01)
        expected = classes(gt, frames)
        max_pitch, max_attacks = ceilings(gt, bound(frozen["shipped"]), frames)
        before = {
            name: classes(bound(frozen[name]), frames) for name in ("shipped", "some_all_vocals")
        }
        for method, notes in frozen.items():
            pred = bound(notes)
            m = compare_notes(gt, pred)
            m.update(
                wer=float(metrics[tag]["wer"]),
                word_mae_p50_p90_s=[0, float(metrics[tag]["word_p90_s"])],
            )
            changed = sum(
                n.pitch is not None and n.pitch % 12 != o.pitch % 12
                for n, o in zip(notes, frozen["shipped"])
            )
            if method == "shipped" and m["correct_class_all"] != float(metrics[tag]["pitch"]):
                raise ValueError("Baseline differs from the fixed corpus")
            target = before["some_all_vocals" if method.startswith("some_") else "shipped"]
            current = classes(pred, frames)
            fixed = (expected >= 0) & (current == expected) & (target != expected)
            broken = (expected >= 0) & (current != expected) & (target == expected)
            gap = (target - expected) % 12
            original_errors = (expected >= 0) & (target >= 0) & (target != expected)
            harmonic_gap = np.isin(gap, HARMONIC_INTERVALS)
            result.append(
                dict(
                    id=tag,
                    language=case["language"],
                    method=method,
                    master_pcm_sha256=meta["master_pcm_sha256"],
                    paired_stem_sha256=meta["stem_sha256"],
                    chart_sha256=sha,
                    changed=changed,
                    repaired_frames=int(fixed.sum()),
                    degraded_frames=int(broken.sum()),
                    repaired_3rd_4th_5th_frames=int((fixed & (target >= 0) & harmonic_gap).sum()),
                    initial_wrong_class_frames=int(original_errors.sum()),
                    initial_3rd_4th_5th_frames=int((original_errors & harmonic_gap).sum()),
                    fixed_bar_pitch_upper_bound=max_pitch,
                    fixed_attack_f1_upper_bound=max_attacks,
                    wer=m["wer"],
                    word_p90_s=m["word_mae_p50_p90_s"][1],
                    pitch=m["correct_class_all"],
                    attacks=m["onset_pitch_f1_100ms"],
                    passes=passes(m),
                )
            )
    if result:
        with args.out.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(result[0]))
            writer.writeheader()
            writer.writerows(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("manifest", "charts", "corpus", "inputs", "text-scores", "out"):
        p.add_argument("--" + field, type=Path, required=True)
    p.add_argument("--partial", action="store_true")
    run(p.parse_args())
