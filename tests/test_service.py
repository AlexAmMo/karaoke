import json
import time
from pathlib import Path
import pytest
from karaoke.service import Service, atomic_json, youtube_id
from karaoke.songs import SongError


@pytest.fixture
def service(tmp_path):
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


def test_instrumental_is_a_separate_confirmed_variant(service, package, tmp_path):
    import subprocess

    service.add_import(str(package))
    wait(service, lambda: bool(service.store.rows("SELECT * FROM songs")))
    original = service.store.rows("SELECT * FROM songs")[0]
    original_text = Path(original["chart"]).read_bytes()
    mp3 = tmp_path / "instrumental.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", original["audio"], str(mp3)], check=True)
    service.detail = original["id"]
    service.candidate_audio = {
        "path": str(mp3),
        "song": original["id"],
        "source": "test:instrumental",
    }
    with pytest.raises(SongError, match="Preescucha"):
        service.confirm_instrumental()
    service.candidate_audio["listened"] = True
    service.confirm_instrumental()
    variants = service.store.rows("SELECT * FROM songs WHERE variant='instrumental'")
    assert len(variants) == 1
    assert variants[0]["parent"] == original["id"]
    assert variants[0]["verified"] == 1
    assert Path(original["chart"]).read_bytes() == original_text
    assert Path(variants[0]["chart"]).exists()


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
def test_youtube_version_confirmation_preserves_song_and_save_intent(service, reserve_turn):
    selected = {
        "song_id": 41,
        "title": "Chosen version",
        "artist": "Fixture",
        "requested_video": "abcdefghijk",
        "match": "Por comprobar",
    }
    service.results = [selected]
    service.request_result(0, reserve_turn)
    assert service.page == "Confirmar versión"
    rows = service.view()["rows"]
    assert any(row["label"] == "Chosen version" and row["sub"] == "Fixture" for row in rows)
    confirmation = next(row for row in rows if row.get("action") == "confirm-version")
    assert confirmation["label"] == (
        "Añadir esta versión a la cola" if reserve_turn else "Guardar esta versión"
    )
    assert service.store.queue() == []
    # A search result refresh must not change which version the host confirms.
    service.results = [{"song_id": 99, "title": "Different version", "artist": "Fixture"}]
    service.handle({"action": "confirm-version"})
    jobs = service.store.rows("SELECT * FROM jobs")
    assert len(jobs) == 1
    assert jobs[0]["source"] == "usdb:41"
    assert json.loads(jobs[0]["payload"])["song"]["title"] == "Chosen version"
    assert len(service.store.queue()) == int(reserve_turn)
    assert service.page == ("Cola" if reserve_turn else "Biblioteca")
    assert selected["requested_video"] == "abcdefghijk"


def test_leaving_version_confirmation_invalidates_pending_action(service):
    service.results = [{"song_id": 41, "title": "Fixture", "requested_video": "abcdefghijk"}]
    service.request_result(0, False)
    service.handle({"action": "page:Buscar"})
    with pytest.raises(SongError, match="seleccionar"):
        service.handle({"action": "confirm-version"})
    assert service.store.rows("SELECT * FROM jobs") == []


@pytest.mark.parametrize("late_failure", [False, True])
def test_instrumental_selection_discards_previous_audio_and_out_of_order_completion(
    service, package, monkeypatch, late_failure
):
    from concurrent.futures import Future
    from karaoke.songs import import_package

    original = import_package(package, service.library)
    service.store.save_song(original)
    service.detail = original["id"]
    service.candidates = [{"url": "test:candidate-a"}, {"url": "test:candidate-b"}]
    service.candidate_audio = {
        "path": "old.mp3",
        "source": "test:old",
        "song": original["id"],
        "listened": True,
    }
    pending = []

    def deferred(_work):
        future = Future()
        pending.append(future)
        return future

    monkeypatch.setattr(service.pool, "submit", deferred)
    service.candidate(0)
    assert service.candidate_audio is None
    with pytest.raises(SongError, match="Preescucha"):
        service.confirm_instrumental()
    service.candidate(1)
    selected_audio = {"path": "b.mp3", "source": "test:candidate-b", "song": original["id"]}
    pending[1].set_result(selected_audio)
    service.tick()
    assert service.candidate_audio == selected_audio
    message = service.message
    if late_failure:
        pending[0].set_exception(SongError("Stale download failure"))
    else:
        pending[0].set_result(
            {"path": "a.mp3", "source": "test:candidate-a", "song": original["id"]}
        )
    service.tick()
    assert service.candidate_audio == selected_audio
    assert service.message == message
    assert not service.candidate_audio.get("listened")


def test_open_catalogue_works_without_usdb_and_rejects_stale_selection(service):
    service.handle({"action": "page:Buscar"})
    songs = [r for r in service.view()["rows"] if r["kind"] == "song"]
    assert {r["label"] for r in songs} == {"On the run", "Northern Star"}
    chosen = songs[0]
    service.handle({"action": chosen["add_action"]})
    assert service.store.queue()[0]["source"].startswith("deluxe:")
    service.search("Northern Star")
    with pytest.raises(SongError, match="búsqueda ha cambiado"):
        service.handle({"action": chosen["add_action"]})
    assert len(service.store.queue()) == 1
    rows = service.view()["rows"]
    assert [r["label"] for r in rows if r["kind"] == "song"] == ["Northern Star"]
    assert {"external:es", "external:eu", "import:open"} <= {r.get("action") for r in rows}


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
def test_assisted_chart_search_opens_reviewed_entry_without_queue_or_account(
    service, query, slug, monkeypatch
):
    import webbrowser
    from karaoke import catalog
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    service.search(query)
    row, = [r for r in service.view()["rows"] if r["kind"] == "song"]
    assert not row["add_action"] and "Necesita importar" in row["sub"]
    service.handle({"action": row["action"]})
    actions = {r["label"]: r.get("action") for r in service.view()["rows"]}
    assert actions["Importar TXT, audio o ZIP"] == "import:open"
    assert "Añadir a la cola" not in actions
    service.handle({"action": actions["Abrir ficha"]})
    assert opened == [catalog.assisted_entry_url("espana:" + slug)]
    assert service.store.queue() == []
