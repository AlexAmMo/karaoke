"""Small conversion controls: never load a model or require ML dependencies."""

import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import numpy as np
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/experiments/heart_conversion.py"
SPEC = importlib.util.spec_from_file_location("heart_conversion", SCRIPT)
heart = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(heart)


@pytest.fixture
def no_models(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "transformers", "ctranslate2", "safetensors"):
            raise AssertionError("No inference dependencies in preparation/control")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.mark.parametrize("device", [None, "cpu"])
def test_pread_wrapper_preserves_all_other_arguments_and_restores(device, no_models):
    calls = []
    sentinel = object()

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    module = SimpleNamespace(safe_open=original)
    with heart.pread_cpu_reader(module):
        assert module.safe_open("voz española", framework="pt", device=device) is sentinel
    assert module.safe_open is original
    assert calls == [(("voz española",), {"framework": "pt", "device": device, "backend": "pread"})]


def test_pread_wrapper_keeps_positional_cpu_and_existing_pread(no_models):
    calls = []
    module = SimpleNamespace(safe_open=lambda *a, **k: calls.append((a, k)))
    with heart.pread_cpu_reader(module):
        module.safe_open("x", "pt", "cpu", backend="pread")
    assert calls == [(("x", "pt", "cpu"), {"backend": "pread"})]


@pytest.mark.parametrize("during_reader", [False, True])
def test_pread_wrapper_restores_after_error(during_reader, no_models):
    def original(*_args, **_kwargs):
        raise RuntimeError("reader failed")

    module = SimpleNamespace(safe_open=original)
    with pytest.raises(RuntimeError):
        with heart.pread_cpu_reader(module):
            if during_reader:
                module.safe_open("x", framework="pt")
            raise RuntimeError("caller failed")
    assert module.safe_open is original


@pytest.mark.parametrize("options", [{"device": "mps"}, {"device": "cuda:0"}, {"device": 0},
                                     {"backend": "mmap"}])
def test_pread_wrapper_rejects_other_device_or_backend_before_read(options, no_models):
    calls = []

    def original(*a, **k):
        calls.append((a, k))

    module = SimpleNamespace(safe_open=original)
    with pytest.raises(ValueError):
        with heart.pread_cpu_reader(module):
            module.safe_open("x", framework="pt", **options)
    assert calls == [] and module.safe_open is original


def test_local_source_rejection_precedes_model_import(tmp_path, no_models, monkeypatch):
    with pytest.raises(ValueError, match="complete local"):
        heart.verify_source(tmp_path)
    (tmp_path / "model.safetensors").write_bytes(b"wrong")
    monkeypatch.setattr(heart, "WEIGHT_BYTES", 5)
    with pytest.raises(ValueError, match="SHA-256"):
        heart.verify_source(tmp_path)


def test_unsupervised_worker_rejected_before_plan_or_import(tmp_path, no_models, monkeypatch):
    monkeypatch.delenv("HEART_CONVERSION_SUPERVISED", raising=False)
    with pytest.raises(ValueError, match="resource supervisor"):
        heart.worker(tmp_path)


def write_source(path, arrays):
    data = b""
    rows = {}
    for name, values in arrays.items():
        values = np.asarray(values, dtype="<f4")
        raw = values.tobytes()
        rows[name] = {"dtype": "F32", "shape": list(values.shape),
                      "data_offsets": [len(data), len(data) + len(raw)]}
        data += raw
    header = json.dumps(rows).encode("utf-8")
    header += b" " * (-len(header) % 8)
    path.write_bytes(struct.pack("<Q", len(header)) + header + data)
    return rows


def test_cast_audit_uses_source_offsets_and_records_rounding(tmp_path, no_models):
    arrays = {"small": [1.0001, 1.e-12, -2.5], "next": [2.75, 0.]}
    rows = write_source(tmp_path / "model.safetensors", arrays)
    marks = []
    audit = heart.audit_cast(tmp_path, rows, lambda *a, **k: marks.append((a, k)))
    for row in audit:
        cast = np.asarray(arrays[row["name"]], dtype="<f4").astype("<f2")
        assert row["fp16_sha256"] == hashlib.sha256(cast.tobytes()).hexdigest()
    assert audit[0]["underflow_to_zero"] == 1
    assert audit[0]["max_abs_rounding_error"] > 0
    assert marks[-1][1]["tensor_count"] == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 65536.])
def test_cast_audit_rejects_nonfinite_or_fp16_overflow(tmp_path, no_models, value):
    rows = write_source(tmp_path / "model.safetensors", {"bad": [value]})
    with pytest.raises(ValueError, match="Nonfinite or FP16-overflowing"):
        heart.audit_cast(tmp_path, rows, lambda *_a, **_k: None)


