"""Transport, RNG policy and deadline controls; never load a model."""

import ast
import importlib.util
import json
import math
from pathlib import Path
import signal
import sys
from types import SimpleNamespace

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/experiments/windowed_game.py"
SPEC = importlib.util.spec_from_file_location("windowed_game", SCRIPT)
windowed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(windowed)


def fake_runner(events_by_window, seen):
    def run(command, _log, checkpoint, timeout):
        assert timeout == 30
        request_path = Path(command[command.index("--request") + 1])
        result = Path(command[command.index("--result") + 1])
        request = windowed.read_json(request_path)
        seen.append(np.load(request["waveform"], allow_pickle=False))
        windowed.guard.write_new(result, {
            "request_sha256": windowed.guard.digest(request_path),
            "seed": 113, "rng_policy": windowed.RNG_POLICY,
            "events": events_by_window[request["window_index"] - 1]})
        windowed.guard.write_checkpoint(checkpoint, {"state": "complete", "returncode": 0})
        checkpoint.with_suffix(".resources.jsonl").write_text('{"fixture":true}\n', encoding="utf-8")
    return run


def test_window_transport_is_exact_and_completed_requests_are_reused(tmp_path):
    wave = np.array([.25, -.5, 1.125], dtype=np.float32)
    events = [[[0., 1., True, 60.25]]]
    seen = []
    backend = windowed.WindowBackend(tmp_path, {"rng_policy": windowed.RNG_POLICY}, "song",
                                      runner=fake_runner(events, seen))
    assert backend.extract("unused", wave, [], "es") == events[0]
    assert np.array_equal(seen[0], wave)
    def never(*_args):
        raise AssertionError("Completed window must not start another worker")
    replay = windowed.WindowBackend(tmp_path, {"rng_policy": windowed.RNG_POLICY}, "song", runner=never)
    assert replay.extract("unused", wave, [], "es") == events[0]
    assert backend.windows == replay.windows


def test_failed_window_is_not_automatically_retried(tmp_path):
    attempts = []
    def failed(_command, _log, checkpoint, _timeout):
        attempts.append(True)
        windowed.guard.write_checkpoint(checkpoint, {"state": "memory-limit", "returncode": -9})
        raise MemoryError("fixture")
    backend = windowed.WindowBackend(tmp_path, {}, "song", runner=failed)
    with pytest.raises(MemoryError):
        backend.extract("unused", np.zeros(4, np.float32), [], "es")
    with pytest.raises(RuntimeError, match="Previous window attempt"):
        backend.extract("unused", np.zeros(4, np.float32), [], "es")
    assert attempts == [True]


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX wall-clock timer")
def test_invalid_existing_plan_is_not_mutated_by_failure_record(tmp_path, monkeypatch):
    frozen = tmp_path / "plan.json"
    frozen.write_text('{"previous":true}\n', encoding="utf-8")
    before = frozen.read_bytes()
    monkeypatch.setattr(windowed.guard, "memory_sampler", lambda: lambda _pid: {
        "rss_bytes": 1024, "physical_footprint_bytes": 1024})
    def invalid(_args):
        raise ValueError("Frozen data changed")
    monkeypatch.setattr(windowed, "prepare_plan", invalid)
    with pytest.raises(ValueError, match="Frozen data changed"):
        windowed.run_arm(SimpleNamespace(output=tmp_path))
    assert frozen.read_bytes() == before
    assert list(tmp_path.iterdir()) == [frozen]


def test_seed_restarts_before_segmenter_and_only_one_extract_is_called():
    calls = []
    result = [(0., 1., True, 60.)]
    runtime = SimpleNamespace(
        InferenceSession=lambda path, **kwargs: calls.append(("session", Path(path).stem, kwargs)),
        set_seed=lambda seed: calls.append(("seed", seed)))
    game = SimpleNamespace(_sessions={}, extract=lambda *_a: calls.append(("extract",)) or result)
    options = object()
    def make_options(threads, policy):
        assert (threads, policy) == (2, "no-arena")
        return options
    for _ in range(2):
        assert windowed.single_extract(runtime, game, make_options, "folder", np.zeros(4), [], "es", 2) is result
    for offset in (0, 7):
        assert [row[1] for row in calls[offset:offset + 4]] == ["encoder", "estimator", "dur2bd", "bd2dur"]
        assert calls[offset + 4] == ("seed", 113)
        assert calls[offset + 5][1] == "segmenter"
        assert calls[offset + 6] == ("extract",)


def test_existing_infer_stitch_and_window_samples_are_preserved(tmp_path):
    existing = ast.parse(SCRIPT.with_name("conditioned_notes.py").read_text(encoding="utf-8"))
    infer = next(node for node in existing.body if isinstance(node, ast.FunctionDef) and node.name == "infer")
    sr = 44100
    mono = np.arange(26 * sr, dtype=np.float32) / sr
    stereo = np.stack([mono, mono * .5], axis=1)
    class Stream:
        samplerate = sr
        def __enter__(self):
            self.position = 0
            return self
        def __exit__(self, *_args):
            pass
        def __len__(self):
            return len(stereo)
        def seek(self, value):
            self.position = value
        def read(self, count, **_kwargs):
            return stereo[self.position:self.position + count]
    scope = {"math": math, "sf": SimpleNamespace(SoundFile=lambda _: Stream()),
             "durations_for": lambda *_args: []}
    exec(compile(ast.Module(body=[infer], type_ignores=[]), "existing-infer", "exec"), scope)
    events = [[[0., 11.9, True, 60.]], [[.8, 3., True, 60.], [3., 14.4, True, 62.]],
              [[1., 3.5, True, 64.]]]
    direct_inputs = []
    def extract(_folder, waveform, _known, _language):
        direct_inputs.append(waveform.copy())
        return events[len(direct_inputs) - 1]
    direct = SimpleNamespace(SAMPLE_RATE=sr, extract=extract)
    transported = []
    proxy = windowed.WindowBackend(tmp_path, {}, "song", runner=fake_runner(events, transported))
    first_trace, second_trace = [], []
    arguments = ("unused", [(0., 26.)], [], "free", "es")
    assert scope["infer"](*arguments, direct, "unused", first_trace) == scope["infer"](
        *arguments, proxy, "unused", second_trace)
    assert first_trace == second_trace
    assert len(transported) == len(direct_inputs) == 3
    assert all(np.array_equal(a, b) for a, b in zip(transported, direct_inputs))


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX wall-clock timer")
def test_global_deadline_reaps_the_current_window(tmp_path, monkeypatch):
    monkeypatch.setattr(windowed.guard, "memory_sampler", lambda: lambda _pid: {
        "rss_bytes": 1024, "physical_footprint_bytes": 1024})
    checkpoint = tmp_path / "execution.json"
    with pytest.raises(TimeoutError, match="Global arm deadline"):
        with windowed.arm_deadline(.05):
            windowed.guard.run_worker([sys.executable, "-c", "import time; time.sleep(30)"],
                                      tmp_path / "log", checkpoint, 30)
    result = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert result["state"] == "interrupted" and result["returncode"] is not None
    assert result["signals"] == ["kill"]
