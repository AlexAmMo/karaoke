"""Prepare and supervise the distinct Heart FP16/pread -> CT2 int8 candidate.

No downloader or transcription is included. Planning and metadata validation do
not import ML runtimes. The only model load is in a separately supervised worker.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
REVISION = "ee842de9aeec454236badef2205dea47a1fd8410"
WEIGHT_BYTES = 3055544304
WEIGHT_SHA = "9e09145b687c26330da96ad2d7ca1fe542d46247700a43a3156b924a6b6e6a07"
LIMIT = 4 * 1024**3
TIMEOUT = 900
MIN_DISK_FREE = 4 * 1024**3  # At conversion time, after the local source already exists.
MONITOR_SHA = "5cc80cefe57a4088701dc3ea1e9bfa2be3ee5120754c4d6a702ccf184ed3ef97"
SUPERVISOR_SHA = "0a36facfe0b49da79a4b8ac24c79bce2fa34f28854891d45f13890ffb9d84cc8"
BASELINE_PLAN_SHA = "0a9e4d81a2462977c8b21871f9cc3fe5451db48ead5d6cb853d2e902e6bf183c"
BASELINE_FREEZE_SHA = "c88bf5aa82893d41a018a88e65f03db8bd6182a092da3f51df79f9f17a253e12"
PILOT = ("bad-bunny-amorfoda", "fito-paez-11-y-6",
         "jonathan-coulton-mr-fancy-pants", "northern-star")
HEADS = [[13, 15], [15, 4], [15, 15], [16, 1], [20, 0], [23, 4]]
VERSIONS = {"torch": "2.8.0", "safetensors": "0.8.0", "transformers": "4.57.1",
            "ctranslate2": "4.9.0", "numpy": "2.5.5", "tokenizers": "0.22.2",
            "huggingface-hub": "0.36.2"}
METADATA_SHA = {
    "config.json": "1cf4e023d6cc6801eebc0c2009c7daf6ade83932bb96a19611c496549a17f323",
    "generation_config.json": "4b7ebbbe7a99573c12749a53e5d119e56a4110d6c44c4336ce33d1fd405ca846",
    "preprocessor_config.json": "9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666",
    "tokenizer_config.json": "2a4c4281cf9f51ac6ccc406fdc711a087afe6530f671fa7b80953edc498275ce",
    "special_tokens_map.json": "e67ae3a0aaa99abcd9f187138e12db1f65c16a14761c50ef10eef2c174a7a691",
    "tokenizer.json": "27fc476bfe7f17299480be2273fc0608e4d5a99aba2ab5dec5374b4482d1a566",
}
RUNTIME_SOURCE_SHA = {
    "ctranslate2/converters/transformers.py": "662ef9cafcb4acfd9e0b785783236325192ef2fb00f430377371441fac47d60b",
    "ctranslate2/specs/model_spec.py": "32d6050ce80cea033b98d27bf539d458c7f337532fa2148f567e33b4541ca431",
    "ctranslate2/specs/common_spec.py": "ed4b90dd8b0ef9f2c087016e5a5e3555b34b40bccd9584df8eb652805ff88039",
    "ctranslate2/converters/utils.py": "bb9d6383753ecd044c32130ea7e28a1ec1d69bab504384c0ae55e246f2e91324",
    "transformers/modeling_utils.py": "bf1c6b2a43cf7c36fb79f37c981424dd6ae78eb863fcaa5d2a37e76c9828611d",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8",
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def record(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def locked_versions(path):
    versions = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, version = line.split("==")
        versions[name.lower().replace("_", "-")] = version
    if any(versions.get(name) != version for name, version in VERSIONS.items()):
        raise ValueError("Environment lock differs from required conversion versions")
    return versions


def checked(row):
    path = Path(row["path"])
    if digest(path) != row["sha256"]:
        raise ValueError(f"Changed frozen file: {path}")
    return path


@contextmanager
def pread_cpu_reader(module):
    """Change only one module's reader, preserving arguments and restoring it."""
    original = module.safe_open

    def cpu_pread(*args, **kwargs):
        device = kwargs.get("device", args[2] if len(args) > 2 else None)
        if device is not None and str(device) != "cpu":
            raise ValueError("Heart conversion requires CPU safetensors reads")
        if kwargs.get("backend", "pread") != "pread":
            raise ValueError("Heart conversion requires pread, not mmap")
        return original(*args, **dict(kwargs, backend="pread"))

    module.safe_open = cpu_pread
    try:
        yield
    finally:
        module.safe_open = original


