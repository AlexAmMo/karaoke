"""Freeze predeclared YourMT3 chart variants before interpreting any reference."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import evaluate_generation_candidate as common
from melody_compare import transform
from karaoke.generation_metrics import Note, extract


ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ("baseline", "pitch", "events")
BASELINE_PLAN = ROOT / "build/generation-next/consensus-releases/v2/plan.json"
BASELINE_PLAN_SHA = "6b2d9e0481a408f2c21cf1f32031907b6bcaf12a1736b210e63b52761db369b0"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def validate_predictions(folder, protocol_path):
    protocol = load(protocol_path)
    for path, digest in protocol["files"].items():
        if sha(path) != digest:
            raise ValueError(f"Changed evaluation dependency: {path}")
    frozen = load(folder / "frozen.json")
    if frozen["completed_ids"] != protocol["pilot_ids"] or frozen["present"] != 4:
        raise ValueError("Require the complete predeclared four-recording pilot")
    for relative, digest in frozen["files"].items():
        if sha(folder / relative) != digest:
            raise ValueError(f"Prediction changed: {relative}")
    plan = load(folder / "plan.json")
    if plan["evaluation_plan"]["sha256"] != sha(protocol_path):
        raise ValueError("Prediction and evaluation protocols differ")
    if load(folder / "execution-frozen.json")["prediction_freeze_sha256"] != sha(folder / "frozen.json"):
        raise ValueError("Execution and prediction freezes differ")
    return protocol


def eligible(events, duration):
    if not events or not math.isfinite(duration) or duration <= 0:
        return False
    if any(len(e) != 3 or not all(math.isfinite(v) for v in e)
           or not 0 <= e[0] < e[1] <= duration or not 0 <= e[2] <= 127
           or e[2] != round(e[2]) for e in events):
        return False
    return all(a[1] <= b[0] for a, b in zip(events, events[1:]))


def checked_baselines(protocol):
    """Compare actual lyric-chart bytes with their earlier freeze, before projection."""
    if sha(BASELINE_PLAN) != BASELINE_PLAN_SHA:
        raise ValueError("Earlier baseline provenance changed")
    expected = {row["id"]: row["baseline"] for row in load(BASELINE_PLAN)["entries"]}
    manifest = load(ROOT / "build/generation-v3/lyrics/final/charts.json")
    for tag in protocol["pilot_ids"]:
        item = expected[tag]
        if Path(manifest[tag]).resolve() != Path(item["path"]).resolve() or sha(manifest[tag]) != item["sha256"]:
            raise ValueError(f"Predicted lyric chart changed since its earlier freeze: {tag}")
    return manifest


def freeze_maps(args):
    protocol = validate_predictions(args.predictions, args.protocol)
    if args.output.exists():
        raise ValueError("Use a new output directory")
    baseline = checked_baselines(protocol)
    manifests = {variant: {} for variant in VARIANTS}
    statuses = []
    for tag in protocol["pilot_ids"]:
        data = load(args.predictions / "arms/lead" / (tag + ".json"))
        valid = eligible(data["events"], data["duration_s"])
        if valid != data["eligible_for_monophonic_map"]:
            raise ValueError(f"Independent eligibility check differs: {tag}")
        manifests["baseline"][tag] = baseline[tag]
        statuses.append({"id": tag, "eligible": valid, "diagnostics": data["diagnostics"],
                         "note_count": len(data["events"])})
        if not valid:
            continue
        projected = transform(Path(baseline[tag]), data["events"], data["duration_s"])
        for variant in ("pitch", "events"):
            path = args.output / "charts" / variant / (tag + ".txt")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                stream.write(projected[variant])
            manifests[variant][tag] = str(path.resolve())
    for variant, manifest in manifests.items():
        path = args.output / (variant + ".json")
        save(path, manifest)
        freeze = common.freeze(path, ROOT / "build/generation-v2/corpus.json",
                               ROOT / "docs/validation/generacion-muestra.json",
                               "yourmt3-" + args.predictions.name + "-" + variant,
                               candidate_revision=sha(__file__))
        save(args.output / variant / "frozen.json", freeze)
    save(args.output / "frozen.json", {
        "created_utc": datetime.now(timezone.utc).isoformat(), "references_interpreted": False,
        "protocol_path": str(args.protocol.resolve()), "protocol_sha256": sha(args.protocol),
        "predictions_path": str(args.predictions.resolve()),
        "prediction_freeze_sha256": sha(args.predictions / "frozen.json"),
        "earlier_baseline_plan_sha256": BASELINE_PLAN_SHA,
        "script_sha256": sha(__file__), "primary": "events", "statuses": statuses,
        "variants": {v: sha(args.output / v / "frozen.json") for v in VARIANTS}})
    (args.output / "source-at-freeze.py").write_bytes(Path(__file__).read_bytes())
    print(json.dumps({"frozen_maps": {v: len(m) for v, m in manifests.items()},
                      "reference_interpretation_started": False}))


def evaluate(args):
    frozen = load(args.output / "frozen.json")
    if frozen["script_sha256"] != sha(__file__) or frozen["protocol_sha256"] != sha(args.protocol):
        raise ValueError("Map evaluator or protocol changed after freeze")
    protocol = validate_predictions(args.predictions, args.protocol)
    if frozen["prediction_freeze_sha256"] != sha(args.predictions / "frozen.json"):
        raise ValueError("Frozen map inputs changed")
    # Check every arm and all chart bytes before the first reference interpretation.
    for variant, digest in frozen["variants"].items():
        path = args.output / variant / "frozen.json"
        if sha(path) != digest:
            raise ValueError("Map freeze changed")
        manifest = load(path)
        common.require_hash(manifest["candidate_manifest"], "candidate manifest")
        for entry in manifest["entries"]:
            if entry["candidate"] is not None:
                common.require_hash(entry["candidate"], "candidate chart")
        if (args.output / variant / "evaluation.json").exists():
            raise ValueError("Evaluation already exists")
    summaries = {}
    for variant in frozen["variants"]:
        path = args.output / variant / "frozen.json"
        result = common.evaluate(path, near_perfect=True)
        save(args.output / variant / "evaluation.json", result)
        summaries[variant] = result["summary"]
    entries = {r["id"]: r for r in load(args.output / "baseline/frozen.json")["entries"]}
    raw = []
    for tag in protocol["pilot_ids"]:
        reference, _ = extract(Path(entries[tag]["reference"]["path"]))
        for arm in ("lead", "lead-and-chorus"):
            data = load(args.predictions / "arms" / arm / (tag + ".json"))
            row = {"id": tag, "arm": arm, "diagnostics": data["diagnostics"],
                   "generated_notes": len(data["events"]), "monophonic_frames_measured": False}
            if data["diagnostics"]["invalid_note_indices"]:
                row["status"] = "invalid_raw_events"
            else:
                notes = [Note(a, b, p, "") for a, b, p in data["events"]]
                metrics = common.offset_metrics(reference, notes)
                count = sum(n.pitch is not None for n in reference) + len(notes)
                row.update(status="evaluated_raw_events", metrics=metrics,
                           onset_pitch_f1_100ms=2 * metrics["matched_attack_count"] / count if count else 0.)
            raw.append(row)
    save(args.output / "raw-event-evaluation.json", {"cohort_denominator": 40,
         "pilot_ids": protocol["pilot_ids"], "rows": raw,
         "scope": "Chronological same-class one-to-one attack/offset matching only; no monophonic painting of polyphony."})
    print(json.dumps(summaries))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze-maps", "evaluate"))
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path,
                        default=ROOT / "build/generation-next/yourmt3/map-evaluation-plan-v1.json")
    args = parser.parse_args()
    {"freeze-maps": freeze_maps, "evaluate": evaluate}[args.command](args)
