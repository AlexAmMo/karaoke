"""Five duets reuse two actual WebRTC streams. Exercise reservation, singing and score delivery."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from test_mobile_voice_group import Voice
from test_remote_session import Phone, wait
from test_session import ROOT, Session, read_json


async def run(engine, output):
    with tempfile.TemporaryDirectory(prefix="karaoke-shared-mics-") as temporary:
        env = {
            **os.environ,
            "SDL_AUDIODRIVER": "dummy",
            "SDL_AUDIO_DRIVER": "dummy",
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
        }
        if engine:
            env["KARAOKE_ENGINE"] = str(engine.resolve())
        session = Session(Path(temporary), [sys.executable, "-m", "karaoke.app"], env)
        peers = []
        try:
            await asyncio.to_thread(session.launch)
            session.import_chart(ROOT / "technical-spike/fixtures/initial/A/song.txt")
            await asyncio.to_thread(
                session.wait, lambda _: bool(session.rows("SELECT id FROM songs"))
            )
            song_id = session.rows("SELECT id FROM songs")[0]["id"]
            session.event("remote:start")
            view = await asyncio.to_thread(
                wait,
                lambda: read_json(session.ipc / "view.json"),
                lambda v: any(r["kind"] == "qr" for r in v.get("rows", [])),
            )
            invitation = " ".join(v.get("label", "") + " " + v.get("sub", "") for v in view["rows"])
            url = re.search(r"http://[\d.]+:\d+", invitation)[0]
            code = re.search(r"(?<!\d)\d{6}(?!\d)", invitation)[0]
            inputs = []
            phones = [Phone(url), Phone(url)]

            async def post(i, route, **data):
                return await asyncio.to_thread(phones[i].post, route, **data)

            async def action(i, op, **data):
                return await asyncio.to_thread(phones[i].action, op, **data)

            for i, frequency in enumerate((440, 523.25)):
                name = f"Micro {i + 1}"
                await post(i, "join", name=name, code=code)
                peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
                peers.append(peer)
                peer.addTrack(Voice(frequency))
                await peer.setLocalDescription(await peer.createOffer())
                answer = await post(i, "mic-offer", sdp=peer.localDescription.sdp)
                await peer.setRemoteDescription(RTCSessionDescription(**answer))
                state = await asyncio.to_thread(
                    wait,
                    lambda: phones[i].post("state"),
                    lambda s: any(key["label"] == "Móvil de " + name for key in s["inputs"]),
                )
                inputs.append(
                    next(key["id"] for key in state["inputs"] if key["label"] == "Móvil de " + name)
                )
            names = [f"Cantante {i + 1}" for i in range(10)]
            for i, name in enumerate(names):
                await action(i % 2, "singer-create", name=name)
            roster = {p["name"]: p["id"] for p in (await post(0, "state"))["singers"]}
            assert len(roster) == 10
            for i, name in enumerate(names):
                await action(i % 2, "singer-input", id=roster[name], input=inputs[i // 5])

            def duet(a, b):
                return [{"singer": roster[names[a]]}, {"singer": roster[names[b]]}]

            try:
                await action(0, "add", id="lib:" + song_id, voices=duet(0, 1))
            except AssertionError as err:
                assert "409" in str(err), err
            else:
                raise AssertionError("A simultaneous duplicate input was accepted")
            assert not (await post(0, "state"))["queue"]
            turns = [
                (await action(i % 2, "add", id="lib:" + song_id, voices=duet(i, i + 5)))["id"]
                for i in range(5)
            ]
            evidence = []
            for i, turn in enumerate(turns):
                state = await post(i % 2, "state")
                await action(i % 2, "start", id=turn, revision=state["revision"])
                sung = await asyncio.to_thread(
                    session.wait,
                    lambda s: (
                        s.get("token") == turn
                        and s.get("position", 0) > 3
                        and s.get("scores", [0])[0] > 0
                    ),
                )
                assert sung["scores"][0] > sung["scores"][1], sung["scores"]
                await action(1 - i % 2, "end", id=turn)
                await asyncio.to_thread(
                    session.wait,
                    lambda _: (
                        session.rows("SELECT state FROM turns WHERE id=?", (turn,))[0]["state"]
                        == "finished"
                    ),
                )
                row = session.rows("SELECT names,scores FROM turns WHERE id=?", (turn,))[0]
                assert json.loads(row["names"]) == [names[i], names[i + 5]]
                score = json.loads(row["scores"])
                assert (
                    len(score) == 2
                    and score[0] > score[1]
                    and not session.rows("SELECT 1 FROM reservations")
                )
                evidence.append({"pair": json.loads(row["names"]), "score": score})
            output.write_text(
                json.dumps(
                    {"streams": 2, "profiles": 10, "turns": evidence, "duplicate_rejected": True},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        finally:
            await asyncio.gather(*(p.close() for p in peers))
            await asyncio.to_thread(session.close)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.engine, args.output))
