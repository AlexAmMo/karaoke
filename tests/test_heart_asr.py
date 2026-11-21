"""Adapter/provenance controls only: no recognizer or model runtime is loaded."""

import argparse
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("heart_asr_tests", ROOT / "scripts/experiments/heart_asr.py")
heart = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = heart
SPEC.loader.exec_module(heart)


def good_resources():
    return {"exit_code": 0, "reaped": True, "stopped_reason": None}


def settings():
    return {"python": "/fake/python", "resources": heart.RESOURCES,
            "inputs": [{"id": tag} for tag in heart.PILOT]}


def conversion_fixture(tmp_path):
    model = tmp_path / "conversion/ct2-model"
    model.mkdir(parents=True)
    for name in ("model.bin", "config.json", "tokenizer.json", "preprocessor_config.json", "vocabulary.json"):
        (model / name).write_bytes(b"synthetic metadata only")
    plan = tmp_path / "conversion-plan.json"
    heart.save(plan, {"conversion": {"quantization": "int8", "load_as_float16": True,
               "device": "cpu", "reader": "transformers.modeling_utils.safe_open: backend=pread"}})
    resources = tmp_path / "conversion/resources.json"
    heart.save(resources, good_resources())
    files = {p.name: heart.digest(p) for p in model.iterdir()}
    complete = tmp_path / "conversion/worker-complete.json"
    heart.save(complete, {"plan_sha256": heart.digest(plan),
               "files": {"ct2-model/" + name: sha for name, sha in files.items()}})
    frozen = tmp_path / "frozen.json"
    heart.save(frozen, {"plan": heart.record(plan), "resources": heart.record(resources),
               "worker_complete": heart.record(complete), "reaped": True,
               "transcription_executed": False, "source_sha256": heart.SOURCE_SHA,
               "model_directory": str(model), "model_files": files})
    return frozen, model, complete, resources


def test_nonzero_audio_options_raw_and_product_without_model():
    pytest.importorskip("scipy", reason="Audio experiment dependencies live in generation-bench/env")
    assert heart.selftest()["model_loaded"] is False


def test_conversion_freeze_consumer_accepts_renamed_manifest(tmp_path):
    frozen, model, _, _ = conversion_fixture(tmp_path)
    result = heart.checked_conversion(frozen)
    assert result["model_directory"] == str(model.resolve())
    assert result["freeze"] == heart.record(frozen)


@pytest.mark.parametrize("change", ["model", "manifest", "resources"])
def test_conversion_freeze_rejects_changed_evidence(tmp_path, change):
    frozen, model, complete, resources = conversion_fixture(tmp_path)
    target = {"model": model / "model.bin", "manifest": complete, "resources": resources}[change]
    target.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Input changed"):
        heart.checked_conversion(frozen)


@pytest.mark.parametrize("control,timeout", [(True, 120), (False, 900)])
def test_one_worker_propagates_quota_deadline_and_freezes_only_after_reap(tmp_path, control, timeout):
    heart.save(tmp_path / "plan.json", {"test": "fake runner"})
    seen = []

    def runner(command, destination, limit, deadline, sampler, environment):
        seen.append((command, limit, deadline, sampler, environment))
        heart.save(destination / "prediction.json", {"test": "no model"})
        heart.save(destination / "resources.json", good_resources())
        heart.save(destination / "part-000.json", {"test": "partial evidence"})
        return good_resources()

    state = (settings(), SimpleNamespace(run_bounded=runner), "sampler", {"fake": "env"})
    row = heart.run_one(argparse.Namespace(output=tmp_path), state, control=control, tag=heart.PILOT[0])
    command, limit, deadline, sampler, environment = seen[0]
    assert limit == 4 * 1024**3 and deadline == timeout
    assert sampler == "sampler" and environment == {"fake": "env"}
    assert command[0] == "/fake/python"
    assert command[-1] == ("--control" if control else heart.PILOT[0])
    assert heart.load(heart.check(row["resources"]))["reaped"]
    assert {Path(r["path"]).name for r in row["partial_evidence"]} == {"launch.json", "part-000.json"}
    with pytest.raises(FileExistsError):
        heart.run_one(argparse.Namespace(output=tmp_path), state, control=control, tag=heart.PILOT[0])
    assert len(seen) == 1


def test_failed_worker_stops_cohort_without_freeze_or_next_song(tmp_path, monkeypatch):
    heart.save(tmp_path / "plan.json", {"test": "fake plan"})
    control = tmp_path / "synthetic-control"
    heart.save(control / "prediction.json", {"test": "fake control"})
    heart.save(control / "resources.json", good_resources())
    heart.save(tmp_path / "synthetic-frozen.json", {"plan_sha256": heart.digest(tmp_path / "plan.json"),
        "reaped": True, "prediction": heart.record(control / "prediction.json"),
        "resources": heart.record(control / "resources.json"), "partial_evidence": []})
    calls = []

    def runner(_command, destination, _limit, _deadline, _sampler, _environment):
        calls.append(destination)
        failed = dict(good_resources(), exit_code=-9, stopped_reason="memory_budget_exceeded")
        heart.save(destination / "resources.json", failed)
        raise RuntimeError("simulated stopped and reaped worker")

    state = (settings(), SimpleNamespace(run_bounded=runner), None, {})
    monkeypatch.setattr(heart, "controller", lambda _: state)
    with pytest.raises(RuntimeError, match="stopped and reaped"):
        heart.execute(argparse.Namespace(output=tmp_path))
    assert len(calls) == 1
    assert heart.load(calls[0] / "resources.json")["reaped"]
    assert not (tmp_path / "frozen.json").exists()
    assert not (tmp_path / "results" / heart.PILOT[1]).exists()


def test_unreaped_result_never_creates_success_freeze(tmp_path, monkeypatch):
    heart.save(tmp_path / "plan.json", {"test": "fake plan"})

    def runner(*_):
        return dict(good_resources(), reaped=False)

    state = (settings(), SimpleNamespace(run_bounded=runner), None, {})
    monkeypatch.setattr(heart, "controller", lambda _: state)
    with pytest.raises(ValueError, match="confirmed reap"):
        heart.synthetic(argparse.Namespace(output=tmp_path))
    assert not (tmp_path / "synthetic-frozen.json").exists()


def test_missing_conversion_prevents_plan_and_audio_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(heart, "baseline_inputs", lambda *_: pytest.fail("baseline opened before conversion"))
    proposal = tmp_path / "proposal.json"
    heart.save(proposal, {"synthetic": "proposal for a missing-conversion test"})
    monkeypatch.setattr(heart, "PROPOSAL_SHA", heart.digest(proposal))
    args = argparse.Namespace(output=tmp_path / "new", conversion_freeze=tmp_path / "missing.json",
        proposal=proposal)
    with pytest.raises(FileNotFoundError, match="missing.json"):
        heart.plan(args)
    assert not args.output.exists()
