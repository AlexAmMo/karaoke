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
    commands = [json.loads(p.read_text()) for p in (service.ipc / "commands").glob("*.json")]
    start = next(c for c in commands if c["op"] == "start")
    assert start["names"] == ["Ana"]
    assert start["token"] == first
    atomic_json(
        service.ipc / "engine.json",
        {"state": "singing", "token": first, "scores": [100], "title": song["title"]},
    )
    service.tick()
    assert service.store.queue()[0]["state"] == "singing"
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
                json.loads(p.read_text())
                for p in (service.ipc / "commands").glob("*.json")
                if json.loads(p.read_text())["op"] == "start"
            ]
        )
        == 1
    )


def test_failed_package_cannot_start(service, package):
    package.write_text(package.read_text().replace("#MP3:audio.wav", "#MP3:missing.wav"))
    service.add_import(str(package))
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
    commands = [json.loads(p.read_text()) for p in (service.ipc / "commands").glob("*.json")]
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
