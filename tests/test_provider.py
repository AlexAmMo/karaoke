"""Pin contract tests: real Syncer parsing/pipeline, only remote boundaries replaced."""

import datetime
import json
import subprocess
from pathlib import Path
import pytest
from karaoke import provider


@pytest.fixture
def usdb_song():
    return dict(
        song_id=42,
        usdb_mtime=1,
        artist="Fixture",
        title="Canción de prueba",
        genre="",
        year=None,
        language="Spanish",
        creator="Tests",
        edition="",
        golden_notes=False,
        rating=0.0,
        views=0,
        sample_url="",
        tags="",
    )


@pytest.fixture
def no_network(monkeypatch):
    import usdb_syncer.song_loader  # noqa: F401 - upstream bootstrap order
    import requests

    def forbidden(*args, **kwargs):
        raise AssertionError("A contract test attempted a real network request")

    monkeypatch.setattr(requests.Session, "request", forbidden)


def test_search_uses_syncer_filters_and_round_trips_metadata(
    tmp_path, monkeypatch, usdb_song, no_network
):
    from usdb_syncer import usdb_scraper, settings
    from usdb_syncer.usdb_song import UsdbSong

    calls = []

    def pages(order, descending, content_filter, session):
        calls.append((order, descending, content_filter))
        yield [UsdbSong.from_json(dict(usdb_song))]

    monkeypatch.setattr(usdb_scraper, "_get_songs_from_usdb", pages)
    result = provider.run(
        {"operation": "search", "root": str(tmp_path), "query": "Fixture - Canción"}
    )
    assert calls == [("rating", True, {"interpret": "Fixture", "title": "Canción"})]
    assert result["songs"] == [usdb_song]
    assert settings.get_audio_separation() is False
    assert settings.get_discord_allowed() is False
    assert settings.get_browser() is settings.Browser.NONE


def test_search_artist_or_title_deduplicates_results(tmp_path, monkeypatch, usdb_song, no_network):
    from usdb_syncer import usdb_scraper
    from usdb_syncer.usdb_song import UsdbSong

    calls = []

    def pages(order, descending, content_filter, session):
        calls.append(content_filter)
        yield [UsdbSong.from_json(dict(usdb_song))]

    monkeypatch.setattr(usdb_scraper, "_get_songs_from_usdb", pages)
    result = provider.run({"operation": "search", "root": str(tmp_path), "query": "Fixture"})
    assert calls == [{"interpret": "Fixture"}, {"title": "Fixture"}]
    assert len(result["songs"]) == 1


@pytest.mark.parametrize("fallback", [False, True])
def test_real_syncer_download_pipeline_prepares_local_media(
    tmp_path, package, monkeypatch, usdb_song, no_network, fallback
):
    from usdb_syncer import SongId, usdb_scraper, resource_dl

    details = usdb_scraper.SongDetails(
        song_id=SongId(42),
        artist="Fixture",
        title="Canción de prueba",
        cover_url=None,
        language="Spanish",
        year=None,
        genre="",
        edition="",
        bpm=120,
        gap=0,
        golden_notes=False,
        song_check=False,
        date_time=datetime.datetime(2026, 1, 1),
        uploader="Tests",
        editors=[],
        views=0,
        rating=0,
        votes=0,
        audio_sample=None,
    )
    notes = ("#VIDEO:v=yearlyTEST01\n" if not fallback else "") + package.read_text(
        encoding="utf-8"
    )
    if fallback:
        from types import SimpleNamespace

        details.comments = [
            SimpleNamespace(contents=SimpleNamespace(youtube_ids=["yearlyTEST01"], urls=[]))
        ]
    monkeypatch.setattr(usdb_scraper, "get_usdb_details", lambda _: details)
    monkeypatch.setattr(usdb_scraper, "get_notes", lambda *_: notes)

    def audio_download(resource, options, browser, path_stem, logger):
        assert resource == "yearlyTEST01"
        assert options.separation is False
        target = path_stem.with_suffix(".mp3")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(package.parent / "audio.wav"), str(target)],
            check=True,
        )
        return resource_dl.ResourceDLResult(content="mp3")

    monkeypatch.setattr(resource_dl, "download_audio", audio_download)
    request = {
        "operation": "download",
        "root": str(tmp_path / "syncer"),
        "destination": str(tmp_path / "download"),
        "song": usdb_song,
        "video": False,
        "progress": str(tmp_path / "progress.json"),
    }
    if fallback:
        with pytest.raises(ValueError, match="audio alternativo"):
            provider.run(request)
        return
    result = provider.run(request)
    assert (
        json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))["stage"] == "preparing"
    )
    from karaoke.songs import validate

    assert len(result["charts"]) == 1
    prepared = validate(Path(result["charts"][0]))
    assert prepared["title"] == "Canción de prueba"
    assert prepared["duration"] >= 4
    assert Path(prepared["audio"]).suffix == ".mp3"


