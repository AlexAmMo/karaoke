"""UVR-MDX-NET Karaoke 2 residual extraction on CPU, stereo float input at 44.1 kHz."""

from pathlib import Path
import hashlib

import numpy as np
import onnxruntime as ort
import soundfile as sf
from scipy.fft import rfft
from scipy.signal import get_window, istft

MODEL_SHA = "bf32e15105a09c0f7dddd2b67346146334d6f3ecb399ed7638eba2ab07cbf5f4"
FFT, HOP, FRAMES, BINS = 5120, 1024, 256, 2048
N = HOP * (FRAMES - 1)
TRIM = FFT // 2
CORE = N - 2 * TRIM
WINDOW = get_window("hann", FFT, fftbins=True).astype(np.float32)


def open_model(path, threads=2):
    with Path(path).open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != MODEL_SHA:
            raise ValueError("Wrong UVR checkpoint")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])


def extract_chunk(wave, session):
    channels = np.pad(wave.T, ((0, 0), (TRIM, TRIM)), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(channels, FFT, axis=1)[:, ::HOP, :]
    full = rfft(frames * WINDOW, axis=-1, workers=1).transpose(0, 2, 1)
    low = full[:, :BINS, :]
    x = np.stack((low.real, low.imag), axis=1).reshape(1, 4, BINS, FRAMES)
    x[:, :, :3, :] = 0
    pred = session.run(None, {"input": np.ascontiguousarray(x)})[0].reshape(2, 2, BINS, FRAMES)
    full.fill(0)
    full[:, :BINS, :] = pred[:, 0] + 1j * pred[:, 1]
    _, instrumental = istft(
        full / WINDOW.sum(),
        fs=44100,
        window=WINDOW,
        nperseg=FFT,
        noverlap=FFT - HOP,
        nfft=FFT,
        boundary=True,
    )
    return (wave - 1.065 * instrumental.T).mean(axis=1)


def separate(source, destination, session):
    # As in MDX-Net's trimmed-window inference, discard 2560 context samples at both edges.
    # Overlap never introduces a lag and the original sample count is preserved.
    with (
        sf.SoundFile(source) as src,
        sf.SoundFile(
            destination, mode="w", samplerate=src.samplerate, channels=1, subtype="FLOAT"
        ) as out,
    ):
        if src.samplerate != 44100 or src.channels != 2:
            raise ValueError("Need stereo 44.1 kHz input")
        for start in range(0, len(src), CORE):
            left, right = max(0, start - TRIM), min(len(src), start + CORE + TRIM)
            offset = left - (start - TRIM)
            wave = np.zeros((N, 2), dtype="float32")
            src.seek(left)
            wave[offset : offset + right - left] = src.read(right - left, dtype="float32")
            lead = extract_chunk(wave, session)
            out.write(lead[TRIM : TRIM + min(CORE, len(src) - start)])
