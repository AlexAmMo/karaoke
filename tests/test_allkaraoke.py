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
    allkaraoke._current_index.cache_clear()
    monkeypatch.setattr(allkaraoke, "fetch", lambda *args: pytest.fail("should use saved index"))
    assert allkaraoke.search("anything", tmp_path, VIDEO) == [hit]
    assert allkaraoke.search("otro", tmp_path) == []


def test_verified_previous_index_survives_offline_upgrade_and_refreshes(tmp_path, monkeypatch):
    previous = json.dumps([ENTRY]).encode()
    added = {**ENTRY, "id": "new-chart", "title": "Nueva"}
    current = json.dumps([ENTRY, added]).encode()
    old_path = tmp_path / f"allkaraoke-{allkaraoke.PREVIOUS_REVISION}.json"
    old_path.write_bytes(previous)
    monkeypatch.setattr(allkaraoke, "PREVIOUS_SHA", hashlib.sha256(previous).hexdigest())
    monkeypatch.setattr(allkaraoke, "INDEX_SHA", hashlib.sha256(current).hexdigest())
    monkeypatch.setattr(allkaraoke.time, "monotonic", lambda: 0)
    attempts = []

    def fetch(*_):
        attempts.append(1)
        if len(attempts) == 1:
            raise allkaraoke.requests.ConnectionError("sin red")
        return current

    monkeypatch.setattr(allkaraoke, "fetch", fetch)
    assert allkaraoke.search("sigo aqui", tmp_path)
    assert not allkaraoke.search("nueva", tmp_path)
    assert len(attempts) == 1
    monkeypatch.setattr(allkaraoke.time, "monotonic", lambda: 301)
    assert allkaraoke.search("nueva", tmp_path)[0]["source"] == "allkaraoke:new-chart"
    assert len(attempts) == 2
    monkeypatch.setattr(allkaraoke.time, "monotonic", lambda: 601)
    monkeypatch.setattr(allkaraoke, "_verified_bytes", lambda *_: pytest.fail("reparsed current index"))
    assert allkaraoke.search("nueva", tmp_path)


def test_new_pin_or_different_video_can_reclaim_excluded_source():
    reviewed_pin = "e6ebb73648ea826702ef15be42255c6b2c2d3c03"
    row = {**ENTRY, "id": "gims-ciel", "video": "KG6ft_YDp5k"}
    assert not allkaraoke._songs(json.dumps([row]), reviewed_pin)
    assert allkaraoke._songs(json.dumps([row]), "future-pin")
    assert allkaraoke._songs(json.dumps([{**row, "video": VIDEO}]), reviewed_pin)


def test_offline_upgrade_rejects_tampered_previous_cache(tmp_path, monkeypatch):
    old = tmp_path / f"allkaraoke-{allkaraoke.PREVIOUS_REVISION}.json"
    old.write_text(json.dumps([ENTRY]))
    monkeypatch.setattr(allkaraoke.time, "monotonic", lambda: 1)

    attempts = []

    def offline(*_):
        attempts.append(1)
        raise allkaraoke.requests.ConnectionError("sin red")

    monkeypatch.setattr(allkaraoke, "fetch", offline)
    for query in ("sigo", "sigo aqui"):
        with pytest.raises(SongError, match="no está disponible"):
            allkaraoke.search(query, tmp_path)
    assert len(attempts) == 1


def test_declared_video_title_and_duration_checked_before_review(package, tmp_path, monkeypatch):
    monkeypatch.setattr(allkaraoke, "fetch", lambda *args: CHART.encode())
    audio = package.with_name("audio.wav")
    for mismatch in ({"title": "Versión en directo"}, {"video_id": "abcdefghijk"},
                     {"reference_duration": 100}):
        with tempfile.TemporaryDirectory(dir=tmp_path) as out, pytest.raises(SongError):
            allkaraoke.prepare_review({**SONG, **mismatch}, Path(out), lambda _: None, audio)
    with tempfile.TemporaryDirectory(dir=tmp_path) as out:
        chart, recording = allkaraoke.prepare_review(SONG, Path(out), lambda _: None, audio)
        assert chart.read_text(encoding="utf-8") == CHART and recording.read_bytes() == audio.read_bytes()


