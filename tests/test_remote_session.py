import json
import shutil

import pytest

from karaoke import allkaraoke, community_catalog
from karaoke.remote_server import RemoteError
from karaoke.service import Service
from karaoke.songs import SongError


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


def generated_replacement(host):
    source = "allkaraoke:replacement"
    song = {"title": "Prueba", "artist": "Artista", "video_id": "IA0uSub1xy4"}
    turn = host.store.request(source, {"kind": "allkaraoke", "song": song}, ["Ana"])
    singer = host.people.create("Ana")
    host.people.configure(singer, input_key="mobile:guest")
    host.people.set_voices(turn, [{"singer": singer, "input": "wire:fixture:0"}])
    host.store.execute("UPDATE jobs SET state='error' WHERE source=?", (source,))
    host.handle({"action": "lab:from-turn:" + turn})
    host.handle({"action": "lab:enqueue"})
    return turn, host.draft_id


def test_generated_turn_shows_progress_review_and_preserves_voices(host, package):
    turn, draft = generated_replacement(host)
    state = host.remote.state("Ana")
    item, = state["queue"]
    assert item["status"] == "waiting"
    assert item["message"] == "Pendiente de generar el mapa y la letra."
    voices, revision = item["voices"], state["revision"]
    for stage, message, expected_status, expected_message in [
        ("working", "Transcribiendo la letra", "working", "Transcribiendo la letra"),
        ("working", "En pausa mientras se canta", "working", "En pausa mientras se canta"),
        ("review", "Listo para revisar", "review", "Revisa la letra y las notas en el ordenador antes de cantar."),
    ]:
        host.store.execute("UPDATE drafts SET state=?,message=? WHERE id=?", (stage, message, draft))
        current = host.remote.state("Ana")
        item, = current["queue"]
        assert (item["status"], item["message"]) == (expected_status, expected_message)
        assert item["id"] == turn and item["names"] == ["Ana"] and item["voices"] == voices
        assert current["revision"] == revision  # Progress must not invalidate a pending reorder.
        with pytest.raises(SongError, match="todavía no está preparado"):
            host.remote.operate("a", "Ana", "action", {
                "op": "start", "id": turn, "revision": current["revision"],
            })
    shutil.copytree(package.parent, host.lab.root / draft / "draft")
    host.lab.approve(draft)
    current = host.remote.state("Ana")
    item, = current["queue"]
    assert item["status"] == "ready" and item["message"] == ""
    assert item["id"] == turn and item["voices"] == voices
    assert current["revision"] != revision


def test_stale_mobile_retry_cannot_restart_download_replaced_by_generation(host):
    turn, _ = generated_replacement(host)
    with pytest.raises(RemoteError, match="borrador"):
        host.remote.operate("a", "Ana", "action", {
            "op": "retry", "id": turn, "revision": host.remote.state("Ana")["revision"],
        })
    assert host.store.rows("SELECT state FROM jobs")[0]["state"] == "error"


@pytest.mark.parametrize("draft_state, expected_message", [
    ("working", "Generando el mapa y la letra"),
    ("error", "No se ha podido generar el borrador. Reintenta en el ordenador."),
    ("cancelled", "Generación cancelada. Puedes reanudarla en el ordenador."),
])
def test_generation_messages_explain_recovery_without_worker_diagnostics(host, draft_state, expected_message):
    turn, draft = generated_replacement(host)
    host.store.execute("UPDATE drafts SET state=?,message=? WHERE id=?",
                       (draft_state, "RuntimeError: decoder /local/models/example.bin", draft))
    item, = host.remote.state("Ana")["queue"]
    assert item["message"] == expected_message
    assert item["status"] == ("working" if draft_state == "working" else "host")
    host.page, host.turn_detail = "Turno", turn
    rows = host.view()["rows"]
    assert any(r.get("label") == expected_message for r in rows)
    assert "lab:detail:" + draft in {r.get("action") for r in rows}
    assert not any(r.get("action", "").startswith("retry:") for r in rows)


def test_generation_projection_is_only_for_linked_turn_and_matching_source(host):
    turn, _ = generated_replacement(host)
    original, = host.store.queue()
    other = host.store.request(original["source"], {"song": {"title": "Prueba"}}, ["Luis"])
    host.store.execute("UPDATE jobs SET state='error' WHERE source=?", (original["source"],))
    items = {t["id"]: t for t in host.remote.state("Ana")["queue"]}
    assert items[turn]["status"] == "waiting" and items[other]["status"] == "error"
    host.store.execute("UPDATE turns SET source='another-edition' WHERE id=?", (turn,))
    items = {t["id"]: t for t in host.remote.state("Ana")["queue"]}
    assert items[turn]["message"] == ""  # An old draft cannot describe a new edition.
    host.store.cancel_turn(turn)
    assert turn not in host.turn_generations()


def test_latest_requested_draft_controls_visible_progress(host):
    turn, first = generated_replacement(host)
    host.store.execute("UPDATE drafts SET state='review' WHERE id=?", (first,))
    host.store.configure("draft_profile", "standard")
    host.handle({"action": "lab:from-turn:" + turn})
    host.handle({"action": "lab:enqueue"})
    assert host.draft_id != first
    generation = host.turn_generations()[turn]
    assert generation["draft_id"] == host.draft_id and generation["status"] == "waiting"


def test_returning_to_existing_draft_updates_the_turns_current_request(host, package):
    turn, quality = generated_replacement(host)
    original = host.store.queue()[0]
    source = original["source"]
    another = host.store.request(source, json.loads(original["job_payload"]), ["Luis"])
    host.store.execute("UPDATE jobs SET state='error' WHERE source=?", (source,))
    host.store.execute("INSERT INTO draft_turns VALUES(?,?,?)", (quality, another, source))
    for profile in ("standard", "quality"):
        host.store.configure("draft_profile", profile)
        host.handle({"action": "lab:from-turn:" + turn})
        host.handle({"action": "lab:enqueue"})
        if profile == "standard":
            standard = host.draft_id
    assert host.draft_id == quality  # Enqueue reuses this still-pending generation.
    assert host.turn_generations()[turn]["draft_id"] == quality
    assert host.turn_generations()[another]["draft_id"] == quality
    # Approving a superseded draft may save it to the library, but cannot steal
    # the queued request from the draft the host most recently chose.
    shutil.copytree(package.parent, host.lab.root / standard / "draft")
    host.store.execute("UPDATE drafts SET state='review' WHERE id=?", (standard,))
    host.lab.approve(standard)
    assert all(row["song_id"] is None for row in host.store.queue())
    assert host.turn_generations()[turn]["draft_id"] == quality
