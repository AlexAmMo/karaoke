import json
import time
from pathlib import Path
import pytest
from karaoke.service import Service, atomic_json, youtube_id
from karaoke.songs import SongError


@pytest.fixture
def service(tmp_path, monkeypatch):
    from karaoke import allkaraoke, community_catalog
    monkeypatch.setattr(allkaraoke, "search", lambda *args: [])
    monkeypatch.setattr(community_catalog, "search", lambda *args: [])
    result = Service(tmp_path / "app")
    yield result
    result.close()


def wait(service, condition, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        service.tick()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError(service.view())


def test_import_queue_engine_handshake_and_manual_next_turn(service, package):
    service.add_import(str(package))
    wait(service, lambda: bool(service.store.rows("SELECT * FROM songs")))
    song = service.store.rows("SELECT * FROM songs")[0]
    first = service.store.request(song["id"], {}, ["Ana"])
    second = service.store.request(song["id"], {}, ["José"])
    service.engine = {"state": "idle"}
    service.start(first)
    commands = [
        json.loads(p.read_text(encoding="utf-8")) for p in (service.ipc / "commands").glob("*.json")
    ]
    start = next(c for c in commands if c["op"] == "start")
    assert start["names"] == ["Ana"]
    assert start["token"] == first
    atomic_json(
        service.ipc / "engine.json",
        {"state": "singing", "token": first, "scores": [100], "title": song["title"]},
    )
    service.tick()
    assert service.store.queue()[0]["state"] == "singing"
    assert service.message.startswith("Cantando.")
    atomic_json(
        service.ipc / "engine.json",
        {"state": "idle", "token": first, "scores": [2000], "title": song["title"]},
    )
    service.tick()
    assert service.active is None
    assert [(t["id"], t["state"]) for t in service.store.queue()] == [(second, "queued")]
    assert json.loads(
        service.store.rows("SELECT scores FROM turns WHERE id=?", (first,))[0]["scores"]
    ) == [2000]
    assert (
        len(
            [
                json.loads(p.read_text(encoding="utf-8"))
                for p in (service.ipc / "commands").glob("*.json")
                if json.loads(p.read_text(encoding="utf-8"))["op"] == "start"
            ]
        )
        == 1
    )


def test_failed_package_cannot_start(service, package):
    package.write_text(
        package.read_text(encoding="utf-8").replace("#MP3:audio.wav", "#MP3:missing.wav"),
        encoding="utf-8",
        newline="\n",
    )
    service.add_import(str(package.parent))
    wait(service, lambda: bool(service.store.rows("SELECT * FROM jobs WHERE state='error'")))
    assert service.store.rows("SELECT * FROM songs") == []
    job = service.store.rows("SELECT * FROM jobs")[0]
    turn = service.store.request(job["source"], {}, ["Ana"])
    with pytest.raises(SongError, match="preparado"):
        service.start(turn)


def test_cancelling_turn_keeps_library(service, package):
    service.add_import(str(package))
    wait(service, lambda: bool(service.store.rows("SELECT * FROM songs")))
    song = service.store.rows("SELECT * FROM songs")[0]
    turn = service.store.request(song["id"], {}, ["Ana"])
    service.handle({"action": "cancel:" + turn})
    assert service.store.queue() == []
    assert Path(song["chart"]).exists()


def test_mute_command_does_not_stop_capture_or_change_turn(service):
    service.handle({"action": "gain:0", "value": "0"})
    commands = [
        json.loads(p.read_text(encoding="utf-8")) for p in (service.ipc / "commands").glob("*.json")
    ]
    assert commands == [{"op": "gain", "player": 0, "value": 0.0}]
    assert service.store.setting("gain0") == 0


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://youtu.be/abcdefghijk", "abcdefghijk"),
        ("https://www.youtube.com/watch?v=abcdefghijk&t=3", "abcdefghijk"),
        ("https://youtube.com/shorts/abcdefghijk", "abcdefghijk"),
        ("https://youtube.com.evil.example/watch?v=abcdefghijk", None),
        ("https://youtube.com/watch?v=bad", None),
        ("file:///tmp/secret", None),
    ],
)
def test_youtube_identity_requires_exact_supported_host(url, expected):
    assert youtube_id(url) == expected


def test_native_commands_keep_order_when_windows_clock_does_not_advance(service, monkeypatch):
    import karaoke.service as service_module

    monkeypatch.setattr(service_module.time, "time_ns", lambda: 123456789)
    service.command("start", token="turn", chart="song.txt", names=["José"])
    service.command("gain", player=0, value=0.5)
    service.command("gain", player=1, value=0.1)
    service.command("music", value=60)
    commands = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((service.ipc / "commands").glob("*.json"))
    ]
    assert [command["op"] for command in commands] == ["start", "gain", "gain", "music"]
    assert commands[0]["names"] == ["José"]