def test_grouped_federation_offers_one_click_for_exact_recording(tmp_path, monkeypatch):
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
        assert row["action"].startswith("result:detail:") and row["add_action"].startswith("result:best:")
        service.handle({"action": row["action"]})
        actions = {r.get("label"): r.get("action") for r in service.view()["rows"]}
        assert actions["Solo descargar"].startswith("result:save:")
        assert actions["Ver otras ediciones"].startswith("page:Ediciones")
        service.handle({"action": "page:Buscar"})
        service.handle({"action": row["add_action"]})
        turn, = service.store.queue()
        assert turn["source"] == "work:" + SONG["source"] and not turn["song_id"]
        payload = json.loads(turn["job_payload"])
        assert payload["song"]["source"] == SONG["source"] and payload["host_song"]["source"] == assisted["source"]
        assert service.page == "Buscar"
    finally:
        service.close()


def test_versions_page_reaches_later_maps_and_can_queue_saved_edition(tmp_path, package):
    from karaoke.songs import import_package

    service = Service(tmp_path / "app")
    try:
        service.results = [{"artist": "Fixture", "title": "Canción de prueba", "song_id": k} for k in range(1, 16)]
        saved = import_package(package, service.library)
        service.store.save_song(saved, "usdb:15")
        service.handle({"action": "result:editions:0:usdb:1"})
        first_page = [r for r in service.view()["rows"] if r["kind"] == "song"]
        assert len(first_page) == 12
        service.handle({"action": "editions:next"})
        second_page = [r for r in service.view()["rows"] if r["kind"] == "song"]
        assert len(second_page) == 3
        saved_row = next(r for r in first_page + second_page if r["action"] == "song:" + saved["id"])
        service.handle({"action": saved_row["add_action"]})
        assert service.store.queue()[0]["song_id"] == saved["id"]
    finally:
        service.close()


@pytest.mark.parametrize("status", ["possible_shift", "inconclusive", "no_large_shift_detected"])
def test_auto_preparation_only_publishes_when_audio_is_aligned(tmp_path, package, monkeypatch, status):
    from karaoke import acoustic

    monkeypatch.setattr(acoustic, "analyze", lambda *_: {"status": status,
        "windows": [{"reliable": True, "offset_s": offset} for offset in [0.05, -0.05, -0.1]]})
    monkeypatch.setattr(allkaraoke, "prepare_review",
                        lambda *args: (package, package.with_name("audio.wav")))
    service = Service(tmp_path / "app")
    try:
        service._request_song(SONG, True)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            service.tick()
            turn, = service.store.queue()
            if turn["preparation"] in ("ready","error"):
                break
            time.sleep(.01)
        assert bool(turn["song_id"]) == (status == "no_large_shift_detected")
        assert len(service.store.rows("SELECT id FROM songs")) == int(status == "no_large_shift_detected")
        if not turn["song_id"]:
            assert turn["preparation"] == "error"
            with pytest.raises(SongError, match="preparado"):
                service.start(turn["id"])
    finally:
        service.close()


