"""Extract private vocal attack envelopes for the timing benchmark, without opening charts."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter1d, median_filter
from scipy.signal import find_peaks, get_window

RATE = 16000
HOP = 80
FFT = 1024


def fingerprint(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def band_filters():
    # 24 overlapping triangular bands per octave on a log-frequency axis.
    centers = 55 * 2 ** (np.arange(174) / 24)
    bins = np.fft.rfftfreq(FFT, 1 / RATE)
    left, mid, right = (part[:, None] for part in (centers[:-2], centers[1:-1], centers[2:]))
    return np.maximum(0, np.minimum((bins - left) / (mid - left), (right - bins) / (right - mid)))


def attacks(voice):
    pcm = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-i",
            str(voice),
            "-vn",
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-threads",
            "1",
            "-",
        ]
    )
    samples = np.frombuffer(pcm, dtype="<f4")
    padded = np.pad(samples, FFT // 2)
    frames = np.lib.stride_tricks.sliding_window_view(padded, FFT)[::HOP]
    bands = band_filters().astype("float32")
    taper = get_window("hann", FFT).astype("float32")
    # Frequency filtering is local to a frame. Carry the three previous frames
    # between blocks so the same novelty function uses bounded working memory.
    novelty = np.zeros(len(frames), dtype="float32")
    prev_frames = np.empty((0, len(bands)), dtype="float32")
    for offset in range(0, len(frames), 1024):
        spectra = np.abs(np.fft.rfft(frames[offset : offset + 1024] * taper)).astype("float32")
        envelopes = np.log1p(20 * (spectra @ bands.T))
        current = maximum_filter1d(envelopes, 3, axis=1, mode="nearest")
        previous = np.concatenate((prev_frames, current))
        first = 3 - len(prev_frames)
        novelty[offset + first : offset + len(envelopes)] = np.maximum(
            0, envelopes[first:] - previous[:-3]
        ).mean(axis=1)
        prev_frames = previous[-3:]
    flux = novelty
    background = median_filter(flux, 41, mode="nearest")
    contrast = flux - background
    threshold = max(0.006, float(np.quantile(contrast, 0.76)))
    indexes, props = find_peaks(contrast, height=threshold, prominence=threshold, distance=8)
    return indexes * HOP / RATE, props["prominences"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stems", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for tag, filename in json.loads(args.stems.read_text()).items():
        out = args.destination / (tag + ".npz")
        voice = Path(filename)
        digest = fingerprint(voice)
        if out.exists():
            with np.load(out) as data:
                if str(data["voice_sha256"]) == digest:
                    continue
        t, strength = attacks(voice)
        temporary = out.with_suffix(".tmp.npz")
        np.savez_compressed(temporary, times=t, strengths=strength, voice_sha256=digest)
        temporary.replace(out)
        print(tag, len(t), flush=True)


if __name__ == "__main__":
    main()
