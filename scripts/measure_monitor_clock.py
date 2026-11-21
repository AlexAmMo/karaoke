#!/usr/bin/env python3
"""Sample the actual native input callback clocks using a disposable, silent Karaoke session."""

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

from test_session import Session


def summarize(values):
    if not values:
        return None
    ordered = sorted(values)
    return {
        "min": min(values),
        "p50": statistics.median(ordered),
        "p95": ordered[round(0.95 * (len(ordered) - 1))],
        "max": max(values),
    }


def measure(args):
    env = dict(os.environ)
    if args.engine:
        env["KARAOKE_ENGINE"] = str(args.engine.resolve())
    env.pop("KARAOKE_TEST_INPUT", None)
    launcher = (
        [str(args.launcher.resolve())] if args.launcher else [sys.executable, "-m", "karaoke.app"]
    )
    with tempfile.TemporaryDirectory(prefix="karaoke-monitor-") as directory:
        session = Session(Path(directory), launcher, env)
        try:
            session.launch(synthetic=False)
            session.native("scan")
            state = session.wait(lambda v: v.get("devices"))
            device = next(
                (item for item in state["devices"] if item["name"] == args.input_name), None
            )
            if not device or not 1 <= args.channel <= device["channels"]:
                raise ValueError(
                    f"No se encontró la entrada {args.input_name}, canal {args.channel}"
                )
            session.native("device", player=0, device=device["index"], channel=args.channel - 1)
            session.native("gain", player=0, value=0)
            session.native("testinput", count=1)
            session.wait(lambda v: v.get("testing") and v.get("input_frames", [0])[0] > 0)
            adc, dac, blocks, trips = [], [], [], []
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                state = session.state()
                active = next(d for d in state["devices"] if d["index"] == device["index"])
                blocks.append(state["input_frames"][0])
                if "adc_to_callback_ms" in active:
                    adc.append(active["adc_to_callback_ms"])
                if "callback_to_dac_ms" in active:
                    dac.append(active["callback_to_dac_ms"])
                if "adc_to_callback_ms" in active and "callback_to_dac_ms" in active:
                    trips.append(active["adc_to_callback_ms"] + active["callback_to_dac_ms"])
                time.sleep(0.2)
            return {
                "driver": state["audio_driver"],
                "capture_backend": state["capture_backend"],
                "input": device["name"],
                "hz": device["hz"],
                "output_frames": state["output_frames"],
                "duplex": state["duplex_monitor"][0],
                "samples_of_engine_state": len(blocks),
                "input_frames": summarize(blocks),
                "adc_to_callback_ms": summarize(adc),
                "callback_to_dac_ms": summarize(dac),
                "adc_to_dac_ms": summarize(trips),
                "input_overflows": active["input_overflows"],
                "output_underflows": active["output_underflows"],
            }
        finally:
            session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-name", required=True)
    parser.add_argument("--channel", type=int, default=1, help="One-based channel")
    parser.add_argument("--seconds", type=float, default=8)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--launcher", type=Path)
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds debe ser al menos 1")
    print(json.dumps(measure(args), ensure_ascii=False, indent=2))