def baseline_record(directory):
    plan, freeze = directory / "plan.json", directory / "frozen.json"
    if digest(plan) != BASELINE_PLAN_SHA or digest(freeze) != BASELINE_FREEZE_SHA:
        raise ValueError("Expected the completed RMS-ASR v3 baseline, not v2")
    data = read_json(freeze)
    if data["plan_sha256"] != BASELINE_PLAN_SHA or len(data["results"]) != 16:
        raise ValueError("Incomplete baseline freeze")
    selected = []
    for row in data["results"]:
        checked(row["prediction"])
        checked(row["resources"])
        if row["arm"] == "vocals-native":
            selected.append(row)
    if [row["id"] for row in selected] != list(PILOT):
        raise ValueError("Unexpected baseline cohort")
    return {"plan": record(plan), "freeze": record(freeze), "selected": selected,
            "scope": "Hashes and identities only; no reference text or evaluation read"}


def own_sources():
    paths = {"adapter": Path(__file__),
             "supervisor": ROOT / "scripts/experiments/yourmt3_notes.py",
             "monitor": ROOT / "scripts/experiments/lead_vocals.py"}
    records = {key: record(path) for key, path in paths.items()}
    if records["supervisor"]["sha256"] != SUPERVISOR_SHA or records["monitor"]["sha256"] != MONITOR_SHA:
        raise ValueError("Frozen supervisor or monitor changed")
    return records


def prepare(args):
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a new empty directory; prior plans and attempts are immutable")
    locked_versions(args.environment_lock)
    plan = {"schema": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "conversion only; no transcription or automatic follow-up",
            "code": own_sources(), "source_directory": str(args.source.resolve()),
            "official_source": {"repo": "HeartMuLa/HeartTranscriptor-oss", "revision": REVISION,
                                "weight_bytes": WEIGHT_BYTES, "weight_sha256": WEIGHT_SHA,
                                "metadata_sha256": METADATA_SHA},
            "python": str(args.python.absolute()), "python_minor": [3, 12],
            "overlay": str(args.overlay.resolve()) if args.overlay else None, "versions": VERSIONS,
            "environment_lock": record(args.environment_lock),
            "runtime_source_sha256": RUNTIME_SOURCE_SHA,
            "baseline": baseline_record(args.baseline), "pilot_ids": list(PILOT),
            "denominator": 40, "references_opened": False,
            "conversion": {"load_as_float16": True, "quantization": "int8", "device": "cpu",
                           "reader": "transformers.modeling_utils.safe_open: backend=pread",
                           "trust_remote_code": False, "local_files_only": True,
                           "copy_files": ["tokenizer.json", "preprocessor_config.json"],
                           "threads": 2, "timeout_seconds": TIMEOUT,
                           "rss_and_footprint_stop_bytes": LIMIT, "sample_seconds": .05,
                           "minimum_free_disk_bytes": MIN_DISK_FREE,
                           "suggested_free_disk_before_external_download_bytes": 12 * 1024**3,
                           "memory_estimate_bytes": 3765099108,
                           "memory_limit_scope": "sampled worker maximum, not a hard allocation bound"},
            "candidate_inference_not_implemented": {"beam_size": 2, "best_of": 1,
                "max_new_tokens": 256, "cpu_threads": 2, "batch": 1, "device": "cpu",
                "compute_type": "int8", "temperature": [0, .1, .2, .4],
                "compression_ratio_threshold": 1.8, "log_prob_threshold": -1.,
                "no_speech_threshold": .4, "condition_on_previous_text": False,
                "word_timestamps": True, "vad_filter": False, "seed": 113},
            "non_equivalence": "FP32->FP16 rounding then int8, CT2/frontend and decoding changes; "
                               "comparison to Turbo is between chains, not weights alone"}
    save_new(args.output / "plan.json", plan)
    print(json.dumps({"plan": str(args.output / "plan.json"), "model_loaded": False}))


