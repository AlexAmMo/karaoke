"""Sing the independent melody and an incorrect melody into two live inputs of the real game."""

import argparse
from bisect import bisect_right
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import extract  # noqa: E402
from test_session import Session, read_json  # noqa: E402


def sing(session, chart, reference, label):
    notes = [n for n in extract(reference)[0] if n.pitch is not None]
    starts = [n.start for n in notes]
    secret = secrets.token_hex(16)
    token = "sing-" + label
    session.native(
        "start",
        token=token,
        chart=str(chart.resolve()),
        names=["Referencia", "Seis semitonos"],
        routes=[dict(mobile=True), dict(mobile=True)],
        mobile_secret=secret,
        precision=2,
    )
    state = session.wait(
        lambda s: s.get("token") == token and s["state"] == "singing" and s["mobile_port"] > 0
    )
    address = ("127.0.0.1", state["mobile_port"])
    path = session.ipc / "engine.json"
    now = time.monotonic()
    deadline, first, origin, stamp = now, now, now - state["position"], None
    frame = np.arange(960, dtype=float) / 48000
    scores = [0, 0]
    sequence = 0
    max_position = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        while time.monotonic() - first < notes[-1].end + 45:
            stat = path.stat().st_mtime_ns
            if stat != stamp:
                stamp = stat
                state = read_json(path)
                if state.get("token") == token:
                    max_position = max(max_position, state["position"])
                    if state["state"] == "idle" and max_position > notes[-1].start:
                        break
                    if state["state"] == "singing":
                        latency = max(0.0, time.time() - stat / 1e9)
                        origin = time.monotonic() - state["position"] - latency
                        scores = [max(a, b) for a, b in zip(scores, state["scores"], strict=True)]
            clock = time.monotonic() - origin
            position = clock - 0.01
            index = bisect_right(starts, position) - 1
            n = notes[index] if index >= 0 else None
            for voice, offset in enumerate((0, 6)):
                if n is not None and position < n.end:
                    hz = 261.625565 * 2 ** (((n.pitch + offset) % 12) / 12)
                    samples = np.sin(2 * np.pi * hz * (clock + frame)) * 9000
                    pcm = samples.astype("<i2").tobytes()
                else:
                    pcm = bytes(1920)
                sender.sendto(
                    struct.pack("<32sBI", secret.encode(), voice, sequence) + pcm, address
                )
            sequence += 1
            deadline += 0.02
            if deadline < time.monotonic() - 0.1:
                deadline = time.monotonic()
            time.sleep(max(0, deadline - time.monotonic()))
    if max_position < notes[-1].start or len(scores) != 2 or scores[0] <= scores[1]:
        raise AssertionError((max_position, notes[-1].end, scores))
    return dict(
        chart_sha256=hashlib.sha256(chart.read_bytes()).hexdigest(),
        scores=scores,
        position_s=round(max_position, 3),
        packets_per_input=sequence,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("raw", "verified", "reference", "launcher", "engine", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    result = dict(
        precision="strict",
        synthetic=True,
        reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
    )
    for mode, path in (("raw", args.raw), ("verified", args.verified)):
        with tempfile.TemporaryDirectory(prefix="karaoke-real-voice-") as d:
            s = Session(
                Path(d),
                [str(args.launcher.resolve())],
                dict(
                    os.environ,
                    SDL_AUDIO_DRIVER="dummy",
                    SDL_AUDIODRIVER="dummy",
                    KARAOKE_ENGINE=str(args.engine.resolve()),
                ),
            )
            try:
                s.launch()
                result[mode] = sing(s, path, args.reference, mode)
                print(mode, result[mode], flush=True)
            finally:
                s.close()
    args.out.write_text(json.dumps(result, indent=2) + "\n")
