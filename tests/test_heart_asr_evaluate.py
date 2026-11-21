"""Exercise the new chain/freeze boundary with synthetic files and no models."""

from argparse import Namespace
import csv
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/experiments/heart_asr_evaluate.py"
SPEC = importlib.util.spec_from_file_location("heart_asr_evaluation", SCRIPT)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def replace(path, data):
    Path(path).write_text(json.dumps(data), encoding="utf-8")
    return evaluation.record(path)


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    def write(name, data):
        path = tmp_path / name
        evaluation.save(path, data)
        return evaluation.record(path)

    ids = [f"synthetic-{i:02d}" for i in range(40)]
    masters = {tag: write(f"{tag}-master.json", {"audio": tag}) for tag in ids}
    stems = {tag: write(f"{tag}-stem.json", {"stem": tag}) for tag in ids[:4]}
    audio = {tag: write(f"{tag}-prepared.json", {"prepared": tag}) for tag in ids[:4]}
    baseline_inputs = [{"id": tag, "audio": masters[tag], "stem": stems[tag]} for tag in ids[:4]]
    baseline_plan = write("baseline-plan.json", {"inputs": baseline_inputs})
    baseline_audio = write("baseline-audio.json", {"prepared": [
        {"id": tag, "kind": "vocals", "audio": audio[tag]} for tag in ids[:4]
    ]})
    references = [{"id": tag, "language": "es", "audio_sha256": masters[tag]["sha256"],
                   "reference": write(f"{tag}-reference.json", {"synthetic_reference": True})}
                  for tag in ids]
    baseline_rule = {"generation_plan": baseline_plan, "prepared_audio": baseline_audio,
        "implementation": evaluation.record(evaluation.METRICS_SOURCE),
        "common_metrics": write("metrics.json", {}), "chart_reader": write("reader.json", {}),
        "identities": write("identities.json", {}), "corpus_manifest": write("corpus.json", {}),
        "references": references, "primary": {"aggregation": "synthetic aggregation"}}
    for key in ("normalization", "alignment", "timing", "missing_policy", "summary_scope", "empty_output"):
        baseline_rule[key] = "synthetic rule " + key
    baseline_protocol = write("baseline-protocol.json", baseline_rule)
    candidate_plan = write("candidate-plan.json", {"planned_transcriptions": 4,
        "arm": "heart-native", "references_opened": False, "inputs": [
            {"id": tag, "language": "es", "original_audio": masters[tag],
             "source_stem": stems[tag], "prepared_audio": audio[tag]} for tag in ids[:4]]})
    artifacts = {}

    def attempt(tag, arm, plan):
        prefix = tag + "-" + arm
        word = {"word": "a", "start": 1., "end": 2.,
                "crosses_input_boundary": False, "nonpositive_duration": False}
        row = {"id": tag, "prediction": write(prefix + "-prediction.json", {
            "id": tag, "arm": arm, "plan_sha256": plan["sha256"], "audio": audio[tag],
            "product_lines": [[word]], "raw_words": [word]}),
            "resources": write(prefix + "-resources.json", {
                "reaped": True, "exit_code": 0, "stopped_reason": None}),
            "partial_evidence": [write(prefix + "-part.json", {"synthetic_part": True})]}
        artifacts[(tag, arm)] = row
        return row

    baseline_rows = []
    for tag in ids:
        for arm in evaluation.shared.ARMS:
            row = {"id": tag, "arm": arm, "prediction": None,
                   "status": "unattempted" if tag in ids[:4] else "outside_pilot"}
            if tag in ids[:4] and arm == "vocals-native":
                row.update(attempt(tag, arm, baseline_plan), status="complete")
            baseline_rows.append(row)
    baseline_frozen = write("baseline-frozen.json", {"protocol": baseline_protocol, "rows": baseline_rows})
    candidate_frozen = write("candidate-frozen.json", {
        "plan_sha256": candidate_plan["sha256"], "present": 4, "planned": 4,
        "results": [attempt(tag, "heart-native", candidate_plan) for tag in ids[:4]]})
    args = Namespace(candidate_plan=Path(candidate_plan["path"]),
        baseline_protocol=Path(baseline_protocol["path"]), baseline_frozen=Path(baseline_frozen["path"]),
        candidate_frozen=Path(candidate_frozen["path"]), protocol=tmp_path / "protocol.json",
        frozen=tmp_path / "comparison-frozen.json", output=tmp_path / "evaluation.json")
    reference_reader = Mock(return_value=([], [("a", 1.)]))
    monkeypatch.setattr(evaluation.shared, "extract", reference_reader)
    return args, artifacts, reference_reader