def verify_plan(output):
    plan = read_json(output / "plan.json")
    if plan["code"] != own_sources() or plan["versions"] != VERSIONS:
        raise ValueError("Adapter, supervisor or expected runtime changed after planning")
    if plan["runtime_source_sha256"] != RUNTIME_SOURCE_SHA:
        raise ValueError("Runtime source pins changed")
    if plan["official_source"] != {"repo": "HeartMuLa/HeartTranscriptor-oss", "revision": REVISION,
                                   "weight_bytes": WEIGHT_BYTES, "weight_sha256": WEIGHT_SHA,
                                   "metadata_sha256": METADATA_SHA}:
        raise ValueError("Official source pins changed")
    settings = plan["conversion"]
    if (settings["rss_and_footprint_stop_bytes"] != LIMIT or settings["timeout_seconds"] != TIMEOUT
            or settings["device"] != "cpu" or not settings["load_as_float16"]
            or settings["quantization"] != "int8" or settings["threads"] != 2):
        raise ValueError("Conversion settings differ from the reviewed quota/variant")
    checked(plan["baseline"]["plan"])
    checked(plan["baseline"]["freeze"])
    checked(plan["environment_lock"])
    return plan


def token_map(path):
    data = read_json(path)
    result = dict(data["model"]["vocab"])
    for row in data["added_tokens"]:
        if row["content"] in result and result[row["content"]] != row["id"]:
            raise ValueError("Conflicting added token")
        result[row["content"]] = row["id"]
    if len(result) != 51865 or sorted(result.values()) != list(range(51865)):
        raise ValueError("Expected exactly 51865 contiguous token IDs")
    for token, number in {"<|en|>": 50259, "<|es|>": 50262, "<|transcribe|>": 50359,
                          "<|nocaptions|>": 50362, "<|notimestamps|>": 50363}.items():
        if result.get(token) != number:
            raise ValueError("Language/task token changed")
    if any(result.get(f"<|{i * .02:.2f}|>") != 50364 + i for i in range(1501)):
        raise ValueError("Timestamp tokens changed")
    return result


def source_header(path):
    with path.open("rb") as stream:
        count = struct.unpack("<Q", stream.read(8))[0]
        if not 0 < count <= 8 * 1024**2:
            raise ValueError("Unexpected safetensors header length")
        header = json.loads(stream.read(count))
    rows = {k: v for k, v in header.items() if k != "__metadata__"}
    offsets = []
    parameters = 0
    for name, row in rows.items():
        shape, (first, last) = row["shape"], row["data_offsets"]
        if (row["dtype"] != "F32" or not shape or any(type(x) is not int or x <= 0 for x in shape)
                or last - first != 4 * math.prod(shape)):
            raise ValueError(f"Unexpected source tensor: {name}")
        parameters += math.prod(shape)
        offsets.append((first, last))
    position = 0
    for first, last in sorted(offsets):
        if first != position:
            raise ValueError("Source tensor bytes overlap or have gaps")
        position = last
    if position + count + 8 != path.stat().st_size or parameters != 763857920:
        raise ValueError("Source size or unique parameter inventory differs")
    return rows