def test_plan_without_weights_or_overlay_freezes_environment(tmp_path, monkeypatch, no_models):
    lock = tmp_path / "requirements.txt"
    lock.write_text("\n".join(f"{k}=={v}" for k, v in heart.VERSIONS.items()) + "\n", encoding="utf-8")
    monkeypatch.setattr(heart, "own_sources", lambda: {"fixture": True})
    monkeypatch.setattr(heart, "baseline_record", lambda _: {"v3": True})
    args = SimpleNamespace(output=tmp_path / "plan-only", source=tmp_path / "not-downloaded",
                           python=Path("/future/python"), overlay=None, baseline=tmp_path,
                           environment_lock=lock)
    heart.prepare(args)
    plan = heart.read_json(args.output / "plan.json")
    assert plan["overlay"] is None and plan["baseline"] == {"v3": True}
    assert plan["conversion"]["rss_and_footprint_stop_bytes"] == 4 * 1024**3
    assert plan["environment_lock"]["sha256"] == heart.digest(lock)
    assert not args.source.exists() and list(args.output.iterdir()) == [args.output / "plan.json"]
    before = (args.output / "plan.json").read_bytes()
    with pytest.raises(ValueError, match="new empty"):
        heart.prepare(args)
    assert (args.output / "plan.json").read_bytes() == before


def test_conversion_with_missing_source_never_launches_supervisor(tmp_path, no_models, monkeypatch):
    monkeypatch.setattr(heart, "verify_plan", lambda _: {"source_directory": str(tmp_path / "missing")})
    monkeypatch.setattr(heart, "module", lambda *_: pytest.fail("Supervisor must not start"))
    with pytest.raises(ValueError, match="complete local"):
        heart.convert(tmp_path)
    assert not (tmp_path / "conversion").exists()


@pytest.mark.parametrize("overlay", [None, "overlay"])
def test_controller_uses_frozen_quota_and_freezes_only_after_reap(tmp_path, no_models, monkeypatch, overlay):
    python = tmp_path / "python"
    python.touch()
    if overlay:
        (tmp_path / overlay).mkdir()
    plan = {"source_directory": str(tmp_path / "source"), "python": str(python),
            "overlay": str(tmp_path / overlay) if overlay else None,
            "code": {"monitor": {"path": "monitor"}, "supervisor": {"path": "supervisor"}}}
    heart.save_new(tmp_path / "plan.json", plan)
    monkeypatch.setattr(heart, "verify_plan", lambda _: plan)
    monkeypatch.setattr(heart, "verify_source", lambda _: {})
    monkeypatch.setattr(heart, "checked", lambda row: Path(row["path"]))
    monkeypatch.setattr(heart.shutil, "disk_usage", lambda _: SimpleNamespace(free=16 * 1024**3))
    monkeypatch.setenv("PYTHONPATH", "must-not-leak")
    calls = []

    def run(command, output, limit, timeout, sampler, environment):
        assert not (tmp_path / "frozen.json").exists()
        calls.append((command, limit, timeout, environment))
        (output / "ct2-model").mkdir()
        (output / "ct2-model/model.bin").write_bytes(b"synthetic-not-a-model")
        heart.save_new(output / "worker-complete.json", {
            "plan_sha256": heart.digest(tmp_path / "plan.json"),
            "files": {"ct2-model/model.bin": heart.digest(output / "ct2-model/model.bin")}})
        status = {"exit_code": 0, "reaped": True, "stopped_reason": None}
        heart.save_new(output / "resources.json", status)
        return status

    monkeypatch.setattr(heart, "module", lambda _path, name: (
        SimpleNamespace(memory_sampler=lambda: object()) if name == "heart_memory_monitor"
        else SimpleNamespace(run_bounded=run)))
    heart.convert(tmp_path)
    command, limit, timeout, environment = calls[0]
    assert limit == 4 * 1024**3 and timeout == 900
    assert command[0] == str(python) and "_worker" in command
    assert environment.get("PYTHONPATH") == plan["overlay"]
    assert environment["HF_HUB_OFFLINE"] == "1" and environment["OMP_NUM_THREADS"] == "2"
    frozen = heart.read_json(tmp_path / "frozen.json")
    assert frozen["reaped"] and not frozen["transcription_executed"]
    with pytest.raises(ValueError, match="Prior conversion"):
        heart.convert(tmp_path)


def encoded_string(value):
    raw = value.encode("utf-8") + b"\0"
    return struct.pack("<H", len(raw)) + raw


def write_ct2(path, variables, aliases=()):
    raw = struct.pack("<I", 6) + encoded_string("WhisperSpec") + struct.pack("<II", 3, len(variables))
    for name, value in variables:
        types = {"float32": 0, "int8": 1, "int16": 2, "int32": 3, "float16": 4}
        raw += encoded_string(name) + struct.pack("<B", value.ndim)
        raw += b"".join(struct.pack("<I", n) for n in value.shape)
        raw += struct.pack("<BI", types[value.dtype.name], value.nbytes) + value.tobytes()
    raw += struct.pack("<I", len(aliases))
    raw += b"".join(encoded_string(a) + encoded_string(b) for a, b in aliases)
    path.write_bytes(raw)


