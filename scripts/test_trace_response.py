#!/usr/bin/env python3
"""Measure the onset of a visible, confirmed pitch from injected PCM in Deluxe's real renderer."""

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import wave

from test_live_pitch import make_chart
from test_session import Session


def run(engine, output, launcher=None):
    env = dict(
        os.environ,
        SDL_AUDIODRIVER="dummy",
        SDL_AUDIO_DRIVER="dummy",
    )
    if engine:
        env["KARAOKE_ENGINE"] = str(engine.resolve())
    command = [str(launcher.resolve())] if launcher else [sys.executable, "-m", "karaoke.app"]
    with tempfile.TemporaryDirectory(prefix="karaoke-trace-") as scratch:
        directory = Path(scratch)
        chart = make_chart(directory)
        chart.write_text(
            "#TITLE:Registro vocal\n#ARTIST:Karaoke\n#MP3:backing.wav\n#BPM:120\n#GAP:500\n: 0 448 21 La\nE\n",
            encoding="utf-8",
        )
        with wave.open(str(directory / "backing.wav"), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(bytes(8000 * 2 * 60))
        data = directory / "data"
        data.mkdir()
        session = Session(data, command, env)
        records = []
        try:
            session.launch()
            session.native(
                "start", chart=str(chart), names=["Voz de prueba"], token="response", precision=2
            )
            session.wait(lambda s: s.get("token") == "response" and s["position"] >= 1.0)
            for _ in range(3):
                for hz in (
                    65.406,
                    82.407,
                    97.999,
                    130.813,
                    174.614,
                    220.0,
                    293.665,
                    391.995,
                    493.883,
                    659.255,
                    783.991,
                ):
                    target = round(69 + 12 * math.log2(hz / 440)) % 12
                    session.native("test-tone", player=0, hz=hz, measure=True)
                    state = session.wait(
                        lambda s: (
                            s.get("tones", [-1])[0] >= 0
                            and s["tones"][0] % 12 == target
                            and s["trace_confirm_ms"][0] > 0
                        ),
                        timeout=3,
                    )
                    records.append(
                        dict(
                            hz=hz,
                            first_ms=state["trace_first_ms"][0],
                            confirm_ms=state["trace_confirm_ms"][0],
                        )
                    )
            first = [r["first_ms"] for r in records]
            confirmed = [r["confirm_ms"] for r in records]
            result = dict(
                driver="SDL dummy",
                input="PCM sintético a 48 kHz",
                sample_count=len(records),
                p50_first_ms=statistics.median(first),
                p95_first_ms=statistics.quantiles(first, n=100, method="inclusive")[94],
                p95_confirm_ms=statistics.quantiles(confirmed, n=100, method="inclusive")[94],
                worst_ms=max(first),
                measurements=records,
            )
            print(json.dumps(result, ensure_ascii=False))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finally:
            session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.engine, args.output, args.launcher)
