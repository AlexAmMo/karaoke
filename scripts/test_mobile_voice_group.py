"""Exercise ten simultaneous local WebRTC clients, preserving the slot and pitch on reconnect."""

import argparse
import asyncio
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path
import socket
import struct
import time

from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame
import numpy as np

from karaoke.mobile_voice import MobileVoices


class Voice(AudioStreamTrack):
    def __init__(self, frequency):
        super().__init__()
        self.frequency = frequency
        self.samples = 0
        self.start_time = None

    async def recv(self):
        if self.start_time is None:
            self.start_time = time.monotonic()
        await asyncio.sleep(max(0, self.start_time + self.samples / 48000 - time.monotonic()))
        phase = (np.arange(960) + self.samples) * (2 * np.pi * self.frequency / 48000)
        frame = AudioFrame.from_ndarray(
            (np.sin(phase)[None] * 6500).astype("<i2"), format="s16", layout="mono"
        )
        frame.sample_rate, frame.time_base, frame.pts = 48000, Fraction(1, 48000), self.samples
        self.samples += 960
        return frame


async def run(duration):
    receiver = MobileVoices()
    frequencies = [250 + 50 * i for i in range(10)]
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.setblocking(False)
    peers = {}
    received, wrong, last, missing = Counter(), Counter(), {}, Counter()
    secret = b"a" * 32

    async def connect(i):
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        peers[i] = peer
        peer.addTrack(Voice(frequencies[i]))
        await peer.setLocalDescription(await peer.createOffer())
        answer = await asyncio.to_thread(
            receiver.submit,
            str(i),
            "Cantante " + str(i + 1),
            "mic-offer",
            {"sdp": peer.localDescription.sdp},
        )
        await peer.setRemoteDescription(RTCSessionDescription(**answer))

    async def listen():
        while True:
            packet = await asyncio.get_running_loop().sock_recv(udp, 2048)
            token, i, seq = struct.unpack("<32sBI", packet[:37])
            assert token == secret and i < 10 and len(packet) == 1957
            if i in last:
                assert seq > last[i], (i, seq, last[i])
                missing[i] += seq - last[i] - 1
            last[i] = seq
            samples = np.frombuffer(packet[37:], dtype="<i2")
            if np.max(np.abs(samples)) < 100:
                continue
            pitch = int(np.argmax(np.abs(np.fft.rfft(samples)))) * 50
            received[i] += 1
            wrong[i] += int(pitch != frequencies[i])

    listener = asyncio.create_task(listen())
    try:
        await asyncio.gather(*(connect(i) for i in range(10)))
        deadline = time.monotonic() + 8
        while len(receiver.inputs()) != 10 and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert len(receiver.inputs()) == 10
        receiver.route(
            "room",
            secret.decode(),
            [{"mobile": True, "key": "mobile:" + str(i)} for i in range(10)],
        )
        receiver.update(
            "room", {"token": "room", "state": "singing", "mobile_port": udp.getsockname()[1]}
        )
        await asyncio.sleep(duration / 2)
        await peers[4].close()
        await asyncio.to_thread(receiver.submit, "4", "Cantante 5", "mic-stop", {})
        await asyncio.sleep(0.5)
        await connect(4)
        await asyncio.sleep(duration / 2)
        if listener.done():
            listener.result()
        assert len(receiver.inputs()) == 10 and len(received) == 10
        assert all(
            received[i] >= duration * 30 and wrong[i] / received[i] < 0.02 for i in range(10)
        )
        return {
            "seconds": duration,
            "tracks": 10,
            "reconnected_slot": 5,
            "voiced_frames": dict(received),
            "unexpected_pitch_frames": dict(wrong),
            "skipped_udp_sequences": dict(missing),
        }
    finally:
        listener.cancel()
        await asyncio.gather(listener, return_exceptions=True)
        await asyncio.gather(*(peer.close() for peer in peers.values()), return_exceptions=True)
        await asyncio.to_thread(receiver.stop)
        udp.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 7200:
        parser.error("expected a duration of 5 to 7200 seconds")
    evidence = json.dumps(asyncio.run(run(args.seconds)), indent=2) + "\n"
    if args.output:
        args.output.write_text(evidence)
    print(evidence)
