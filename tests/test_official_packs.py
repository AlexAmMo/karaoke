import hashlib
from contextlib import nullcontext

import pytest

from karaoke import catalog, official_packs
from karaoke.official_pack_manifest import PACKAGES
from karaoke.provider import PreparationProgress
from karaoke.songs import SongError


def test_official_search_uses_chart_metadata_and_original_assets():
    assert catalog.starter_songs("Dead Smiling Pirates")[0]["title"] == "I 18"
    assert catalog.starter_songs("Systemabsturz")[0]["language"] == "German"
    assert catalog.starter_songs("Joshua Morin")[0]["source"] == "deluxe:on-the-run"
    assert catalog.starter_songs("Northern Star")[0]["source"] == "deluxe:northern-star"
    assert len(catalog.starter_songs()) == 39
    for _, _, _, _, _, files in PACKAGES.values():
        assert {"song.txt", "license.txt"} <= files.keys()
        assert all("instrumental" not in name for name in files)
        assert all(size > 0 and len(digest) == 64 for size, digest in files.values())


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass

    def iter_content(self, _):
        yield self.content


def test_official_download_accepts_only_pinned_bytes_before_adapting_missing_background(tmp_path, monkeypatch):
    key = "wasteland-wailers-dare-master"
    raw = b"#BACKGROUND:background.png\r\n#MP3:audio.mp3\r\n: 0 1 2 a\r\nE\r\n"
    manifest = {"song.txt": (len(raw), hashlib.sha256(raw).hexdigest())}
    monkeypatch.setitem(PACKAGES, key, ("folder", "artist", "title", "", "", manifest))

    class Session:
        content = raw

        def get(self, url, **options):
            assert url.endswith("/folder/song.txt") and options["stream"]
            return nullcontext(FakeResponse(self.content))

    session = Session()
    monkeypatch.setattr(official_packs.requests, "Session", lambda: nullcontext(session))
    progress = PreparationProgress(None, tmp_path)
    chart = catalog.download_starter(key, tmp_path, progress)
    assert chart.read_bytes() == raw.split(b"\r\n", 1)[1]

    session.content = raw.replace(b"0 1 2", b"0 1 3")
    with pytest.raises(SongError, match="edición publicada"):
        catalog.download_starter(key, tmp_path, progress)
    assert chart.read_bytes() == raw.split(b"\r\n", 1)[1]
