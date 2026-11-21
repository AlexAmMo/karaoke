"""Apply a mid/side spectral mask while retaining the source sample clock."""

import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import istft, stft


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
