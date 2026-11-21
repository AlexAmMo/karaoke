#!/usr/bin/env python3
"""Validate each pitch setting against Deluxe scoring, with two synthetic singers.

uv run python scripts/test_pitch_precision.py [--launcher PATH] [--engine PATH]
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

from test_live_pitch import make_chart, pitch_at, set_tones
from test_session import Session, read_json


def check_input_dropout(session, song_id):
    turn = session.enqueue(song_id)
    session.event("start:" + turn)

    def position(seconds):
        return session.wait(
            lambda state: state.get("token") == turn
            and state.get("state") == "singing"
            and state["position"] >= seconds
        )

    position(0.2)
    set_tones(session, [440, 440])
    before = position(2.5)
    connected = position(3.5)
    for player in range(2):
        assert connected["scores"][player] > before["scores"][player]
    # Stop callbacks on the first input. The other mic keeps producing the same vowel.
    session.native("test-tone", player=0, connected=False)
    expired = position(4.25)
    later = position(5.75)
    assert later["scores"][0] == expired["scores"][0], (expired["scores"], later["scores"])
    assert later["tones"][0] == -1, later["tones"]
    assert later["scores"][1] > expired["scores"][1], (expired["scores"], later["scores"])
    # The first sample after the gap must not make the previous vowel fresh again.
    probe = session.ipc / "test-silent-frame.json"
    session.native("test-silent-frame", player=0)
    session.wait(lambda _: "pitch" in read_json(probe))
    assert read_json(probe)["pitch"] == -1, read_json(probe)
    session.native("test-tone", player=0, hz=440)
    resumed = position(7.25)
    assert resumed["scores"][0] > later["scores"][0], (later["scores"], resumed["scores"])
    print("PASS input dropout, sustained second singer, silent first frame and recovery", flush=True)


def check(launcher, engine):
    env = dict(os.environ, SDL_AUDIODRIVER="dummy", SDL_AUDIO_DRIVER="dummy")
    if engine:
        env["KARAOKE_ENGINE"] = str(engine.resolve())
    command = [str(launcher.resolve())] if launcher else [sys.executable, "-m", "karaoke.app"]
    with tempfile.TemporaryDirectory(prefix="karaoke-precision-") as scratch:
        root = Path(scratch)
        chart = make_chart(root)
        data = root / "data"
        data.mkdir()
        session = Session(data, command, env)
        try:
            session.launch()
            session.import_chart(chart)
            query = "SELECT id FROM songs WHERE title=?"
            session.wait(lambda _: session.rows(query, ("Guía de afinación",)))
            song_id = session.rows(query, ("Guía de afinación",))[0]["id"]

            # A fresh installation starts at normal. During each performance select
            # the next level, so the same checks detect a mid-phrase rule change.
            for level, next_level in ((1, 0), (0, 2), (2, 1)):
                turn = session.enqueue(song_id)
                session.event("start:" + turn)

                def position(seconds):
                    return session.wait(
                        lambda s: (
                            s.get("token") == turn
                            and s.get("state") == "singing"
                            and s["position"] >= seconds
                        )
                    )

                position(0.2)
                session.event(f"pitch:{next_level}")
                for offset in range(4):
                    # The fixture holds A4 from song seconds 2 through 9.
                    # One singer is sharp and the other equally flat.
                    start = 2.15 + offset * 1.65
                    position(start)
                    hz = [440 * 2 ** (n / 12) for n in (offset, -offset)]
                    set_tones(session, hz)
                    before = position(start + 0.6)
                    after = position(start + 1.4)
                    for player, frequency in enumerate(hz):
                        assert after["tones"][player] % 12 == pitch_at(frequency), (
                            level,
                            hz,
                            after,
                        )
                        gain = after["scores"][player] - before["scores"][player]
                        assert (gain > 0) == (offset <= 2 - level), (level, offset, player, gain)
                    print(f"PASS level {level}, ±{offset} semitones", flush=True)
                session.wait(
                    lambda _: session.rows(
                        "SELECT id FROM turns WHERE id=? AND state='finished'", (turn,)
                    )
                )
            check_input_dropout(session, song_id)
        finally:
            session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--engine", type=Path)
    args = parser.parse_args()
    check(args.launcher, args.engine)
