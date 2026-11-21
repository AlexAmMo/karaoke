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


def test_mobile_precision_and_volume_can_be_edited_by_different_guests(host):
    room = host.remote
    def save(guest, **changes):
        room.operate(guest, guest, "action", {"op": "settings", "changes": changes})

    assert room.state("Ana")["pitch_precision"] == 1
    save("Ana", pitch_precision=0)
    save("Luis", music=41)
    assert room.state("Luis")["pitch_precision"] == 0
    assert room.state("Ana")["music"] == 41
    with pytest.raises(RemoteError):
        save("Luis", pitch_precision=2, music=False)
    assert host.pitch_precision == 0
    with pytest.raises(RemoteError):
        save("Luis", pitch_precision=3)
    save("Luis", pitch_precision=2, music=60)
    assert host.pitch_precision == 2
    assert host.store.setting("music") == 60


def test_host_assistance_can_save_without_a_turn_and_survives_queue_changes(host):
    song = {"artist": "Película", "title": "Canción"}
    source = "host:espana:example"
    host.store.request_host(source, song, None)
    turn = host.store.request_host(source, song, ["Sol"], "guest:1")
    assert host.store.request_host(source, song, ["Sol"], "guest:1") == turn
    host.store.cancel_turn(turn)
    assert not host.store.queue()
    job, = host.independent_preparations()
    assert job["state"] == "host"
    assert host.store.accept_host_package(source, "spanish-package:example", {"song": song})
    job, = host.independent_preparations()
    assert job["state"] == "waiting" and not host.store.queue()