def test_verified_instrumental_is_saved_automatically_as_a_separate_version(service, package, monkeypatch):
    from karaoke import acoustic, allkaraoke
    from karaoke.songs import import_package
    import shutil

    original = import_package(package, service.library)
    service.store.save_song(original)
    service.detail = original["id"]
    service.page = "Instrumental"
    service.candidates = [{"url": "https://youtu.be/abcdefghijk", "title": "Fixture instrumental"}]
    def fetch(song, folder, guard):
        path = folder / "different.wav"
        shutil.copyfile(original["audio"], path)
        return path
    verified = []
    monkeypatch.setattr(allkaraoke, "download_recording", fetch)
    monkeypatch.setattr(acoustic, "require_alignment", lambda *args: verified.append(args))
    service.handle({"action": "candidate:0"})
    wait(service, lambda: bool(service.store.rows("SELECT id FROM songs WHERE variant='instrumental'")))
    variant, = service.store.rows("SELECT * FROM songs WHERE variant='instrumental'")
    assert variant["parent"] == original["id"] and variant["verified"]
    assert verified and service.page == "Canción" and service.detail == variant["id"]


def test_ending_performance_requires_explicit_confirmation(service):
    service.engine = {"state": "singing"}
    service.handle({"action": "end"})
    assert service.page == "Terminar canción"
    assert list((service.ipc / "commands").glob("*.json")) == []
    service.handle({"action": "confirm-end"})
    commands = [
        json.loads(p.read_text(encoding="utf-8")) for p in (service.ipc / "commands").glob("*.json")
    ]
    assert commands == [{"op": "end"}]


@pytest.mark.parametrize("reserve_turn", [False, True])
def test_youtube_requires_exact_video_identity(service, reserve_turn):
    selected = {"song_id": 41, "title": "Tema", "artist": "Cantante", "requested_video": "abcdefghijk"}
    service.results = [selected]
    with pytest.raises(SongError, match="compatible"):
        service.request_result(0, reserve_turn)
    assert not service.store.queue() and not service.store.rows("SELECT id FROM jobs")


def test_obsolete_instrumental_completion_cannot_replace_the_active_selection(service, package, monkeypatch):
    from concurrent.futures import Future
    from karaoke.songs import import_package

    original = import_package(package, service.library)
    service.store.save_song(original)
    service.page, service.detail = "Instrumental", original["id"]
    service.candidates = [{"url": "https://youtu.be/abcdefghijk", "title": "Primera"}, {"url": "https://youtu.be/00000000000", "title": "Segunda"}]
    pending = []
    def deferred(_work):
        future = Future()
        pending.append(future)
        return future
    monkeypatch.setattr(service.pool, "submit", deferred)
    service.candidate(0)
    service.candidate(1)
    pending[0].set_exception(SongError("Stale download failure"))
    service.tick()
    assert service.message != "Stale download failure" and service.instrumental_busy
    pending[1].set_exception(SongError("No coincide"))
    service.tick()
    assert service.message == "No coincide" and not service.instrumental_busy
    assert len(service.store.rows("SELECT id FROM songs")) == 1


def test_open_catalogue_works_without_usdb_and_rejects_stale_selection(service):
    service.handle({"action": "page:Buscar"})
    songs = [r for r in service.view()["rows"] if r["kind"] == "song"]
    titles = {s["title"] for s in service.results}
    assert {"On the run", "Northern Star", "Code Monkey", "Verdächtig"} <= titles
    assert len(titles) == 39
    assert songs and len(songs) < len(titles)
    chosen = songs[0]
    service.handle({"action": chosen["add_action"]})
    assert service.store.queue()[0]["source"].startswith("deluxe:")
    service.search("Northern Star")
    with pytest.raises(SongError, match="búsqueda ha cambiado"):
        service.handle({"action": chosen["add_action"]})
    assert len(service.store.queue()) == 1
    rows = service.view()["rows"]
    assert [r["label"] for r in rows if r["kind"] == "song"] == ["Northern Star"]
    actions = {r.get("action") for r in rows}
    assert actions.isdisjoint({"external:es", "external:eu", "import:open", "search"})
    service.handle({"action": "page:Descargas"})
    assert "import:open" in {r.get("action") for r in service.view()["rows"]}
    service.handle({"action": "page:Otros catálogos"})
    assert {"external:es", "external:eu"} <= {r.get("action") for r in service.view()["rows"]}


