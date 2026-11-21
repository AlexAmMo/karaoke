"""Digital silence must not become invented lyrics; no model or audio device is used."""

import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from karaoke import generation_worker as worker


def audio_modules(monkeypatch, samples, factory):
    soundfile = ModuleType("soundfile")
    soundfile.read = lambda *args, **kwargs: (samples, 16000)
    signal = ModuleType("scipy.signal")
    signal.resample_poly = lambda waveform, up, down: waveform.copy()
    scipy = ModuleType("scipy")
    scipy.signal = signal
    whisper = ModuleType("faster_whisper")
    whisper.WhisperModel = factory
    for name, module in (
        ("soundfile", soundfile), ("scipy", scipy),
        ("scipy.signal", signal), ("faster_whisper", whisper),
    ):
        monkeypatch.setitem(sys.modules, name, module)


@pytest.mark.parametrize("samples", [
    np.empty((0, 2), dtype=np.float32),
    np.zeros((16000, 2), dtype=np.float32),
    np.tile(np.array([0.25, -0.25], dtype=np.float32), (16000, 1)),
])
def test_empty_or_silent_mono_input_never_loads_recognizer(monkeypatch, samples):
    def forbidden_model(*args, **kwargs):
        pytest.fail("A recognizer must not invent lyrics from digital silence")

    audio_modules(monkeypatch, samples, forbidden_model)
    assert worker.transcribe("unused.wav", "unused-model", "auto") == ([], "auto")


def test_very_quiet_nonzero_audio_is_still_transcribed(monkeypatch):
    samples = np.full((16000, 1), 1e-9, dtype=np.float32)
    calls = []

    def recognize(waveform, **options):
        calls.append(waveform.copy())
        word = SimpleNamespace(word=" soft", start=0.1, end=0.3)
        return iter([SimpleNamespace(words=[word])]), SimpleNamespace(language="en")

    model = SimpleNamespace(transcribe=recognize)
    audio_modules(monkeypatch, samples, lambda *a, **kw: model)
    lines, language = worker.transcribe("unused.wav", "unused-model", "en")
    assert language == "en" and lines == [[{"word": "soft", "start": 0.1, "end": 0.3}]]
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0], samples[:, 0])


def test_skipping_silent_windows_preserves_absolute_word_clock(monkeypatch):
    samples = np.zeros((72 * 16000, 1), dtype=np.float32)
    samples[35 * 16000:36 * 16000] = 0.25
    calls = []

    def recognize(waveform, **options):
        calls.append(waveform.copy())
        assert waveform.any(), "A silent context window reached the recognizer"
        # The middle window begins at 21 s, including its three-second context.
        word = SimpleNamespace(word=" voice", start=14.0, end=15.0)
        return iter([SimpleNamespace(words=[word])]), SimpleNamespace(language="en")

    model = SimpleNamespace(transcribe=recognize)
    audio_modules(monkeypatch, samples, lambda *a, **kw: model)
    lines, language = worker.transcribe("unused.wav", "unused-model", "en", windowed=True)
    assert language == "en" and lines == [[{"word": "voice", "start": 35.0, "end": 36.0}]]
    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0], samples[21 * 16000:51 * 16000, 0])
