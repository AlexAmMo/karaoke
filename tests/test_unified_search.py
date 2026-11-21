from pathlib import Path

import pytest

from karaoke import allkaraoke, community_catalog
from karaoke.service import Service
from karaoke.songs import SongError, import_package


@pytest.fixture
def host(tmp_path, monkeypatch):
    app = Service(tmp_path / "host")
    monkeypatch.setattr(allkaraoke, "search", lambda *args: [])
    monkeypatch.setattr(community_catalog, "search", lambda *args: [])
    monkeypatch.setattr(app, "cover", lambda *args, **kwargs: {"path": ""})
    try:
        yield app
    finally:
        app.close()


def test_save_first_then_two_guests_join_one_job_and_undo_only_their_turn(host):
    room = host.remote
    def find(guest):
        return room.operate(guest, guest, "search", {"q": "On the run"})["items"][0]
    def act(guest, op, item, key, **more):
        return room.operate(guest, guest, "action", {"id": item, "op": op, "request_id": key, **more})
    first = find("Ana")
    assert first["availability"] == "direct"
    act("Ana", "save", first["id"], "save")
    assert not host.store.queue()
    assert find("Luis")["availability"] == "working"
    a = act("Ana", "add", first["id"], "one")["id"]
    b = act("Luis", "add", find("Luis")["id"], "two")["id"]
    assert a != b and len(host.store.rows("SELECT id FROM jobs")) == 1
    assert act("Ana", "add", first["id"], "one")["id"] == a
    act("Ana", "remove", a, "undo", revision=room.state("Ana")["revision"])
    assert [r["id"] for r in host.store.queue()] == [b]
    assert host.store.rows("SELECT state FROM jobs")[0]["state"] == "waiting"


def test_approved_generation_matches_only_its_exact_video_and_needs_no_network(host, package, monkeypatch):
    song = import_package(package, host.library)
    host.store.save_song(song)
    video = "01abCD34fgh"
    draft = host.lab.enqueue(video, song["title"], song["artist"], "es", "standard")
    host.store.execute("UPDATE drafts SET state='approved', song_id=? WHERE id=?", (song["id"],draft))
    monkeypatch.setattr(host, "search_indices", lambda _: None)
    host.search("https://youtu.be/" + video)
    host.results += [{"source": "allkaraoke:x", "video_id": video, "artist": "Fixture", "title": "Nombre alternativo"}]
    rows = host.view()["rows"]
    found = [r for r in rows if r["kind"] == "song"]
    assert len(found) == 1 and "Descargada" in found[0]["sub"]
    assert all(row.get("action") != "page:Generar" for row in rows)
    assert host.local_results("https://youtu.be/DIFFERENTid") == []
    host.handle({"action":found[0]["add_action"], "value":"tap"})
    assert host.store.queue()[0]["song_id"] == song["id"]
    turn = host.view()["undo"]
    host.handle({"action":"undo:" + turn})
    assert not host.store.queue()


def test_missing_audio_never_shows_start_and_saved_filter_works_offline(host, package, monkeypatch):
    song = import_package(package, host.library)
    host.store.save_song(song)
    host.handle({"action":"search:saved"})
    host.handle({"action":"field:query", "value":"Fixture"})
    assert not host.futures
    host.enqueue_song(song["id"])
    Path(song["audio"]).unlink()
    assert not any(row.get("kind") == "song" for row in host.view()["rows"])
    host.page="Cola"
    view = host.view()
    assert view["stage"]["action"].startswith("turn:")
    assert not any(row.get("action", "").startswith("start:") for row in view["rows"])
    assert host.remote.state("Ana")["queue"][0]["status"] == "missing"
    assert host.remote.operate("a", "Ana", "search", {"saved_only":True})["items"] == []
    with pytest.raises(SongError,match="Falta el mapa"):
        host.enqueue_song(song["id"])


def test_failed_preparation_is_identified_and_retry_does_not_reserve_a_turn(host):
    room = host.remote
    result = room.operate("a", "Ana", "search", {"q":"On the run"})["items"][0]
    room.operate("a", "Ana", "action", {"op":"save", "id":result["id"]})
    host.store.execute("UPDATE jobs SET state='error',message='No se pudo leer la grabación.'")
    assert room.operate("a", "Ana", "search", {"q":"On the run"})["items"][0]["availability"] == "failed"
    host.search("On the run")
    row = next(r for r in host.view()["rows"] if r["kind"] == "song")
    assert "Preparación fallida" in row["sub"] and not row["add_action"]
    host.handle({"action": row["action"]})
    retry = next(r for r in host.view()["rows"] if r["label"] == "Reintentar descarga")
    host.handle({"action": retry["action"]})
    assert not host.store.queue()
    assert host.store.rows("SELECT state FROM jobs") == [{"state":"waiting"}]
