"""Check held durations for already frozen candidates that passed the first four gates."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import passes
from karaoke.generation_verification import _confirmed_intervals, _measure, _mono_timeline


def predictions(rows, folder, field, methods=None):
    for row in rows:
        name, tag = row["metodo"], row["id"]
        if not int(row["supera_objetivos"]) or (methods and name not in methods):
            continue
        path = folder / tag / (name + ".txt")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row[field]:
            raise ValueError(f"Changed prediction for {tag}, {name}")
        yield tag, name, path


def run(args):
    cases = {r["tag"]: r for group in json.loads(args.corpus.read_text()).values() for r in group}
    candidates = []
    with args.ornament_scores.open() as file:
        candidates.extend(predictions(csv.DictReader(file), args.ornaments, "salida_sha256"))
    with args.timing_scores.open() as file:
        candidates.extend(
            predictions(csv.DictReader(file), args.fusion, "borrador_sha256", {"consenso-completo"})
        )
    results = []
    with tempfile.TemporaryDirectory() as directory:
        final = Path(directory) / "confirmed.txt"
        for tag, name, path in candidates:
            case = cases[tag]
            reference = Path(case["reference"])
            if hashlib.sha256(reference.read_bytes()).hexdigest() != case["chart_sha"]:
                raise ValueError(f"Changed reference for {tag}")
            gold = _mono_timeline(reference, case["duration"])
            start = _measure(gold, _mono_timeline(path, case["duration"]))
            if not passes(start):
                raise ValueError(f"Could not reproduce initial acceptance for {tag}")
            _confirmed_intervals(path, gold[0], final)
            m = _measure(gold, _mono_timeline(final, case["duration"]))
            results.append(
                dict(
                    id=tag,
                    method=name,
                    source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    reference_sha256=case["chart_sha"],
                    raw_precision=start["scored_frame_precision"],
                    final_precision=m["scored_frame_precision"],
                    final_correct_class=m["correct_class_all"],
                    final_onset_f1=m["onset_pitch_f1_100ms"],
                    final_word_p90_s=m["word_mae_p50_p90_s"][1],
                    final_wer=m["wer"],
                    eligible_after_confirmation=passes(m) and m["scored_frame_precision"] >= 0.9,
                )
            )
    with args.output.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("corpus", "ornaments", "ornament-scores", "fusion", "timing-scores", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    run(parser.parse_args())
