"""Measure the shipped FCPE on mixed-vocal vs spatially centred vocal audio without reading charts."""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import onnxruntime as ort
import soundfile as sf
import soxr

from lead_separation import centre_block, digest

MODEL_SHA = "09c5717de92ddd5e4efc5177104f973d205102b2b5596ba91eeb19711cb90d12"


def contours(src, model):
    with sf.SoundFile(src) as f:
        rate, length = f.samplerate, len(f)
        core = 512 * 1024
        mono, center = [], []
        for start in range(0, length, core):
            end = min(length, start + core)
            left, right = max(0, start - 2048), min(length, end + 2048)
            f.seek(left)
            audio = f.read(right - left, always_2d=True, dtype="float32")
            a, b = start - left, end - left
            mono.append(audio[a:b].mean(axis=1))
            center.append(centre_block(audio, rate)[a:b])
    preds = []
    for channel in (mono, center):
        signal = soxr.resample(np.concatenate(channel), rate, 16000, quality="HQ")
        # Fixed 18 s core with 2 s on each side; all boundaries fall exactly on the 10 ms lattice.
        # Split inference gives the same bounded cost on a low-memory PC and on the runner.
        parts = []
        for a in range(0, len(signal), 18 * 16000):
            b = min(len(signal), a + 18 * 16000)
            left, right = max(0, a - 2 * 16000), min(len(signal), b + 2 * 16000)
            f0 = model.run(["f0"], {"audio": signal[left:right][None]})[0][0]
            count = (b - a + 159) // 160
            selected = f0[(a - left) // 160 : (a - left) // 160 + count]
            if len(selected) != count:
                selected = np.pad(selected, (0, count - len(selected)))
            parts.append(selected)
        preds.append(np.concatenate(parts))
    return preds


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--stems", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ids", nargs="*")
    p.add_argument("--threads", type=int, default=2)
    args = p.parse_args()
    if digest(args.model) != MODEL_SHA:
        raise ValueError("Unexpected FCPE model")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = args.threads
    opts.inter_op_num_threads = 1
    opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
    model = ort.InferenceSession(
        str(args.model), sess_options=opts, providers=["CPUExecutionProvider"]
    )
    args.output.mkdir(parents=True, exist_ok=True)
    for tag, source in json.loads(args.stems.read_text()).items():
        if args.ids and tag not in args.ids:
            continue
        path = args.output / (tag + ".npz")
        sha = digest(source)
        if path.is_file():
            with np.load(path) as z:
                if str(z["source_sha"]) == sha:
                    continue
        started = time.monotonic()
        a, b = contours(source, model)
        seconds = round(time.monotonic() - started, 3)
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(
            tmp, raw=a, center=b, source_sha=sha, model_sha=MODEL_SHA, seconds=seconds
        )
        tmp.replace(path)
        print(tag, len(a), seconds, flush=True)


if __name__ == "__main__":
    main()
