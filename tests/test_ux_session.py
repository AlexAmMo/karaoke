"""Regression checks for interactions that share a running karaoke session."""
import threading
import subprocess
from unittest.mock import Mock, call

from karaoke.app import stop_engine
from karaoke.service import Service


def test_close_reaps_an_engine_stuck_in_a_native_dialog():
    engine, service = Mock(), Mock()
    engine.poll.return_value = None
    engine.wait.side_effect = [subprocess.TimeoutExpired("engine", 8), subprocess.TimeoutExpired("engine", 5), 0]

    stop_engine(engine, service)

    service.command.assert_called_once_with("quit")
    assert engine.method_calls == [
        call.poll(), call.wait(timeout=8), call.terminate(), call.wait(timeout=5), call.kill(), call.wait()
    ]


def test_latest_search_does_not_block_song_preparation(tmp_path, monkeypatch):
    service = Service(tmp_path)
    service.store.configure("username", "Test")
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_catalogue(operation, query, cursor=None):
        calls.append(query)
        if query == "Alex":
            started.set()
            assert release.wait(5)
        return {"songs": []}

    monkeypatch.setattr(service, "provider", slow_catalogue)
    monkeypatch.setattr(service, "search_indices", lambda _: None)
    try:
        service.search("Alex")
        assert started.wait(5)
        service.search("Alex Ubago")
        service.search("Alex Ubago Sigo Aquí")
        assert service.pool.submit(lambda: "libre").result(timeout=2) == "libre"
        assert service.futures[1][0].cancelled()
        release.set()
        service.futures[-1][0].result(timeout=4)
        service.tick()
        assert calls == ["Alex", "Alex Ubago Sigo Aquí"]
        assert not service.search_busy
    finally:
        release.set()
        service.close()


def test_playback_updates_the_library_once_per_transition(tmp_path):
    service = Service(tmp_path)
    try:
        service.active = "turn"
        service.store.execute(
            "INSERT INTO turns(id,source,names,position,state,created) VALUES (?,?,?,?,'starting',0)",
            ("turn", "local", '["Ana"]', 1),
        )
        service.engine = {"state": "singing", "token": "turn"}
        service.tick()
        changes = service.store.db.total_changes
        for _ in range(5):
            service.tick()
        assert service.store.db.total_changes == changes
        assert service.store.queue()[0]["state"] == "singing"
    finally:
        service.close()
