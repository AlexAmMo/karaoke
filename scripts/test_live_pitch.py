#!/usr/bin/env python3
"""Verify live pitch on actual rendered frames, using isolated synthetic microphones.

uv run python scripts/test_live_pitch.py --launcher PATH_TO_KARAOKE --output build/pitch-qa
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from test_session import Session


def make_chart(path):
    # One phrase at eight beats per second with headroom above and below A4.
    with wave.open(str(path / "backing.wav"), "wb") as sound:
        sound.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
        sound.writeframes(bytes(44100 * 2 * 18))
    Image.new("RGB", (800, 600), (22, 25, 34)).save(path / "stage.jpg")
    chart = path / "phrase.txt"
    chart.write_text(
        "#TITLE:Guía de afinación\n#ARTIST:Karaoke\n#LANGUAGE:Spanish\n"
        "#MP3:backing.wav\n#BACKGROUND:stage.jpg\n#BPM:120\n#GAP:1000\n"
        ": 0 6 15 Can\n: 8 56 21 ta \n: 80 16 23 así\nE\n",
        encoding="utf-8",
    )
    return chart


def screenshot(session, output, name, number):
    session.native("test-screenshot")
    target = session.ipc / f"screenshot{number:04d}.jpg"

    def complete(_):
        if target.exists():
            with target.open("rb") as image:
                if image.seek(0, 2) >= 2:
                    image.seek(-2, 2)
                    return image.read() == b"\xff\xd9"
        return False

    session.wait(complete, timeout=8)
    copy = output / (name + ".jpg")
    shutil.copyfile(target, copy)
    return copy


def pitch_at(frequency):
    return round(69 + 12 * np.log2(frequency / 440)) % 12


def set_tones(session, frequencies):
    for player, hz in enumerate(frequencies):
        session.native("test-tone", player=player, hz=hz)


def verify_frames(before, after, state, players):
    """Compare strips inside the staff, excluding note edges and pitch transitions."""

    def crop_stage(frame):
        with Image.open(frame) as image:
            width, height = image.size
            assert state["panel_collapsed"], "Reference geometry expects a collapsed panel"
            assert (width, height) == (state["drawable_width"], state["drawable_height"])
            stage_width = min(width, round(height * 4 / 3))
            stage_height = min(height, round(stage_width * 3 / 4))
            left, top = (width - stage_width) // 2, (height - stage_height) // 2
            stage = image.crop((left, top, left + stage_width, top + stage_height))
            return np.asarray(stage.resize((800, 600), Image.Resampling.BOX), dtype=np.int16)

    difference = np.abs(crop_stage(after) - crop_stage(before)).max(axis=2)
    checks = []
    for player in range(players):
        bottom = 250 if players == 2 and player == 0 else 430
        target_y = bottom - (21 - 15) * 7.5
        # Intervals lie well inside each tone's steady state. A sampled rest
        # occupies beats 64..80, between the long target and the final note.
        for label, beat, offset in [
            ("high", 18, 3),
            ("low", 32, -3),
            ("silence", 45, None),
            ("hit", 57, 0),
            ("rest", 73, 3),
        ]:
            if player == 1 and offset:
                offset = -offset
            x = round(40 + 720 * beat / 96)
            strip = difference[:, x - 5 : x + 6]
            if offset is None:
                delta = float(
                    np.max(np.median(strip[round(target_y) - 28 : round(target_y) + 29], axis=1))
                )
                passed = delta < 22
            else:
                y = round(target_y - 7.5 * offset)
                delta = float(np.max(np.median(strip[y - 3 : y + 4], axis=1)))
                passed = delta > 26
            checks.append(
                {"singer": player + 1, "interval": label, "pixel_change": delta, "passed": passed}
            )
    return checks


def run(launcher, engine, output, players):
    environment = dict(os.environ, SDL_AUDIODRIVER="dummy", SDL_AUDIO_DRIVER="dummy")
    environment["SDL_WINDOW_ACTIVATE_WHEN_SHOWN"] = "0"
    if engine:
        environment["KARAOKE_ENGINE"] = str(engine.resolve())
    command = [str(launcher.resolve())] if launcher else [sys.executable, "-m", "karaoke.app"]
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="karaoke-pitch-") as scratch:
        root = Path(scratch)
        chart = make_chart(root)
        data = root / "data"
        data.mkdir()
        session = Session(data, command + ["--window-size", "1280x800"], environment)
        try:
            session.launch()
            session.native("panel", collapsed=True)
            session.native(
                "start", chart=str(chart), token="pitch-test", names=["Voz 1", "Voz 2"][:players]
            )
            session.wait(lambda s: s.get("token") == "pitch-test" and s.get("state") == "singing")
            set_tones(session, [0] * players)

            def position(seconds):
                return session.wait(
                    lambda s: s.get("state") == "singing" and s["position"] >= seconds
                )

            position(1.2)
            before = screenshot(session, output, f"{players}-silence", 1)
            samples = []
            for seconds, hz1, hz2 in [
                (2, 523.251, 369.994),
                (4, 369.994, 523.251),
                (6, 0, 0),
                (7.3, 440, 440),
                (9.1, 523.251, 369.994),
            ]:
                position(seconds)
                frequencies = [hz1, hz2][:players]
                set_tones(session, frequencies)
                state = position(seconds + 0.8)
                for i, hz in enumerate(frequencies):
                    if hz:
                        assert state["tones"][i] % 12 == pitch_at(hz), (hz, state["tones"])
                    else:
                        assert state["levels"][i] < 0.01, state["levels"]
                samples.append(
                    {
                        "frequencies_hz": frequencies,
                        "song_seconds": state["position"],
                        "tones": state["tones"][:players],
                        "scores": state["scores"],
                    }
                )
            state = position(10.85)
            after = screenshot(session, output, f"{players}-pitch", 2)
            checks = verify_frames(before, after, state, players)
            checks.append(
                {
                    "check": "points only during the matched note",
                    "passed": all(score == 0 for s in samples[:3] for score in s["scores"])
                    and all(score > 0 for score in samples[-1]["scores"]),
                }
            )
            return {
                "players": players,
                "samples": samples,
                "checks": checks,
                "passed": all(c["passed"] for c in checks),
            }
        finally:
            session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--players", type=int, nargs="+", choices=(1, 2), default=(1, 2))
    args = parser.parse_args()
    results = [run(args.launcher, args.engine, args.output, players) for players in args.players]
    report = {
        "passed": all(result["passed"] for result in results),
        "input": "synthetic PCM",
        "runs": results,
    }
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["passed"] else 1)
