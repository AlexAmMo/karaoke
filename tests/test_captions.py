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


def test_spanish_spelling_recovers_authored_words_only_with_time_and_literal_anchors():
    singular = "nube campo roca canto monte rama valle brisa paso cielo puerto faro".split()
    heard = ["sol" + str(i) if i % 4 else singular[(i // 4) % 12] + "s" for i in range(90)]
    authored = [w[:-1] if i % 4 == 0 else w for i, w in enumerate(heard)]
    transcript = [[{"word": w, "start": i} for i, w in enumerate(heard)]]
    track = {
        "language": "es",
        "video_id": "IA0uSub1xy4",
        "cues": [[i - 0.1, i + 0.4, w] for i, w in enumerate(authored)],
    }
    text, proof = matching_lyrics([track], transcript, "es")
    assert text.splitlines() == authored and proof["agreement"] < 0.79
    assert proof["variant_agreement"] == proof["time_coverage"] == 1
    assert not matching_lyrics([{**track, "language": "en"}], transcript, "en")
    # Same words sung later in the bridge, and an alternate cut missing a verse.
    shifted = [
        [a + (6 if 30 <= i < 60 else 0), b + (6 if 30 <= i < 60 else 0), w]
        for i, (a, b, w) in enumerate(track["cues"])
    ]
    assert not matching_lyrics([{**track, "cues": shifted}], transcript, "es")
    assert not matching_lyrics([{**track, "cues": track["cues"][:60]}], transcript, "es")
    assert not matching_lyrics([track], [[{"word": "la", "start": i} for i in range(90)]], "es")