def test_two_fixed_chains_reuse_metrics_and_preserve_denominator(comparison):
    args, _, reference_reader = comparison
    evaluation.protocol(args)
    evaluation.freeze(args)
    reference_reader.assert_not_called()
    evaluation.evaluate(args)
    assert reference_reader.call_count == 4
    result = evaluation.load(args.output)
    assert len(result["rows"]) == 80
    assert result["primary_summary"]["paired"] == 4
    assert result["primary_summary"]["unpaired"] == 36
    assert result["primary_summary"]["equal"] == 4
    for arm in evaluation.ARMS:
        assert result["summary"][arm]["measured"] == 4
        assert result["summary"][arm]["missing"] == 36
        assert result["summary"][arm]["product"]["pooled_wer_measured"] == 0
    with args.output.with_suffix(".csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 160
    assert sum(row["status"] == "complete" for row in rows) == 16
    assert all(row["wer_unrounded"] == "" for row in rows if row["status"] != "complete")
    rule = evaluation.load(args.protocol)
    assert rule["shared_metrics"] == evaluation.record(evaluation.METRICS_SOURCE)
    assert "not an isolated model" in rule["comparison_scope"]


@pytest.mark.parametrize("arm", ["vocals-native", "heart-native"])
@pytest.mark.parametrize("artifact", ["prediction", "resources", "partial_evidence"])
def test_late_change_in_either_chain_rejected_before_reference(comparison, arm, artifact):
    args, artifacts, reference_reader = comparison
    evaluation.protocol(args)
    evaluation.freeze(args)
    last = artifacts[("synthetic-03", arm)]
    signed = last[artifact][0] if artifact == "partial_evidence" else last[artifact]
    with Path(signed["path"]).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="Changed input"):
        evaluation.evaluate(args)
    reference_reader.assert_not_called()
    assert not args.output.exists()


@pytest.mark.parametrize("field", ["original_audio", "source_stem", "prepared_audio"])
def test_protocol_rejects_different_input_identity(comparison, field):
    args, _, reference_reader = comparison
    candidate = evaluation.load(args.candidate_plan)
    candidate["inputs"][-1][field] = candidate["inputs"][0][field]
    replace(args.candidate_plan, candidate)
    with pytest.raises(ValueError, match="Changed|identical prepared"):
        evaluation.protocol(args)
    reference_reader.assert_not_called()
    assert not args.protocol.exists()


def test_absent_plan_or_generation_freeze_prevents_progress(comparison):
    args, _, reference_reader = comparison
    evaluation.protocol(args)
    args.candidate_frozen.unlink()
    with pytest.raises(FileNotFoundError):
        evaluation.freeze(args)
    assert not args.frozen.exists()
    args.candidate_plan.unlink()
    with pytest.raises(FileNotFoundError):
        evaluation.protocol(args)
    reference_reader.assert_not_called()


@pytest.mark.parametrize("fault", ["unreaped", "wrong_chain"])
def test_terminal_worker_and_chain_identity_required_before_freeze(comparison, fault):
    args, _, reference_reader = comparison
    evaluation.protocol(args)
    frozen = evaluation.load(args.candidate_frozen)
    last = frozen["results"][-1]
    field = "resources" if fault == "unreaped" else "prediction"
    target = Path(last[field]["path"])
    value = evaluation.load(target)
    if fault == "unreaped":
        value["reaped"] = False
    else:
        value["arm"] = "vocals-native"
    last[field] = replace(target, value)
    replace(args.candidate_frozen, frozen)
    with pytest.raises(ValueError, match="reap|another chain"):
        evaluation.freeze(args)
    reference_reader.assert_not_called()
    assert not args.frozen.exists()
