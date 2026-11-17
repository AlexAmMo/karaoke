import json
import sys
import time
import zipfile
from pathlib import Path

import pytest

from karaoke import service as service_module
from karaoke import spanish_picker
from karaoke.service import Service


def test_picker_links_to_exact_song_and_accepts_publisher_downloads():
    assert spanish_picker.search_url({"artist": "Mulán", "title": "A & B"}).endswith(
        "artista=Mul%C3%A1n&cancion=A+%26+B"
    )
    assert spanish_picker.publisher_url("https://ultrastar-es.org/foro/ucp.php")
    assert not spanish_picker.publisher_url("https://ultrastar-es.org@example.org/")
    assert not spanish_picker.publisher_url("file:///etc/hosts")
    assert spanish_picker.download_kind("notes.txt", "text/plain") == ""
    assert spanish_picker.download_kind("edition", "application/x-bittorrent") == "torrent"


@pytest.mark.parametrize("cancel", [True, False])
def test_picker_to_library_without_external_browser(tmp_path, package, monkeypatch, cancel):
    app = Service(tmp_path / "app")
    zipped = tmp_path / "provider.zip"
    with zipfile.ZipFile(zipped, "w") as archive:
        for member in (package, package.parent / "audio.wav"):
            archive.write(member, member.name)
    picker = tmp_path / "provider.py"
    picker.write_text(
        "import json,shutil,sys\nfrom pathlib import Path\nr=json.load(sys.stdin)\n"
        + (
            ""
            if cancel
            else f"shutil.copyfile({str(zipped)!r},Path(r['destination'])/'edition.zip')\n"
        )
        + "Path(r['response']).write_text("
        + repr(
            json.dumps({"status": "cancelled"} if cancel else {"status": "selected", "kind": "zip"})
        )
        + ")\n"
    )
    monkeypatch.setattr(service_module, "child_command", lambda _: [sys.executable, str(picker)])
    # This fixture checks the real subprocess, staging, import, queue and cleanup.
    # Acoustic scoring of the transferred bytes is exercised by test_torrent_package.
    monkeypatch.setattr(service_module.acoustic, "require_alignment", lambda *_: None)
    app.results = [
        {"source": "community-es:example", "artist": "Fixture", "title": "Canción de prueba"}
    ]
    try:
        app.handle({"action": "result:obtain:0:community-es:example", "value": "gesture"})
        assert not app.store.queue() and not app.added_token
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            app.tick()
            jobs = app.store.rows("SELECT * FROM jobs")
            if app.spanish_picker is None and (
                cancel or (jobs and jobs[0]["state"] in ("ready", "error"))
            ):
                break
            time.sleep(0.03)
        assert app.spanish_picker is None
        if cancel:
            assert not app.added_token and not app.store.queue() and not jobs
        else:
            assert jobs[0]["state"] == "ready", jobs[0]["message"]
            assert app.added_token == "gesture"
            assert len(app.store.queue()) == 1
            song = app.song(app.store.queue()[0]["song_id"])
            assert song["verified"] and Path(song["audio"]).is_file()
        assert not list((app.root / "spanish-packages").iterdir())
    finally:
        app.close()
