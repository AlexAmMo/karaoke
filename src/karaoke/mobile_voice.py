"""Receive a guest's WebRTC audio in memory and route it only to its reserved native slot."""

from __future__ import annotations

import asyncio
import concurrent.futures
import re
import socket
import struct
import threading

from .remote_server import RemoteError


class MobileVoices:
    def __init__(self):
        self.lock = threading.RLock()
        self.thread = None
        self.loop = None
        self.clients = {}
        self.peers = {}
        self.routing = {}
        self.identity = None
        self.sequence = {}
        self.port = 0
        self.epoch = 0

    def inputs(self):
        with self.lock:
            return {
                "mobile:" + client: {"mobile": True, "label": "Móvil de " + name}
                for client, name in self.clients.items()
            }

    def route(self, turn, secret, inputs):
        with self.lock:
            self.identity = (turn, secret.encode("ascii"))
            self.routing = {r["key"][7:]: i for i, r in enumerate(inputs) if r.get("mobile")}
            self.sequence.clear()
            self.port = 0

    def update(self, turn, engine):
        with self.lock:
            self.port = 0
            if (
                self.identity
                and turn == self.identity[0] == engine.get("token")
                and engine.get("state") == "singing"
                and not engine.get("paused")
            ):
                self.port = int(engine.get("mobile_port") or 0)

    def submit(self, client, name, operation, payload, epoch=None):
        if operation == "mic-stop":
            with self.lock:
                if self.loop:
                    asyncio.run_coroutine_threadsafe(self._close(client), self.loop)
                self.clients.pop(client, None)
            return {"ok": True}
        sdp = payload.get("sdp")
        if (
            not isinstance(sdp, str)
            or len(sdp) > 32768
            or not sdp.startswith("v=0")
            or len(re.findall(r"^m=", sdp, re.M)) != 1
            or not re.search(r"^m=audio ", sdp, re.M)
        ):
            raise RemoteError("Oferta de micrófono no válida.")
        with self.lock:
            if epoch is not None and epoch != self.epoch:
                raise RemoteError("La sala se ha cerrado.", 410)
            if not self.loop:
                self.loop = asyncio.new_event_loop()
                self.thread = threading.Thread(
                    target=self.loop.run_forever, daemon=True, name="micrófonos-web"
                )
                self.thread.start()
            future = asyncio.run_coroutine_threadsafe(
                self._offer(client, name, sdp, self.epoch), self.loop
            )
        try:
            return future.result(24)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise RemoteError(
                "El enlace de voz ha caducado. Vuelve a activar el micro.", 503
            ) from None
        except ImportError:
            raise RemoteError("Esta instalación carece del receptor WebRTC.", 503) from None

    async def _close(self, client, peer=None):
        current = self.peers.get(client)
        if current is None or (peer and current is not peer):
            return
        self.peers.pop(client)
        with self.lock:
            self.clients.pop(client, None)
        await current.close()

    async def _offer(self, client, name, sdp, epoch):
        from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

        if client not in self.peers and len(self.peers) >= 10:
            raise RemoteError("Los diez micrófonos móviles están ocupados.", 409)
        old = self.peers.get(client)
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.peers[client] = peer
        with self.lock:
            self.clients.pop(client, None)
        if old:
            await old.close()

        @peer.on("connectionstatechange")
        async def connection_changed():
            if peer.connectionState in ("failed", "closed"):
                await self._close(client, peer)

        @peer.on("track")
        def received(track):
            if track.kind == "audio":
                asyncio.create_task(self._listen(client, name, track, peer, epoch))

        try:
            await peer.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
            await peer.setLocalDescription(await peer.createAnswer())
            if epoch != self.epoch or self.peers.get(client) is not peer:
                raise RemoteError("La sala se ha cerrado.", 410)
            return {"sdp": peer.localDescription.sdp, "type": "answer"}
        except BaseException:
            await self._close(client, peer)
            raise

    async def _listen(self, client, name, track, peer, epoch):
        from av import AudioResampler
        from aiortc.mediastreams import MediaStreamError

        resampler = AudioResampler(format="s16", layout="mono", rate=48000, frame_size=960)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.setblocking(False)
            try:
                while epoch == self.epoch and self.peers.get(client) is peer:
                    frame = await asyncio.wait_for(track.recv(), timeout=8)
                    with self.lock:
                        if epoch != self.epoch or self.peers.get(client) is not peer:
                            break
                        self.clients[client] = name
                    for mono in resampler.resample(frame):
                        with self.lock:
                            slot = self.routing.get(client)
                            if not self.port or slot is None or not self.identity:
                                continue
                            seq = self.sequence.get(client, 0)
                            self.sequence[client] = (seq + 1) % (1 << 32)
                            packet = (
                                struct.pack("<32sBI", self.identity[1], slot, seq)
                                + bytes(mono.planes[0])[:1920]
                            )
                            sender.sendto(packet, ("127.0.0.1", self.port))
            except (MediaStreamError, TimeoutError, OSError):
                pass
            finally:
                await self._close(client, peer)

    def stop(self):
        with self.lock:
            self.epoch += 1
            loop, thread = self.loop, self.thread
            self.loop = self.thread = self.identity = None
            self.port = 0
            self.clients.clear()
            self.routing.clear()
        if loop:

            async def shutdown():
                await asyncio.gather(
                    *(self._close(k) for k in list(self.peers)), return_exceptions=True
                )
                for task in asyncio.all_tasks():
                    if task is not asyncio.current_task():
                        task.cancel()
                await asyncio.sleep(0)

            try:
                asyncio.run_coroutine_threadsafe(shutdown(), loop).result(5)
            finally:
                loop.call_soon_threadsafe(loop.stop)
                thread.join(3)
                if not thread.is_alive():
                    loop.close()
