#!/usr/bin/env python3
"""Exercise the host's visible controls with a real catalogue and an isolated data directory."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from test_session import ROOT, Session, read_json


def run(launcher: Path, output: Path, check_remote_cover=False):
    report = {"passed": False, "checks": [], "input": "synthetic", "real_catalogue": True}
    chart = ROOT / "technical-spike/fixtures/staging/C/song.txt"
    if not chart.exists() or not any(chart.parent.glob("*.wav")):
        subprocess.run(
            [sys.executable, str(ROOT / "technical-spike/scripts/generate_fixtures.py")], check=True
        )
    started = time.monotonic()

    def check(name, assertion, **observations):
        report["checks"].append({"name": name, "passed": bool(assertion), **observations})
        if not assertion:
            raise AssertionError(name)

    with tempfile.TemporaryDirectory(prefix="karaoke-host-journey-") as temp:
        session = Session(
            Path(temp),
            [str(launcher.resolve())],
            {
                **os.environ,
                "SDL_AUDIO_DRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
                "SDL_WINDOW_ACTIVATE_WHEN_SHOWN": "0",
            },
        )
        view_path = session.ipc / "view.json"

        def page(name):
            session.event("page:" + name)
            session.wait(lambda _: read_json(view_path).get("page") == name)

        def row(predicate, timeout=15):
            session.wait(
                lambda _: any(predicate(r) for r in read_json(view_path).get("rows", [])),
                timeout=timeout,
            )
            return next(r for r in read_json(view_path)["rows"] if predicate(r))

        def click(action, value=""):
            control = row(lambda r: r.get("action") == action)
            session.event(control["action"], value)

        def add_result(title):
            song = row(lambda r: r.get("label") == title and r.get("add_action"), timeout=60)
            session.event(song["add_action"])

        def queue():
            return [r["id"] for r in session.queue()]

        def jobs_ready():
            failed = session.rows("SELECT message FROM jobs WHERE state='error'")
            if failed:
                raise RuntimeError(failed[0]["message"])
            return all(turn["song_id"] for turn in session.queue())

        def wait_turn_end(turn, timeout):
            session.wait(
                lambda _: bool(
                    session.rows("SELECT 1 FROM turns WHERE id=? AND state='finished'", (turn,))
                ),
                timeout=timeout,
            )

        try:
            session.launch()
            page("Ajustes")
            click("page:Cantantes")
            click("field:player1", "Ana")
            click("field:player2", "")
            click("page:Ajustes")
            click("music", "30")
            click("gain:0", "20")
            click("page:Micrófonos")
            click("testinput")
            session.wait(lambda s: s.get("testing"))
            click("testinput")
            session.wait(lambda s: not s.get("testing"))
            check("Configure one singer, backing volume, microphone return and input meter", True)
            page("Buscar")
            query = "Alex Ubago Sigo Aqui"
            click("field:query", query)
            row(lambda r: r.get("label") == "Sigo Aquí" and r.get("add_action"), timeout=60)
            rows = read_json(view_path)["rows"]
            check(
                "Typing a title produces one matching work without a submit or source button",
                sum(r.get("label") == "Sigo Aquí" for r in rows) == 1
                and all(
                    r.get("action") not in ("search", "external:es", "external:eu", "import:open")
                    for r in rows
                ),
                visible_controls=[r["kind"] for r in rows],
            )
            add_result("Sigo Aquí")
            session.wait(lambda _: len(queue()) == 1)
            first = queue()[0]
            session.wait(lambda _: jobs_ready(), timeout=180)
            saved = session.rows("SELECT id,source,verified FROM songs WHERE title='Sigo Aquí'")
            check(
                "One add action prepares the exact recording with no listening or edition step",
                len(saved) == 1
                and saved[0]["source"].startswith("allkaraoke:")
                and saved[0]["verified"] == 1
                and session.queue()[0]["song_id"] == saved[0]["id"],
                source=saved[0]["source"],
            )
            page("Cola")
            click("start:" + first)
            session.wait(lambda s: s.get("token") == first and s.get("position", 0) > 1.5)
            session.event("pause")
            time.sleep(0.8)
            paused = session.state()["position"]
            time.sleep(0.8)
            check("Pause holds playback position", abs(session.state()["position"] - paused) < 0.2)
            session.event("pause")
            session.wait(lambda s: s.get("position", 0) > paused + 0.4)
            session.native("panel", collapsed=True)
            session.wait(lambda s: s.get("panel_collapsed") and s.get("cursor_visible"))
            session.native("panel", collapsed=False)
            session.wait(lambda s: not s.get("panel_collapsed"))
            page("Buscar")
            click("field:query", "sigo aqui")
            cover_result = row(
                lambda r: (
                    r.get("label") == "Sigo Aquí"
                    and r.get("add_action")
                    and (not check_remote_cover or r.get("cover"))
                ),
                timeout=60,
            )
            check(
                "The result remains available with its cover or artist fallback after being queued",
                Path(cover_result["cover"]).is_file()
                if cover_result.get("cover")
                else bool(cover_result.get("artist")),
                album_cover_available=bool(cover_result["cover"]),
                artist=cover_result["artist"],
            )
            check(
                "Search while singing keeps the current recording playing",
                session.state().get("token") == first and session.state()["position"] > paused,
            )
            page("Descargas")
            click("import:open")
            click("field:import", str(chart))
            click("import")
            session.wait(lambda _: session.rows("SELECT id FROM songs WHERE title='Probe C'"))
            page("Buscar")
            click("field:query", "")
            click("search:saved")
            add_result("Probe C")
            add_result("Sigo Aquí")
            session.wait(lambda _: len(queue()) == 3)
            _, second, repeat = queue()
            page("Cola")
            click("turn:" + repeat)
            click("up:" + repeat)
            session.wait(lambda _: queue() == [first, repeat, second])
            click("cancel:" + repeat)
            session.wait(lambda _: queue() == [first, second])
            check(
                "Import, add a second song, reorder and remove a repeat while singing",
                session.state().get("token") == first,
            )
            wait_turn_end(first, 255)
            scores = json.loads(
                session.rows("SELECT scores FROM turns WHERE id=?", (first,))[0]["scores"]
            )
            check(
                "Full song reaches scores and returns to the session with next turn queued",
                len(scores) == 1 and scores[0] > 0 and queue() == [second],
                title="Sigo Aquí",
                scores=scores,
            )
            page("Cola")
            click("start:" + second)
            session.wait(lambda s: s.get("token") == second and s.get("position", 0) > 1)
            wait_turn_end(second, 45)
            check("Sing next turn and empty the queue", queue() == [])
            session.close()
            session.launch()
            check(
                "Reopen, retain prepared songs and stay idle",
                session.state()["state"] == "idle"
                and not queue()
                and bool(session.rows("SELECT 1 FROM songs WHERE id=?", (saved[0]["id"],))),
            )
            report["passed"] = True
        except Exception as exc:
            report["error"] = str(exc)[:1400]
            raise
        finally:
            session.close()
            report["elapsed_seconds"] = round(time.monotonic() - started, 2)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--check-remote-cover",
        action="store_true",
        help="Require real remote cover art for Sigo Aquí in this online run",
    )
    options = parser.parse_args()
    run(options.launcher, options.output, options.check_remote_cover)
