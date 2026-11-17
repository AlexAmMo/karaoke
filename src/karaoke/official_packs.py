"""Fetch the exact chart, audio, credits and visuals of an official vocal edition."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote

import requests

from .official_pack_manifest import PACKAGES
from .songs import SongError

REVISION = "c9246c799050acec96a03183df4b85493d283d51"
RAW_URL = f"https://raw.githubusercontent.com/UltraStar-Deluxe/songs/{REVISION}/Creative%20Commons/"
STARTERS = {
    key: (artist, title, license_name)
    for key, (_, artist, title, _, license_name, _) in PACKAGES.items()
}


def official_songs():
    for key, (_, artist, title, language, license_name, _) in PACKAGES.items():
        yield {
            "source": "deluxe:" + key,
            "title": title,
            "artist": artist,
            "language": language,
            "license": license_name,
            "match": "Paquete con voz original",
        }


def download_starter(key: str, destination: Path, progress) -> Path:
    if key not in PACKAGES:
        raise SongError("Este paquete ya no está en el catálogo de inicio.")
    directory, _, title, _, _, files = PACKAGES[key]
    package = destination / key
    package.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        for name, (size, expected) in files.items():
            progress.check_space()
            progress.write("downloading", f"Descargando {title} · {name}")
            url = RAW_URL + quote(directory + "/" + name)
            digest = hashlib.sha256()
            received = 0
            with NamedTemporaryFile(dir=package, delete=False) as tmp:
                pending = Path(tmp.name)
            try:
                with session.get(url, stream=True, timeout=(8, 20)) as response:
                    response.raise_for_status()
                    with pending.open("wb") as out:
                        for block in response.iter_content(128 * 1024):
                            received += len(block)
                            if received > size:
                                raise SongError("El tamaño del recurso difiere de la edición publicada.")
                            out.write(block)
                            digest.update(block)
                if received != size or digest.hexdigest() != expected:
                    raise SongError(
                        "El paquete no coincide con la edición publicada. Reintenta la preparación."
                    )
                pending.replace(package / name)
            finally:
                pending.unlink(missing_ok=True)
    chart = package / "song.txt"
    if key == "wasteland-wailers-dare-master":
        # The pinned chart names an absent decoration. Keep every byte of its notes,
        # timing and media declarations, including line endings, except that header.
        lines = chart.read_bytes().splitlines(keepends=True)
        chart.write_bytes(b"".join(
            line for line in lines if line.rstrip(b"\r\n") != b"#BACKGROUND:background.png"
        ))
    return chart