def test_login_error_is_not_empty_search(tmp_path, monkeypatch, no_network):
    from usdb_syncer import errors, usdb_scraper

    def pages(*_):
        raise errors.UsdbLoginError()
        yield []

    monkeypatch.setattr(usdb_scraper, "_get_songs_from_usdb", pages)
    with pytest.raises(errors.UsdbLoginError):
        provider.run({"operation": "search", "root": str(tmp_path), "query": "Fixture"})


def test_video_resolution_cap_has_no_unbounded_fallback(no_network):
    from usdb_syncer import download_options, settings

    settings.set_video(True, temp=True)
    settings.set_video_resolution(settings.VideoResolution.P720, temp=True)
    original = download_options.download_options().video_options
    bounded = provider._bounded_video_options(original)
    assert bounded.max_resolution is settings.VideoResolution.P720
    alternatives = bounded.ytdl_format().split("/")
    assert alternatives
    assert all("[height<=720]" in part and "[width<=1280]" in part for part in alternatives)


def test_download_progress_measures_resource_bytes_without_inventing_total(tmp_path):
    target = tmp_path / "progress.json"
    progress = provider.PreparationProgress(str(target), tmp_path)
    progress.download({"status": "downloading", "downloaded_bytes": 25, "total_bytes": 100})
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result["percent"] == 25
    assert result["estimated"] is False
    progress.download({"status": "downloading", "downloaded_bytes": 25})
    assert "percent" not in json.loads(target.read_text(encoding="utf-8"))
    progress.postprocess({"status": "started"})
    assert json.loads(target.read_text(encoding="utf-8"))["stage"] == "preparing"
    assert not list(tmp_path.glob("*.tmp"))


def test_progress_hooks_do_not_leak_across_jobs(tmp_path, no_network):
    from usdb_syncer import resource_dl, settings

    progress = provider.PreparationProgress(None, tmp_path)
    original = resource_dl._ytdl_options
    with provider._report_downloads(resource_dl, progress):
        options = resource_dl._ytdl_options(
            "best", settings.Browser.NONE, tmp_path / "file", settings.get_ytdlp_rate_limit()
        )
        assert options["progress_hooks"] == [progress.download]
        assert options["postprocessor_hooks"] == [progress.postprocess]
    assert resource_dl._ytdl_options is original


def test_worker_reads_utf8_protocol_even_with_legacy_console_encoding(tmp_path):
    import os
    import sys

    response = tmp_path / "response.json"
    invalid_resolution = "resolución inválida ñ"
    request = {
        "root": str(tmp_path / "worker"),
        "response": str(response),
        "operation": "search",
        "query": "fixture",
        "resolution": invalid_resolution,
    }
    process = subprocess.run(
        [sys.executable, "-m", "karaoke.provider"],
        input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"},
        timeout=30,
    )
    assert process.returncode == 0, process.stderr.decode("utf-8", errors="replace")
    assert invalid_resolution in json.loads(response.read_text(encoding="utf-8"))["error"]
