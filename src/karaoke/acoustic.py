"""Estimate gross melody timing offsets in a local recording before listener review."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import numpy as np

from .songs import SongError, read_chart


_RATE = 11025
_HOP = 220
_FFT = 2048
_WINDOW = 45.0
_LAGS = np.arange(-80, 81) * 0.025
_MAX_SECONDS = 20 * 60
_TIME_BUDGET = 24.0


def _local_audio(path, start, seconds, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    # Decode at most one short interval. Input seeking avoids decoding the whole file.
    completed = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-ss",
            f"{start:.6f}",
            "-i",
            str(Path(path).resolve()),
            "-t",
            f"{seconds:.6f}",
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(_RATE),
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdin=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        timeout=min(remaining, 10),
        check=True,
    )
    return np.frombuffer(completed.stdout, dtype="<f4")


def _chroma(signal):
    """Framewise pitch classes. Local spectral contrast reduces sustained accompaniment."""
    windows = np.lib.stride_tricks.sliding_window_view(
        np.pad(signal, (_FFT // 2, _FFT // 2)), _FFT
    )[::_HOP]
    midi = np.arange(44, 80)
    base = 440 * 2 ** ((midi - 69) / 12)
    harmonics = np.array([1, 2, 3, 4])
    bins = np.rint(base[:, None] * harmonics * _FFT / _RATE).astype(int)
    weights = np.array([1, 0.75, 0.45, 0.25], dtype=np.float32)
    taper = np.hanning(_FFT).astype(np.float32)
    chroma = np.empty((len(windows), 12), dtype=np.float32)
    # Keep intermediate spectra independent of the interval's length.
    for i in range(0, len(windows), 64):
        spec = np.log1p(np.abs(np.fft.rfft(windows[i : i + 64] * taper, axis=1)))
        cumulative = np.cumsum(np.pad(spec, ((0, 0), (10, 9))), axis=1)
        floor = (cumulative[:, 19:] - cumulative[:, :-19]) / 19
        strengths = np.maximum(spec - floor, 0)[:, bins] @ weights
        classes = np.stack([strengths[:, midi % 12 == pc].max(axis=1) for pc in range(12)], axis=1)
        centered = classes - classes.mean(axis=1, keepdims=True)
        chroma[i : i + len(classes)] = centered / (classes.std(axis=1, keepdims=True) + 1e-5)
    return chroma


def _measure(notes, audio, lo, hi, deadline):
    candidates = [n for n in notes if lo <= n[0] < hi]
    detail = {
        "from_s": round(lo, 2),
        "to_s": round(hi, 2),
        "notes": len(candidates),
        "reliable": False,
    }
    if len(candidates) < 9 or len({n[2] for n in candidates}) < 3:
        return detail
    # Leave room to evaluate +/-2 s without clipping notes into silence at an interval edge.
    decode_start = max(0, lo - 2.2)
    signal = _local_audio(audio, decode_start, hi - decode_start + 2.2, deadline)
    if len(signal) < _FFT or np.sqrt(np.mean(np.square(signal))) < 0.0008:
        return detail
    chroma = _chroma(signal)
    duration = len(signal) / _RATE
    # The memory bound for the lag search is independent of chart density.
    if len(candidates) > 240:
        candidates = [candidates[i] for i in np.linspace(0, len(candidates) - 1, 240, dtype=int)]
    samples = [
        (start + f * length - decode_start, pitch)
        for start, length, pitch in candidates
        for f in (0.25, 0.55, 0.80)
        if 2.05 <= start + f * length - decode_start <= duration - 2.05
    ]
    if len(samples) < 24:
        return detail
    times, pitch = np.array(samples).T
    pitch = pitch.astype(int)
    indices = np.rint((times[None, :] + _LAGS[:, None]) * _RATE / _HOP).astype(int)
    scores = chroma[indices, pitch].mean(axis=1)
    peak_index = int(scores.argmax())
    lag = _LAGS[peak_index]
    # Two controls reject repeating chords and unrelated music: do other times work
    # equally well, and do transposed melodies fit the very same frames equally well?
    other_times = scores[np.abs(_LAGS - lag) > 0.45]
    wrong_pitch = max(
        float(chroma[indices[peak_index], (pitch + shift) % 12].mean()) for shift in range(1, 12)
    )
    score = float(scores[peak_index])
    contrast = score - float(np.percentile(other_times, 75))
    pitch_margin = score - wrong_pitch
    reliable = abs(lag) < 1.95 and score >= 0.42 and contrast >= 0.18 and pitch_margin >= 0.10
    detail.update(
        offset_s=round(float(lag), 3),
        peak_score=round(score, 3),
        score_at_zero=round(float(scores[len(_LAGS) // 2]), 3),
        timing_contrast=round(contrast, 3),
        pitch_margin=round(pitch_margin, 3),
        reliable=bool(reliable),
    )
    return detail


def _report(windows):
    reliable = [w for w in windows if w["reliable"]]
    shifted_regions = [
        name
        for name, w in zip(("inicio", "centro", "final"), windows)
        if w["reliable"]
        and abs(w["offset_s"]) >= 0.45
        and w["peak_score"] - w["score_at_zero"] >= 0.18
    ]
    if shifted_regions:
        status = "possible_shift"
        message = "Posible desfase en " + ", ".join("el " + name for name in shifted_regions) + "."
    elif len(reliable) == 3 and all(abs(w["offset_s"]) <= 0.25 for w in reliable):
        status = "no_large_shift_detected"
        message = "Sin indicios de un desfase grande en los tres tramos."
    else:
        status = "inconclusive"
        message = "La melodía no permite estimar con seguridad la sincronía de los tres tramos."
    if windows:
        offsets = [
            f"{w['offset_s']:+.2f}".replace(".", ",") + " s" if w["reliable"] else "?"
            for w in windows
        ]
        message += " Inicio / centro / final: " + " · ".join(offsets) + "."
    return {"status": status, "message": message, "windows": windows}


def analyze(chart: Path, audio: Path) -> dict:
    """Positive lag means recording later than notes. This diagnostic never edits a map."""
    deadline = time.monotonic() + _TIME_BUDGET
    try:
        text, meta = read_chart(chart)
        beat = 60 / (4 * float(meta["BPM"].replace(",", ".")))
        gap = float(meta.get("GAP", "0").replace(",", ".")) / 1000
        # Spoken/rap/freestyle notes carry no trustworthy pitch for this measurement.
        notes = []
        for match in re.finditer(r"^[:*]\s+(-?\d+)\s+(\d+)\s+(-?\d+)", text, re.M):
            start, length, pitch = map(int, match.groups())
            if length * beat >= 0.1 and 0 <= gap + start * beat <= _MAX_SECONDS:
                notes.append((gap + start * beat, length * beat, pitch % 12))
            if len(notes) > 50_000:
                return _report([])
        if not notes or meta["end_seconds"] > _MAX_SECONDS:
            return _report([])
        first = min(n[0] for n in notes)
        end = max(n[0] + n[1] for n in notes)
        width = min((end - first) / 3, _WINDOW)
        middle = (first + end) / 2
        intervals = [
            (first, first + width),
            (middle - width / 2, middle + width / 2),
            (end - width, end),
        ]
        windows = [_measure(notes, audio, lo, hi, deadline) for lo, hi in intervals]
        return _report(windows)
    except (OSError, SongError, ValueError, OverflowError, subprocess.SubprocessError):
        return _report([])
