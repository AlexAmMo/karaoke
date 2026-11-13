#!/usr/bin/env python3
"""Measure packaged SDL logical/drawable geometry without UI automation.

Opens isolated synthetic sessions sequentially. Run only after coordinating the
desktop with its owner. This checks geometry, not visual sharpness or microphone
hardware. The OS may constrain a requested window size to the available screen.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import tempfile
import time
from pathlib import Path

from test_session import Session, resolve_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--require-hidpi", action="store_true")
    parser.add_argument(
        "--same-display",
        action="store_true",
        help="Require the same physical pixel density at both sizes; use only when both windows stay on one monitor.",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    launcher = args.launcher.resolve()
    environment = dict(os.environ)
    environment.pop("KARAOKE_ENGINE", None)
    if args.engine:
        environment["KARAOKE_ENGINE"] = str(args.engine.resolve())
    engine = resolve_engine(launcher, environment)
    report = {
        "scope": "Real packaged launcher and SDL geometry in synthetic demo mode. No UI automation, visual sharpness or physical audio validation.",
        "platform": platform.platform(),
        "launcher": str(launcher),
        "launcher_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
        "engine_override": environment.get("KARAOKE_ENGINE"),
        "engine_path": str(engine),
        "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
        "path_environment": environment.get("PATH"),
        "require_hidpi": args.require_hidpi,
        "same_display": args.same_display,
        "windows": [],
        "passed": False,
    }
    started = time.monotonic()
    session = None
    reference_scale = {}
    try:
        for size in ("1280x800", "1920x1080"):
            data = Path(tempfile.mkdtemp(prefix="karaoke-display-"))
            session = Session(
                data, [str(launcher), "--window-size", size], environment
            )
            measurement = {"requested_size": size, "data_directory": str(data)}
            report["windows"].append(measurement)
            session.launch()
            state = session.wait(
                lambda s: s.get("drawable_width", 0) > 0
                and s.get("drawable_height", 0) > 0
            )
            observations = []
            for index in range(3):
                if index:
                    deadline = time.monotonic() + 1
                    state = session.wait(lambda _: time.monotonic() >= deadline)
                observations.append(
                    {
                        key: state.get(key)
                        for key in (
                            "width", "height", "drawable_width", "drawable_height",
                            "pixel_scale_x", "pixel_scale_y",
                        )
                    }
                )
            measurement["geometry_observations"] = observations
            # Preserve the observed state before checking anything: window
            # managers can legitimately constrain a requested 1920x1080 window.
            measurement["engine_state"] = state
            measurement["requested_size_honored"] = (
                f'{state.get("width")}x{state.get("height")}' == size
            )
            checks = {}
            for axis, logical_key, drawable_key in (
                ("x", "width", "drawable_width"),
                ("y", "height", "drawable_height"),
            ):
                logical = state[logical_key]
                drawable = state[drawable_key]
                scale = state[f"pixel_scale_{axis}"]
                checks[f"finite_positive_geometry_{axis}"] = all(
                    isinstance(value, (int, float))
                    and math.isfinite(value)
                    and value > 0
                    for value in (logical, drawable, scale)
                )
                if not checks[f"finite_positive_geometry_{axis}"]:
                    raise AssertionError(f"Invalid {axis} geometry: {state}")
                checks[f"drawable_matches_logical_times_scale_{axis}"] = abs(
                    drawable - logical * scale
                ) <= 1
                if args.require_hidpi:
                    checks[f"physical_pixels_exceed_logical_units_{axis}"] = scale > 1
                if args.same_display:
                    reference_scale.setdefault(axis, scale)
                    # A window-size request cannot change the density of the
                    # same screen. Allow a single drawable pixel of rounding.
                    checks[f"same_display_density_{axis}"] = math.isclose(
                        scale, reference_scale[axis], abs_tol=1 / logical
                    )
            checks["synthetic_mode"] = state.get("synthetic") is True
            measurement["checks"] = checks
            if not all(checks.values()):
                raise AssertionError(f"Display checks failed for {size}: {checks}")
            measurement["close_exit_code"] = session.close()
            if measurement["close_exit_code"] != 0:
                raise AssertionError(f"Session did not close successfully: {size}")
            session = None
            print(json.dumps(measurement, ensure_ascii=False), flush=True)
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if session:
            try:
                session.close()
            except Exception as exc:
                report["cleanup_error"] = str(exc)
                report["passed"] = False
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("EVIDENCE " + str(args.output.resolve()), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
