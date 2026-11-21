#!/usr/bin/env python3
"""Exercise score timing at 10 fps and hold a real engine analysis reader during live UDP input."""

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import sys
import tempfile
import threading
import time

from test_group_audio import exercise_timing, tone_frames
from test_live_pitch import make_chart
from test_session import Session


def exercise_capture_contention(session, directory):
    chart = make_chart(directory)
    key = secrets.token_hex(16)
    session.native(
        "start",
        chart=str(chart),
        names=["Voz 1", "Voz 2"],
        token="contention",
        routes=[dict(mobile=True, gain=0.5), dict(mobile=True, gain=0.5)],
        mobile_secret=key,
    )
    state = session.wait(lambda s: s["state"] == "singing" and s.get("mobile_port"))
    address = ("127.0.0.1", state["mobile_port"])
    stop = threading.Event()
    pcm = tone_frames(440)

    def send():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            deadline = time.monotonic()
            seq = 0
            while not stop.is_set():
                for slot in (0, 1):
                    sender.sendto(
                        struct.pack("<32sBI", key.encode(), slot, seq) + pcm[seq % len(pcm)],
                        address,
                    )
                seq += 1
                deadline += 0.02
                stop.wait(max(0, deadline - time.monotonic()))

    worker = threading.Thread(target=send)
    worker.start()
    try:
        before = session.wait(lambda s: s["position"] > 2 and min(s["scores"]) > 0)
        session.native("test-hold-analysis", player=0, milliseconds=180)
        recovered = session.wait(
            lambda s: (
                s["position"] > before["position"] + 1
                and s["tones"] == [9, 9]
                and min(s["scores"]) > min(before["scores"])
            )
        )
        skipped = [
            b - a
            for a, b in zip(before["analysis_skipped_blocks"], recovered["analysis_skipped_blocks"])
        ]
        assert skipped[0] >= 3 and skipped[1] <= 1, skipped
        assert min(recovered["monitor_peaks"]) > 0, recovered
        assert max(recovered["monitor_queue_ms"]) <= 31, recovered
        print(
            "PASS contention",
            json.dumps(
                {
                    "analysis_skipped_blocks": skipped,
                    "monitor_queue_ms": recovered["monitor_queue_ms"],
                    "monitor_peaks": recovered["monitor_peaks"],
                    "scores_after_recovery": recovered["scores"],
                }
            ),
            flush=True,
        )
    finally:
        stop.set()
        worker.join(2)
        session.native("end", token="contention")
        session.wait(lambda s: s["state"] == "idle")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--launcher", type=Path)
    args = parser.parse_args()
    env = dict(os.environ, SDL_AUDIODRIVER="dummy", SDL_AUDIO_DRIVER="dummy")
    if args.engine:
        env["KARAOKE_ENGINE"] = str(args.engine.resolve())
    launcher = (
        [str(args.launcher.resolve())] if args.launcher else [sys.executable, "-m", "karaoke.app"]
    )
    with tempfile.TemporaryDirectory(prefix="karaoke-score-clock-") as scratch:
        root = Path(scratch)
        (root / "engine.ini").write_text(
            "[Game]\nPlayers=1\nDifficulty=Medium\nMicDelay=0\n[Graphics]\nFullScreen=Off\nMaxFramerate=10\n"
            "[Advanced]\nScreenFade=Off\n[Sound]\nBackgroundMusic=Off\nAudioVolume=0\nPreviewVolume=0\n"
            "VoicePassthrough=On\n",
            encoding="utf-8",
        )
        session = Session(root, launcher, env)
        try:
            session.launch()
            exercise_timing(session, root / "timing")
            exercise_capture_contention(session, root)
        finally:
            session.close()


if __name__ == "__main__":
    main()
