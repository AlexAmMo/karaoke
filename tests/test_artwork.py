import io
import json
import threading
from pathlib import Path

import pytest
from PIL import Image

from karaoke import artwork


def picture():
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360), color="blue").save(buffer, format="PNG")
    return buffer.getvalue()


def resolved(resolver, song):
    resolver.get(song)
    with resolver.condition:
        assert resolver.condition.wait_for(lambda: not resolver.active and not resolver.queue, 4)
    return resolver.get(song)


def test_async_thumbnail_reuses_source_offline_without_changing_package(tmp_path, monkeypatch):
    source = tmp_path / "audio.mp3"
    source.write_bytes(b"test")
    song = dict(id="local", source="usdb:21", artist="Test", title="Song", audio=str(source))
    folder = tmp_path / "cache"
    resolver = artwork.ArtworkResolver(folder)
    started, release = threading.Event(), threading.Event()
    requests = []

    def fetch(url):
        requests.append(url)
        started.set()
        assert release.wait(4)
        return picture()

    monkeypatch.setattr(resolver, "_fetch", fetch)
    try:
        assert resolver.get(song)["path"] == ""
        assert started.wait(timeout=2)
        assert resolver.get(song)["path"] == ""
        release.set()
        art = resolved(resolver, song)
        assert art["kind"] == "Portada de USDB"
        assert requests == ["https://usdb.animux.de/data/cover/21.jpg"]
        with Image.open(art["path"]) as image:
            assert image.format == "JPEG" and image.size == (600, 600)
        assert source.read_bytes() == b"test"
    finally:
        release.set()
        resolver.close()
    reopened = artwork.ArtworkResolver(folder)
    assert reopened.get(song) == art
    assert reopened.worker is None
    assert reopened.get(song, local_cover="/managed/local.png")["path"] == "/managed/local.png"
    reopened.close()


def test_embedded_beats_provider_even_if_result_was_negatively_cached(tmp_path, monkeypatch):
    resolver = artwork.ArtworkResolver(tmp_path)
    network = []
    monkeypatch.setattr(resolver, "_fetch", lambda url, *args: network.append(url))
    monkeypatch.setattr(artwork, "_embedded", lambda path: picture() if path else None)
    search = dict(source="usdb:2", artist="Unknown", title="Unknown")
    local = dict(search, audio="/local/track.mp3")
    try:
        assert resolved(resolver, search) == artwork.MISSING
        prior = list(network)
        assert prior
        assert resolved(resolver, local)["kind"] == "Portada del audio"
        assert network == prior
    finally:
        resolver.close()


@pytest.fixture
def recording():
    artist = {"name": "Band", "artist": {"id": "10000000-0000-0000-0000-000000000001"}}

    def release(n, kind, **fields):
        return {
            "status": "Official",
            "artist-credit": [artist],
            "release-group": {
                "id": f"20000000-0000-0000-0000-{n:012d}",
                "primary-type": kind,
                "title": "Test" if kind == "Single" else "Debut",
                **fields,
            },
        }

    return {
        "title": "Test",
        "length": 100000,
        "artist-credit": [artist],
        "releases": [
            release(1, "Album"),
            release(2, "Single"),
            release(3, "Album", **{"secondary-types": ["Live"]}),
        ],
    }


def test_release_selection_requires_artist_edition_and_unambiguous_group(recording):
    response = {"recordings": [recording]}
    song = {"title": "Test", "artist": "Bánd", "duration": 100}
    choices, artist = artwork._release_choices(response, song)
    assert [tier for tier, _ in choices] == ["Single", "Album"]
    assert artist
    assert artwork._release_choices(response, dict(song, artist="Other")) == ([], "")
    assert artwork._release_choices(response, dict(song, duration=200)) == ([], artist)
    album = recording["releases"][0]["release-group"].copy()
    album["id"] = "20000000-0000-0000-0000-000000000009"
    recording["releases"].append({"status": "Official", "release-group": album})
    assert [tier for tier, _ in artwork._release_choices(response, song)[0]] == ["Single"]


def test_portrait_from_artist_identity_preserves_author_and_license(
    tmp_path, monkeypatch, recording
):
    resolver = artwork.ArtworkResolver(tmp_path)
    recording["releases"] = []

    def fetch(url, *args):
        if "/ws/2/recording" in url:
            response = {"recordings": [recording]}
        elif "/ws/2/artist" in url:
            response = {
                "relations": [
                    {"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q55"}}
                ]
            }
        elif "wikidata.org/w/api.php" in url:
            response = {"claims": {"P18": [{"mainsnak": {"datavalue": {"value": "Band.jpg"}}}]}}
        elif "commons.wikimedia.org/w/api.php" in url:
            response = {
                "query": {
                    "pages": {
                        "1": {
                            "imageinfo": [
                                {
                                    "thumburl": "https://upload.wikimedia.org/thumb/test.jpg",
                                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Band.jpg",
                                    "extmetadata": {
                                        "Artist": {"value": "<b>Ana</b>"},
                                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        else:
            assert url == "https://upload.wikimedia.org/thumb/test.jpg"
            return picture()
        return json.dumps(response).encode()

    monkeypatch.setattr(resolver, "_fetch", fetch)
    try:
        art = resolved(resolver, {"artist": "Band", "title": "Test"})
        assert art["kind"] == "Foto del artista"
        assert art["credit"] == "Ana" and art["license"] == "CC BY-SA 4.0"
        assert Path(art["path"]).is_file() and art["url"].endswith("File:Band.jpg")
    finally:
        resolver.close()


def test_current_search_precedes_starter_thumbnails_without_starving_library(tmp_path, monkeypatch):
    resolver = artwork.ArtworkResolver(tmp_path)
    started, release = threading.Event(), threading.Event()
    calls = []

    def resolve(song):
        calls.append(song["title"])
        started.set()
        assert release.wait(3)

    def request(title, search=""):
        resolver.get({"artist": "Band", "title": title}, search=search)

    monkeypatch.setattr(resolver, "_resolve", resolve)
    try:
        request("Active")
        assert started.wait(2)
        request("Library")
        request("Previous query", "old")
        for i in range(4):
            request(str(i), "new")
        release.set()
        with resolver.condition:
            assert resolver.condition.wait_for(lambda: not resolver.active and not resolver.queue, 4)
        assert calls == ["Active", "0", "1", "2", "Library", "3", "Previous query"]
    finally:
        release.set()
        resolver.close()
