from pathlib import Path

import pytest
from PIL import Image

from karaoke.service import Service
from karaoke.songs import SongError, import_package


@pytest.fixture
def service(tmp_path):
    app = Service(tmp_path / "app")
    yield app
    app.close()


def save_song(service, song_id, title, chart=None):
    song = {
        "id": song_id,
        "title": title,
        "artist": "Fixture",
        "chart": str(chart or service.library / song_id / "song.txt"),
        "audio": str(service.library / song_id / "audio.wav"),
        "duration": 4,
    }
    service.store.save_song(song)
    return song


def selected(carousel):
    return carousel["songs"][carousel["index"]]["id"]


def test_imported_cover_is_real_local_image_in_managed_package(service, package):
    image = package.parent / "art" / "portada.png"
    image.parent.mkdir()
    Image.new("RGB", (24, 24), "blue").save(image)
    package.write_text(
        "#COVER:art/portada.png\n" + package.read_text(encoding="utf-8"), encoding="utf-8"
    )
    song = import_package(package, service.library)
    service.store.save_song(song)
    carousel = service.view()["carousel"]
    assert carousel["total"] == 1
    assert carousel["has_previous"] is False
    assert carousel["has_next"] is False
    assert carousel["songs"] == [{
        "id": song["id"], "title": "Canción de prueba", "artist": "Fixture",
        "cover": str(Path(song["chart"]).parent / "art/portada.png"),
    }]
    # Missing or externally replaced artwork invalidates cached image metadata.
    cover = Path(carousel["songs"][0]["cover"])
    cover.write_bytes(b"not an image")
    assert service.view()["carousel"]["songs"][0]["cover"] == ""
    Image.new("RGB", (32, 32), "red").save(cover)
    assert service.view()["carousel"]["songs"][0]["cover"] == str(cover)
    cover.unlink()
    assert service.view()["carousel"]["songs"][0]["cover"] == ""


@pytest.mark.parametrize("kind", ["missing", "corrupt", "traversal", "absolute", "remote", "oversized"])
def test_carousel_never_exposes_invalid_or_outside_cover(service, package, kind):
    cover = package.parent / "cover.png"
    Image.new("RGB", (24, 24), "blue").save(cover)
    name = "cover.png"
    if kind == "missing":
        cover.unlink()
    elif kind == "corrupt":
        cover.write_bytes(b"not an image")
    elif kind == "traversal":
        outside = package.parent.parent / "outside.png"
        Image.new("RGB", (24, 24), "blue").save(outside)
        name = "../outside.png"
    elif kind == "absolute":
        name = str(cover.resolve())
    elif kind == "remote":
        name = "https://example.invalid/cover.png"
    elif kind == "oversized":
        Image.new("RGB", (4097, 1), "blue").save(cover)
    # Models a library chart edited after import; view must independently check
    # containment and image validity instead of trusting the old import result.
    package.write_text(
        f"#COVER:{name}\n" + package.read_text(encoding="utf-8"), encoding="utf-8"
    )
    save_song(service, "edited", "Edited package", package)
    assert service.view()["carousel"]["songs"][0]["cover"] == ""


def test_bounded_carousel_reaches_entire_library_without_changing_panel_or_song(service):
    for number in range(30):
        save_song(service, str(number), f"Song {number:03}")
    service.page = "Cola"
    service.engine = {"state": "singing", "token": "active-turn", "scores": [123]}
    visited = []
    for number in range(30):
        carousel = service.view()["carousel"]
        assert carousel["total"] == 30
        assert 1 <= len(carousel["songs"]) <= 5
        assert selected(carousel) == str(number)
        assert carousel["has_previous"] == (number > 0)
        assert carousel["has_next"] == (number < 29)
        visited.append(selected(carousel))
        service.handle({"action": "carousel:next"})
    assert len(set(visited)) == 30
    assert selected(service.view()["carousel"]) == "29"  # No wrap at the end.
    service.handle({"action": "carousel:previous"})
    assert selected(service.view()["carousel"]) == "28"
    assert service.page == "Cola"
    assert service.engine == {"state": "singing", "token": "active-turn", "scores": [123]}
    assert list((service.ipc / "commands").glob("*.json")) == []
    service.page = "Biblioteca"
    song_rows = [row for row in service.view()["rows"] if row.get("action", "").startswith("song:")]
    assert len(song_rows) <= 5


def test_selection_is_stable_after_insert_and_enqueue_reuses_existing_package(service):
    save_song(service, "one", "B song")
    save_song(service, "two", "C song")
    service.handle({"action": "carousel:select:two"})
    service.page = "Ajustes"
    save_song(service, "before", "A song")
    assert selected(service.view()["carousel"]) == "two"
    service.fields.update(player1="Ana", player2="José")
    service.handle({"action": "carousel:enqueue"})
    assert service.page == "Ajustes"
    assert len(service.store.queue()) == 1
    assert service.store.queue()[0]["song_id"] == "two"
    assert service.store.queue()[0]["state"] == "queued"
    assert service.store.rows("SELECT * FROM jobs") == []
    assert list((service.ipc / "commands").glob("*.json")) == []
    service.handle({"action": "song:one"})
    assert selected(service.view()["carousel"]) == "one"
    assert service.page == "Canción"


def test_filter_and_stale_selection_never_enqueue_a_different_song(service):
    assert service.view()["carousel"] == {
        "songs": [], "index": 0, "total": 0, "has_previous": False, "has_next": False,
    }
    save_song(service, "spanish", "Canción española")
    save_song(service, "english", "English song")
    service.handle({"action": "field:local", "value": "cancion"})
    carousel = service.view()["carousel"]
    assert carousel["total"] == 1
    assert selected(carousel) == "spanish"
    with pytest.raises(SongError):
        service.handle({"action": "carousel:select:english"})
    service.store.execute("DELETE FROM songs WHERE id=?", ("spanish",))
    with pytest.raises(SongError):
        service.handle({"action": "carousel:enqueue"})
    assert service.store.queue() == []
    assert service.store.rows("SELECT * FROM jobs") == []
    assert service.view()["carousel"]["songs"] == []
