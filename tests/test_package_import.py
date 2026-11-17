import os
from pathlib import Path
import zipfile

import pytest

from karaoke.package_import import chart_index
from karaoke.service import Service
from karaoke.songs import SongError


def test_zip_selection_retains_nested_media(package, tmp_path):
    z = tmp_path / "collection.zip"
    with zipfile.ZipFile(z, "w") as out:
        for prefix in ("One", "Two"):
            out.write(package, prefix + "/song.txt")
            out.write(package.parent / "audio.wav", prefix + "/audio.wav")
        out.writestr("license.txt", "Test collection")
    assert [name for name, _ in chart_index(z)] == ["One/song.txt", "Two/song.txt"]
    s = Service(tmp_path / "app")
    try:
        s.add_import(str(z))
        future, completion = s.futures.pop()
        completion(future.result(timeout=4))
        s.handle({"action": "import:toggle:0"})
        s.handle({"action": "import:zip"})
        jobs = s.store.rows("select * from jobs")
        assert len(jobs) == 1 and "Two/song.txt" in jobs[0]["payload"]
        assert Path(s.prepare(jobs[0])["audio"]).is_file()
        stamp = z.stat()
        os.utime(z, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 2_000_000_000))
        with pytest.raises(SongError, match="cambiado"):
            s.prepare(jobs[0])
    finally:
        s.close()


@pytest.mark.parametrize(
    "name", ["../escape.txt", "C:/outside.wav", "sub/CON.txt", "sub/../../escape.txt"]
)
def test_archive_paths_are_portable_and_contained(tmp_path, name):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as out:
        out.writestr(name, "unused")
    with pytest.raises(SongError):
        chart_index(z)


def test_missing_recording_can_be_paired_without_modifying_chart(package, tmp_path, monkeypatch):
    data = package.read_text().replace("audio.wav", "unavailable.mp3")
    package.write_text(data)
    service = Service(tmp_path / "app")
    try:
        service.add_import(str(package))
        assert service.page == "Asociar grabación"
        service.handle({"action": "field:pair_audio", "value": str(package.parent / "audio.wav")})
        assert "import:listen:1" in [r.get("action") for r in service.view()["rows"]]
        with pytest.raises(SongError, match="fragmentos"):
            service.handle({"action": "import:pair"})
        from types import SimpleNamespace
        from karaoke import package_import, sync_review

        clock = [100.0]
        monkeypatch.setattr(package_import, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        monkeypatch.setattr(
            sync_review, "play_review", lambda *args: SimpleNamespace(poll=lambda: 0)
        )
        for i in range(len(service.pair_points)):
            service.handle({"action": f"import:listen:{i}"})
            clock[0] += 10
        assert service.pair_points[0].caption == "sí"
        service.handle({"action": "import:pair"})
        song = service.prepare(service.store.rows("select * from jobs")[0])
        assert song["title"] == "Canción de prueba"
        assert Path(song["audio"]).exists()
        assert package.read_text() == data
    finally:
        service.close()


def test_tempo_change_ignored_by_deluxe_cannot_silently_drift(package):
    from karaoke.songs import read_chart

    text = package.read_text()
    package.write_text(text.replace("- 8", "B 8 180\n- 8"))
    with pytest.raises(SongError, match="cambia de tempo"):
        read_chart(package)
    package.write_text(text.replace("- 8", "B 8 120\n- 8"))
    assert read_chart(package)[1]["BPM"] == "120"


def test_reviewed_files_cannot_be_swapped_while_queued(package, tmp_path):
    from karaoke.package_import import prepare_local, signature

    audio = package.with_name("audio.wav")
    payload = dict(
        kind="paired",
        chart=str(package),
        audio=str(audio),
        review_signatures=[signature(package), signature(audio)],
    )
    audio.write_bytes(audio.read_bytes() + b"changed")
    with pytest.raises(SongError, match="cambiado"):
        prepare_local(payload, tmp_path)
