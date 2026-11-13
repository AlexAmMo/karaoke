from collections import namedtuple
from pathlib import Path
import pytest
from karaoke.songs import SongError, import_package, normalize, resource, validate


def test_import_is_validated_copied_and_idempotent(package, tmp_path):
    library = tmp_path / "library"
    original = package.read_bytes()
    first = import_package(package, library)
    second = import_package(package, library)
    third = import_package(Path(first["chart"]), library)
    assert first["id"] == second["id"] == third["id"]
    assert first["title"] == "Canción de prueba"
    assert Path(first["audio"]).is_file()
    assert first["duration"] == pytest.approx(4)
    assert len(list(library.iterdir())) == 1
    assert package.read_bytes() == original


@pytest.mark.parametrize(
    "name",
    [
        "../secret.wav",
        "/tmp/secret.wav",
        "C:/secret.wav",
        "C:\\secret.wav",
        "\\\\server\\secret.wav",
    ],
)
def test_media_cannot_escape_package(package, name):
    with pytest.raises(SongError):
        resource(package.parent, name)


def test_absolute_path_inside_package_is_rejected(package):
    with pytest.raises(SongError):
        resource(package.parent, str(package.parent / "audio.wav"))


def test_symlink_outside_package_rejected(package, tmp_path):
    external = tmp_path / "external.wav"
    external.write_bytes(b"not a song")
    (package.parent / "linked.wav").symlink_to(external)
    with pytest.raises(SongError):
        resource(package.parent, "linked.wav")


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("#BPM:120", "#BPM:NaN"),
        lambda s: s.replace("#GAP:0", "#GAP:Infinity"),
        lambda s: s.replace(": 0 8 21", ": 0 0 21"),
        lambda s: s.replace("E\n", ""),
        lambda s: s + "P2\n: 0 8 21 Other\n",
        lambda s: "#RELATIVE:YES\n" + s,
    ],
)
def test_incompatible_or_malformed_charts_fail_before_import(package, tmp_path, change):
    package.write_text(change(package.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    with pytest.raises(SongError):
        import_package(package, tmp_path / "library")
    assert not (tmp_path / "library").exists()


def test_audio_must_cover_notes(package):
    package.write_text(
        package.read_text(encoding="utf-8").replace(": 8 8 21", ": 80 8 21"),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(SongError, match="acaba antes"):
        validate(package)


def test_missing_media_does_not_become_ready(package):
    (package.parent / "audio.wav").unlink()
    with pytest.raises(SongError):
        validate(package)


def test_low_disk_stops_import_without_partial_package(package, tmp_path, monkeypatch):
    import karaoke.songs as songs

    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(songs.shutil, "disk_usage", lambda _: usage(100, 99, 1))
    library = tmp_path / "library"
    with pytest.raises(SongError, match="espacio"):
        import_package(package, library)
    assert list(library.iterdir()) == []


def test_legacy_encoding_and_accent_search(package, tmp_path):
    package.write_bytes(package.read_text(encoding="utf-8").encode("cp1252"))
    imported = import_package(package, tmp_path / "library")
    assert validate(Path(imported["chart"]))["title"] == "Canción de prueba"
    assert normalize("CANCIÓN de PRUEBA") == "cancion de prueba"


def test_line_endings_do_not_create_duplicate_packages(package, tmp_path):
    library = tmp_path / "library"
    first = import_package(package, library)
    package.write_bytes(package.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    second = import_package(package, library)
    assert first["id"] == second["id"]


def test_external_deletion_does_not_mark_corrupt_library_package_ready(package, tmp_path):
    library = tmp_path / "library"
    first = import_package(package, library)
    Path(first["audio"]).unlink()
    with pytest.raises(SongError):
        import_package(package, library)
