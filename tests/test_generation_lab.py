from pathlib import Path
import shutil
import requests
from karaoke.service import Service
from karaoke.draft_review import DraftEditor
from karaoke.songs import validate


def test_review_is_bound_to_draft_and_audio(tmp_path, package):
    host = Service(tmp_path / "host")
    lab = host.lab
    try:
        uid = lab.enqueue("IA0uSub1xy4", "Título", "Artista", "es", "standard")
        assert lab.enqueue("IA0uSub1xy4", "Título", "Artista", "es", "standard") == uid
        assert not host.store.queue()
        folder = lab.root / uid / "draft"
        shutil.copytree(package.parent, folder)
        chart = folder / "song.txt"
        audio = Path(validate(chart)["audio"])
        host.store.execute("UPDATE drafts SET state='review' WHERE id=?", (uid,))
        ed = DraftEditor(lab, uid)
        lab.editor = ed
        api = ed.url + "chart"
        snap = requests.get(api).json()
        assert requests.get(ed.origin + "/invalid/chart").status_code == 404
        assert requests.post(api, json={"approve": True}).status_code == 403
        partial = requests.get(ed.url + "audio", headers={"Range": "bytes=0-15"})
        assert partial.status_code == 206 and len(partial.content) == 16
        assert partial.content == audio.read_bytes()[:16]
        response = requests.post(
            api, headers={"Origin": ed.origin}, json={**snap, "body": "#MP3:bad\nE"}
        )
        assert response.status_code == 400
        overlap = snap["body"].replace(": 0 ", ": 1 ", 1)
        rejected = requests.post(
            api, headers={"Origin": ed.origin}, json={"body": overlap, "revision": snap["revision"]}
        )
        assert rejected.status_code == 400 and "solapan" in rejected.json()["error"]
        edited = snap["body"].replace(": 0 8 ", ": 1 7 ", 1)
        changed = requests.post(
            api, headers={"Origin": ed.origin}, json={"body": edited, "revision": snap["revision"]}
        )
        changed.raise_for_status()
        confirmed = requests.post(
            api,
            headers={"Origin": ed.origin},
            json={"body": edited, "revision": changed.json()["revision"], "approve": True},
        )
        confirmed.raise_for_status()
        assert (
            confirmed.json()["state"] == "approved"
            and len(host.store.rows("SELECT * FROM songs")) == 1
        )
        stale = requests.post(
            api, headers={"Origin": ed.origin}, json={"body": edited, "revision": snap["revision"]}
        )
        assert stale.status_code == 400
        assert not host.store.queue()
    finally:
        host.close()


def test_worker_progress_pauses_while_singing_and_resumes(tmp_path):
    import sys
    import time
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import patch

    host = Service(tmp_path / "host")
    lab = host.lab
    script = tmp_path / "analyze.py"
    marker = tmp_path / "completed"
    script.write_text(
        "import json,sys,time\nfrom pathlib import Path\n"
        'print(json.dumps({"stage":"Analizando la melodía"}),flush=True)\n'
        "while not Path(sys.argv[1]).exists():time.sleep(.02)\n"
        'Path(sys.argv[2]).write_text("ok")\n'
    )
    with ThreadPoolExecutor(max_workers=1) as pool, patch("karaoke.generation_lab.WORKER", script):
        try:
            uid = lab.enqueue("IA0uSub1xy4", "Prueba", "", "es", "quality")
            lab.current = uid
            host.store.execute("UPDATE drafts SET state='working' WHERE id=?", (uid,))
            release = tmp_path / "resume"
            task = pool.submit(
                lab.run, [sys.executable, script, release, marker], lab.row(uid), tmp_path / "log"
            )
            deadline = time.monotonic() + 8
            while (
                lab.row(uid)["message"] != "Analizando la melodía" and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            assert lab.row(uid)["message"] == "Analizando la melodía"
            lab.pause_analysis(True)
            assert "pausa" in lab.row(uid)["message"]
            release.touch()
            time.sleep(0.15)
            assert not marker.exists()
            lab.pause_analysis(False)
            task.result(timeout=5)
            assert marker.read_text() == "ok"
        finally:
            lab.pause_analysis(False)
            (tmp_path / "resume").touch()
            host.close()
