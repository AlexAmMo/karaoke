"""Freeze predictions, then evaluate the fixed development corpus without fitting its clock.

Freeze never opens a reference chart. Candidate input is a JSON object mapping corpus IDs
to chart paths, or a directory containing <id>/draft.txt (alternatively <id>.txt).
Missing predictions remain failures in the full cohort denominator. Use a fresh frozen
manifest for each candidate revision; evaluation rejects any changed input bytes.

Example:
    uv run python scripts/experiments/evaluate_generation_candidate.py freeze \
      --candidates build/candidate/charts.json --corpus build/generation-v2/corpus.json \
      --output build/candidate/frozen.json --label candidate-v1
    uv run python scripts/experiments/evaluate_generation_candidate.py evaluate \
      --frozen build/candidate/frozen.json --output build/candidate/evaluation.json \
      --near-perfect
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from karaoke.generation_metrics import passes  # noqa: E402
from karaoke.generation_verification import _measure, _mono_timeline  # noqa: E402

COHORT_SIZE = 40
COHORT_NOTE = (
    "These 40 recordings have already informed development and model selection. "
    "They are a development/regression cohort, not an unseen holdout. "
    "Results cannot establish reliability for arbitrary YouTube recordings."
)
RESEARCH_TARGET = {
    "wer_max": 0.01,
    "word_p90_seconds_max": 0.08,
    "correct_class_all_min": 0.98,
    "onset_pitch_f1_100ms_min": 0.95,
    "scored_frame_precision_min": 0.98,
    "scope": "Stricter research target; does not change production admission rules.",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def file_record(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path)}


def require_hash(record, label):
    path = Path(record["path"])
    if not path.is_file() or digest(path) != record["sha256"]:
        raise ValueError(f"Changed or missing {label}: {path}")
    return path


def unique_rows(rows, label):
    if not isinstance(rows, list):
        raise ValueError(f"{label} must contain a list of recording identities")
    mapped = {}
    for row in rows:
        tag = row["tag"]
        if not isinstance(tag, str) or Path(tag).name != tag or tag in (".", ".."):
            raise ValueError(f"Invalid recording ID in {label}")
        if tag in mapped:
            raise ValueError(f"Duplicate recording ID in {label}: {tag}")
        mapped[tag] = row
    return mapped


def candidates_from(source, identities):
    source = Path(source)
    if source.is_dir():
        result = {}
        for tag in identities:
            options = [source / tag / "draft.txt", source / (tag + ".txt")]
            present = [path for path in options if path.is_file()]
            if len(present) > 1:
                raise ValueError(f"Ambiguous candidate files for {tag}")
            if present:
                result[tag] = present[0]
        return result
    mapping = load(source)
    if not isinstance(mapping, dict) or not all(isinstance(p, str) for p in mapping.values()):
        raise ValueError("Candidate manifest must map recording IDs to chart path strings")
    extra = set(mapping) - set(identities)
    if extra:
        raise ValueError(f"Unknown candidate IDs: {sorted(extra)}")
    return {tag: Path(path) for tag, path in mapping.items()}


def freeze(candidates, corpus, identities, label, candidate_revision=None):
    identities = Path(identities)
    identity_rows = unique_rows(load(identities), "identity manifest")
    if len(identity_rows) != COHORT_SIZE:
        raise ValueError(f"Expected the fixed {COHORT_SIZE}-recording cohort")
    raw = load(corpus)
    rows = unique_rows(sum(raw.values(), []) if isinstance(raw, dict) else raw, "corpus")
    if not set(identity_rows).issubset(rows):
        raise ValueError("Corpus is missing frozen recording identities")
    predictions = candidates_from(candidates, identity_rows)
    entries = []
    for tag, identity in sorted(identity_rows.items()):
        row = rows[tag]
        for key in ("audio_sha", "chart_sha"):
            if row[key] != identity[key]:
                raise ValueError(f"Corpus identity differs for {tag}: {key}")
        duration = float(row["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"Invalid recording duration for {tag}")
        audio = file_record(row["audio"])
        if audio["sha256"] != identity["audio_sha"]:
            raise ValueError(f"Master audio hash differs for {tag}")
        # Store only the previously frozen reference identity. Do not open it here.
        reference = {
            "path": str(Path(row["reference"]).resolve()),
            "sha256": identity["chart_sha"],
        }
        prediction = predictions.get(tag)
        present = prediction is not None and prediction.is_file()
        entries.append(
            {
                "id": tag,
                "language": identity["language"],
                "duration_seconds": duration,
                "audio": audio,
                "reference": reference,
                "candidate": file_record(prediction) if present else None,
                "candidate_status": "frozen" if present else "missing",
            }
        )
    return {
        "schema_version": 1,
        "stage": "frozen_predictions",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "candidate_revision": candidate_revision,
        "cohort_size": COHORT_SIZE,
        "cohort_note": COHORT_NOTE,
        "identity_manifest": file_record(identities),
        "corpus_manifest": file_record(corpus),
        "candidate_manifest": file_record(candidates) if Path(candidates).is_file() else None,
        "entries": entries,
    }


def offset_metrics(reference, candidate):
    """Match each same-class attack once at ±100 ms, then measure its note release."""
    offsets, duration_errors = [], []
    matching_ends = 0
    for pitch in range(12):
        gold = [n for n in reference if n.pitch is not None and n.pitch % 12 == pitch]
        found = [n for n in candidate if n.pitch is not None and n.pitch % 12 == pitch]
        i = j = 0
        while i < len(gold) and j < len(found):
            a, b = gold[i], found[j]
            if a.start < b.start - 0.1:
                i += 1
            elif b.start < a.start - 0.1:
                j += 1
            else:
                offsets.append(abs(b.end - a.end))
                duration = a.end - a.start
                duration_errors.append(b.end - b.start - duration)
                matching_ends += abs(b.end - a.end) <= max(0.05, 0.2 * duration)
                i += 1
                j += 1
    total = sum(n.pitch is not None for n in reference) + sum(
        n.pitch is not None for n in candidate
    )
    return {
        "matched_attack_count": len(offsets),
        "matched_offset_count": matching_ends,
        "matched_offset_p50_p90_seconds": (
            np.round(np.percentile(offsets, [50, 90]), 4).tolist() if offsets else []
        ),
        "matched_duration_bias_p50_seconds": (
            round(float(np.median(duration_errors)), 4) if duration_errors else None
        ),
        "onset_pitch_offset_f1": round(2 * matching_ends / total, 4) if total else 0.0,
        "offset_tolerance": "max(50 ms, 20% of reference note duration)",
    }


def meets_research_target(metrics):
    p90 = metrics.get("word_mae_p50_p90_s", [])
    return bool(
        len(p90) == 2
        and metrics.get("wer", math.inf) <= RESEARCH_TARGET["wer_max"]
        and p90[1] <= RESEARCH_TARGET["word_p90_seconds_max"]
        and (metrics.get("correct_class_all") or 0) >= RESEARCH_TARGET["correct_class_all_min"]
        and (metrics.get("onset_pitch_f1_100ms") or 0)
        >= RESEARCH_TARGET["onset_pitch_f1_100ms_min"]
        and (metrics.get("scored_frame_precision") or 0)
        >= RESEARCH_TARGET["scored_frame_precision_min"]
    )


def safe_timeline(path, duration):
    try:
        timeline = _mono_timeline(path, duration)
        if timeline is None or not any(n.pitch is not None for n in timeline[0]):
            return None
        if not all(
            math.isfinite(n.start) and math.isfinite(n.end) and 0 <= n.start < n.end
            for n in timeline[0]
        ):
            return None
        return timeline
    except (KeyError, ValueError, OverflowError, ZeroDivisionError):
        return None


def evaluate(frozen_path, near_perfect=False):
    frozen = load(frozen_path)
    if frozen.get("schema_version") != 1 or frozen.get("stage") != "frozen_predictions":
        raise ValueError("Expected a frozen prediction manifest")
    identities_path = require_hash(frozen["identity_manifest"], "identity manifest")
    require_hash(frozen["corpus_manifest"], "corpus manifest")
    if frozen.get("candidate_manifest"):
        require_hash(frozen["candidate_manifest"], "candidate manifest")
    identities = unique_rows(load(identities_path), "identity manifest")
    entries = frozen["entries"]
    ids = [entry["id"] for entry in entries]
    if (
        frozen.get("cohort_size") != COHORT_SIZE
        or len(identities) != COHORT_SIZE
        or len(ids) != COHORT_SIZE
        or len(set(ids)) != COHORT_SIZE
        or set(ids) != set(identities)
    ):
        raise ValueError("Frozen entries do not match the complete fixed cohort")
    # Validate every source before evaluating, including missing/failed candidates.
    for entry in entries:
        identity = identities[entry["id"]]
        if (
            entry["audio"]["sha256"] != identity["audio_sha"]
            or entry["reference"]["sha256"] != identity["chart_sha"]
        ):
            raise ValueError(f"Frozen identity differs for {entry['id']}")
        for name in ("audio", "reference"):
            require_hash(entry[name], f"{name} for {entry['id']}")
        if entry["candidate"] is not None:
            require_hash(entry["candidate"], f"candidate for {entry['id']}")
    rows = []
    for entry in entries:
        row = {
            "id": entry["id"],
            "language": entry["language"],
            "status": "missing",
            "passes_initial_four_gates": False,
            "passes_five_gates": False,
        }
        if near_perfect:
            row["meets_near_perfect_research_target"] = False
        gold = safe_timeline(Path(entry["reference"]["path"]), entry["duration_seconds"])
        if gold is None:
            raise ValueError(f"Invalid reference timeline: {entry['id']}")
        if entry["candidate"] is not None:
            path = Path(entry["candidate"]["path"])
            candidate = safe_timeline(path, entry["duration_seconds"])
            row["candidate_sha256"] = entry["candidate"]["sha256"]
            if candidate is None:
                row["status"] = "invalid_timeline"
            else:
                metrics = _measure(gold, candidate)
                metrics.update(offset_metrics(gold[0], candidate[0]))
                row.update(
                    status="evaluated",
                    metrics=metrics,
                    passes_initial_four_gates=passes(metrics),
                    passes_five_gates=bool(
                        passes(metrics) and metrics["scored_frame_precision"] >= 0.90
                    ),
                )
                if near_perfect:
                    row["meets_near_perfect_research_target"] = meets_research_target(metrics)
        rows.append(row)
    totals = Counter(row["status"] for row in rows)
    qualified = sum(row["passes_five_gates"] for row in rows)
    summary = {
        "cohort_size": COHORT_SIZE,
        "evaluated_count": totals["evaluated"],
        "missing_count": totals["missing"],
        "invalid_count": totals["invalid_timeline"],
        "passes_initial_four_gates": sum(row["passes_initial_four_gates"] for row in rows),
        "passes_five_gates": qualified,
        "five_gate_fraction_of_full_cohort": qualified / COHORT_SIZE,
        "by_language": {},
    }
    for language in sorted({r["language"] for r in rows}):
        selected = [r for r in rows if r["language"] == language]
        summary["by_language"][language] = {
            "total": len(selected),
            "passes_five_gates": sum(r["passes_five_gates"] for r in selected),
        }
    result = {
        "schema_version": 1,
        "stage": "evaluated_predictions",
        "label": frozen["label"],
        "candidate_revision": frozen["candidate_revision"],
        "frozen_manifest_sha256": digest(frozen_path),
        "cohort_note": COHORT_NOTE,
        "evaluation_scope": (
            "Full recording timelines; no fitted shift, transposition, clipping, reference-based "
            "correction, or exclusion of missing predictions. Five gates describe chart quality; "
            "they do not perform the product's acoustic recording-identity check."
        ),
        "summary": summary,
        "recordings": rows,
    }
    if near_perfect:
        qualified = sum(row["meets_near_perfect_research_target"] for row in rows)
        result["near_perfect_research_target"] = RESEARCH_TARGET
        summary["meets_near_perfect_research_target"] = qualified
        summary["near_perfect_fraction_of_full_cohort"] = qualified / COHORT_SIZE
    return result


def write_new(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Existing results must not silently masquerade as a new candidate run.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("freeze", help="Fingerprint predictions without opening gold charts")
    first.add_argument("--candidates", type=Path, required=True)
    first.add_argument("--corpus", type=Path, required=True)
    first.add_argument(
        "--identities", type=Path, default=ROOT / "docs/validation/generacion-muestra.json"
    )
    first.add_argument("--label", required=True)
    first.add_argument("--candidate-revision")
    first.add_argument("--output", type=Path, required=True)
    second = commands.add_parser("evaluate", help="Score the previously frozen complete cohort")
    second.add_argument("--frozen", type=Path, required=True)
    second.add_argument("--output", type=Path, required=True)
    second.add_argument("--near-perfect", action="store_true")
    args = parser.parse_args()
    if args.command == "freeze":
        payload = freeze(
            args.candidates, args.corpus, args.identities, args.label, args.candidate_revision
        )
    else:
        payload = evaluate(args.frozen, args.near_perfect)
    write_new(args.output, payload)
    summary = payload["summary"] if "summary" in payload else {"frozen": len(payload["entries"])}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
