#!/usr/bin/env python3
"""Run a long native performance with five PCM senders, five synthetic inputs and controlled reconnects."""

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import statistics
import struct
import sys
import tempfile
import threading
import time
import wave

from test_group_audio import tone_frames
from test_session import Session


def run(engine, seconds, destination):
    secret = secrets.token_hex(16)
    inputs = list(range(0, 10, 2))
    env = dict(
        os.environ,
        SDL_AUDIODRIVER="dummy",
        SDL_AUDIO_DRIVER="dummy",
        KARAOKE_ENGINE=str(engine.resolve()),
    )
    with tempfile.TemporaryDirectory(prefix="karaoke-soak-") as tmp:
        root = Path(tmp)
        with wave.open(str(root / "music.wav"), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            for _ in range(seconds + 60):
                audio.writeframesraw(bytes(16000))
        chart = root / "song.txt"
        chart.write_text(
            f"#TITLE:Prueba sostenida\n#ARTIST:Karaoke\n#MP3:music.wav\n#BPM:120\n#GAP:1000\n: 0 {(seconds + 55) * 8} 21 La\nE\n",
            encoding="utf-8",
        )
        data = root / "data"
        data.mkdir()
        session = Session(data, [sys.executable, "-m", "karaoke.app"], env)
        stop = threading.Event()
        blocked = threading.Event()
        counts = {"datagrams": 0, "invalid": 0}
        tones = {i: tone_frames(523 if i == 8 else 440) for i in inputs}
        worker = None
        try:
            session.launch()
            session.native(
                "start",
                token="soak",
                names=[f"Voz {i + 1}" for i in range(10)],
                chart=str(chart),
                precision=2,
                mobile_secret=secret,
                routes=[
                    dict(mobile=i % 2 == 0, device=i, channel=0, gain=0.12 if i < 2 else 0.0)
                    for i in range(10)
                ],
            )
            state = session.wait(
                lambda s: (
                    s.get("token") == "soak" and s["state"] == "singing" and s.get("mobile_port")
                )
            )
            endpoint = ("127.0.0.1", state["mobile_port"])
            for i in range(1, 10, 2):
                session.native("test-tone", player=i, hz=440)

            def transmit():
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    base = time.monotonic()
                    seq = 0
                    while not stop.is_set():
                        for i in inputs:
                            paused = blocked.is_set() and i == 0
                            # Same sequence and old turn tag cannot score, even during a reconnect.
                            tag = b"0" * 32 if paused and seq % 2 else secret.encode()
                            sequence = 0 if paused else seq
                            sock.sendto(
                                struct.pack("<32sBI", tag, i, sequence) + tones[i][seq % 50],
                                endpoint,
                            )
                            counts["datagrams"] += 1
                            counts["invalid"] += int(paused)
                        seq += 1
                        stop.wait(max(0, base + seq * 0.02 - time.monotonic()))

            worker = threading.Thread(target=transmit)
            worker.start()
            begin = time.monotonic()
            next_action = 10
            next_minute = 60
            next_cut = 34
            end_cut = 0
            cuts = 0
            stalled = None
            state_times = []
            last_position = -1
            last_scores = [0] * 10
            caps = [0] * 10
            peak_fifo = [0] * 10
            while time.monotonic() - begin < seconds:
                elapsed = time.monotonic() - begin
                state = session.state()
                assert state["state"] == "singing" and state["token"] == "soak", state
                if state["position"] != last_position:
                    state_times.append(elapsed)
                    last_position = state["position"]
                scores = state["scores"]
                assert (
                    len(scores) == 10
                    and all(a >= b for a, b in zip(scores, last_scores))
                    and scores[8] == 0
                ), scores
                last_scores = scores
                for i, n in enumerate(state["monitor_queue_ms"]):
                    peak_fifo[i] = max(peak_fifo[i], n)
                for i, n in enumerate(state["monitor_dropped_frames"]):
                    caps[i] = max(caps[i], n)
                if elapsed >= next_action:
                    session.native("panel", collapsed=(next_action // 10) % 2 == 0)
                    session.event("page:Buscar")
                    session.event("field:query", "zz prueba local " + str(next_action))
                    next_action += 10
                if not blocked.is_set() and elapsed >= next_cut:
                    blocked.set()
                    end_cut = elapsed + 3
                    next_cut += 70
                    stalled = None
                if (
                    blocked.is_set()
                    and elapsed > end_cut - 1.8
                    and stalled is None
                    and state["tones"][0] == -1
                ):
                    stalled = (scores[0], scores[1])
                if blocked.is_set() and elapsed > end_cut + 20:
                    raise AssertionError(
                        (
                            "dropout did not settle",
                            elapsed,
                            stalled,
                            scores,
                            state["tones"],
                            state["mobile_received"],
                            state["mobile_rejected"],
                        )
                    )
                if blocked.is_set() and elapsed >= end_cut and stalled and scores[1] > stalled[1]:
                    assert stalled[0] == scores[0], (stalled, scores)
                    cuts += 1
                    blocked.clear()
                if elapsed >= next_minute:
                    print(
                        "elapsed",
                        round(elapsed),
                        "s, position",
                        round(state["position"], 2),
                        "s, scores",
                        scores,
                        "UDP",
                        sum(state["mobile_received"]),
                        flush=True,
                    )
                    next_minute += 60
                time.sleep(0.1)
            stop.set()
            worker.join()
            deltas = [b - a for a, b in zip(state_times, state_times[1:])]
            result = dict(
                elapsed_s=round(time.monotonic() - begin, 3),
                song_position_s=state["position"],
                cuts=cuts,
                datagrams_sent=counts["datagrams"],
                invalid_sent=counts["invalid"],
                accepted=state["mobile_received"],
                rejected=state["mobile_rejected"],
                gap_frames=state["mobile_gap_frames"],
                scores=state["scores"],
                peak_monitor_queue_ms=peak_fifo,
                monitor_dropped_frames=caps,
                output_frames=state["output_frames"],
                output_hz=state["output_hz"],
                audio_driver=state["audio_driver"],
                state_interval_p95_s=round(statistics.quantiles(deltas, n=100)[94], 3),
                max_state_interval_s=round(max(deltas), 3),
            )
            assert (
                result["rejected"] > 0
                and result["cuts"] > 0
                and all(0 <= v <= 40 for v in peak_fifo)
            ), result
            assert (
                abs(state["scores"][1] - state["scores"][9]) < 150
                and state["scores"][0] < state["scores"][1]
            ), result
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result), flush=True)
        finally:
            stop.set()
            if worker:
                worker.join()
            session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=1200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 60 <= args.seconds <= 10800:
        parser.error("duration must be between 60 seconds and 3 hours")
    run(args.engine, args.seconds, args.output)
