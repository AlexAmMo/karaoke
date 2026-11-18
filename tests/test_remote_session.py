import pytest

from karaoke import allkaraoke, community_catalog
from karaoke.remote_server import RemoteError
from karaoke.service import Service


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


def test_search_and_queue_belong_to_different_scopes(host):
    host.fields["query"] = "sigo aquí"
    host.search("sigo aquí")
    room = host.remote
    ana = room.operate("a", "Ana", "search", {"q": "On the run"})["items"][0]
    luis = room.operate("l", "Luis", "search", {"q": "Melendi"})["items"][0]
    assert ana["title"] == "On the run" and luis["artist"] == "Melendi"
    assert host.query == "sigo aquí" and host.fields["query"] == "sigo aquí"

    add = {"op": "add", "id": ana["id"], "request_id": "song-1"}
    first = room.operate("a", "Ana", "action", add)
    assert room.operate("a", "Ana", "action", add) == first
    with pytest.raises(RemoteError):
        room.operate("l", "Luis", "action", add)  # Never consume another guest's selection.
    room.operate("l", "Luis", "search", {"q": "On the run"})
    second = room.operate("l", "Luis", "action", add)
    assert first["id"] != second["id"]
    assert len(host.store.rows("SELECT * FROM jobs")) == 1

    state = room.state("Ana")
    assert [t["names"] for t in state["queue"]] == [["Ana"], ["Luis"]]
    room.operate("l", "Luis", "action", {"op": "up", "id": second["id"], "revision": state["revision"]})
    with pytest.raises(RemoteError, match="cola ha cambiado"):
        room.operate("a", "Ana", "action", {"op": "remove", "id": first["id"], "revision": state["revision"]})
    assert [t["id"] for t in room.state("Ana")["queue"]] == [second["id"], first["id"]]


def test_host_assisted_package_keeps_queue_slots_and_ignores_removed_requests(host):
    room = host.remote
    item = room.operate("a", "Ana", "search", {"q": "Melendi"})["items"][0]["editions"][0]
    room.operate("l", "Luis", "search", {"q": "Melendi"})
    for client in ("a", "l"):
        room.operate(client, client, "action", {"op": "add", "id": item["id"], "request_id": "1"})
    rows = host.store.queue()
    assert [t["preparation"] for t in rows] == ["host", "host"]
    waiting = rows[0]["source"]
    host.handle({"action": "cancel:" + rows[0]["id"]})
    host.store.accept_host_package(waiting, "spanish-package:example", {"song": {"title": "Ejemplo"}})
    left, = host.store.queue()
    assert left["id"] == rows[1]["id"] and left["preparation"] == "waiting"
    assert left["source"] == "spanish-package:example"
    assert not host.store.rows("SELECT 1 FROM jobs WHERE state='host'")
    # A selection window still open when all guests withdraw can't resurrect a turn.
    assert not host.store.accept_host_package(waiting, "spanish-package:other", {})
    assert not host.store.rows("SELECT 1 FROM jobs WHERE source='spanish-package:other'")


def test_mobile_transport_targets_current_performance_and_cannot_delete_queued_audio(host, package):
    from karaoke.songs import SongError, import_package

    song = import_package(package, host.library)
    host.store.save_song(song)
    room = host.remote
    item = room.operate("a", "Ana", "library", {})["items"][0]
    turn_id = room.operate("a", "Ana", "action", {"op": "add", "id": item["id"], "request_id": "1"})["id"]
    with pytest.raises(SongError, match="Quita primero"):
        room.operate("a", "Ana", "action", {"op": "delete", "id": item["id"], "confirm": True})
    host.engine = {"state": "singing", "token": turn_id}
    host.active = turn_id
    calls = []
    host.command = lambda op, **params: calls.append((op, params))
    for op in ("pause", "resume", "end"):
        with pytest.raises(RemoteError):
            room.operate("a", "Ana", "action", {"op": op, "id": "old-performance"})
        room.operate("a", "Ana", "action", {"op": op, "id": turn_id})
    assert calls == [("set-paused", {"token": turn_id, "paused": True}),
                     ("set-paused", {"token": turn_id, "paused": False}),
                     ("end", {"token": turn_id})]