def test_search_remote_pages_merge_without_duplicate_or_wrong_queue_item(service, monkeypatch):
    from time import monotonic, sleep

    service.store.configure("username", "fixture")
    examples = [{"song_id": i, "title": f"Canción {i}", "artist": "Artista"} for i in range(15)]

    def search(operation, query, cursor):
        assert operation == "search" and query == "Artista"
        return ({"songs": examples[:14], "next_cursor": {"0": 100}} if cursor is None
                else {"songs": examples[13:], "next_cursor": {}})

    monkeypatch.setattr(service, "provider", search)
    def finish():
        deadline = monotonic() + 4
        while service.search_busy and monotonic() < deadline:
            service.tick()
            sleep(0.01)
        assert not service.search_busy

    service.search("Artista")
    finish()
    rows = service.view()["rows"]
    assert len([r for r in rows if r["kind"] == "song"]) == 12
    first = next(r for r in rows if r["kind"] == "song")
    service.handle({"action": "search:next"})
    service.handle({"action": "search:more"})
    finish()
    assert len(service.results) == 15 and service.search_cursor is None
    service.handle({"action": first["add_action"]})
    assert service.store.queue()[0]["source"] == first["add_action"].split(":", 3)[-1]


@pytest.mark.parametrize("query,slug", [
    ("Melendi Caminando por la vida", "caminando-por-la-vida"),
    ("Fito & Fitipaldis - Soldadito marinero", "soldadito-marinero"),
    ("Hombres G Devuelveme a mi chica", "devuelveme-a-mi-chica"),
    ("Nino Bravo Libre", "libre"),
    ("Joan Manuel Serrat - Mediterraneo", "mediterraneo"),
    ("Nach Efectos vocales", "efectos-vocales"),
])
def test_spanish_search_offers_in_app_picker_without_an_account(service, query, slug, monkeypatch):
    from karaoke import catalog

    selected = []
    monkeypatch.setattr(service, "obtain_spanish", lambda item, token: selected.append((item, token)),
                        raising=False)
    service.search(query)
    pending, = [r for r in service.view()["rows"] if r["kind"] == "song"]
    assert not pending["add_action"] and "Comprobando ediciones" in pending["sub"]
    service.prefer_direct_until = 0
    assert next(r for r in service.view()["rows"] if r["kind"] == "song")["add_action"]
    wait(service, lambda: not service.futures)
    row, = [r for r in service.view()["rows"] if r["kind"] == "song"]
    assert "Elegir en UltraStar España" in row["sub"]
    assert row["add_action"] == f"result:obtain:{service.search_generation}:espana:{slug}"
    service.handle({"action": row["add_action"], "value": "first"})
    service.handle({"action": row["action"]})
    actions = {r["label"]: r.get("action") for r in service.view()["rows"]}
    assert actions["Obtener en Karaoke"] == row["add_action"]
    service.handle({"action": actions["Obtener en Karaoke"], "value": "second"})
    assert [(catalog.source_key(song), token) for song, token in selected] == [
        ("espana:" + slug, "first"), ("espana:" + slug, "second")
    ]
    assert not any((a or "").startswith(("external:", "result:open:")) for a in actions.values())
    assert service.store.queue() == [] and not service.view()["added_token"]


def test_open_package_keeps_complete_original_credits_after_staging_cleanup(service, package, monkeypatch):
    import shutil
    credits = "On the run\nJoshua Morin\nCC BY-SA 2.5\nOriginal credits preserved.\n".encode()
    source = "deluxe:on-the-run"
    song = next(x for x in service.results if x["source"] == source)
    service._request_song(song, False)
    job, = service.store.rows("SELECT * FROM jobs")

    def prepared(operation, *, key, destination):
        assert operation == "starter" and key == "on-the-run"
        target = Path(destination) / key
        shutil.copytree(package.parent, target)
        (target / "license.txt").write_bytes(credits)
        return {"charts": [str(target / package.name)]}

    monkeypatch.setattr(service, "provider", prepared)
    saved = service.prepare(job)
    assert Path(saved["chart"]).with_name("license.txt").read_bytes() == credits
    assert not (service.root / "downloads" / job["id"]).exists()


def test_queue_offers_first_ready_turn_while_earlier_download_is_blocked(service, package):
    from karaoke.songs import import_package

    pending = service.store.request("usdb:10", {"kind": "usdb", "song": {"title": "Pendiente"}}, service.names())
    service.store.execute("UPDATE jobs SET state='error', message='Grabación no disponible'")
    song = import_package(package, service.library)
    service.store.save_song(song)
    ready = service.store.request(song["id"], {}, service.names())
    service.handle({"action": "page:Cola"})
    rows = service.view()["rows"]
    assert rows[0]["action"] == "start:" + ready
    assert rows[0]["sub"] == song["title"]
    assert [t["id"] for t in service.store.queue()] == [pending, ready]
    service.handle({"action": "turn:" + pending})
    actions = {row.get("action", "") for row in service.view()["rows"]}
    assert any(action.startswith("retry:") for action in actions)
    assert "cancel:" + pending in actions


