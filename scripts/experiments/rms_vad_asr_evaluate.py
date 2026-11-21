"""Freeze RMS-ASR evaluation rules and outputs before opening reference lyrics.

`protocol`, `freeze` and `selftest` never open a reference chart or load models.
Primary WER uses product_lines; raw words are a separate complete diagnostic.
Missing recordings stay in the forty-recording denominator for every arm.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import statistics
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from karaoke.generation_metrics import TOKEN, compare_words, extract  # noqa: E402
from karaoke.songs import read_chart  # noqa: E402

ARMS = ("mix-native", "mix-rms", "vocals-native", "vocals-rms")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def check(item):
    path = Path(item["path"])
    if digest(path) != item["sha256"]:
        raise ValueError(f"Changed input: {path}")
    return path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def words(items):
    return [(match.group(), float(item["start"])) for item in items
            for match in TOKEN.finditer(unicodedata.normalize("NFKC", item["word"].casefold()))]


def operations(reference, hypothesis):
    """Count operations with exactly the common evaluator's traceback tie order."""
    a, b = len(reference), len(hypothesis)
    cost = [list(range(b + 1))] + [[i] + [0] * b for i in range(1, a + 1)]
    for i in range(1, a + 1):
        for j in range(1, b + 1):
            different = reference[i - 1][0] != hypothesis[j - 1][0]
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1, cost[i - 1][j - 1] + different)
    i, j, counts = a, b, Counter(S=0, D=0, I=0, C=0)
    pairs = []
    while i or j:
        equal = i and j and reference[i - 1][0] == hypothesis[j - 1][0]
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (not equal):
            counts["C" if equal else "S"] += 1
            if equal:
                pairs.append({"reference_index": i - 1, "hypothesis_index": j - 1,
                    "reference_start": float(reference[i - 1][1]),
                    "hypothesis_start": float(hypothesis[j - 1][1]),
                    "delta_seconds": float(hypothesis[j - 1][1] - reference[i - 1][1])})
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            counts["D"] += 1
            i -= 1
        else:
            counts["I"] += 1
            j -= 1
    assert counts["S"] + counts["D"] + counts["I"] == cost[a][b]
    assert counts["C"] + counts["S"] + counts["D"] == a
    assert counts["C"] + counts["S"] + counts["I"] == b
    return {**counts, "edits": cost[a][b], "matched_pairs": list(reversed(pairs))}


def measure(reference, hypothesis):
    if not reference:
        raise ValueError("Reference contains no lexical words")
    common = compare_words(reference, hypothesis)
    detail = operations(reference, hypothesis)
    assert detail["edits"] == common["edits"] and detail["C"] == common["exact"]
    return {**common, **detail, "wer_unrounded": detail["edits"] / len(reference),
            "matched_reference_fraction": detail["C"] / len(reference)}


def selftest():
    def as_words(text):
        return [(token, float(i)) for i, token in enumerate(text.split())]
    cases = [
        ("a b c", "a z c", (1, 0, 0)),
        ("a b c", "a c", (0, 1, 0)),
        ("a b", "a x b", (0, 0, 1)),
        ("la la la", "la la", (0, 1, 0)),
        ("a b c", "", (0, 3, 0)),
        ("a b", "b a", (2, 0, 0)),
    ]
    for ref, hyp, expected in cases:
        result = measure(as_words(ref), as_words(hyp))
        assert tuple(result[k] for k in ("S", "D", "I")) == expected
    shifted = measure([("a", 1.0), ("a", 2.0)], [("a", 1.5), ("a", 2.5)])
    assert shifted["word_mae_p50_p90_s"] == [.5, .5]
    assert shifted["matched_reference_fraction"] == 1
    assert words([{"word": " ¡SÍ, la la!", "start": 3.0}]) == [("sí", 3.), ("la", 3.), ("la", 3.)]
    assert "torch" not in sys.modules and "faster_whisper" not in sys.modules
    return {"S_D_I_cases": len(cases), "timing_without_shift_fit": True,
            "repetition_accent_and_common_normalization": True}


