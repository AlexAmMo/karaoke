"""Separate the stereo vocal centre, then transcribe in the original clock with the same SOME.

No chart or lyrics are read. Only one private temporary waveform is retained at a time.
"""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time

import numpy as np
import soundfile as sf
from scipy.signal import istft, stft

from melody_transcribe import MODEL_SHA, device_turn, infer, some_predictor


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def centre_block(x, rate):
    """Use stereo equality as a conservative spatial cue; floor the soft mask at -14 dB."""
    if len(x) < 2048:
        return x.mean(axis=1)
    spec_args = dict(fs=rate, window="hann", nperseg=2048, noverlap=1536)
    _, _, mid = stft((x[:, 0] + x[:, -1]) * 0.5, **spec_args)
    _, _, side = stft((x[:, 0] - x[:, -1]) * 0.5, **spec_args)
    signal, residual = abs(mid) ** 2, abs(side) ** 2
    mask = signal / np.maximum(signal + 8 * residual, 1.0e-18)
    _, out = istft(mid * np.maximum(mask, 0.2), **spec_args)
    return out[: len(x)]


def separate_center(source, destination):
    with (
        sf.SoundFile(source) as src,
        sf.SoundFile(
            destination, mode="w", samplerate=src.samplerate, channels=1, subtype="FLOAT"
        ) as out,
    ):
        for start in range(0, len(src), 512 * 640):
            end = min(len(src), start + 512 * 640)
            left, right = max(0, start - 2048), min(len(src), end + 2048)
            src.seek(left)
            audio = src.read(right - left, always_2d=True, dtype="float32")
            mono = centre_block(audio, src.samplerate)
            out.write(mono[start - left : end - left])


def run(args):
    if digest(args.model) != MODEL_SHA["some"]:
        raise ValueError("Unexpected SOME checkpoint")
    args.output.mkdir(exist_ok=True, parents=True)
    predict = None
    if args.method == "mdx":
        from lead_mdx import open_model, separate

        net = open_model(args.separator, args.threads)
    completed = set()
    while True:
        sources = json.loads(args.stems.read_text())
        for tag, filepath in sources.items():
            if args.ids and tag not in args.ids:
                continue
            if tag in completed:
                continue
            source = Path(filepath)
            stem_sha = digest(source)
            config = dict(
                stem_sha256=stem_sha,
                some_sha256=MODEL_SHA["some"],
                model=args.method,
                device=args.device,
                core=18,
                pad=2,
            )
            output = args.output / f"{tag}.json"
            if output.is_file() and json.loads(output.read_text())["settings"] == config:
                completed.add(tag)
                continue
            with tempfile.TemporaryDirectory(dir=args.output) as temporary:
                isolated = Path(temporary) / "source.wav"
                started = time.monotonic()
                if args.method == "mdx":
                    separate(source, isolated, net)
                else:
                    separate_center(source, isolated)
                pre_s = time.monotonic() - started
                if sf.info(source).frames != sf.info(isolated).frames:
                    raise ValueError("The separator changed the source clock")
                with device_turn(args.device_lock):
                    if predict is None:
                        predict = some_predictor(args)
                    started = time.monotonic()
                    events = infer(isolated, predict, 18, 2)
                    elapsed = time.monotonic() - started
                payload = dict(
                    events=events,
                    settings=config,
                    seconds=round(elapsed, 3),
                    separation_s=round(pre_s, 3),
                    frames=sf.info(isolated).frames,
                )
                tmp = output.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload))
                tmp.replace(output)
                completed.add(tag)
                print(
                    tag, len(completed), len(events), round(pre_s, 2), round(elapsed, 2), flush=True
                )
        if len(completed) >= (len(args.ids) if args.ids else args.expect):
            return
        time.sleep(8)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "source", "stems", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--method", choices=["center", "mdx"], default="center")
    p.add_argument("--separator", type=Path)
    p.add_argument("--device", default="mps")
    p.add_argument("--device-lock", type=Path)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--expect", type=int, default=40)
    p.add_argument("--ids", nargs="+")
    run(p.parse_args())
