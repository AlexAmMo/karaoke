import io
import json

from karaoke.generation_assets.captions import manual_tracks, matching_lyrics

PHRASES = ("hoy viajamos bajo nubes", "vemos flores entre piedras", "vuelven luces sobre ríos")


def sample():
    events = [
        {"tStartMs": i * 10000, "dDurationMs": 2400, "segs": [{"utf8": line}]}
        for i, line in enumerate(PHRASES)
    ]
    info = {
        "id": "IA0uSub1xy4",
        "duration": 24,
        "subtitles": {"es": [{"ext": "json3", "url": "https://www.youtube.com/api/timedtext"}]},
    }
    transcript = [
        [{"word": w, "start": i * 10 + j * 0.45} for j, w in enumerate(line.split())]
        for i, line in enumerate(PHRASES)
    ]
    return info, lambda _: io.BytesIO(json.dumps({"events": events}).encode()), transcript


def test_authored_caption_needs_agreement_throughout_recording():
    info, fetch, transcript = sample()
    tracks = manual_tracks(info, "auto", fetch)
    text, evidence = matching_lyrics(tracks, transcript, "es")
    assert text.splitlines() == list(PHRASES)
    assert evidence["time_coverage"] == evidence["agreement"] == 1
    assert not matching_lyrics(tracks, transcript, "en")
    transcript[1][0]["word"] = "salimos"
    for word in transcript[2]:
        word["start"] += 7
    assert not matching_lyrics(tracks, transcript, "es")


def test_never_accept_machine_captions_or_an_unrelated_track():
    info, fetch, transcript = sample()
    info["automatic_captions"] = info.pop("subtitles")
    assert not manual_tracks(info, "auto", fetch)
    info["subtitles"] = info["automatic_captions"]
    tracks = manual_tracks(info, "es", fetch)
    for cue in tracks[0]["cues"]:
        cue[2] = "canta libre otra letra"
    assert not matching_lyrics(tracks, transcript, "es")