def protocol(args):
    generation = load(args.predictions / "plan.json")
    identities = load(args.identities)
    if len(identities) != 40 or len({r["tag"] for r in identities}) != 40:
        raise ValueError("Expected forty distinct identities")
    corpus = load(args.corpus)
    corpus = {r["tag"]: r for group in corpus.values() for r in group}
    references = []
    for row in identities:
        source = corpus[row["tag"]]
        if any(source[k] != row[k] for k in ("chart_sha", "audio_sha")):
            raise ValueError("Reference identity mismatch")
        # Store previously signed reference identity, without opening its text.
        references.append({"id": row["tag"], "language": row["language"],
            "audio_sha256": row["audio_sha"],
            "reference": {"path": str(Path(source["reference"]).resolve()), "sha256": row["chart_sha"]}})
    if set(generation["arms"]) != set(ARMS) or generation["planned_transcriptions"] != 16:
        raise ValueError("Unexpected generation design")
    reference_by_id = {r["id"]: r for r in references}
    if len(generation["inputs"]) != 4 or len({r["id"] for r in generation["inputs"]}) != 4:
        raise ValueError("Expected four different pilot recordings")
    for entry in generation["inputs"]:
        if entry["audio"]["sha256"] != reference_by_id[entry["id"]]["audio_sha256"]:
            raise ValueError("Generation and reference master identities differ")
    rule = {"created_utc": datetime.now(timezone.utc).isoformat(),
        "generation_plan": record(args.predictions / "plan.json"),
        "prepared_audio": record(args.predictions / "audio-frozen.json"),
        "implementation": record(__file__), "common_metrics": record(inspect.getsourcefile(compare_words)),
        "chart_reader": record(inspect.getsourcefile(read_chart)),
        "identities": record(args.identities), "corpus_manifest": record(args.corpus),
        "primary": {"metric": "WER of product_lines", "comparison": ["mix-rms", "mix-native"],
                    "aggregation": "report each song, paired deltas, equal/improved/worse, median and pooled S+D+I over reference words"},
        "secondary": "same complete metrics on raw_words; all four arms; no selection by song",
        "normalization": "common TOKEN after NFKC/casefold; keep accents and repetitions; each lexical token inherits its ASR word start",
        "alignment": "common unit-cost Levenshtein; traceback prefers diagonal, then deletion, then insertion",
        "timing": "common exact lexical matches only, absolute start deltas; p50/p90 and signed per-third medians; publish match count/fraction and matched indices; no clock fit",
        "denominator": 40, "scheduled_conditions": 16, "rows": 160,
        "missing_policy": "all forty identities in every arm; unattempted/failed/invalid remain missing with null WER and no success; no invented WER for absent output",
        "summary_scope": "WER statistics only measured outputs, explicit measured/40 and missing/40; never extrapolate four-song success to forty",
        "empty_output": "completed empty transcription is measured as all reference words deleted, WER1, with timing null",
        "freeze_policy": "freeze completed predictions and every attempted worker's final resource status before reference text; reject folders without confirmed reap",
        "reference_text_opened": False, "references": references, "selftest": selftest()}
    save(args.protocol, rule)
    print(json.dumps({"protocol_sha256": digest(args.protocol), "reference_text_opened": False}))


def validate_protocol(args):
    rule = load(args.protocol)
    for key in ("generation_plan", "prepared_audio", "implementation", "common_metrics", "chart_reader", "identities", "corpus_manifest"):
        check(rule[key])
    return rule, load(check(rule["generation_plan"]))


def freeze(args):
    rule, generation = validate_protocol(args)
    prepared = {(r["id"], r["kind"]): r for r in load(check(rule["prepared_audio"]))["prepared"]}
    selected = {r["id"] for r in generation["inputs"]}
    rows = []
    for entry in rule["references"]:
        for arm in ARMS:
            row = {"id": entry["id"], "arm": arm,
                   "status": "unattempted" if entry["id"] in selected else "outside_pilot", "prediction": None}
            folder = args.predictions / "results" / entry["id"] / arm
            if folder.exists():
                resources = load(folder / "resources.json")
                if not resources["reaped"]:
                    raise ValueError("Worker not confirmed reaped; cannot freeze its outputs")
                row["resources"] = record(folder / "resources.json")
                row["status"] = "failed"
                if resources["exit_code"] == 0 and not resources["stopped_reason"]:
                    row["prediction"] = record(folder / "prediction.json")
                    candidate = load(check(row["prediction"]))
                    if (candidate["plan_sha256"] != rule["generation_plan"]["sha256"] or
                        candidate["id"] != entry["id"] or candidate["arm"] != arm or
                        candidate["audio"] != prepared[(entry["id"], arm.split("-")[0])]["audio"]):
                        raise ValueError("Prediction belongs to a different condition")
                    row["status"] = "complete"
                row["partial_evidence"] = [record(p) for p in sorted(folder.glob("part-*.json"))]
            rows.append(row)
    save(args.frozen, {"protocol": record(args.protocol), "rows": rows,
                      "reference_text_opened": False, "cohort_size": 40,
                      "created_utc": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"frozen": len(rows), "statuses": dict(Counter(r["status"] for r in rows))}))


