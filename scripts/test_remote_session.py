#!/usr/bin/env python3
"""Run two authenticated LAN controllers against a disposable packaged karaoke session."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import time
import uuid

import requests

from test_session import ROOT, Session, read_json


def wait(read, check, seconds=15):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        result = read()
        if check(result):
            return result
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for the mobile session")


class Phone:
    def __init__(self, address):
        self.url = address.rstrip("/")
        self.http = requests.Session()
        self.http.trust_env = False
        self.http.headers["Origin"] = self.url

    def post(self, operation, **data):
        response = self.http.post(f"{self.url}/api/{operation}", json=data, timeout=8)
        if not response.ok:
            raise AssertionError(
                f"{operation} returned {response.status_code}: {response.text[:160]}"
            )
        return response.json()

    def action(self, action, **data):
        return self.post("action", op=action, request_id=uuid.uuid4().hex, **data)


def check(launcher, data):
    environment = dict(os.environ, SDL_AUDIODRIVER="dummy", SDL_AUDIO_DRIVER="dummy")
    # A chance outage in an external catalogue must not disable party controls.
    environment.update(HTTPS_PROXY="http://127.0.0.1:1", HTTP_PROXY="http://127.0.0.1:1")
    command = [str(launcher.resolve())] if launcher else [sys.executable, "-m", "karaoke.app"]
    session = Session(data, command, environment)
    try:
        session.launch()
        for label, chart in (("A", "initial/A"), ("B", "staging/B")):
            session.import_chart(ROOT / f"technical-spike/fixtures/{chart}/song.txt")
            session.wait(
                lambda _: session.rows("SELECT 1 FROM songs WHERE title=?", ("Probe " + label,))
            )
        session.event("page:Ajustes")
        session.event("remote:start")

        def view():
            return read_json(session.ipc / "view.json")

        pair = wait(view, lambda v: any(r["kind"] == "qr" for r in v.get("rows", [])))
        assert Path(next(r["path"] for r in pair["rows"] if r["kind"] == "qr")).is_file()
        instructions = " ".join(str(r.get(k, "")) for r in pair["rows"] for k in ("label", "sub"))
        url = re.search(r"http://[\d.]+:\d+", instructions).group()
        code = re.search(r"(?<!\d)\d{6}(?!\d)", instructions).group()
        ana, luis = Phone(url), Phone(url)
        for phone, name in ((ana, "Ana"), (luis, "Luis")):
            assert phone.http.get(url + "/", timeout=4).ok
            phone.post("join", name=name, code=code)
        session.event("page:Biblioteca")
        wait(view, lambda v: v.get("page") == "Buscar" and any(r.get("style") == "checked" for r in v["rows"]))
        with ThreadPoolExecutor(2) as pool:
            results = list(
                pool.map(
                    lambda args: args[0].post("search", q=args[1]),
                    ((ana, "Probe A"), (luis, "Probe B")),
                )
            )
        selected = [
            next(row["id"] for row in result["items"] if row["title"] == title)
            for result, title in zip(results, ("Probe A", "Probe B"))
        ]
        assert view()["page"] == "Buscar"
        retry = dict(op="add", id=selected[0], names=["Ana"], request_id=uuid.uuid4().hex)
        ana.post("action", **retry)
        ana.post("action", **retry)
        luis.action("add", id=selected[1], names=["Luis"])
        state = ana.post("state")
        first, second = state["queue"]
        assert [row["names"] for row in state["queue"]] == [["Ana"], ["Luis"]]
        luis.action("up", id=second["id"], revision=state["revision"])
        assert ana.post("state")["queue"][0]["id"] == second["id"]
        revision = ana.post("state")["revision"]
        ana.action("start", id=second["id"], revision=revision)
        session.wait(lambda s: s.get("token") == second["id"] and s.get("position", 0) > 0.2)
        for operation, flag in (("pause", True), ("resume", False)):
            luis.action(operation, id=second["id"], revision=luis.post("state")["revision"])
            session.wait(lambda s: s.get("paused") is flag)
        ana.action("end", id=second["id"], revision=ana.post("state")["revision"], confirmed=True)
        session.wait(lambda s: s.get("state") == "idle")
        state = wait(lambda: ana.post("state"), lambda v: len(v["queue"]) == 1)
        ana.action("remove", id=first["id"], revision=state["revision"])
        assert not luis.post("state")["queue"]
        session.event("remote:stop")
        wait(view, lambda v: v.get("page") == "Móviles" and not any(r["kind"] == "qr" for r in v.get("rows", [])))
        try:
            ana.http.post(url + "/api/state", json={}, timeout=2).raise_for_status()
        except requests.RequestException:
            pass
        else:
            raise AssertionError("A closed room still accepts commands")
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path)
    args = parser.parse_args()
    if not (ROOT / "technical-spike/fixtures/initial/A/tone.wav").is_file():
        subprocess.run(
            [sys.executable, str(ROOT / "technical-spike/scripts/generate_fixtures.py")], check=True
        )
    with tempfile.TemporaryDirectory(prefix="karaoke-remotes-") as scratch:
        check(args.launcher, Path(scratch))
    print("PASS: two controllers, separate searches, queue, playback, retries and closed room")
