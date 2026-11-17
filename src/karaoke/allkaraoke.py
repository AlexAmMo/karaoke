"""Read a pinned chart catalogue. Each map stays bound to its own video and timings."""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from urllib.parse import parse_qs, quote, urlsplit

import requests

from . import catalog
from .songs import SongError, duration, read_chart

REVISION = "978f076b8b8b6641057ba16a66693155aedc2cf2"
BASE = f"https://raw.githubusercontent.com/Asvarox/allkaraoke/{REVISION}/public/songs/"
INDEX_SHA = "f3591b4a2fdb42b768286d277383f61ceb47a01c45f464c22f6380dd209b1d97"
_LOCK = threading.Lock()


def fetch(url, limit):
    with requests.get(url, stream=True, timeout=(5, 15)) as response:
        response.raise_for_status()
        value = bytearray()
        for block in response.iter_content(65536):
            value.extend(block)
            if len(value) > limit:
                raise SongError("El recurso de catálogo excede el tamaño esperado.")
        return bytes(value)


@functools.lru_cache(maxsize=2)
def _index(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"allkaraoke-{REVISION}.json"
    raw = path.read_bytes() if path.is_file() and path.stat().st_size < 8_000_000 else b""
    if hashlib.sha256(raw).hexdigest() != INDEX_SHA:
        raw = fetch(BASE + "index.json", 8_000_000)
        if hashlib.sha256(raw).hexdigest() != INDEX_SHA:
            raise SongError("El índice de AllKaraoke no coincide con la revisión esperada.")
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as tmp:
            tmp.write(raw)
        os.replace(tmp.name, path)
    songs = []
    for row in json.loads(raw):
        if not row["artist"] or not row["title"] or not row.get("video"):
            continue
        songs.append({
            "source": "allkaraoke:" + row["id"], "artist": row["artist"], "title": row["title"],
            "language": ", ".join(row.get("language") or []), "creator": row.get("author") or "",
            "video_id": row["video"], "reference_duration": row.get("duration"),
            "tracks": row.get("tracksCount"), "origin": row.get("sourceUrl") or "",
        })
    return songs


def search(query, directory, video_id=None):
    with _LOCK:
        songs = _index(directory)
    if video_id:
        return [s for s in songs if s["video_id"] == video_id]
    if not catalog.tokens(query):
        return []
    return sorted((s for s in songs if catalog.matches(query, s)), key=lambda s: catalog.rank(query, s))


def load_chart(song, directory):
    key = song["source"].removeprefix("allkaraoke:")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", key) or not re.fullmatch(r"[\w-]{11}", song["video_id"], re.ASCII):
        raise SongError("Identificador de edición no válido.")
    chart = directory / "song.txt"
    chart.write_bytes(fetch(BASE + quote(key, safe="") + ".txt", 8_000_000))
    text, meta = read_chart(chart)
    if (meta["ARTIST"], meta["TITLE"]) != (song["artist"], song["title"]):
        raise SongError("La identidad del mapa difiere de la ficha elegida.")
    if meta.get("VIDEO") != "v=" + song["video_id"] or not re.search(
        r"^#ALLKARAOKE_ID:" + re.escape(key) + r"\s*$", text, re.M
    ):
        raise SongError("La grabación declarada en el mapa difiere de la ficha.")
    return chart


def download_recording(song, directory, guard):
    from yt_dlp import YoutubeDL

    video = song["video_id"]
    opts = {"quiet": True, "noprogress": True, "no_warnings": True, "noplaylist": True, "format": "bestaudio/best",
            "outtmpl": str(directory / "recording.%(ext)s"), "socket_timeout": 12,
            "retries": 1, "extractor_retries": 1, "fragment_retries": 1,
            "max_filesize": 200 * 1024**2, "progress_hooks": [guard],
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                "preferredquality": "192"}]}
    with YoutubeDL(opts) as dl:
        info = dl.extract_info("https://www.youtube.com/watch?v=" + video, download=True)
    if not info or info.get("id") != video:
        raise SongError("El proveedor devolvió otra grabación.")
    return directory / "recording.mp3"


def prepare_review(song, directory, guard, local=None):
    chart = load_chart(song, directory)
    if local:
        local = Path(local)
        if local.stat().st_size > 512 * 1024**2 or not local.is_file():
            raise SongError("El archivo de audio no es compatible.")
        guard(None)
        audio = directory / ("recording" + local.suffix.lower())
        shutil.copyfile(local, audio)
    else:
        audio = download_recording(song, directory, guard)
    actual = duration(audio)
    expected = song.get("reference_duration")
    if local and not expected:
        raise SongError("La ficha carece de duración de referencia. Prepara el vídeo exacto del mapa.")
    if not math.isfinite(actual) or (expected and abs(actual - expected) > 2):
        raise SongError("La duración difiere de la grabación de referencia. Selecciona la edición exacta.")
    _, meta = read_chart(chart)
    if meta["end_seconds"] > actual + 0.1:
        raise SongError("La grabación termina antes que las notas.")
    return chart, audio

def source_usdb_id(song):
    """Match a publisher attribution, without following arbitrary source URLs."""
    ref = urlsplit(song.get("origin") or "")
    if ref.hostname != "usdb.animux.de" or ref.path != "/index.php":
        return None
    values = parse_qs(ref.query).get("id", [])
    return "usdb:" + values[0] if len(values) == 1 and values[0].isdigit() else None
