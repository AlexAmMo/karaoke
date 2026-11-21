"""Only wrapper seams: no weights, recognizer, reference lyrics or real plan."""

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/experiments/heart_asr_no_timestamps.py"
SPEC = importlib.util.spec_from_file_location("heart_no_timestamps_tests", WRAPPER)
variant = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = variant
SPEC.loader.exec_module(variant)


def original_runner():
    spec = importlib.util.spec_from_file_location("heart_unmodified_test", variant.BASE_PATH)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    return original


def test_hash_is_checked_before_executing_changed_runner(tmp_path):
    changed = tmp_path / "changed.py"
    changed.write_text("raise AssertionError('must never execute')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="before import"):
        variant.load_runner(changed, variant.BASE_SHA)


def test_private_runner_has_exactly_one_decode_change_and_no_original_contamination():
    original = original_runner()
    assert variant.base.DECODE == dict(original.DECODE, without_timestamps=True)
    assert "without_timestamps" not in original.DECODE
    assert variant.base is not original
    for name in ("MODEL", "RESOURCES", "CONTROL", "VERSIONS", "ARM", "PILOT"):
        assert getattr(variant.base, name) == getattr(original, name)
    assert original.__file__ == str(variant.BASE_PATH)
    sources = variant.own_sources()
    assert sources["adapter"] == variant.base.record(WRAPPER)
    assert sources["base_runner"] == variant.base.record(variant.BASE_PATH)


def test_effective_recognizer_kwargs_only_add_without_timestamps():
    seen = []

    class Fake:
        def transcribe(self, waveform, **kwargs):
            seen.append((waveform, kwargs))
            return iter([]), SimpleNamespace(language="es")

    recorder = variant.base.HeartRecordingModel(Fake(), "es")
    segments, _ = recorder.transcribe([.1, .2], language="es", beam_size=5,
        word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
    assert list(segments) == []
    assert seen[0][1] == dict(variant.BASE_DECODE, language="es", without_timestamps=True)
    assert seen[0][1]["word_timestamps"] is True


@pytest.mark.parametrize("changed", [{"beam_size": 3}, {"word_timestamps": False}, {"without_timestamps": False}])
def test_runtime_decode_guard_rejects_other_changes(monkeypatch, changed):
    monkeypatch.setattr(variant.base, "DECODE", dict(variant.VARIANT_DECODE, **changed))
    with pytest.raises(ValueError, match="Only without_timestamps"):
        variant.guard_variant()


def test_proposal_guard_accepts_only_single_option_and_metadata():
    original = {"inference": {"beam_size": 2, "word_timestamps": True},
                "source_model": {"revision": "fixed", "local_bytes_verified": False},
                "cohort": {"quota": 4096}, "inputs": ["all four"]}
    proposed = deepcopy(original)
    proposed["inference"]["without_timestamps"] = True
    proposed["source_model"]["local_bytes_verified"] = True
    proposed["status"] = "reviewed metadata"
    variant.validate_proposal_delta(proposed, original)
    for key, value in (("inference", {"beam_size": 3}), ("cohort", {"quota": 8192}),
                       ("inputs", ["one favorable song"]), ("new_parameter", 12)):
        changed = deepcopy(proposed)
        changed[key] = value
        with pytest.raises(ValueError):
            variant.validate_proposal_delta(changed, original)


@pytest.mark.parametrize("control,deadline", [(True, 120), (False, 900)])
def test_child_command_and_launch_record_use_wrapper_with_same_guard(tmp_path, control, deadline):
    variant.base.save(tmp_path / "plan.json", {"synthetic": "runner seam, no real plan"})
    observed = []

    def fake_run(command, destination, limit, timeout, sampler, environment):
        observed.append((command, limit, timeout, sampler, environment))
        resources = {"exit_code": 0, "reaped": True, "stopped_reason": None}
        variant.base.save(destination / "resources.json", resources)
        variant.base.save(destination / "prediction.json", {"fake": True})
        return resources

    settings = {"python": "/fixed/independent/python", "resources": variant.base.RESOURCES}
    state = (settings, SimpleNamespace(run_bounded=fake_run), "sampler", {"guard": "yes"})
    tag = variant.base.PILOT[0]
    row = variant.base.run_one(argparse.Namespace(output=tmp_path), state, control=control, tag=tag)
    command, limit, timeout, sampler, environment = observed[0]
    assert command[1] == str(WRAPPER)
    assert command[2] == "_worker"
    assert limit == 4 * 1024**3 and timeout == deadline
    assert sampler == "sampler" and environment == {"guard": "yes"}
    folder = Path(row["resources"]["path"]).parent
    assert variant.base.load(folder / "launch.json")["command"] == command
    assert variant.base.load(folder / "resources.json")["reaped"]


def test_old_plan_is_rejected_before_any_conversion_or_audio_read(tmp_path, monkeypatch):
    original = original_runner()
    variant.base.save(tmp_path / "plan.json", {"code": original.own_sources(), "decode": original.DECODE})
    monkeypatch.setattr(variant.base, "checked_conversion", lambda _: pytest.fail("conversion opened"))
    with pytest.raises(ValueError, match="Source or fixed experiment settings changed"):
        variant.verify_plan(tmp_path)


def test_child_inspection_is_stdlib_and_has_both_source_hashes():
    completed = subprocess.run([sys.executable, str(WRAPPER), "inspect"],
                               check=True, capture_output=True, text=True, timeout=10)
    value = json.loads(completed.stdout)
    assert value["model_loaded"] is False
    assert value["child_entry_point"] == str(WRAPPER)
    assert value["sources"]["adapter"] == variant.base.record(WRAPPER)
    assert value["sources"]["base_runner"]["sha256"] == variant.BASE_SHA
    assert value["decode"] == variant.VARIANT_DECODE
    assert value["hypothesis_decision"] == variant.HYPOTHESIS_DECISION


def test_cli_worker_requires_supervisor_before_importing_runtime():
    completed = subprocess.run([sys.executable, str(WRAPPER), "_worker", "--control"],
                               capture_output=True, text=True, timeout=10)
    assert completed.returncode != 0
    assert "Worker requires its resource supervisor" in completed.stderr


def test_real_waveform_and_raw_filters_use_new_kwargs_without_models():
    pytest.importorskip("scipy", reason="Audio selftest runs separately in the fixed Heart environment")
    assert variant.base.selftest()["model_loaded"] is False
