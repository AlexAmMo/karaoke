import asyncio
import socket
import struct
from fractions import Fraction

import numpy as np
import pytest
from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame

from karaoke.mobile_voice import MobileVoices


class TestTone(AudioStreamTrack):
    __test__ = False

    def __init__(self):
        super().__init__()
        self.samples = 0

    async def recv(self):
        await asyncio.sleep(0.02)
        samples = np.arange(960) + self.samples
        sound = (np.sin(samples * (2 * np.pi * 440 / 48000)) * 8000).astype("int16")[None, :]
        f = AudioFrame.from_ndarray(sound, format="s16", layout="mono")
        f.pts = self.samples
        f.sample_rate = 48000
        f.time_base = Fraction(1, 48000)
        self.samples += 960
        return f


def test_webrtc_received_only_for_current_performer_and_room():
    async def run():
        receiver = MobileVoices()
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        sender = TestTone()
        pc.addTrack(sender)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("127.0.0.1", 0))
        udp.setblocking(False)
        try:
            await pc.setLocalDescription(await pc.createOffer())
            answer = await asyncio.to_thread(
                receiver.submit, "guest", "Ana", "mic-offer", {"sdp": pc.localDescription.sdp}
            )
            await pc.setRemoteDescription(RTCSessionDescription(**answer))
            for _ in range(100):
                if receiver.inputs():
                    break
                await asyncio.sleep(0.035)
            assert receiver.inputs()["mobile:guest"]["label"] == "Móvil de Ana"
            receiver.route("turn", "a" * 32, [{"mobile": True, "key": "mobile:guest"}])
            receiver.update(
                "turn", {"token": "turn", "state": "singing", "mobile_port": udp.getsockname()[1]}
            )
            pkt = await asyncio.wait_for(asyncio.get_running_loop().sock_recv(udp, 4096), 2)
            key, slot, seq = struct.unpack("<32sBI", pkt[:37])
            assert (key, slot, seq) == (b"a" * 32, 0, 0)
            assert len(pkt) == 1957 and np.max(np.abs(np.frombuffer(pkt[37:], dtype="<i2"))) > 100
            receiver.update(
                "other", {"token": "turn", "state": "singing", "mobile_port": udp.getsockname()[1]}
            )
            await asyncio.sleep(0.1)
            try:
                late = udp.recv(4096)
            except BlockingIOError:
                late = b""
            assert not late
        finally:
            sender.stop()
            await pc.close()
            await asyncio.to_thread(receiver.stop)
            udp.close()
        assert not receiver.inputs()

    asyncio.run(run())


@pytest.mark.parametrize("layout", ["mono", "stereo"])
@pytest.mark.parametrize("timestamps, expected, initial_sequence", [
    ([0, 960, 4800, 5760], [0, 1, 5, 6], 0),
    ([0, 960, 960, 1920], [0, 1, 2], 0),
    ([0, 960, 0, 960], [0, 1, 3, 4], 0),
    ([None, None, None], [0, 1, 2], 0),
    ([0, 960, ("pause", 1920), 2880, ("resume", 3840), 4800], [0, 1, 4, 5], 0),
    ([0, 960, ("turn", 0), 960], [0, 1, 0, 1], 0),
    ([0, 960], [3, 4], 2),  # A replacement stream starts after an explicit gap.
])
def test_capture_timeline_preserves_gaps_and_resets_at_turn_boundaries(
    timestamps, expected, initial_sequence, layout
):
    """Drive the actual resampler/UDP bridge without a browser or microphone."""
    from aiortc.mediastreams import MediaStreamError

    class Track:
        def __init__(self, receiver, port):
            self.positions = iter(timestamps)
            self.receiver, self.port, self.turn = receiver, port, "turn"

        async def recv(self):
            try:
                position = next(self.positions)
            except StopIteration:
                raise MediaStreamError from None
            if isinstance(position, tuple):
                action, position = position
                if action == "turn":
                    self.turn = "next-turn"
                    self.receiver.route(self.turn, "b" * 32,
                                        [{"mobile": True, "key": "mobile:guest"}])
                self.receiver.update(self.turn, {"token": self.turn, "state": "singing",
                                                "paused": action == "pause",
                                                "mobile_port": self.port})
            channels = 1 if layout == "mono" else 2
            frame = AudioFrame.from_ndarray(np.zeros((1, 960 * channels), dtype="int16"),
                                           format="s16", layout=layout)
            frame.pts = position
            frame.sample_rate = 48000
            frame.time_base = Fraction(1, 48000)
            return frame

    class Peer:
        async def close(self):
            pass

    async def run():
        receiver = MobileVoices()
        peer = Peer()
        receiver.peers["guest"] = peer
        receiver.route("turn", "a" * 32, [{"mobile": True, "key": "mobile:guest"}])
        receiver.sequence["guest"] = initial_sequence
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.bind(("127.0.0.1", 0))
            udp.setblocking(False)
            receiver.update("turn", {"token": "turn", "state": "singing",
                                     "mobile_port": udp.getsockname()[1]})
            track = Track(receiver, udp.getsockname()[1])
            await receiver._listen("guest", "Ana", track, peer, receiver.epoch)
            sequences = []
            while True:
                try:
                    packet = udp.recv(4096)
                except BlockingIOError:
                    break
                sequences.append(struct.unpack("<32sBI", packet[:37])[2])
            assert sequences == expected

    asyncio.run(run())
