import shutil
import wave

import numpy as np
import pytest

from karaoke.acoustic import analyze


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="El análisis necesita ffmpeg")
@pytest.mark.parametrize(
    ("offset", "audio_kind", "expected"),
    [
        (0.0, "melody", "no_large_shift_detected"),
        (0.9, "melody", "possible_shift"),
        (0.9, "late_edit", "possible_shift"),
        (0.0, "silence", "inconclusive"),
        (0.0, "drone", "inconclusive"),
    ],
)
def test_recording_offsets_and_inconclusive_audio(tmp_path, offset, audio_kind, expected):
    rate = 11025
    beat = 0.125
    pitches = np.random.default_rng(31).integers(0, 12, size=100)
    signal = np.zeros(58 * rate)
    lines = ["#TITLE:Sync diagnostic", "#ARTIST:Fixture", "#GAP:0", "#BPM:120"]
    for index, pitch in enumerate(pitches):
        tick = 24 + 4 * index
        lines.append(f": {tick} 3 {pitch} la")
        local_offset = 0 if audio_kind == "late_edit" and index < 65 else offset
        start = round((tick * beat + local_offset) * rate)
        size = round(3 * beat * rate)
        if audio_kind in {"melody", "late_edit"}:
            freq = 440 * 2 ** ((60 + pitch - 69) / 12)
            t = np.arange(size) / rate
            signal[start : start + size] = (
                np.sin(2 * np.pi * freq * t) + 0.26 * np.sin(4 * np.pi * freq * t)
            ) * np.hanning(size)
    if audio_kind == "drone":
        signal = np.sin(2 * np.pi * 261.63 * np.arange(len(signal)) / rate)
    chart = tmp_path / "chart.txt"
    chart.write_text("\n".join([*lines, "E"]), encoding="utf-8")
    original = chart.read_bytes()
    audio = tmp_path / "recording.wav"
    with wave.open(str(audio), "wb") as writer:
        writer.setparams((1, 2, rate, len(signal), "NONE", "not compressed"))
        writer.writeframes((signal * 16000).astype("<i2").tobytes())

    result = analyze(chart, audio)
    assert chart.read_bytes() == original
    assert result["status"] == expected
    assert len(result["windows"]) == 3
    if audio_kind in {"melody", "late_edit"}:
        for i, segment in enumerate(result["windows"]):
            expected_offset = 0 if audio_kind == "late_edit" and i < 2 else offset
            assert segment["reliable"]
            assert abs(segment["offset_s"] - expected_offset) <= 0.17
        if audio_kind == "late_edit":
            assert "Posible desfase en el final" in result["message"]
    else:
        assert not any(w["reliable"] for w in result["windows"])