def test_ct2_inventory_validates_small_tensors_and_aliases(tmp_path, no_models):
    path = tmp_path / "model.bin"
    write_ct2(path, [("weight", np.array([[1, -2]], dtype=np.int8)),
                     ("scale", np.array([1.], dtype=np.float32))], [("shared", "weight")])
    inventory = heart.binary_inventory(path)
    assert inventory["variables"]["weight"]["shape"] == [1, 2]
    assert inventory["variables"]["weight"]["dtype"] == "int8"
    assert inventory["aliases"] == {"shared": "weight"}
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match="Truncated"):
        heart.binary_inventory(path)


@pytest.mark.parametrize("bad", ["nan", "scale", "alias"])
def test_ct2_inventory_rejects_corrupt_values_and_aliases(tmp_path, no_models, bad):
    path = tmp_path / "model.bin"
    name = "weight_scale" if bad == "scale" else "normal"
    value = np.array([float("nan") if bad == "nan" else -1.], dtype=np.float32)
    write_ct2(path, [(name, value)], [("a", "b"), ("b", "a")] if bad == "alias" else [])
    with pytest.raises(ValueError):
        heart.binary_inventory(path)


def full_tokenizer(path):
    vocab = {f"token-{i}": i for i in range(51865)}
    specials = {"<|en|>": 50259, "<|es|>": 50262, "<|transcribe|>": 50359,
                "<|nocaptions|>": 50362, "<|notimestamps|>": 50363}
    specials.update({f"<|{i * .02:.2f}|>": 50364 + i for i in range(1501)})
    for token, number in specials.items():
        del vocab[f"token-{number}"]
        vocab[token] = number
    path.write_text(json.dumps({"model": {"vocab": vocab}, "added_tokens": []}), encoding="utf-8")
    return vocab


def test_vocabulary_keeps_exact_timestamp_ids(tmp_path, no_models):
    path = tmp_path / "tokenizer.json"
    full_tokenizer(path)
    assert heart.token_map(path)["<|30.00|>"] == 51864
    value = heart.read_json(path)
    vocab = value["model"]["vocab"]
    vocab["<|0.00|>"], vocab["<|0.02|>"] = vocab["<|0.02|>"], vocab["<|0.00|>"]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="Timestamp"):
        heart.token_map(path)


def test_output_config_is_validated_and_never_overwritten(tmp_path, no_models, monkeypatch):
    output, source = tmp_path / "out", tmp_path / "source"
    output.mkdir()
    source.mkdir()
    for name in ("tokenizer.json", "preprocessor_config.json"):
        (output / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(heart, "METADATA_SHA", {p.name: heart.digest(p) for p in output.iterdir()})
    monkeypatch.setattr(heart, "token_map", lambda _: {"one": 0})
    (output / "vocabulary.json").write_text('["one"]', encoding="utf-8")
    config = output / "config.json"
    config.write_text('{"alignment_heads": [[0,0]]}', encoding="utf-8")
    (source / "generation_config.json").write_text(json.dumps({"lang_to_id": {"es": 50262},
        "suppress_tokens": [], "begin_suppress_tokens": []}), encoding="utf-8")
    before = config.read_bytes()
    with pytest.raises(ValueError, match="alignment"):
        heart.validate_output(output, source)
    assert config.read_bytes() == before


def test_output_layer_norm_is_not_a_numbered_transformer_layer(tmp_path, no_models, monkeypatch):
    output, source = tmp_path / "out", tmp_path / "source"
    output.mkdir()
    source.mkdir()
    (output / "tokenizer.json").write_text("{}", encoding="utf-8")
    (output / "preprocessor_config.json").write_text('{"feature_size":80}', encoding="utf-8")
    monkeypatch.setattr(heart, "METADATA_SHA", {p.name: heart.digest(p) for p in output.iterdir()})
    monkeypatch.setattr(heart, "token_map", lambda _: {"one": 0})
    (output / "vocabulary.json").write_text('["one"]', encoding="utf-8")
    (output / "config.json").write_text(json.dumps({"alignment_heads": heart.HEADS,
        "lang_ids": [50262], "suppress_ids": [], "suppress_ids_begin": []}), encoding="utf-8")
    (source / "generation_config.json").write_text(json.dumps({"lang_to_id": {"es": 50262},
        "suppress_tokens": [], "begin_suppress_tokens": []}), encoding="utf-8")
    rows = {name: {"shape": shape, "dtype": "int8"} for name, shape in {
        "decoder/embeddings/weight": [51865, 1024], "encoder/conv1/weight": [1024, 80, 3],
        "encoder/conv2/weight": [1024, 1024, 3]}.items()}
    for side in ("encoder", "decoder"):
        rows[side + "/layer_norm/gamma"] = {"shape": [1024], "dtype": "float16"}
        for number in range(24):
            rows[f"{side}/layer_{number}/layer_norm/gamma"] = {"shape": [1024], "dtype": "float16"}
    monkeypatch.setattr(heart, "binary_inventory", lambda _: {"variables": rows, "aliases": {}})
    assert heart.validate_output(output, source)["alignment_heads"] == heart.HEADS
    del rows["encoder/layer_23/layer_norm/gamma"]
    with pytest.raises(ValueError, match="layer inventory"):
        heart.validate_output(output, source)
