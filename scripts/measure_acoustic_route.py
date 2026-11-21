#!/usr/bin/env python3
"""Emit seven short pulses and measure a real speaker-to-microphone route. No mic recording is saved."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import tempfile

from test_session import Session


def run(args):
    environment = dict(os.environ)
    for variable in ("KARAOKE_TEST_INPUT", "SDL_AUDIODRIVER", "SDL_AUDIO_DRIVER"):
        environment.pop(variable, None)
    if args.engine:
        environment["KARAOKE_ENGINE"] = str(args.engine.resolve())
    if args.mixer:
        environment["KARAOKE_MONITOR_PATH"] = "mixer"
    if args.frames:
        environment["KARAOKE_AUDIO_BLOCK"] = str(args.frames)
    command = (
        [str(args.launcher.resolve())] if args.launcher else [sys.executable, "-m", "karaoke.app"]
    )
    with tempfile.TemporaryDirectory(prefix="karaoke-acoustic-") as scratch:
        session = Session(Path(scratch), command, environment)
        try:
            session.launch(synthetic=False)
            session.native("scan")
            current = session.wait(lambda state: state.get("devices"), timeout=35)
            candidates = [
                device for device in current["devices"] if device["name"] == args.input_name
            ]
            if len(candidates) != 1:
                raise RuntimeError(
                    "Choose one connected input by its exact name. Detected: "
                    + ", ".join(d["name"] for d in current["devices"])
                )
            device = candidates[0]
            if args.channel < 1 or args.channel > device["channels"]:
                raise RuntimeError(f"This device has {device['channels']} input channels.")
            session.native(
                "calibrate",
                name=device["name"],
                device=device["index"],
                channel=args.channel - 1,
                purpose="scoring" if args.music else "monitor",
            )
            active = session.wait(
                lambda state: state.get("calibration", {}).get("status") in ("running", "failed")
            )
            end = session.wait(
                lambda state: state.get("calibration", {}).get("status") in ("done", "failed"),
                timeout=15,
            )
            report = {
                "date_utc": datetime.now(timezone.utc).isoformat(),
                "computer": platform.platform(),
                "audio_driver": current.get("audio_driver"),
                "capture_backend": current.get("capture_backend"),
                "output_frames": current.get("output_frames"),
                "output_hz": current.get("output_hz"),
                "input_hz": device.get("hz"),
                "input_block_frames": active.get("input_frames", [])[0]
                if active.get("input_frames")
                else None,
                "calibration": end["calibration"],
            }
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return end["calibration"]["status"] == "done"
        finally:
            session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-name", required=True, help="Exact OS name of the microphone")
    parser.add_argument("--channel", type=int, default=1, help="One-based input channel")
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--mixer",
        action="store_true",
        help="Measure through the SDL mixer instead of using a wired duplex callback",
    )
    parser.add_argument(
        "--music",
        action="store_true",
        help="Measure the backing track output, as the scoring calibration does in the app",
    )
    parser.add_argument("--frames", type=int, choices=(128, 256, 512, 1024, 2048))
    raise SystemExit(0 if run(parser.parse_args()) else 1)