def verify_source(directory):
    weight = directory / "model.safetensors"
    if not weight.is_file() or weight.stat().st_size != WEIGHT_BYTES:
        raise ValueError("A complete local official FP32 checkpoint is required; no download is performed")
    if digest(weight) != WEIGHT_SHA:
        raise ValueError("Local checkpoint SHA-256 differs from the official source")
    for name, sha in METADATA_SHA.items():
        if digest(directory / name) != sha:
            raise ValueError(f"Changed source metadata: {name}")
    token_map(directory / "tokenizer.json")
    return source_header(weight)


def runtime_record(lock):
    if list(sys.version_info[:2]) != [3, 12]:
        raise ValueError("Expected Python3.12 conversion worker")
    versions = {name: importlib.metadata.version(name) for name in VERSIONS}
    if versions != VERSIONS:
        raise ValueError(f"Worker dependency mismatch: {versions}")
    files = {}
    for relative, expected in RUNTIME_SOURCE_SHA.items():
        package = relative.split("/", 1)[0]
        path = importlib.metadata.distribution(package).locate_file(relative)
        if digest(path) != expected:
            raise ValueError(f"Runtime implementation changed: {relative}")
        files[relative] = record(path)
    all_versions = {d.metadata["Name"].lower().replace("_", "-"): d.version
                    for d in importlib.metadata.distributions()}
    if all_versions != locked_versions(lock):
        raise ValueError("Worker packages differ from the complete frozen environment")
    return {"versions": versions, "all_versions": all_versions, "files": files, "python": sys.version,
            "executable": sys.executable, "sys_path": sys.path}


def audit_cast(directory, rows, mark):
    """Audit pinned source bytes in 4-MiB reads; retain only scalar statistics."""
    import numpy as np

    audit = []
    with (directory / "model.safetensors").open("rb") as source:
        data_start = 8 + struct.unpack("<Q", source.read(8))[0]
        for name, row in rows.items():
            first, last = row["data_offsets"]
            source.seek(data_start + first)
            sha = hashlib.sha256()
            maximum = 0.
            underflow = 0
            for offset in range(first, last, 4 * 1024**2):
                count = min(last - offset, 4 * 1024**2)
                raw = source.read(count)
                if len(raw) != count:
                    raise ValueError("Source tensor was truncated during audit")
                part = np.frombuffer(raw, dtype="<f4")
                if not np.isfinite(part).all() or np.max(np.abs(part)) > np.finfo(np.float16).max:
                    raise ValueError(f"Nonfinite or FP16-overflowing tensor: {name}")
                cast = part.astype("<f2")
                if not np.isfinite(cast).all():
                    raise ValueError("Nonfinite FP16 cast")
                underflow += int(np.count_nonzero((part != 0) & (cast == 0)))
                maximum = max(maximum, float(np.max(np.abs(part - cast.astype(np.float32)))))
                sha.update(cast.tobytes())
            audit.append({"name": name, "shape": row["shape"], "fp16_sha256": sha.hexdigest(),
                          "max_abs_rounding_error": maximum, "underflow_to_zero": underflow})
            del raw, part, cast
    mark("after_source_cast_audit", tensor_count=len(audit))
    return audit


