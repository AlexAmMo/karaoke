"""Resource guards only: no separator, PyTorch or audio inference is executed."""

import importlib.util
import ctypes
import json
import os
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
    plan = json.loads((output / "plan-v3.json").read_text(encoding="utf-8"))
    assert plan["settings"]["device"] == "cpu"
    assert plan["settings"]["chunk_samples"] == 4 * 44100
    assert "no inference yet" in plan["scope"]
    assert list(output.iterdir()) == [output / "plan-v3.json"]


@pytest.fixture
def fake_monitor(monkeypatch):
    monkeypatch.setattr(lead, "memory_sampler", lambda: lambda _pid: {
        "rss_bytes": 1024, "physical_footprint_bytes": 2048})


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


def test_timeout_reaps_an_ordinary_cpu_worker_and_records_failure(tmp_path, fake_monitor):
    checkpoint = tmp_path / "execution.json"
    with pytest.raises(TimeoutError, match="no further songs"):
        lead.run_worker([sys.executable, "-c", "import time; time.sleep(30)"],
                        tmp_path / "worker.log", checkpoint, .05)
    state = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert state["state"] == "timed-out"
    assert state["returncode"] is not None
    assert state["signals"] == ["terminate"]


def test_interrupting_controller_also_terminates_its_worker(tmp_path, monkeypatch, fake_monitor):
    class Interrupted:
        pid = 123
        terminated = False

        def wait(self, timeout):
            if not self.terminated:
                raise KeyboardInterrupt
            return -15

        def terminate(self):
            self.terminated = True

        kill = terminate

        def poll(self):
            return None

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
        (tmp_path / "cpu-probe-v3.json").write_text("{}", encoding="utf-8")

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


@pytest.mark.parametrize("field", ["rss_bytes", "physical_footprint_bytes"])
def test_memory_threshold_kills_small_worker_without_large_allocation(tmp_path, monkeypatch, field):
    sample = {"rss_bytes": 1024, "physical_footprint_bytes": 1024, field: lead.WORKER_MEMORY_STOP}
    monkeypatch.setattr(lead, "memory_sampler", lambda: lambda _pid: sample)
    checkpoint = tmp_path / "execution" / "memory.json"
    with pytest.raises(MemoryError, match="1.5 GiB"):
        lead.run_worker([sys.executable, "-c", "import time; time.sleep(30)"],
                        tmp_path / "worker.log", checkpoint, 2)
    state = json.loads(checkpoint.read_text())
    assert state["state"] == "memory-limit" and state["signals"] == ["kill"]
    assert state["returncode"] is not None and state["resource_samples"] == 1
    assert lead.WORKER_MEMORY_STOP < lead.MEMORY_LIMIT


def test_monitor_failure_stops_and_reaps_worker(tmp_path, monkeypatch):
    def failing(_pid):
        raise OSError("lost worker memory telemetry")

    monkeypatch.setattr(lead, "memory_sampler", lambda: failing)
    checkpoint = tmp_path / "execution.json"
    with pytest.raises(OSError, match="lost worker"):
        lead.run_worker([sys.executable, "-c", "import time; time.sleep(30)"],
                        tmp_path / "worker.log", checkpoint, 2)
    state = json.loads(checkpoint.read_text())
    assert state["state"] == "interrupted" and state["signals"] == ["kill"]
    assert state["returncode"] is not None


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple libproc is only available on macOS")
def test_native_worker_memory_sampling_on_small_process(tmp_path):
    # The SDK's rusage_info_v0 has a 16-byte UUID followed by ten uint64 fields.
    assert ctypes.sizeof(lead.RUsageInfoV0) == 96
    sample = lead.memory_sampler()(os.getpid())
    assert sample["rss_bytes"] > 0 and sample["physical_footprint_bytes"] > 0
    checkpoint = tmp_path / "execution.json"
    lead.run_worker([sys.executable, "-c", "import time; a=bytearray(32*1024**2); time.sleep(.2)"],
                    tmp_path / "worker.log", checkpoint, 2)
    state = json.loads(checkpoint.read_text())
    assert state["state"] == "complete" and state["returncode"] == 0
    assert state["resource_samples"] >= 2
    assert state["sampled_max_rss_bytes"] >= 32 * 1024 ** 2
    assert state["sampled_max_physical_footprint_bytes"] >= 32 * 1024 ** 2


def test_single_song_retains_declared_cohort_and_does_not_start_others(tmp_path, monkeypatch):
    stems, charts = tmp_path / "stems.json", tmp_path / "charts.json"
    stems.write_text(json.dumps(dict.fromkeys(lead.PILOT, "audio.wav")))
    charts.write_text(json.dumps(dict.fromkeys(lead.PILOT, "chart.json")))
    args = SimpleNamespace(device="cpu", chunk_seconds=4, timeout_seconds=900,
                           stems=stems, charts=charts, output=tmp_path / "new",
                           ids=None, worker=False, only=[lead.PILOT[0]], model_dir=tmp_path)
    started = []

    def worker(command, _log, _checkpoint, _timeout):
        started.append(command[command.index("--ids") + 1:])
        lead.write_new(args.output / "separation" / (lead.PILOT[0] + ".json"), {})

    monkeypatch.setattr(lead, "run_worker", worker)
    lead.bounded_separation(args)
    plan = json.loads((args.output / "plan-v3.json").read_text())
    assert plan["ids"] == list(lead.PILOT)
    assert started == [[lead.PILOT[0]]]
    assert not (args.output / "lead-stems.json").exists()
