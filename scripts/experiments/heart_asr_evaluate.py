"""Compare complete Heart and Turbo vocal ASR chains using audited lyric metrics.

Protocol and freeze never read reference lyrics. A complete, terminal four-song
Heart generation freeze is required before freezing either comparison arm.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import importlib.util
import inspect
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[2]
METRICS_SOURCE = ROOT / "scripts/experiments/rms_vad_asr_evaluate.py"
SPEC = importlib.util.spec_from_file_location("heart_shared_lyric_metrics", METRICS_SOURCE)
shared = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shared)
check, digest, load, record, save = shared.check, shared.digest, shared.load, shared.record, shared.save

BASELINE, CANDIDATE = "turbo-vocals-native", "heart-native"
ARMS = (BASELINE, CANDIDATE)
COUNT_KEYS = ("S", "D", "I", "C", "ref_words", "hyp_words")
COMPARISON_SCOPE = (
    "Complete ASR chains, not an isolated model comparison: weights, FP16/int8 path, "
    "runtime/frontend and decoding settings differ. No per-song arm selection. "
    "Word timestamps do not establish musical note endings or near-perfect maps."
)


def identity(item):
    return str(Path(item["path"]).resolve()), item["sha256"]


def context(candidate_plan, baseline_protocol, baseline_frozen):
    """Validate fixed inputs and the historical baseline without opening lyrics."""
    generation = load(candidate_plan)
    rule, baseline_generation = shared.validate_protocol(argparse.Namespace(protocol=baseline_protocol))
    old_frozen = load(baseline_frozen)
    if old_frozen["protocol"] != record(baseline_protocol):
        raise ValueError("Changed baseline evaluation protocol")
    baseline_predictions = shared.validate_frozen_predictions(rule, baseline_generation, old_frozen)
    inputs = {row["id"]: row for row in generation["inputs"]}
    if len(generation["inputs"]) != 4 or len(inputs) != 4:
        raise ValueError("Expected four distinct Heart pilot inputs")
    if generation["planned_transcriptions"] != 4 or generation["arm"] != CANDIDATE:
        raise ValueError("Unexpected Heart generation design")
    if generation["references_opened"]:
        raise ValueError("Candidate generation must not inspect reference lyrics")
    baseline_inputs = {row["id"]: row for row in baseline_generation["inputs"]}
    references = {row["id"]: row for row in rule["references"]}
    if set(inputs) != set(baseline_inputs):
        raise ValueError("Heart and Turbo pilot recordings differ")
    prepared = {(row["id"], row["kind"]): row for row in load(check(rule["prepared_audio"]))["prepared"]}
    baseline_rows = {(row["id"], row["arm"]): row for row in old_frozen["rows"]}
    for tag, entry in inputs.items():
        historical = baseline_inputs[tag]
        if entry["language"] != references[tag]["language"]:
            raise ValueError("Changed input language")
        if historical["audio"]["sha256"] != references[tag]["audio_sha256"]:
            raise ValueError("Baseline recording and reference identity differ")
        if identity(entry["original_audio"]) != identity(historical["audio"]):
            raise ValueError("Changed original recording")
        if identity(entry["source_stem"]) != identity(historical["stem"]):
            raise ValueError("Changed source vocal stem")
        if identity(entry["prepared_audio"]) != identity(prepared[(tag, "vocals")]["audio"]):
            raise ValueError("Heart and Turbo must consume identical prepared vocal audio")
        check(entry["prepared_audio"])
        if (tag, "vocals-native") not in baseline_predictions:
            raise ValueError("Complete fixed Turbo vocals-native baseline is required")
    return {"generation": generation, "inputs": inputs, "baseline_rule": rule,
            "baseline_rows": baseline_rows, "references": references}


def protocol(args):
    ctx = context(args.candidate_plan, args.baseline_protocol, args.baseline_frozen)
    old = ctx["baseline_rule"]
    rule = {"created_utc": datetime.now(timezone.utc).isoformat(),
        "implementation": record(__file__), "shared_metrics": record(METRICS_SOURCE),
        "common_metrics": record(inspect.getsourcefile(shared.compare_words)),
        "chart_reader": record(inspect.getsourcefile(shared.read_chart)),
        "candidate_plan": record(args.candidate_plan),
        "baseline_protocol": record(args.baseline_protocol), "baseline_frozen": record(args.baseline_frozen),
        "references": old["references"], "pilot_ids": list(ctx["inputs"]),
        "primary": {"metric": "WER of product_lines", "comparison": [CANDIDATE, BASELINE],
            "aggregation": old["primary"]["aggregation"]},
        "secondary": "All raw_words metrics for both fixed chains; no selection by song",
        "comparison_scope": COMPARISON_SCOPE, "denominator": 40,
        "scheduled_conditions": 8, "condition_rows": 80, "csv_rows": 160,
        "reference_text_opened": False,
        "freeze_policy": "Require complete candidate generation freeze and validate all predictions, partial evidence and reaped workers before any reference text",
    }
    for key in ("normalization", "alignment", "timing", "missing_policy", "summary_scope", "empty_output"):
        rule[key] = old[key]
    save(args.protocol, rule)
    print(shared.json.dumps({"protocol_sha256": digest(args.protocol), "reference_text_opened": False}))


def validate_protocol(args):
    rule = load(args.protocol)
    for key in ("implementation", "shared_metrics", "common_metrics", "chart_reader", "candidate_plan", "baseline_protocol", "baseline_frozen"):
        check(rule[key])
    ctx = context(check(rule["candidate_plan"]), check(rule["baseline_protocol"]), check(rule["baseline_frozen"]))
    if rule["references"] != ctx["baseline_rule"]["references"] or set(rule["pilot_ids"]) != set(ctx["inputs"]):
        raise ValueError("Changed comparison identities")
    return rule, ctx


def candidate_records(path, rule, ctx):
    frozen = load(path)
    if frozen["plan_sha256"] != rule["candidate_plan"]["sha256"]:
        raise ValueError("Candidate freeze belongs to another generation plan")
    if frozen["present"] != 4 or frozen["planned"] != 4 or len(frozen["results"]) != 4:
        raise ValueError("All four candidate workers must be terminal before comparison freeze")
    records = {row["id"]: row for row in frozen["results"]}
    if set(records) != set(ctx["inputs"]):
        raise ValueError("Candidate freeze does not contain the fixed pilot")
    return records


def validate_rows(rule, ctx, frozen):
    """Finish every identity/resource check before the caller can read any gold."""
    expected = {(tag, arm) for tag in ctx["references"] for arm in ARMS}
    rows = frozen["rows"]
    if len(rows) != 80 or {(row["id"], row["arm"]) for row in rows} != expected:
        raise ValueError("Comparison must preserve forty identities per chain")
    source_rows = candidate_records(check(frozen["candidate_generation_frozen"]), rule, ctx)
    predictions = {}
    for row in rows:
        tag, arm = row["id"], row["arm"]
        if tag not in ctx["inputs"]:
            if row != {"id": tag, "arm": arm, "status": "outside_pilot", "prediction": None}:
                raise ValueError("Outside-pilot condition cannot contain predictions")
            continue
        if row["status"] != "complete":
            raise ValueError("Both fixed pilot chains must be complete")
        source = ctx["baseline_rows"][(tag, "vocals-native")] if arm == BASELINE else source_rows[tag]
        for field in ("prediction", "resources", "partial_evidence"):
            if row[field] != source[field]:
                raise ValueError("Comparison output differs from its generation freeze")
        for item in row["partial_evidence"]:
            check(item)
        worker = load(check(row["resources"]))
        if not worker["reaped"] or worker["exit_code"] != 0 or worker["stopped_reason"]:
            raise ValueError("Complete successful worker with confirmed reap is required")
        prediction = load(check(row["prediction"]))
        expected_plan = ctx["baseline_rule"]["generation_plan"]["sha256"] if arm == BASELINE else rule["candidate_plan"]["sha256"]
        expected_arm = "vocals-native" if arm == BASELINE else CANDIDATE
        if prediction["id"] != tag or prediction["arm"] != expected_arm or prediction["plan_sha256"] != expected_plan:
            raise ValueError("Prediction belongs to another chain or song")
        if identity(prediction["audio"]) != identity(ctx["inputs"][tag]["prepared_audio"]):
            raise ValueError("Prediction used different prepared vocal audio")
        predictions[(tag, arm)] = prediction
    return predictions


def freeze(args):
    rule, ctx = validate_protocol(args)
    candidate = candidate_records(args.candidate_frozen, rule, ctx)
    rows = []
    for reference in rule["references"]:
        tag = reference["id"]
        for arm in ARMS:
            row = {"id": tag, "arm": arm, "status": "outside_pilot", "prediction": None}
            if tag in ctx["inputs"]:
                source = ctx["baseline_rows"][(tag, "vocals-native")] if arm == BASELINE else candidate[tag]
                row.update(status="complete", **{key: source[key] for key in ("prediction", "resources", "partial_evidence")})
            rows.append(row)
    frozen = {"protocol": record(args.protocol), "candidate_generation_frozen": record(args.candidate_frozen),
              "rows": rows, "reference_text_opened": False, "cohort_size": 40,
              "created_utc": datetime.now(timezone.utc).isoformat()}
    validate_rows(rule, ctx, frozen)
    save(args.frozen, frozen)
    print(shared.json.dumps({"frozen": len(rows), "statuses": dict(Counter(row["status"] for row in rows))}))


def evaluate(args):
    rule, ctx = validate_protocol(args)
    frozen = load(args.frozen)
    if frozen["protocol"] != record(args.protocol):
        raise ValueError("Changed frozen comparison protocol")
    predictions = validate_rows(rule, ctx, frozen)
    gold, rows = {}, []
    for row in frozen["rows"]:
        tag, arm = row["id"], row["arm"]
        result = {key: row[key] for key in ("id", "arm", "status")}
        if row["status"] == "complete":
            if tag not in gold:
                _, gold[tag] = shared.extract(check(ctx["references"][tag]["reference"]))
            prediction = predictions[(tag, arm)]
            views = {"product": [word for line in prediction["product_lines"] for word in line],
                     "raw": prediction["raw_words"]}
            result["metrics"] = {view: shared.measure(gold[tag], shared.words(items)) for view, items in views.items()}
            result["product_minus_raw_wer"] = result["metrics"]["product"]["wer_unrounded"] - result["metrics"]["raw"]["wer_unrounded"]
            result["raw_boundary_crossings"] = sum(bool(word["crosses_input_boundary"]) for word in prediction["raw_words"])
            result["raw_nonpositive_durations"] = sum(bool(word["nonpositive_duration"]) for word in prediction["raw_words"])
        rows.append(result)
    summary = {}
    for arm in ARMS:
        present = [row for row in rows if row["arm"] == arm and row["status"] == "complete"]
        summary[arm] = {"cohort_size": 40, "measured": len(present), "missing": 40 - len(present)}
        for view in ("product", "raw"):
            metrics = [row["metrics"][view] for row in present]
            totals = {key: sum(metric[key] for metric in metrics) for key in COUNT_KEYS}
            summary[arm][view] = totals | {
                "pooled_wer_measured": (totals["S"] + totals["D"] + totals["I"]) / totals["ref_words"] if totals["ref_words"] else None,
                "median_wer_measured": statistics.median(metric["wer_unrounded"] for metric in metrics) if metrics else None}
    indexed = {(row["id"], row["arm"]): row for row in rows}
    paired = [{"id": tag, **{view + "_wer_delta":
        indexed[(tag, CANDIDATE)]["metrics"][view]["wer_unrounded"] - indexed[(tag, BASELINE)]["metrics"][view]["wer_unrounded"]
        for view in ("product", "raw")}} for tag in ctx["inputs"]]
    deltas = [row["product_wer_delta"] for row in paired]
    primary = {"paired": len(paired), "unpaired": 40 - len(paired), "cohort_size": 40,
               "improved": sum(delta < 0 for delta in deltas), "worse": sum(delta > 0 for delta in deltas),
               "equal": sum(delta == 0 for delta in deltas), "median_delta": statistics.median(deltas)}
    save(args.output, {"protocol": record(args.protocol), "frozen_predictions": record(args.frozen),
        "scope": COMPARISON_SCOPE, "summary": summary, "primary_summary": primary,
        "primary_paired": paired, "rows": rows})
    fields = ["id", "arm", "status", "view", *COUNT_KEYS, "wer_unrounded", "word_p50_s", "word_p90_s", "matched_reference_fraction"]
    with args.output.with_suffix(".csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            for view in ("product", "raw"):
                data = {key: row[key] for key in ("id", "arm", "status")}
                metric = row.get("metrics", {}).get(view, {})
                data.update({key: metric[key] for key in fields if key in metric})
                times = metric.get("word_mae_p50_p90_s", [])
                data.update(view=view, word_p50_s=times[0] if times else None, word_p90_s=times[1] if times else None)
                writer.writerow(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("protocol", "freeze", "evaluate"))
    base = ROOT / "build/generation-next/heart-asr/v1"
    previous = ROOT / "build/generation-next/rms-vad-asr/v3"
    for name, default in {
        "candidate-plan": base / "plan.json", "candidate-frozen": base / "frozen.json",
        "baseline-protocol": previous / "evaluation-protocol-preflight-v2.json",
        "baseline-frozen": previous / "evaluation-inputs-frozen-preflight-v2.json",
        "protocol": base / "evaluation-protocol.json", "frozen": base / "evaluation-inputs-frozen.json",
        "output": base / "evaluation.json",
    }.items():
        parser.add_argument("--" + name, type=Path, default=default)
    args = parser.parse_args()
    {"protocol": protocol, "freeze": freeze, "evaluate": evaluate}[args.command](args)
