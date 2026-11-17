import concurrent.futures
import sys
import threading

import pytest

from karaoke.account import AccountChanged, SessionExpired
from karaoke.service import Service
from karaoke.songs import SongError


@pytest.fixture
def service(tmp_path):
    app = Service(tmp_path / "app")
    yield app
    app.close()


def test_search_and_download_share_a_login_and_refresh_once_on_concurrent_expiry(
    service, monkeypatch
):
    first_requests = threading.Barrier(2, timeout=4)
    retries = threading.Barrier(2, timeout=4)
    logins = []
    credentials_read = []

    def credentials():
        credentials_read.append(True)
        return {"username": "fixture", "password": "fixture-password"}

    def worker(op, **kwargs):
        if op == "login":
            assert kwargs["password"] == "fixture-password"
            logins.append(True)
            return {"cookies": [{"value": f"session-{len(logins)}"}]}
        assert "password" not in kwargs and "username" not in kwargs
        if kwargs["session_cookies"][0]["value"] == "session-1":
            first_requests.wait()
            raise SessionExpired("La sesión ha caducado.")
        retries.wait()
        return {"ok": op}

    monkeypatch.setattr(service, "credentials", credentials)
    monkeypatch.setattr(service, "_provider_worker", worker)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        work = [pool.submit(service.provider, op) for op in ("download", "search")]
        assert [f.result(10)["ok"] for f in work] == ["download", "search"]
    assert len(logins) == len(credentials_read) == 2


def test_logout_during_login_cannot_restore_an_old_account(service, monkeypatch):
    import keyring

    start, release = threading.Event(), threading.Event()
    stored = []

    def worker(op, **kwargs):
        start.set()
        assert release.wait(timeout=4)
        return {"cookies": [{"value": "old"}]}

    monkeypatch.setattr(service, "_provider_worker", worker)
    monkeypatch.setattr(keyring, "set_password", lambda *values: stored.append(values))
    service.fields.update(username="old", password="secret")
    service.handle({"action": "login"})
    assert start.wait(4)
    service.handle({"action": "logout"})
    release.set()
    service.futures[0][0].result(timeout=4)
    service.tick()
    assert service.account.cookies is None and not stored
    assert not service.store.setting("username", "")


def test_stale_operation_cannot_retry_as_new_account(service, monkeypatch):
    start, release = threading.Event(), threading.Event()

    def paused(op, **kwargs):
        if op == "login":
            return {"cookies": [{"value": "old"}]}
        start.set()
        assert release.wait(timeout=4)
        raise SessionExpired("caducada")

    monkeypatch.setattr(service, "_provider_worker", paused)
    monkeypatch.setattr(service, "credentials", lambda: {"username": "old", "password": "secret"})
    with concurrent.futures.ThreadPoolExecutor() as pool:
        old = pool.submit(service.provider, "details")
        assert start.wait(4)
        generation = service._change_account(pending=True)
        service.account.finish_change(generation, "new", ["new-session"])
        release.set()
        with pytest.raises(AccountChanged):
            old.result(4)
    assert service.account.cookies == ["new-session"]


def test_only_private_pipes_transport_authentication_material(service, monkeypatch, tmp_path):
    import karaoke.service as module

    script = tmp_path / "worker.py"
    script.write_text(
        "import json,sys\nfrom pathlib import Path\nr=json.load(sys.stdin)\n"
        'if r["operation"] == "login":\n'
        ' assert r["private_login"] and "response" not in r and "password" in r\n'
        ' print("KARAOKE_LOGIN "+json.dumps({"cookies":[{"value":"private-cookie-fixture"}]}))\n'
        "else:\n"
        ' assert "password" not in r and r["session_cookies"][0]["value"]=="private-cookie-fixture"\n'
        ' Path(r["response"]).write_text(json.dumps({"songs":[]}))\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "child_command", lambda _: [sys.executable, str(script)])
    monkeypatch.setattr(
        service, "credentials", lambda: {"username": "u", "password": "private-password-fixture"}
    )
    assert service.provider("search")["songs"] == []
    for file in service.root.rglob("*"):
        if file.is_file():
            contents = file.read_bytes()
            assert b"private-cookie-fixture" not in contents
            assert b"private-password-fixture" not in contents


def test_disconnected_account_keeps_open_catalogue(service):
    service.handle({"action": "logout"})
    with pytest.raises(SongError, match="Conecta"):
        service.provider("details", song_id=1)
    service.handle({"action": "page:Buscar"})
    displayed = [r for r in service.view()["rows"] if r["kind"] == "song"]
    assert displayed and all(":deluxe:" in row["action"] for row in displayed)
    assert len(service.results) == 39
