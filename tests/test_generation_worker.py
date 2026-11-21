"""Tests that do not download trained models or use network services during application CI."""

import numpy as np
import pytest

from karaoke import generation_worker as w


LYRICS = "Una nube cruza el valle y las hojas vuelan junto al viejo roble"


def row(**kwargs):
    return {
        "id": 10,
        "artistName": "María",
        "trackName": "El valle",
        "duration": 180,
        "plainLyrics": LYRICS,
        **kwargs,
    }


def test_text_lookup_requires_recording_and_ordered_content():
    assert (
        w.choose_candidate([row()], LYRICS, "Banda sonora (Maria)", "El valle", 179)[1]["id"] == 10
    )
    for mismatched in [
        row(duration=280),
        row(artistName="Segunda voz"),
        row(trackName="El valle (directo)"),
        row(plainLyrics=" ".join(reversed(LYRICS.split()))),
        row(instrumental=True),
        row(duration=float("nan")),
        row(plainLyrics=""),
        row(id="bad"),
    ]:
        assert w.choose_candidate([mismatched], LYRICS, "Maria", "El valle", 180) is None
    assert w.choose_candidate([row()], "una nube", "Maria", "El valle", 180) is None


def test_holds_continue_to_next_vowel_and_stop_at_vocal_rest():
    syllables = [
        {"line_index": 0, "syllable": "voz ", "start": 0.1, "end": 0.21},
        {"line_index": 1, "syllable": "sur ", "start": 3.0, "end": 3.3},
    ]
    events = [(0.11, 0.35, 62), (0.36, 1.5, 64), (2.3, 2.5, 65), (3.0, 3.3, 67)]
    pitch = {"times": np.arange(0, 4, 0.01), "frequencies": np.full(400, 300)}
    output = w.join_syllables_and_notes(syllables, events, pitch, 4)
    assert [(n["syllable"], n["pitch"]) for n in output] == [("voz", 62), ("~ ", 64), ("sur ", 67)]
    assert output[1]["end"] == 1.5
    chart = w.chart_text(output, "Mi título", "Artista\n#GAP:30", "es", 4)
    assert "#ARTIST:Artista #GAP:30\n" in chart
    assert "#MP3:audio.mp3" in chart
    assert ": 7 14 2 voz\n" in chart
    assert chart.endswith("E\n")


def test_uncertain_note_has_no_invented_frequency_and_remains_unscored():
    syllables = [{"line_index": 0, "syllable": "sol ", "start": 0.1, "end": 0.2}]
    pitch = {"times": np.arange(50) * 0.01, "frequencies": np.zeros(50)}
    notes = w.join_syllables_and_notes(syllables, [], pitch, 0.5)
    assert "F 6 6 0 sol " in w.chart_text(notes, "Title", "Artist", "es", 0.5)
    stats = w.acoustic_evidence(notes, pitch)
    assert stats["uncertain_notes"] == 1 and stats["pitch_consensus"] is None
    assert stats["review_regions"][0]["reasons"] == ["weak_vocal"]


def test_disagreement_is_localized_for_review():
    notes = [{"start": 0.1, "end": 0.8, "pitch": 60, "musical_support": 1}]
    f0 = {"times": np.arange(100) * 0.01, "frequencies": np.full(100, 440.0)}
    stats = w.acoustic_evidence(notes, f0)
    assert stats["pitch_consensus"] == 0
    assert stats["review_regions"] == [
        {"start": 0.1, "end": 0.8, "reasons": ["pitch_disagreement"]}
    ]
    with pytest.raises(ValueError, match="notas"):
        w.chart_text([], "title", "artist", "en", 100)
