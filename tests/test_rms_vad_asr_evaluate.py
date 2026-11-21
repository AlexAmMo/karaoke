"""Validate every frozen ASR artifact before consulting any reference lyrics."""

from argparse import Namespace
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/experiments/rms_vad_asr_evaluate.py"
SPEC = importlib.util.spec_from_file_location("rms_vad_asr_evaluation", SCRIPT)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


@pytest.fixture
def frozen_cohort(tmp_path, monkeypatch):
    """Two complete workers and one failed worker in the fixed 40-by-4 design."""
    def write(name, value):
        path = tmp_path / name
        evaluation.save(path, value)
        return evaluation.record(path)

    protocol = write("protocol.json", {})
    ids = [f"synthetic-{i:02d}" for i in range(40)]
    references = [
        {"id": tag, "reference": write(f"{tag}-reference.json", {"synthetic": True})}
        for tag in ids
    ]
    audio = {"path": "synthetic-audio-not-opened", "sha256": "synthetic-audio"}
    prepared = write("prepared.json", {"prepared": [
        {"id": tag, "kind": kind, "audio": audio}
        for tag in ids[:4] for kind in ("mix", "vocals")
    ]})
    rule = {"references": references, "generation_plan": {"sha256": "synthetic-plan"},
            "prepared_audio": prepared}
    generation = {"inputs": [{"id": tag} for tag in ids[:4]]}
    rows = []
    for tag in ids:
        for arm in evaluation.ARMS:
            row = {"id": tag, "arm": arm, "prediction": None,
                   "status": "unattempted" if tag in ids[:4] else "outside_pilot"}
            complete = (tag, arm) in ((ids[0], "mix-native"), (ids[3], "vocals-rms"))
            failed = (tag, arm) == (ids[1], "mix-rms")
            if complete or failed:
                prefix = f"{tag}-{arm}"
                row["resources"] = write(f"{prefix}-resources.json", {
                    "reaped": True, "exit_code": 0 if complete else 1, "stopped_reason": None,
                })
                row["partial_evidence"] = [write(f"{prefix}-part.json", {"synthetic": True})]
                row["status"] = "complete" if complete else "failed"
            if complete:
                word = {"word": "a", "start": 1., "end": 2.,
                        "crosses_input_boundary": False, "nonpositive_duration": False}
                row["prediction"] = write(f"{prefix}-prediction.json", {
                    "plan_sha256": "synthetic-plan", "id": tag, "arm": arm, "audio": audio,
                    "product_lines": [[word]], "raw_words": [word],
                })
            rows.append(row)
    frozen = write("frozen.json", {"protocol": protocol, "rows": rows})
    reference_reader = Mock(return_value=([], [("a", 1.)]))
    monkeypatch.setattr(evaluation, "validate_protocol", lambda args: (rule, generation))
    monkeypatch.setattr(evaluation, "extract", reference_reader)
    args = Namespace(protocol=Path(protocol["path"]), frozen=Path(frozen["path"]),
                     output=tmp_path / "result.json")
    last = next(row for row in rows if (row["id"], row["arm"]) == (ids[3], "vocals-rms"))
    return args, last, reference_reader


@pytest.mark.parametrize("artifact", ["prediction", "resources", "partial_evidence"])
def test_changed_late_artifact_rejected_before_any_reference(frozen_cohort, artifact):
    args, last, reference_reader = frozen_cohort
    signed = last[artifact][0] if artifact == "partial_evidence" else last[artifact]
    # Valid JSON with different bytes isolates the frozen-integrity check.
    with Path(signed["path"]).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="Changed input"):
        evaluation.evaluate(args)
    reference_reader.assert_not_called()
    assert not args.output.exists()
    assert not args.output.with_suffix(".csv").exists()


def test_valid_frozen_artifacts_allow_evaluation_with_full_denominator(frozen_cohort):
    args, _, reference_reader = frozen_cohort
    evaluation.evaluate(args)
    assert reference_reader.call_count == 2
    result = json.loads(args.output.read_text(encoding="utf-8"))
    assert len(result["rows"]) == 160
    assert result["summary"]["mix-native"]["measured"] == 1
    assert result["summary"]["mix-native"]["missing"] == 39
    assert result["summary"]["mix-rms"]["measured"] == 0
    assert result["summary"]["mix-rms"]["product"]["pooled_wer_measured"] is None
    assert result["primary_summary"]["paired"] == 0
    assert result["primary_summary"]["unpaired"] == 40
    assert all(row["metrics"]["product"]["wer_unrounded"] == 0
               for row in result["rows"] if row["status"] == "complete")
