#!/usr/bin/env python3
"""Exercise the complete app + real Deluxe process through its private JSON protocol.

Run after closing other development windows:
    uv run python scripts/test_session.py

This is an opt-in desktop integration test, not a unit test or a microphone test.
It opens the actual native window, uses only original generated test media and
injects A4/B4 into the engine's analysis path through the explicit --demo mode.
No UI automation, remote catalogue access or microphone capture is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def atomic_json(path: Path, value: dict):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return {}


class Session:
    def __init__(self, data: Path, launcher: list[str], environment: dict):
        self.data = data
        self.launcher = launcher
        self.environment = environment
        self.ipc = data / "ipc"
        self.process = None
        self.log = None
        self.launch_count = 0
        self.samples = []

    def launch(self):
        self.launch_count += 1
        self.log = (self.data / f"launcher-{self.launch_count}.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [*self.launcher, "--data-dir", str(self.data), "--demo"],
            cwd=ROOT,
            env=self.environment,
            stdout=self.log,
            stderr=self.log,
        )
        self.wait(lambda state: bool(state.get("synthetic")), timeout=45)

    def state(self):
        if self.process is not None and self.process.poll() is not None:
            raise AssertionError(
                f"Launcher exited unexpectedly: {self.process.returncode}; {self.data}"
            )
        value = read_json(self.ipc / "engine.json")
        if value:
            self.samples.append(
                {"at": round(time.monotonic(), 3), "launch": self.launch_count, **value}
            )
        return value

    def rows(self, sql: str, args=()):
        path = self.data / "library.sqlite3"
        if not path.exists():
            return []
        # Do not instantiate Store here: its crash recovery mutates live turns.
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(sql, args)]

    def queue(self):
        return self.rows(
            "SELECT * FROM turns WHERE state IN ('queued','starting','singing') ORDER BY position,created"
        )

    def wait(self, predicate, timeout=25):
        deadline = time.monotonic() + timeout
        last = {}
        while time.monotonic() < deadline:
            last = self.state()
            if predicate(last):
                return last
            time.sleep(0.08)
        raise AssertionError(
            f"Timed out. Engine: {last}; view: {read_json(self.ipc / 'view.json')}"
        )

    def event(self, action: str, value=""):
        atomic_json(
            self.ipc / "events" / (str(time.time_ns()) + "-" + uuid.uuid4().hex + ".json"),
            {"action": action, "value": str(value)},
        )

    def native(self, operation: str):
        atomic_json(self.ipc / "commands" / (str(time.time_ns()) + ".json"), {"op": operation})

    def enqueue(self, song_id: str):
        previous = {turn["id"] for turn in self.queue()}
        self.event("song:" + song_id)
        self.wait(lambda _: read_json(self.ipc / "view.json").get("page") == "Canción")
        self.event("enqueue")
        self.wait(lambda _: len({turn["id"] for turn in self.queue()} - previous) == 1)
        return next(turn["id"] for turn in self.queue() if turn["id"] not in previous)

    def close(self):
        if self.process and self.process.poll() is None:
            self.native("quit")
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
                    raise AssertionError("Launcher did not exit after native quit and terminate")
        if self.log:
            self.log.close()
            self.log = None
        return self.process.returncode if self.process else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--launcher",
        type=Path,
        help="Optional packaged Karaoke executable; defaults to the current Python interpreter",
    )
    parser.add_argument(
        "--engine", type=Path, help="Override the native engine executable for a source run"
    )
    parser.add_argument("--output", type=Path, default=ROOT / "docs/evidence/session-macos.json")
    args = parser.parse_args()
    data = Path(tempfile.mkdtemp(prefix="karaoke-session-"))
    environment = dict(os.environ)
    if args.engine:
        environment["KARAOKE_ENGINE"] = str(args.engine.resolve())
    launcher = (
        [str(args.launcher.resolve())] if args.launcher else [sys.executable, "-m", "karaoke.app"]
    )
    subprocess.run(
        [sys.executable, str(ROOT / "technical-spike/scripts/generate_fixtures.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    session = Session(data, launcher, environment)
    checks = []
    started = time.monotonic()
    result = {
        "scope": "Real desktop app and Deluxe, synthetic audio input. Not physical microphones, latency, live downloads, or visual/accessibility verification.",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "data_directory": str(data),
        "launcher_command": [*launcher, "--data-dir", str(data), "--demo"],
        "engine_override": environment.get("KARAOKE_ENGINE"),
        "path_environment": environment.get("PATH", ""),
        "checks": checks,
    }

    def check(name: str, condition: bool, evidence=None):
        item = {"name": name, "passed": bool(condition)}
        if evidence is not None:
            item["evidence"] = evidence
        checks.append(item)
        print(("PASS " if condition else "FAIL ") + name, flush=True)
        if not condition:
            raise AssertionError(name)

    try:
        session.launch()
        # Packaged apps need not ship test songs. Feed these original fixtures
        # through the same public import action used by the desktop interface.
        for relative in ("initial/A/song.txt", "staging/B/song.txt"):
            session.event("field:import", str(ROOT / "technical-spike/fixtures" / relative))
            session.event("import")
        session.wait(lambda _: len(session.rows("SELECT * FROM songs")) == 2)
        check(
            "Explicit synthetic demo is identified in both engine and interface",
            session.state().get("synthetic") is True
            and read_json(session.ipc / "view.json").get("synthetic") is True,
        )
        duplicate = subprocess.run(
            [*launcher, "--data-dir", str(data), "--demo"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=8,
        )
        check(
            "Second launcher cannot acquire the running session lock",
            duplicate.returncode == 1 and session.process.poll() is None,
            {"second_exit": duplicate.returncode, "message": duplicate.stderr.strip()},
        )
        songs = {song["title"]: song for song in session.rows("SELECT * FROM songs")}
        turn_a = session.enqueue(songs["Probe A"]["id"])
        turn_b = session.enqueue(songs["Probe B"]["id"])
        duplicate_b = session.enqueue(songs["Probe B"]["id"])
        check(
            "Three turns reuse two prepared packages",
            len(session.queue()) == 3 and len(session.rows("SELECT * FROM songs")) == 2,
        )
        session.event("music", "0")
        session.event("gain:0", "50")
        session.event("gain:1", "10")
        session.event("start:" + turn_a)
        state = session.wait(
            lambda s: (
                s.get("state") == "singing"
                and s.get("token") == turn_a
                and s.get("position", 0) > 2
                and s.get("monitor_peaks", [0])[0] > 3500
            )
        )
        score_before = state["scores"][0]
        check(
            "Real engine recognizes independent A and B pitch classes",
            [tone % 12 for tone in state["tones"][:2]] == [9, 11] and state["levels"][0] > 0.2,
            {"tones": state["tones"], "levels": state["levels"]},
        )
        check(
            "Per-player monitoring gains are independent",
            3500 <= state["monitor_peaks"][0] <= 4100 and 600 <= state["monitor_peaks"][1] <= 900,
            {"peaks": state["monitor_peaks"]},
        )
        session.event("gain:0", "0")
        muted = session.wait(
            lambda s: (
                s.get("state") == "singing"
                and s.get("monitor_peaks", [1])[0] == 0
                and s.get("scores", [0])[0] > score_before
            )
        )
        check(
            "Muting return preserves analysis and accumulating score",
            muted["levels"][0] > 0.2 and muted["scores"][0] > score_before,
            {
                "before": score_before,
                "after": muted["scores"][0],
                "level": muted["levels"][0],
                "monitor_peak": muted["monitor_peaks"][0],
            },
        )
        position_before = muted["position"]
        session.event("field:import", str(ROOT / "technical-spike/fixtures/staging/C/song.txt"))
        session.event("import")
        state = session.wait(
            lambda s: (
                len(session.rows("SELECT * FROM songs")) == 3
                and s.get("position", 0) > position_before + 0.3
            )
        )
        check(
            "Another package imports while the current song continues",
            state.get("state") == "singing"
            and state.get("token") == turn_a
            and state["position"] > position_before,
            {"before": position_before, "after": state["position"]},
        )
        song_c = session.rows("SELECT * FROM songs WHERE title='Probe C'")[0]
        turn_c = session.enqueue(song_c["id"])
        state = session.wait(
            lambda s: (
                s.get("state") == "idle"
                and session.rows("SELECT state FROM turns WHERE id=?", (turn_a,))[0]["state"]
                == "finished"
            )
        )
        check(
            "Engine produces independent final scores",
            state["scores"][0] > 1000 and state["scores"][1] < state["scores"][0] / 2,
            {"scores": state["scores"]},
        )
        idle_start = time.monotonic()
        session.wait(lambda s: time.monotonic() - idle_start > 1.2 and s.get("state") == "idle")
        check(
            "Results do not automatically start the next turn",
            [turn["id"] for turn in session.queue()] == [turn_b, duplicate_b, turn_c],
        )
        session.event("cancel:" + duplicate_b)
        session.wait(lambda _: [turn["id"] for turn in session.queue()] == [turn_b, turn_c])
        check(
            "Cancelling a repeated turn retains its library package",
            Path(songs["Probe B"]["chart"]).is_file(),
        )
        session.event("start:" + turn_b)
        session.wait(
            lambda s: (
                s.get("state") == "singing"
                and s.get("token") == turn_b
                and s.get("position", 0) > 1
            )
        )
        check(
            "Newly selected song starts without restarting the engine launcher",
            session.launch_count == 1,
        )
        exit_code = session.close()
        check(
            "Closing native game shuts down the main app", exit_code == 0, {"exit_code": exit_code}
        )
        from karaoke.app import instance_lock

        with instance_lock(data / "app.lock"):
            check("Main app releases its instance lock on close", True)
        session.launch()
        session.wait(
            lambda s: s.get("state") == "idle" and len(session.rows("SELECT * FROM songs")) == 3
        )
        restored = session.queue()
        check(
            "Interrupted turn and pending queue recover in original order",
            [(r["id"], r["state"]) for r in restored] == [(turn_b, "queued"), (turn_c, "queued")],
            [{"id": r["id"], "state": r["state"], "position": r["position"]} for r in restored],
        )
        idle_start = time.monotonic()
        state = session.wait(
            lambda s: time.monotonic() - idle_start > 1.2 and s.get("state") == "idle"
        )
        check(
            "Restoring a session never resumes playback automatically", state.get("token", "") == ""
        )
        session.event("start:" + turn_c)
        state = session.wait(
            lambda s: (
                s.get("state") == "singing"
                and s.get("token") == turn_c
                and s.get("position", 0) > 2
            )
        )
        check(
            "Host can explicitly skip to another ready turn",
            session.queue()[0]["id"] == turn_b
            and session.queue()[0]["state"] == "queued"
            and state["title"] == "Probe C",
        )
        check("Final close succeeds", session.close() == 0)
        result["passed"] = True
    except Exception as exc:
        checks.append({"name": "integration run completed", "passed": False, "error": str(exc)})
        result["passed"] = False
        print("FAIL " + str(exc), flush=True)
    finally:
        try:
            session.close()
        except Exception as exc:
            checks.append({"name": "cleanup", "passed": False, "error": str(exc)})
            result["passed"] = False
        result["elapsed_seconds"] = round(time.monotonic() - started, 2)
        result["samples"] = session.samples
        engine = args.engine
        if not engine:
            from karaoke.app import engine_path

            engine = engine_path()
        if engine.is_file():
            result["engine_sha256"] = hashlib.sha256(engine.read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print("EVIDENCE " + str(args.output.resolve()), flush=True)
        print("DATA " + str(data), flush=True)
    raise SystemExit(0 if result.get("passed") else 1)


if __name__ == "__main__":
    main()