def binary_inventory(path):
    """Inspect the fixed CT2 v6 serialization in bounded chunks, without loading CT2."""
    import numpy as np

    rows, aliases = {}, {}
    size = path.stat().st_size
    with path.open("rb") as stream:
        def exact(n):
            data = stream.read(n)
            if len(data) != n:
                raise ValueError("Truncated CT2 binary")
            return data

        def scalar(fmt):
            return struct.unpack("<" + fmt, exact(struct.calcsize("<" + fmt)))[0]

        def string():
            n = scalar("H")
            if not n:
                raise ValueError("Empty CT2 encoded string")
            value = exact(n)
            if value[-1] != 0:
                raise ValueError("Malformed CT2 string")
            return value[:-1].decode("utf-8")

        if scalar("I") != 6 or string() != "WhisperSpec" or scalar("I") != 3:
            raise ValueError("Unexpected CT2 binary/spec version")
        count = scalar("I")
        if not 0 < count < 10000:
            raise ValueError("Unexpected CT2 variable count")
        types = ("<f4", "i1", "<i2", "<i4", "<f2", None)
        for _ in range(count):
            name = string()
            rank = scalar("B")
            if rank > 4:
                raise ValueError("Unexpected CT2 tensor rank")
            shape = [scalar("I") for _ in range(rank)]
            kind, nbytes = scalar("B"), scalar("I")
            if kind >= len(types) or types[kind] is None:
                raise ValueError("Unexpected CT2 tensor dtype")
            dtype = np.dtype(types[kind])
            if (nbytes != math.prod(shape) * dtype.itemsize or stream.tell() + nbytes > size
                    or name in rows):
                raise ValueError("CT2 tensor size or identity mismatch")
            sha = hashlib.sha256()
            remaining = nbytes
            while remaining:
                data = exact(min(remaining, 1024**2))
                values = np.frombuffer(data, dtype=dtype)
                if np.issubdtype(dtype, np.floating) and not np.isfinite(values).all():
                    raise ValueError(f"Nonfinite CT2 tensor: {name}")
                if name.endswith("weight_scale") and np.any(values <= 0):
                    raise ValueError("Nonpositive CT2 quantization scale")
                sha.update(data)
                remaining -= len(data)
            rows[name] = {"shape": shape, "dtype": dtype.name, "bytes": nbytes,
                          "sha256": sha.hexdigest()}
        count = scalar("I")
        if count >= 10000:
            raise ValueError("Unexpected CT2 alias count")
        for _ in range(count):
            name, target = string(), string()
            if name in aliases or name in rows:
                raise ValueError("Duplicate CT2 alias")
            aliases[name] = target
        if stream.read(1):
            raise ValueError("Trailing CT2 bytes")
    for name in aliases:
        seen, target = {name}, aliases[name]
        while target in aliases:
            if target in seen:
                raise ValueError("CT2 alias cycle")
            seen.add(target)
            target = aliases[target]
        if target not in rows:
            raise ValueError("CT2 alias references missing data")
    return {"variables": rows, "aliases": aliases}


