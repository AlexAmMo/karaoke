import hashlib
import json
import tempfile
import time
from pathlib import Path

import pytest

from karaoke import allkaraoke, community_catalog
from karaoke.service import Service
from karaoke.songs import SongError

VIDEO = "IA0uSub1xy4"
ENTRY = {"id": "alex-ubago-sigo-aqui", "title": "Sigo Aquí", "artist": "Álex Ubago",
         "video": VIDEO, "duration": 4, "tracksCount": 1, "language": ["Spanish"]}
SONG = {"source": "allkaraoke:" + ENTRY["id"], "title": ENTRY["title"], "artist": ENTRY["artist"],
        "video_id": VIDEO, "reference_duration": 4, "language": "Spanish"}
CHART = (f"#TITLE:Sigo Aquí\n#ARTIST:Álex Ubago\n#BPM:120\n#GAP:0\n#VIDEO:v={VIDEO}\n"
         f"#ALLKARAOKE_ID:{ENTRY['id']}\n: 0 4 18 uno\n- 4\n: 8 4 20 dos\n- 12\n: 16 4 20 tres\nE\n")


def test_catalogue_pinned_identity_offline_and_accent_lookup(tmp_path, monkeypatch):
    payload = json.dumps([ENTRY]).encode()
    monkeypatch.setattr(allkaraoke, "INDEX_SHA", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(allkaraoke, "fetch", lambda *args: payload)
    hit, = allkaraoke.search("sigo aqui alex ubago", tmp_path)
    assert hit["video_id"] == VIDEO and hit["source"] == SONG["source"]
    allkaraoke._index.cache_clear()
    monkeypatch.setattr(allkaraoke, "fetch", lambda *args: pytest.fail("should use saved index"))
    assert allkaraoke.search("anything", tmp_path, VIDEO) == [hit]
    assert allkaraoke.search("otro", tmp_path) == []


def test_declared_video_title_and_duration_checked_before_review(package, tmp_path, monkeypatch):
    monkeypatch.setattr(allkaraoke, "fetch", lambda *args: CHART.encode())
    audio = package.with_name("audio.wav")
    for mismatch in ({"title": "Versión en directo"}, {"video_id": "abcdefghijk"},
                     {"reference_duration": 100}):
        with tempfile.TemporaryDirectory(dir=tmp_path) as out, pytest.raises(SongError):
            allkaraoke.prepare_review({**SONG, **mismatch}, Path(out), lambda _: None, audio)
    with tempfile.TemporaryDirectory(dir=tmp_path) as out:
        chart, recording = allkaraoke.prepare_review(SONG, Path(out), lambda _: None, audio)
        assert chart.read_text() == CHART and recording.read_bytes() == audio.read_bytes()


def test_grouped_federation_without_login_keeps_versions_and_blocks_unreviewed_queue(tmp_path, monkeypatch):
    assisted = {**SONG, "source": "community-es:fixture", "catalogue_url": "https://example.org"}
    monkeypatch.setattr(allkaraoke, "search", lambda *args: [SONG])
    monkeypatch.setattr(community_catalog, "search", lambda *args: [assisted])
    service = Service(tmp_path)
    try:
        service.search("alex ubago sigo aqui")
        deadline = time.monotonic() + 5
        while service.futures and time.monotonic() < deadline:
            service.tick()
        row, = [r for r in service.view()["rows"] if r["kind"] == "song"]
        assert row["action"].startswith("result:editions:") and not row["add_action"]
        service.handle({"action": row["action"]})
        row = next(r for r in service.view()["rows"] if "AllKaraoke" in r["sub"])
        service.handle({"action": row["action"]})
        actions = [r["action"] for r in service.view()["rows"] if "action" in r]
        assert any(a.startswith("result:recording:") for a in actions)
        with pytest.raises(SongError, match="Revisa"):
            service._request_song(SONG, True)
        assert not service.store.queue()
    finally:
        service.close()


def test_versions_page_reaches_later_maps_and_can_queue_saved_edition(tmp_path, package):
    from karaoke.songs import import_package

    service = Service(tmp_path / "app")
    try:
        service.results = [{"artist": "Fixture", "title": "Tema", "song_id": k} for k in range(1, 16)]
        saved = import_package(package, service.library)
        service.store.save_song(saved, "usdb:15")
        service.handle({"action": "result:editions:0:usdb:1"})
        rows = service.view()["rows"]
        assert len([r for r in rows if r["kind"] == "song"]) == 12
        service.handle({"action": "editions:next"})
        rows = [r for r in service.view()["rows"] if r["kind"] == "song"]
        assert len(rows) == 3 and rows[-1]["action"] == "song:" + saved["id"]
        service.handle({"action": rows[-1]["add_action"]})
        assert service.store.queue()[0]["song_id"] == saved["id"]
    finally:
        service.close()


@pytest.mark.parametrize("estimate_fails", [True, False])
def test_acoustic_estimate_is_advisory_and_retains_listening_checks(
    tmp_path, package, monkeypatch, estimate_fails
):
    from karaoke import acoustic

    def estimate(chart, audio):
        assert chart == package and audio == package.with_name("audio.wav")
        if estimate_fails:
            raise RuntimeError("decoder unavailable")
        return {"status": "possible_shift", "message": "Posible desfase en dos ventanas."}

    monkeypatch.setattr(acoustic, "analyze", estimate)
    monkeypatch.setattr(allkaraoke, "prepare_review",
                        lambda *args: (package, package.with_name("audio.wav")))
    service = Service(tmp_path / "app")
    try:
        service.page = "Versión"
        service.result_detail = SONG
        service.begin_catalogue_review(SONG, local=False)
        deadline = time.monotonic() + 3
        while service.review_busy and time.monotonic() < deadline:
            service.tick()
        assert service.page == "Asociar grabación"
        assert ("no disponible" if estimate_fails else "Posible desfase") in service.pair_analysis_note
        assert not service.pair_heard
        with pytest.raises(SongError, match="fragmentos"):
            service.handle({"action": "import:pair"})
        assert not service.store.queue()
    finally:
        service.close()