def test_group_does_not_try_another_artist_or_mix_and_publishes_only_successful_map(
    tmp_path, package, monkeypatch
):
    from karaoke import acoustic

    primary = {**SONG, "source": "allkaraoke:a", "origin": "https://usdb.animux.de/index.php?link=gettxt&id=23"}
    compatible = {**SONG, "source": "allkaraoke:b"}
    wrong_cut = {**SONG, "source": "allkaraoke:c", "video_id": "00000000000"}
    wrong_artist = {**SONG, "source": "allkaraoke:d", "artist": "Otro artista"}
    duet = {**SONG, "source": "allkaraoke:e", "artist": "Álex Ubago feat. Invitado"}
    attempted = []
    def prepare(song, *args):
        attempted.append(song["source"])
        if song["source"] == primary["source"]:
            raise SongError("No disponible")
        return package, package.with_name("audio.wav")
    monkeypatch.setattr(allkaraoke, "prepare_review", prepare)
    monkeypatch.setattr(acoustic, "require_alignment", lambda *args: None)
    s = Service(tmp_path / "app")
    try:
        s.results = [primary, compatible, wrong_cut, wrong_artist, duet]
        s.add_best(primary)
        job, = s.store.rows("select * from jobs")
        assert [x["source"] for x in json.loads(job["payload"])["alternatives"]] == ["allkaraoke:b"]
        saved = s.prepare(job)
        s.store.finish_job(job, saved, saved["edition_source"])
        assert attempted == ["allkaraoke:a", "allkaraoke:b"]
        assert s.store.queue()[0]["song_id"] == saved["id"]
        aliases = {row["source"] for row in s.store.rows("select source from song_sources")}
        assert aliases == {job["source"], "allkaraoke:b"}
        s.add_best(primary)
        assert [turn["song_id"] for turn in s.store.queue()] == [saved["id"], saved["id"]]
        assert len(s.store.rows("SELECT id FROM jobs")) == 1
    finally:
        s.close()


def test_declared_cross_reference_refuses_other_usdb_recording_even_with_matching_title(
    tmp_path, package, monkeypatch
):
    s = Service(tmp_path / "app")
    try:
        fallback = {"artist": "Fixture", "title": "Canción de prueba", "song_id": 23}
        monkeypatch.setattr(s, "provider", lambda *args, **kw:
                            {"charts": [str(package)], "audio_resource": "WRONGVIDEO1"})
        with pytest.raises(SongError, match="otra grabación"):
            s.prepare_edition(fallback, "usdb:23", tmp_path, {"id": "job"}, {"exact_video": VIDEO})
        assert not list(s.library.iterdir())
    finally:
        s.close()


def test_available_search_groups_keep_languages_and_recordings_separate(tmp_path):
    s = Service(tmp_path)
    try:
        s.query = "mulan"
        title = "Tema"
        es = {"source": "community-es:chart", "artist": "Mulán", "title": title, "language": "Español"}
        fr = {**es, "source": "allkaraoke:fr", "language": "French", "video_id": VIDEO}
        direct = {**es, "source": "allkaraoke:live", "title": title + " (Live)", "video_id": VIDEO}
        unknown = {**es, "source": "community-eu:song", "language": ""}
        s.results = [unknown, es, fr, direct]
        rows = s.view()["rows"]
        songs = [r for r in rows if r["kind"] == "song"]
        assert [(r["label"], r["add_action"].split(":")[1] if r["add_action"] else None)
                for r in songs] == [(title, "obtain"), (title, "best"), (direct["title"], "best"), (title, None)]
        assert "Español" in songs[0]["sub"] and "French" in songs[1]["sub"]
        assert [r["label"] for r in rows][-2:] == ["Sin descarga integrada", title]
        s.handle({"action": songs[1]["add_action"]})
        assert s.store.queue()[0]["source"] == fr["source"]
        s.handle({"action": songs[-1]["action"]})
        assert all(not r.get("add_action") and not r.get("action", "").startswith(("result:open:", "result:queue:", "result:obtain:"))
                   for r in s.view()["rows"])
    finally:
        s.close()


def test_pasted_video_never_selects_a_name_only_spanish_chart(tmp_path):
    s = Service(tmp_path)
    try:
        s.query = "https://www.youtube.com/watch?v=" + VIDEO
        s.results = [{"source": "community-es:id", "artist": "Mulán", "title": "Tema"}]
        row, = [r for r in s.view()["rows"] if r["kind"] == "song"]
        assert not row["add_action"]
        with pytest.raises(SongError, match="solicitado"):
            s.handle({"action": "result:obtain:0:community-es:id"})
    finally:
        s.close()