def validate_output(directory, source):
    for name in ("tokenizer.json", "preprocessor_config.json"):
        if digest(directory / name) != METADATA_SHA[name]:
            raise ValueError(f"Copied artifact changed: {name}")
    tokens = token_map(directory / "tokenizer.json")
    ordered = [k for k, _ in sorted(tokens.items(), key=lambda item: item[1])]
    if read_json(directory / "vocabulary.json") != ordered:
        raise ValueError("Converted vocabulary differs from source token IDs")
    config = read_json(directory / "config.json")
    generation = read_json(source / "generation_config.json")
    expected = {"alignment_heads": HEADS, "lang_ids": sorted(generation["lang_to_id"].values()),
                "suppress_ids": generation["suppress_tokens"],
                "suppress_ids_begin": generation["begin_suppress_tokens"]}
    if any(config.get(k) != v for k, v in expected.items()):
        raise ValueError("Converted alignment/language/suppression config changed")
    if read_json(directory / "preprocessor_config.json")["feature_size"] != 80:
        raise ValueError("Expected 80 mel bins")
    inventory = binary_inventory(directory / "model.bin")
    rows, aliases = inventory["variables"], inventory["aliases"]
    for name, shape in {"decoder/embeddings/weight": [51865, 1024],
                        "encoder/conv1/weight": [1024, 80, 3],
                        "encoder/conv2/weight": [1024, 1024, 3]}.items():
        while name in aliases:
            name = aliases[name]
        if rows.get(name, {}).get("shape") != shape or rows[name]["dtype"] != "int8":
            raise ValueError("Converted principal tensor shape/type mismatch")
    names = set(rows) | set(aliases)
    for side in ("encoder", "decoder"):
        layers = {int(match.group(1)) for name in names
                  if (match := re.match(rf"{side}/layer_([0-9]+)/", name))}
        if layers != set(range(24)):
            raise ValueError("Converted layer inventory differs")
    if any(row["dtype"] != "int8" for name, row in rows.items() if name.endswith("/weight")):
        raise ValueError("An expected quantized weight is not int8")
    return {"inventory": inventory, "files": {p.name: digest(p) for p in sorted(directory.iterdir())
                                                if p.is_file()}, "tokens": len(tokens),
            "alignment_heads": config["alignment_heads"]}


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@contextmanager
def catch_termination():
    def stopped(_signum, _frame):
        raise InterruptedError("Conversion controller terminated")
    previous = signal.signal(signal.SIGTERM, stopped)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def convert(output):
    plan = verify_plan(output)
    # Reject missing/wrong local weights before spawning or importing a runtime.
    verify_source(Path(plan["source_directory"]))
    if shutil.disk_usage(output).free < MIN_DISK_FREE:
        raise ValueError("Less than4GiB free after source preparation; conversion has not started")
    attempt = output / "conversion"
    if attempt.exists():
        raise ValueError("Prior conversion attempt exists; no automatic retry")
    if ((plan["overlay"] and not Path(plan["overlay"]).is_dir())
            or not Path(plan["python"]).is_file()):
        raise ValueError("Prepare the separate conversion overlay/interpreter first")
    monitor = module(checked(plan["code"]["monitor"]), "heart_memory_monitor")
    supervisor = module(checked(plan["code"]["supervisor"]), "heart_supervisor")
    sampler = monitor.memory_sampler()  # Fail before starting an unmonitored child.
    attempt.mkdir()
    save_new(attempt / "request.json", {"plan_sha256": digest(output / "plan.json"),
                                      "source_sha256": WEIGHT_SHA})
    environment = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", OMP_NUM_THREADS="2",
                       MKL_NUM_THREADS="2", OPENBLAS_NUM_THREADS="1", HF_HUB_OFFLINE="1",
                       TRANSFORMERS_OFFLINE="1", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
                       HEART_CONVERSION_SUPERVISED="1")
    environment.pop("PYTHONPATH", None)
    if plan["overlay"]:
        environment["PYTHONPATH"] = plan["overlay"]
    command = [plan["python"], str(Path(__file__).resolve()), "_worker", "--output", str(output.resolve())]
    save_new(attempt / "launch.json", {"command": command, "quota_bytes": LIMIT, "timeout": TIMEOUT})
    with catch_termination():
        resources = supervisor.run_bounded(command, attempt, LIMIT, TIMEOUT, sampler, environment)
    if resources["exit_code"] != 0 or not resources["reaped"] or resources["stopped_reason"]:
        raise ValueError("Conversion worker did not finish and reap successfully")
    complete = read_json(attempt / "worker-complete.json")
    if complete["plan_sha256"] != digest(output / "plan.json"):
        raise ValueError("Worker completed another plan")
    for name, sha in complete["files"].items():
        if digest(attempt / name) != sha:
            raise ValueError("Completed conversion artifact changed")
    save_new(output / "frozen.json", {"plan": record(output / "plan.json"),
             "resources": record(attempt / "resources.json"),
             "worker_complete": record(attempt / "worker-complete.json"),
             "model_directory": str((attempt / "ct2-model").resolve()),
             "model_files": {p.name: digest(p) for p in sorted((attempt / "ct2-model").iterdir())},
             "source_sha256": WEIGHT_SHA, "reaped": True, "transcription_executed": False,
             "numerical_equivalence_to_fp32": False})


