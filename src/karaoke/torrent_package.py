"""Receive a publisher's package in staging and identify its exact UltraStar edition."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import libtorrent as lt

from . import acoustic, catalog
from .package_import import MAX_BYTES, MAX_MEMBERS, safe_name, zip_members
from .songs import SongError, read_chart, validate

MAX_TORRENT = 4 * 1024**2
STALL_SECONDS = 120
MAX_SECONDS = 30 * 60


def _edition(charts, song):
    expected = catalog.tokens(song["artist"]), catalog.tokens(song["title"])
    matches = []
    for chart in charts:
        try:
            _, meta = read_chart(chart)
        except (SongError, UnicodeError):
            continue
        if (catalog.tokens(meta["ARTIST"]), catalog.tokens(meta["TITLE"])) == expected:
            matches.append(chart)
    if len(matches) != 1:
        raise SongError("El paquete debe contener un único mapa de la edición elegida.")
    return matches[0]


def _check_recording(chart):
    info = validate(chart)
    acoustic.require_alignment(chart, Path(info["audio"]))
    return chart


def _space(directory, size):
    if size > MAX_BYTES or size * 2 + 256 * 1024**2 > shutil.disk_usage(directory).free:
        raise SongError("El paquete supera el límite de tamaño o el espacio disponible.")


def prepare_zip(archive: Path, destination: Path, song: dict) -> Path:
    """Extract only the selected map and media explicitly referenced by that map."""
    if archive.stat().st_size > MAX_BYTES:
        raise SongError("El ZIP supera los 2 GB.")
    work = Path(tempfile.mkdtemp(prefix="zip-", dir=destination))
    try:
        with zipfile.ZipFile(archive) as package:
            files = zip_members(package)
            _space(
                work,
                sum(
                    entry.file_size
                    for name, entry in files.items()
                    if name.lower().endswith(".txt") and entry.file_size <= 8_000_000
                ),
            )
            charts = {}
            for name, entry in files.items():
                if name.lower().endswith(".txt") and entry.file_size <= 8_000_000:
                    chart = work / name
                    chart.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(entry) as source, chart.open("xb") as target:
                        shutil.copyfileobj(source, target)
                    charts[chart] = name
            chart = _edition(charts, song)
            _, meta = read_chart(chart)
            names = {meta.get("AUDIO") or meta.get("MP3", "")}
            names.update(meta[key] for key in ("VIDEO", "COVER", "BACKGROUND") if meta.get(key))
            media = {}
            for name in names:
                path = chart.parent / safe_name(name)
                member = files.get(path.relative_to(work).as_posix())
                if not member or path in charts:
                    raise SongError("Falta un recurso del mapa seleccionado en el ZIP.")
                media[path] = member
            _space(work, sum(member.file_size for member in media.values()))
            for path, member in media.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, path.open("xb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
        return _check_recording(chart)
    except zipfile.BadZipFile:
        raise SongError("El ZIP de la edición está dañado.") from None


def _torrent_params(torrent_file, work):
    with torrent_file.open("rb") as file:
        data = file.read(MAX_TORRENT + 1)
    if len(data) > MAX_TORRENT:
        raise SongError("El archivo torrent de la edición es demasiado grande.")
    try:
        params = lt.load_torrent_buffer(
            data,
            {
                "max_buffer_size": MAX_TORRENT,
                "max_pieces": 131072,
                "max_decode_depth": 48,
                "max_decode_tokens": 100000,
            },
        )
    except (RuntimeError, ValueError):
        raise SongError("La descarga no contiene un archivo torrent válido.") from None
    layout = params.ti.layout()
    if not 0 < layout.num_files() <= MAX_MEMBERS or not 0 < layout.total_size() <= MAX_BYTES:
        raise SongError("El torrent supera el límite de archivos o tamaño de una canción.")
    _space(work, layout.total_size())
    names = set()
    for index in range(layout.num_files()):
        if layout.file_flags(index) & lt.file_storage.flag_symlink:
            raise SongError("El torrent contiene enlaces a archivos externos.")
        # libtorrent reports native separators even though torrent paths are portable.
        name = safe_name(layout.file_path(index).replace(os.sep, "/")).casefold()
        if name in names:
            raise SongError("El torrent contiene archivos duplicados.")
        names.add(name)
    if not any(name.endswith((".txt", ".zip")) for name in names):
        raise SongError("El torrent no contiene un mapa UltraStar.")
    if not params.trackers or not all(
        urlsplit(url).scheme in ("http", "https", "udp") for url in params.trackers
    ):
        raise SongError("El torrent no incluye un rastreador compatible.")
    params.save_path = str(work.resolve())
    params.flags |= (
        lt.torrent_flags.disable_dht
        | lt.torrent_flags.disable_lsd
        | lt.torrent_flags.disable_pex
        | lt.torrent_flags.override_web_seeds
    )
    params.flags &= ~(lt.torrent_flags.paused | lt.torrent_flags.auto_managed)
    params.http_seeds = []
    params.url_seeds = []
    return params


def _download(params, progress):
    session = lt.session(
        {
            "enable_dht": False,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
            "listen_interfaces": "0.0.0.0:0,[::]:0",
            "stop_tracker_timeout": 2,
            "ssrf_mitigation": True,
            "validate_https_trackers": True,
        }
    )
    handle = session.add_torrent(params)
    try:
        started = last_progress = time.monotonic()
        received = -1
        while True:
            status = handle.status()
            if status.errc.value():
                raise SongError("No se ha podido escribir o verificar el paquete de la edición.")
            if status.is_seeding:
                break
            now = time.monotonic()
            if received < status.total_done:
                received, last_progress = status.total_done, now
            if now - last_progress > STALL_SECONDS or now - started > MAX_SECONDS:
                raise SongError(
                    "La descarga no ha terminado. Puede que falten fuentes. Reintenta más tarde."
                )
            if progress:
                progress(
                    f"Descargando la edición · {round(status.progress * 100)}%"
                    if status.num_peers
                    else "Esperando a las fuentes de la edición…"
                )
            time.sleep(0.25)
    finally:
        session.remove_torrent(handle)


def prepare_torrent(torrent_file: Path, destination: Path, song: dict, progress=None) -> Path:
    """Receive one bundle. The caller owns destination and cleans it on every outcome."""
    work = Path(tempfile.mkdtemp(prefix="torrent-", dir=destination))
    params = _torrent_params(torrent_file, work)
    _download(params, progress)
    charts = [p for p in work.rglob("*") if p.is_file() and p.suffix.lower() == ".txt"]
    if not charts:
        archives = [p for p in work.rglob("*") if p.is_file() and p.suffix.lower() == ".zip"]
        if len(archives) == 1:
            return prepare_zip(archives[0], destination, song)
    return _check_recording(_edition(charts, song))
