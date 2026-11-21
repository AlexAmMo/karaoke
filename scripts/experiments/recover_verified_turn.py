"""Exercise verification, import, queue recovery and singing in the actual packaged host."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from test_session import Session
from karaoke.service import Service


def run(launcher, prediction):
    manifest = json.loads((prediction / "generation.json").read_text(encoding="utf-8"))
    video = manifest["video_id"]
    raw_hash = hashlib.sha256((prediction / "song.txt").read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="karaoke-release-turn-") as temp:
        root = Path(temp)
        # Reproduce a saved pending turn after the background worker has written its
        # raw prediction. The package under test makes every subsequent decision.
        host = Service(root)
        try:
            source = "youtube:" + video
            turn = host.store.request(
                source, {"kind": "youtube", "video_id": video}, ["Luna"], initial_state="error"
            )
            host.draft_turn = (turn, source, video)
            host.handle({"action": "field:generate_url", "value": "https://youtu.be/" + video})
            host.handle({"action": "lab:enqueue"})
            saved = host.store.rows("SELECT draft_id FROM draft_turns WHERE turn_id=?", (turn,))
            folder = host.lab.root / saved[0]["draft_id"] / "draft"
            shutil.copytree(prediction, folder)
            (folder / "verified.txt").unlink(missing_ok=True)
        finally:
            host.close()

        session = Session(
            root,
            [str(launcher.resolve())],
            {**os.environ, "SDL_AUDIODRIVER": "dummy", "SDL_AUDIO_DRIVER": "dummy"},
        )
        try:
            session.launch()
            session.wait(
                lambda _: any(t["id"] == turn and t["song_id"] for t in session.queue()), timeout=90
            )
            found = session.queue()
            assert len(found) == 1 and found[0]["names"] == '["Luna"]'
            assert found[0]["source"].startswith("verified:")
            chart = Path(
                session.rows("SELECT chart FROM songs WHERE id=?", (found[0]["song_id"],))[0][
                    "chart"
                ]
            )
            proof = json.loads((chart.parent / "generation.json").read_text(encoding="utf-8"))
            assert proof["verification"]["generated_sha256"] == raw_hash
            assert (
                proof["review"]["library_chart_sha256"]
                == hashlib.sha256(chart.read_bytes()).hexdigest()
            )
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
            session.wait(lambda _: not session.queue())
            return dict(
                video=video,
                source=proof["verification"]["source"],
                scoring=proof["verification"]["scoring"],
                raw_sha256=raw_hash,
                chart_sha256=proof["review"]["library_chart_sha256"],
                preserved_named_turn=True,
                native_position_s=round(state["position"], 3),
                synthetic_input=True,
            )
        finally:
            session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("launcher", "prediction", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(run(args.launcher, args.prediction), indent=2, ensure_ascii=False) + "\n"
    )
