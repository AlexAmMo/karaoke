"""Resource guards only: no separator, PyTorch or audio inference is executed."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/experiments/lead_vocals.py"
SPEC = importlib.util.spec_from_file_location("lead_vocals", SCRIPT)
lead = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lead)


def cli_without_torch(*arguments):
    guard = """
import builtins, runpy, sys
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name in ('torch', 'soundfile') or name.startswith('torch.'):
        raise AssertionError('INFERENCE_DEPENDENCY_MUST_NOT_LOAD')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    return subprocess.run([sys.executable, "-c", guard, str(SCRIPT), *arguments],
                          capture_output=True, text=True, timeout=10)


def test_old_mps_command_rejected_before_model_or_torch(tmp_path):
    output = tmp_path / "never-created"
    result = cli_without_torch("separate", "--model-dir", str(tmp_path / "missing-model"),
                               "--output", str(output), "--device", "mps")
    assert result.returncode == 2
    assert "MPS is disabled" in result.stderr
    assert "INFERENCE_DEPENDENCY_MUST_NOT_LOAD" not in result.stderr
    assert not output.exists()


def test_twenty_second_window_exceeds_limit_and_four_seconds_fits(tmp_path):
    assert lead.attention_estimate(20 * 44100)["estimated_bytes"] > lead.MEMORY_LIMIT
    assert lead.attention_estimate(4 * 44100)["estimated_bytes"] < lead.MEMORY_LIMIT
    result = cli_without_torch("separate", "--model-dir", str(tmp_path / "missing-model"),
                               "--output", str(tmp_path / "out"), "--chunk-seconds", "20")
    assert result.returncode == 2 and "2 GiB preflight" in result.stderr
    assert "INFERENCE_DEPENDENCY_MUST_NOT_LOAD" not in result.stderr


def test_plan_does_not_touch_old_probe_or_load_models(tmp_path):
    stems, charts = tmp_path / "stems.json", tmp_path / "charts.json"
    stems.write_text("{}", encoding="utf-8")
    charts.write_text("{}", encoding="utf-8")
    old = tmp_path / "pilot"
    old.mkdir()
    probe = old / "probe.json"
    probe.write_text('{"previous": true}\n', encoding="utf-8")
    args = SimpleNamespace(device="cpu", chunk_seconds=4, timeout_seconds=900,
                           stems=stems, charts=charts, output=old, ids=None, worker=False)
    before = probe.read_bytes()
    with pytest.raises(ValueError, match="new empty directory"):
        lead.prepare_plan(args)
    assert probe.read_bytes() == before
    output = tmp_path / "pilot-cpu-v2"
    result = cli_without_torch("plan", "--model-dir", str(tmp_path / "missing-model"),
                               "--output", str(output), "--stems", str(stems), "--charts", str(charts))
    assert result.returncode == 0, result.stderr
    plan = json.loads((output / "plan-v2.json").read_text(encoding="utf-8"))
    assert plan["settings"]["device"] == "cpu"
    assert plan["settings"]["chunk_samples"] == 4 * 44100
    assert "no inference yet" in plan["scope"]
    assert list(output.iterdir()) == [output / "plan-v2.json"]


def test_immutable_json_is_not_partially_published(tmp_path):
    target = tmp_path / "frozen.json"
    with pytest.raises(ValueError):
        lead.write_new(target, {"not_finite": float("nan")})
    assert list(tmp_path.iterdir()) == []
    lead.write_new(target, {"complete": True})
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        lead.write_new(target, {"changed": True})
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_timeout_reaps_an_ordinary_cpu_worker_and_records_failure(tmp_path):
    checkpoint = tmp_path / "execution.json"
    with pytest.raises(TimeoutError, match="no further songs"):
        lead.run_worker([sys.executable, "-c", "import time; time.sleep(30)"],
                        tmp_path / "worker.log", checkpoint, .05)
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert state["state"] == "timed-out"
    assert state["returncode"] is not None
    assert state["signals"] == ["terminate"]


def test_interrupting_controller_also_terminates_its_worker(tmp_path, monkeypatch):
    class Interrupted:
        pid = 123
        terminated = False

        def wait(self, timeout):
            if not self.terminated:
                raise KeyboardInterrupt
            return -15

        def terminate(self):
            self.terminated = True

    process = Interrupted()
    monkeypatch.setattr(lead.subprocess, "Popen", lambda *_a, **_k: process)
    checkpoint = tmp_path / "execution.json"
    with pytest.raises(KeyboardInterrupt):
        lead.run_worker(["never-executed"], tmp_path / "worker.log", checkpoint, 10)
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert process.terminated
    assert state["state"] == "interrupted" and state["returncode"] == -15


def test_probe_uses_the_same_bounded_worker_without_inference(tmp_path, monkeypatch):
    captured = []
    args = SimpleNamespace(output=tmp_path, timeout_seconds=3, model_dir=tmp_path,
                           stems=tmp_path / "stems", charts=tmp_path / "charts", chunk_seconds=4)
    monkeypatch.setattr(lead, "prepare_plan", lambda _: {"ids": ["fixture"]})

    def run(command, log, checkpoint, timeout):
        captured.append((command, timeout))
        (tmp_path / "cpu-probe-v2.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(lead, "run_worker", run)
    lead.bounded_probe(args)
    command, timeout = captured[0]
    assert "probe" in command and "--worker" in command and timeout == 3
    assert command[command.index("--device") + 1] == "cpu"
    assert command[command.index("--chunk-seconds") + 1] == "4"


@pytest.mark.parametrize("window, timeout", [(float("nan"), 900), (4, float("inf")), (0, 900)])
def test_invalid_resource_settings_rejected(window, timeout):
    with pytest.raises(ValueError):
        lead.preflight(SimpleNamespace(device="cpu", chunk_seconds=window, timeout_seconds=timeout))