def evaluate(args):
    rule, _ = validate_protocol(args)
    frozen = load(args.frozen)
    if frozen["protocol"] != record(args.protocol):
        raise ValueError("Changed frozen evaluation protocol")
    references = {r["id"]: r for r in rule["references"]}
    expected = {(tag, arm) for tag in references for arm in ARMS}
    if len(frozen["rows"]) != 160 or {(r["id"], r["arm"]) for r in frozen["rows"]} != expected:
        raise ValueError("Frozen conditions do not preserve the complete denominator")
    gold, rows = {}, []
    for row in frozen["rows"]:
        result = {"id": row["id"], "arm": row["arm"], "status": row["status"]}
        if row["status"] != "complete":
            rows.append(result)
            continue
        if row["id"] not in gold:
            _, gold[row["id"]] = extract(check(references[row["id"]]["reference"]))
        candidate = load(check(row["prediction"]))
        views = {"product": [w for line in candidate["product_lines"] for w in line], "raw": candidate["raw_words"]}
        result["metrics"] = {name: measure(gold[row["id"]], words(items)) for name, items in views.items()}
        result["product_minus_raw_wer"] = result["metrics"]["product"]["wer_unrounded"] - result["metrics"]["raw"]["wer_unrounded"]
        result["raw_boundary_crossings"] = sum(bool(w["crosses_input_boundary"]) for w in candidate["raw_words"])
        result["raw_nonpositive_durations"] = sum(bool(w["nonpositive_duration"]) for w in candidate["raw_words"])
        rows.append(result)
    summary = {}
    for arm in ARMS:
        subset = [r for r in rows if r["arm"] == arm and r["status"] == "complete"]
        summary[arm] = {"cohort_size": 40, "measured": len(subset), "missing": 40 - len(subset)}
        for view in ("product", "raw"):
            metrics = [r["metrics"][view] for r in subset]
            total = {key: sum(m[key] for m in metrics) for key in ("S", "D", "I", "C", "ref_words", "hyp_words")}
            summary[arm][view] = total | {
                "pooled_wer_measured": (total["S"] + total["D"] + total["I"]) / total["ref_words"] if total["ref_words"] else None,
                "median_wer_measured": statistics.median(m["wer_unrounded"] for m in metrics) if metrics else None}
    by_condition = {(r["id"], r["arm"]): r for r in rows}
    paired = []
    for tag in references:
        left, right = [by_condition[(tag, arm)] for arm in ("mix-rms", "mix-native")]
        if left["status"] == right["status"] == "complete":
            paired.append({"id": tag, "product_wer_delta": left["metrics"]["product"]["wer_unrounded"] - right["metrics"]["product"]["wer_unrounded"],
                           "raw_wer_delta": left["metrics"]["raw"]["wer_unrounded"] - right["metrics"]["raw"]["wer_unrounded"]})
    deltas = [r["product_wer_delta"] for r in paired]
    primary_summary = {"paired": len(deltas), "cohort_size": 40,
        "unpaired": 40 - len(deltas), "improved": sum(d < 0 for d in deltas),
        "worse": sum(d > 0 for d in deltas), "equal": sum(d == 0 for d in deltas),
        "median_delta": statistics.median(deltas) if deltas else None}
    save(args.output, {"protocol": record(args.protocol), "frozen_predictions": record(args.frozen),
        "scope": "lyrics and timing only; four development songs, missing retained in denominator40; no near-perfect melody claim",
        "summary": summary, "primary_summary": primary_summary, "primary_paired": paired, "rows": rows})
    fields = ["id", "arm", "status", "view", "S", "D", "I", "C", "ref_words", "hyp_words", "wer_unrounded", "word_p50_s", "word_p90_s", "matched_reference_fraction"]
    with args.output.with_suffix(".csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            for view in ("product", "raw"):
                data = {k: row[k] for k in ("id", "arm", "status")}
                measured = row.get("metrics", {}).get(view, {})
                data.update({k: measured[k] for k in fields if k in measured})
                times = measured.get("word_mae_p50_p90_s", [])
                data.update(view=view, word_p50_s=times[0] if times else None, word_p90_s=times[1] if times else None)
                writer.writerow(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("protocol", "freeze", "evaluate", "selftest"))
    base = ROOT / "build/generation-next/rms-vad-asr/v1"
    for name, default in {"predictions": base, "protocol": base / "evaluation-protocol.json",
        "frozen": base / "evaluation-inputs-frozen.json", "output": base / "evaluation.json",
        "identities": ROOT / "docs/validation/generacion-muestra.json",
        "corpus": ROOT / "build/generation-v2/corpus.json"}.items():
        parser.add_argument("--" + name, type=Path, default=default)
    args = parser.parse_args()
    if args.command == "selftest":
        print(json.dumps(selftest(), indent=2))
    else:
        {"protocol": protocol, "freeze": freeze, "evaluate": evaluate}[args.command](args)