def test_first_run_search_and_single_singer_settings(service):
    assert service.page == "Buscar"
    service.handle({"action": "page:Ajustes"})
    def actions():
        return {row.get("action") for row in service.view()["rows"]}

    assert "gain:1" not in actions()
    assert {"page:Micrófonos", "page:Cuenta USDB", "page:Descargas"} <= actions()
    assert actions().isdisjoint({"login", "scan", "save-settings"})
    service.handle({"action": "field:player1", "value": "Lucía"})
    service.handle({"action": "field:player2", "value": "Juan"})
    assert service.store.setting("player1") == "Lucía"
    assert "gain:1" in actions()
    service.handle({"action": "page:Micrófonos"})
    assert "page:Entrada 2" in actions()


def test_host_secondary_workflow_device_directory_and_recovery(tmp_path, package):
    from karaoke.songs import import_package

    root = tmp_path / "session"
    service = Service(root)

    def act(action, value=""):
        service.handle({"action": action, "value": value})

    def actions():
        return {r.get("action") for r in service.view()["rows"]}

    try:
        assert service.page == "Buscar"
        act("page:Ajustes")
        act("field:player1", "Ángela")
        act("field:player2", "José")
        assert "gain:1" in actions()
        service.engine = {
            "state": "idle", "testing": True, "levels": [0.1, 0.7],
            "devices": [{"name": "USB", "channels": 2, "players": [1, 2], "index": 7}],
        }
        act("page:Micrófonos")
        assert {r["label"] for r in service.view()["rows"]} >= {"Señal de Ángela", "Señal de José"}
        act("page:Entrada 2")
        assert "device:1:7:1" in actions()
        act("device:1:7:1")
        command = json.loads(next((service.ipc / "commands").glob("*.json")).read_text())
        assert (command["player"], command["device"], command["channel"]) == (1, 7, 1)
        act("page:Descargas")
        future_library = tmp_path / "library"
        act("field:library", str(future_library))
        assert "save-settings" in actions()
        act("save-settings")
        assert service.library == future_library.resolve()
        act("page:Cuenta USDB")
        assert "login" in actions() and "logout" not in actions()
        act("page:Cola")
        assert "page:Buscar" in actions()

        failed = service.store.request(
            "usdb:7", {"kind": "usdb", "song": {"title": "Pendiente"}}, service.names()
        )
        service.store.execute("UPDATE jobs SET state='error',message='Recurso no disponible'")
        song = import_package(package, service.library)
        service.store.save_song(song)
        service.enqueue_song(song["id"])
        ready = service.store.queue()[1]["id"]
        assert "start:" + ready in actions()
        act("turn:" + failed)
        assert any(a and a.startswith("retry:") for a in actions())
        assert "down:" + failed in actions() and "up:" + failed not in actions()
        act("down:" + failed)
        assert service.store.queue()[0]["id"] == ready
        act("cancel:" + failed)
    finally:
        service.close()
    reopened = Service(root)
    try:
        assert reopened.page == "Biblioteca"
        assert reopened.names() == ["Ángela", "José"]
        assert reopened.library == future_library.resolve()
        assert [(turn["id"], turn["state"]) for turn in reopened.store.queue()] == [(ready, "queued")]
    finally:
        reopened.close()


def test_paste_spanish_publisher_search_preserves_exact_song_and_stays_in_karaoke(service, monkeypatch):
    from karaoke import community_catalog

    queries = []
    def search(query, _folder):
        queries.append(query)
        return [{"source": "community-es:mulan", "artist": "Mulán", "title": "Todo un hombre haré de ti"}]
    monkeypatch.setattr(community_catalog, "search", search)
    url = "https://ultrastar-es.org/es/canciones?artista=Mul%C3%A1n&cancion=Todo+un+hombre+har%C3%A9+de+ti"
    service.handle({"action": "field:query", "value": url})
    wait(service, lambda: not service.futures)
    assert queries == ["Mulán - Todo un hombre haré de ti"]
    field, row = service.view()["rows"]
    assert field["value"] == url and row["label"] == "Todo un hombre haré de ti"
    assert row["add_action"].endswith(":community-es:mulan")
    assert "Elegir en UltraStar España" in row["sub"]
