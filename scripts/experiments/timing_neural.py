"""Align the fixed draft's words to the separated voice with Qwen3-ForcedAligner Q4_K."""

import argparse
import ctypes as ct
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import unicodedata

import numpy as np

from timing_predict import apply_offsets, parse, serialize

MODEL_SHA = "a7bb4cbeacc6414f11a5d23dc7661a51a941a71e6d559dc7b408b52473f2ae84"
RATE = 16000


class Context(ct.Structure):
    _fields_ = [
        ("n_threads", ct.c_int),
        ("verbosity", ct.c_int),
        ("use_gpu", ct.c_bool),
        ("flash_attn", ct.c_bool),
    ]


class ForcedAligner:
    """CrispASR 0.8.54 exposes the Qwen C API inside the shared library."""

    def __init__(self, library, model, threads, device):
        with model.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != MODEL_SHA:
                raise ValueError("Unexpected Qwen weights")
        self.lib = ct.CDLL(str(library.resolve()))
        self.lib.qwen3_asr_context_default_params.argtypes = []
        self.lib.qwen3_asr_context_default_params.restype = Context
        self.lib.qwen3_asr_init_from_file.argtypes = [ct.c_char_p, Context]
        self.lib.qwen3_asr_init_from_file.restype = ct.c_void_p
        self.lib.qwen3_asr_align_words.argtypes = [
            ct.c_void_p,
            ct.POINTER(ct.c_float),
            ct.c_int,
            ct.POINTER(ct.c_char_p),
            ct.c_int,
            ct.POINTER(ct.c_int64),
            ct.POINTER(ct.c_int64),
        ]
        self.lib.qwen3_asr_align_words.restype = ct.c_int
        self.lib.qwen3_asr_free.argtypes = [ct.c_void_p]
        self.lib.qwen3_asr_free.restype = None
        options = self.lib.qwen3_asr_context_default_params()
        options.n_threads, options.verbosity, options.use_gpu = threads, 0, device == "gpu"
        self.context = self.lib.qwen3_asr_init_from_file(str(model).encode(), options)
        if not self.context:
            raise ValueError("Could not load Qwen3-ForcedAligner")

    def align(self, pcm, words):
        count = len(words)
        text = (ct.c_char_p * count)(*[word.encode("utf-8") for word in words])
        begin, end = (ct.c_int64 * count)(), (ct.c_int64 * count)()
        code = self.lib.qwen3_asr_align_words(
            self.context,
            pcm.ctypes.data_as(ct.POINTER(ct.c_float)),
            len(pcm),
            text,
            count,
            begin,
            end,
        )
        if code:
            raise RuntimeError(f"Qwen inference failed ({code})")
        return np.asarray(begin) / 1000, np.asarray(end) / 1000

    def close(self):
        self.lib.qwen3_asr_free(self.context)


@dataclass
class Word:
    text: str
    owner: int
    start: float
    end: float


def lyric_words(rows):
    flat, owners = [], []
    for i, row in enumerate(rows):
        if i and row.line != rows[i - 1].line:
            flat.append(" ")
            owners.append(i)
        text = unicodedata.normalize("NFKC", row.lyric.casefold()).replace("~", "")
        flat.extend(text)
        owners.extend([i] * len(text))
    tokens = list(re.finditer(r"[^\W_]+(?:['’][^\W_]+)*", "".join(flat)))
    words = []
    for i, token in enumerate(tokens):
        onset = owners[token.start()]
        next_row = owners[tokens[i + 1].start()] if i + 1 < len(tokens) else len(rows)
        # Include melismatic continuations before the next word.
        end_row = max(owners[token.end() - 1], next_row - 1)
        words.append(Word(token.group(), onset, rows[onset].start / 60, rows[end_row].end / 60))
    return words


def batches(words):
    batch = []
    for word in words:
        if batch and (word.start - batch[0].start > 22 or word.start - batch[-1].end > 2):
            yield batch
            batch = []
        batch.append(word)
    if batch:
        yield batch


def word_offsets(model, words, row_count, voice):
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(voice),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            "-",
        ]
    )
    audio = np.frombuffer(raw, dtype="<f4").copy()
    strict, direct = np.zeros(row_count), np.zeros(row_count)
    log = []
    for batch in batches(words):
        # Use coarse, unreviewed generated phrase boundaries for windowing only.
        a = max(0, int((batch[0].start - 0.8) * RATE))
        b = min(len(audio), int((batch[-1].end + 0.8) * RATE), a + 32 * RATE)
        starts, ends = model.align(audio[a:b], [word.text for word in batch])
        valid = (starts >= 0) & (ends > starts) & (ends <= (b - a) / RATE + 0.08)
        deltas = a / RATE + starts - np.array([word.start for word in batch])
        # Monotonic repair sometimes collapses whole words onto one instant.
        ok = valid & (abs(deltas) <= 0.25)
        supports_window = int(ok.sum()) >= max(1, 0.7 * len(batch))
        for i, word in enumerate(batch):
            if ok[i]:
                direct[word.owner] = deltas[i]
            if supports_window and ok[i] and abs(deltas[i]) <= 0.16:
                strict[word.owner] = 0.5 * deltas[i]
            log.append([word.owner, round(float(deltas[i]), 3), bool(valid[i])])
    return {"qwen": direct, "qwen-consenso": strict}, log


def predict(model, rows, voice):
    shifts, log = word_offsets(model, lyric_words(rows), len(rows), voice)
    return {name: apply_offsets(rows, vector) for name, vector in shifts.items()}, log


@contextmanager
def device_slot(path):
    if path is None:
        yield
        return
    import fcntl

    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("charts", type=Path)
    parser.add_argument("stems", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--expect", type=int, default=0)
    parser.add_argument("--device", choices=("cpu", "gpu"), default="cpu")
    parser.add_argument("--device-lock", type=Path, help="Optional shared POSIX GPU lock")
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    while True:
        charts = json.loads(args.charts.read_text())
        stems = json.loads(args.stems.read_text())
        available = sorted(charts.keys() & stems.keys())
        pending = [tag for tag in available if not (args.output / tag / "hashes.json").is_file()]
        for start in range(0, len(pending), 4):
            # Hold weights only while this process owns the device. Other models
            # can use the entire GPU between these short batches.
            with device_slot(args.device_lock):
                model = ForcedAligner(args.library, args.model, args.threads, args.device)
                try:
                    for tag in pending[start : start + 4]:
                        folder = args.output / tag
                        folder.mkdir(exist_ok=True)
                        started = time.monotonic()
                        headers, rows = parse(Path(charts[tag]))
                        variants, anchors = predict(model, rows, Path(stems[tag]))
                        hashes = {}
                        for method, alternative in variants.items():
                            private = folder / (method + ".txt")
                            private.write_text(serialize(headers, alternative))
                            hashes[method] = hashlib.sha256(private.read_bytes()).hexdigest()
                        (folder / "anchors.json").write_text(json.dumps(anchors))
                        temp = folder / "hashes.tmp"
                        temp.write_text(json.dumps(hashes))
                        temp.replace(folder / "hashes.json")
                        print(tag, len(anchors), round(time.monotonic() - started, 2), flush=True)
                finally:
                    model.close()
                    del model
        if len(available) >= args.expect:
            return
        time.sleep(20)


if __name__ == "__main__":
    main()