def worker(output):
    if os.environ.get("HEART_CONVERSION_SUPERVISED") != "1":
        raise ValueError("The conversion worker must be launched by its resource supervisor")
    plan = verify_plan(output)
    attempt = output / "conversion"
    request = read_json(attempt / "request.json")
    if request != {"plan_sha256": digest(output / "plan.json"), "source_sha256": WEIGHT_SHA}:
        raise ValueError("Worker request differs from plan")
    source = Path(plan["source_directory"])
    with (attempt / "worker.log").open("x", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
        with (attempt / "phases.jsonl").open("x", encoding="utf-8") as phases:
            def mark(phase, **fields):
                phases.write(json.dumps({"phase": phase, "unix_time": time.time(),
                                         "pid": os.getpid(), **fields}) + "\n")
                phases.flush()
            try:
                mark("before_local_source_validation")
                rows = verify_source(source)
                save_new(attempt / "runtime.json", runtime_record(checked(plan["environment_lock"])))
                mark("before_source_cast_audit")
                save_new(attempt / "source-cast-audit.json", audit_cast(source, rows, mark))
                mark("before_torch_import")
                import torch
                torch.set_num_threads(2)
                torch.set_num_interop_threads(1)
                torch.set_default_device("cpu")
                from transformers import modeling_utils
                from ctranslate2.converters import TransformersConverter
                mark("after_converter_import")

                class LocalConverter(TransformersConverter):
                    def load_model(self, model_class, model_name_or_path, **kwargs):
                        if kwargs.get("dtype") != torch.float16:
                            raise ValueError("Conversion must load weights as FP16")
                        mark("before_from_pretrained")
                        with pread_cpu_reader(modeling_utils):
                            model, info = model_class.from_pretrained(
                                model_name_or_path, **kwargs, local_files_only=True,
                                use_safetensors=True, output_loading_info=True)
                        missing = set(info["missing_keys"])
                        tied = model.proj_out.weight is model.model.decoder.embed_tokens.weight
                        if (info["unexpected_keys"] or info["mismatched_keys"] or info["error_msgs"]
                                or (missing and not (tied and missing <= {"proj_out.weight"}))):
                            raise ValueError(f"Incomplete checkpoint load: {info}")
                        for parameter in model.parameters():
                            if parameter.device.type != "cpu" or parameter.dtype != torch.float16:
                                raise ValueError("Model parameter is not CPU FP16")
                        save_new(attempt / "loading-info.json", {"info": info, "projection_tied": tied})
                        mark("after_from_pretrained")
                        return model

                converter = LocalConverter(str(source), load_as_float16=True,
                                           low_cpu_mem_usage=True, trust_remote_code=False,
                                           copy_files=["tokenizer.json", "preprocessor_config.json"])
                mark("before_conversion")
                converter.convert(str(attempt / "ct2-staging"), quantization="int8", force=False)
                mark("after_conversion")
                validation = validate_output(attempt / "ct2-staging", source)
                save_new(attempt / "validation.json", validation)
                (attempt / "ct2-staging").rename(attempt / "ct2-model")
                mark("after_validation")
            except BaseException as error:
                mark("failed", error=repr(error))
                raise
    files = {str(p.relative_to(attempt)): digest(p) for p in sorted(attempt.rglob("*"))
             if p.is_file() and p.name not in ("resources.jsonl", "resources.json")}
    save_new(attempt / "worker-complete.json", {"plan_sha256": digest(output / "plan.json"),
                                              "files": files, "numerical_equivalence_to_fp32": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "convert", "_worker"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--python", type=Path, default=ROOT / "build/generation-next/heart-transcriptor/env/bin/python")
    parser.add_argument("--environment-lock", type=Path,
                        default=ROOT / "build/generation-next/heart-transcriptor/requirements-lock.txt")
    parser.add_argument("--baseline", type=Path, default=ROOT / "build/generation-next/rms-vad-asr/v3")
    args = parser.parse_args()
    try:
        if args.command == "plan":
            if args.source is None:
                parser.error("plan requires --source; no checkpoint is downloaded")
            prepare(args)
        elif args.command == "convert":
            convert(args.output)
        else:
            worker(args.output)
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
