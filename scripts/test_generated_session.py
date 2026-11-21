"""Check video link → generated chart → verification or local review → queue → singing in a private test library."""

import argparse
import json
import os
from pathlib import Path
import tempfile
import time

import requests
from karaoke.draft_review import DraftEditor
from karaoke.service import Service, youtube_id
from test_session import Session


def approve_in_editor(host, uid):
    ed = DraftEditor(host.lab, uid)
    host.lab.editor = ed
    api = ed.url + "chart"
    snap = requests.get(api, timeout=4).json()
    partial = requests.get(ed.url + "audio", headers={"Range": "bytes=0-511"}, timeout=4)
    assert partial.status_code == 206 and len(partial.content) == 512
    response = requests.post(
        api,
        headers={"Origin": ed.origin},
        json={"revision": snap["revision"], "body": snap["body"], "approve": True},
        timeout=15,
    )
    response.raise_for_status()
    assert response.json()["state"] == "approved"
    return len(snap["regions"])


def run(args):
    with tempfile.TemporaryDirectory(prefix="karaoke-draft-session-") as temporary:
        root = Path(temporary)
        host = Service(root)
        try:
            host.handle({"action": "page:Generar"})
            host.handle({"action": "field:generate_url", "value": args.video})
            host.handle({"action": "lab:enqueue"})
            uid = host.draft_id
            started = time.monotonic()
            last = None
            while time.monotonic() - started < 2400:
                host.lab.tick()
                draft = host.lab.row(uid)
                point = draft["state"], draft["message"]
                if point != last:
                    print(round(time.monotonic() - started, 1), point, flush=True)
                    last = point
                if draft["state"] in ("review", "approved"):
                    break
                if draft["state"] in ("error", "cancelled"):
                    raise RuntimeError(draft["message"])
                time.sleep(0.2)
            else:
                raise TimeoutError("Generation did not finish within 40 minutes")
            assert not host.store.queue()
            home = host.lab.root / uid / "draft"
            manifest = json.loads((home / "generation.json").read_text(encoding="utf-8"))
            assert (
                manifest["video_id"] == youtube_id(args.video)
                and not manifest["automatically_verified"]
            )
            automatic = draft["state"] == "approved"
            assert automatic == args.expect_verified, (
                f"Unexpected generation outcome: {draft['message']}"
            )
            regions = None if automatic else approve_in_editor(host, uid)
            song = host.lab.row(uid)["song_id"]
            turn = host.enqueue_song(song)
            provenance = json.loads(
                Path(host.song(song)["chart"])
                .with_name("generation.json")
                .read_text(encoding="utf-8")
            )
            assert (
                provenance["review"]["chart_sha256"]
                and provenance["video_id"] == manifest["video_id"]
            )
            assert provenance["automatically_verified"] == automatic
            if automatic:
                assert provenance["verification"]["chart_sha256"] == manifest["chart_sha256"]
            evidence = {
                "video_id": manifest["video_id"],
                "title": host.song(song)["title"],
                "artist": host.song(song)["artist"],
                "generation_seconds": round(time.monotonic() - started, 1),
                "source": manifest["lyrics"]["kind"],
                "notes": manifest["notes"],
                "analyzed_duration_s": round(manifest["duration"], 3),
                "method": manifest["method"],
                "models": manifest["models"],
                "regions": regions,
                "approval": "automatic" if automatic else "explicit in temporary test data",
                "verification": provenance.get("verification"),
            }
        finally:
            host.close()
        session = Session(
            root, [str(args.launcher.resolve())], {**os.environ, "SDL_AUDIODRIVER": "dummy"}
        )
        try:
            session.launch()
            session.event("start:" + turn)
            state = session.wait(
                lambda s: (
                    s.get("token") == turn
                    and s.get("state") == "singing"
                    and s.get("position", 0) > 2
                ),
                timeout=45,
            )
            session.event("end")
            session.event("confirm-end")
            session.wait(lambda _: not session.queue(), timeout=30)
            evidence.update(
                native_singing=True,
                actual_position_s=state.get("position"),
                synthetic_microphone=True,
            )
        finally:
            session.close()
        return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-verified", action="store_true")
    args = parser.parse_args()
    if not youtube_id(args.video):
        parser.error("Use an exact YouTube URL")
    output = json.dumps(run(args), indent=2, ensure_ascii=False) + "\n"
    args.output.write_text(output, encoding="utf-8")
    print(output)
