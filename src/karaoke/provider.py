"""Process boundary around the pinned Syncer API and yt-dlp.

Private upstream entry points are intentional: their exact revision is locked.
No GUI, server, automatic browser-cookie access, AI separation or web posting.
"""

from __future__ import annotations
import dataclasses
import json
import os
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class PreparationProgress:
    """Publish observable stages and measured per-resource byte progress."""

    def __init__(self, path: str | None, destination: Path):
        self.path = Path(path) if path else None
        self.destination = destination
        self.stage = "checking"

    def write(self, stage: str, message: str, **details):
        self.stage = stage
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
        temp.write_text(
            json.dumps(
                {"stage": stage, "message": message, "updated": time.time(), **details},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(temp, self.path)

    def check_space(self):
        folder = self.destination
        while not folder.exists():
            folder = folder.parent
        if shutil.disk_usage(folder).free < 256 * 1024**2:
            raise ValueError("Preparación detenida: no hay espacio libre suficiente.")

    def download(self, event: dict):
        self.check_space()
        status = event.get("status")
        if status == "downloading":
            downloaded = event.get("downloaded_bytes") or 0
            total = event.get("total_bytes") or event.get("total_bytes_estimate")
            values = {"downloaded_bytes": downloaded}
            if total and total > 0:
                values.update(
                    percent=min(100, round(100 * downloaded / total, 1)),
                    total_bytes=total,
                    estimated=not bool(event.get("total_bytes")),
                )
            self.write("downloading", "Descargando recurso", **values)
        elif status == "finished":
            self.write("preparing", "Descarga terminada; preparando medios")

    def postprocess(self, event: dict):
        if event.get("status") in ("started", "processing"):
            self.write("preparing", "Procesando audio o vídeo con FFmpeg")


class _ProgressLogger:
    def __init__(self, original, progress):
        self.original, self.progress = original, progress

    def __getattr__(self, name):
        return getattr(self.original, name)

    def debug(self, message, *args, **kwargs):
        if isinstance(message, str) and message.startswith("Running job: "):
            job = message.removeprefix("Running job: ")
            labels = {
                "AUDIO_DOWNLOAD": ("downloading", "Descargando audio"),
                "VIDEO_DOWNLOAD": ("downloading", "Descargando vídeo"),
                "TXT_WRITTEN": ("preparing", "Preparando mapa de notas"),
                "WRITE_AUDIO_TAGS": ("preparing", "Preparando metadatos de audio"),
                "WRITE_VIDEO_TAGS": ("preparing", "Preparando metadatos de vídeo"),
            }
            if job in labels:
                self.progress.check_space()
                self.progress.write(*labels[job])
        self.original.debug(message, *args, **kwargs)


@contextmanager
def _report_downloads(resource_dl, progress):
    original = resource_dl._ytdl_options

    def options(*args, **kwargs):
        value = original(*args, **kwargs)
        value["progress_hooks"] = [*value.get("progress_hooks", []), progress.download]
        value["postprocessor_hooks"] = [*value.get("postprocessor_hooks", []), progress.postprocess]
        return value

    resource_dl._ytdl_options = options
    try:
        yield
    finally:
        resource_dl._ytdl_options = original


def _bounded_video_options(options):
    """Syncer's last fallback ignores resolution; honor the user's actual cap."""

    class BoundedVideoOptions(type(options)):
        def ytdl_format(self):
            return "/".join(
                part
                for part in super().ytdl_format().split("/")
                if "[height<=" in part and "[width<=" in part
            )

    return BoundedVideoOptions(**dataclasses.asdict(options))


def run(request: dict) -> dict:
    import requests
    from PySide6.QtCore import QCoreApplication

    # This is the upstream bootstrap order. Importing settings/download_options
    # first currently triggers its utils/settings circular import.
    from usdb_syncer.song_loader import _SongLoader
    from usdb_syncer import SongId, db, download_options, resource_dl, settings, usdb_scraper, utils
    from usdb_syncer.usdb_song import UsdbSong, UsdbSongEncoder

    _app = QCoreApplication.instance() or QCoreApplication([])
    root = Path(request["root"])
    root.mkdir(parents=True, exist_ok=True)
    utils.AppPaths.db = root / "syncer.sqlite3"
    settings.set_discord_allowed(False, temp=True)
    settings.set_audio_separation(False, temp=True)
    settings.set_browser(settings.Browser.NONE, temp=True)
    settings.set_audio_normalization(settings.AudioNormalization.DISABLE, temp=True)
    settings.set_audio_embed_artwork(False, temp=True)
    settings.set_video_embed_artwork(False, temp=True)
    settings.set_audio(True, temp=True)
    settings.set_video(request.get("video", True), temp=True)
    settings.set_video_resolution(
        settings.VideoResolution(request.get("resolution", "720p")), temp=True
    )
    settings.set_song_dir(Path(request.get("destination", root / "downloads")), temp=True)
    if os.environ.get("KARAOKE_FFMPEG_DIR"):
        settings.set_ffmpeg_dir(os.environ["KARAOKE_FFMPEG_DIR"], temp=True)
    session = requests.Session()
    user = request.get("username", "")
    password = request.get("password", "")
    if user and password:
        if not usdb_scraper.login_to_usdb(session, user, password):
            raise ValueError("USDB no acepta estas credenciales.")
    usdb_scraper.SessionManager._session = session
    operation = request["operation"]
    if operation == "login":
        if not usdb_scraper.get_logged_in_usdb_user(session):
            raise ValueError("No se ha podido iniciar sesión en USDB.")
        return {"ok": True}
    if operation == "search":
        query = request["query"].strip()
        if " - " in query:
            artist, title = query.split(" - ", 1)
            filters = [{"interpret": artist, "title": title}]
        else:
            filters = [{"interpret": query}, {"title": query}]
        results = {}
        for content_filter in filters:
            # First page is sufficient for an interactive, bounded result list.
            batch = next(usdb_scraper._get_songs_from_usdb("rating", True, content_filter, session))
            for song in batch:
                item = json.loads(json.dumps(song, cls=UsdbSongEncoder))
                results[str(int(song.song_id))] = item
        return {"songs": list(results.values())[:100]}
    if operation == "details":
        details = usdb_scraper.get_usdb_details(SongId(int(request["song_id"])))
        return {
            "videos": list(details.all_comment_videos()),
            "title": details.title,
            "artist": details.artist,
        }
    if operation == "download":
        progress = PreparationProgress(request.get("progress"), Path(request["destination"]))
        progress.check_space()
        progress.write("checking", "Comprobando mapa y recursos asociados")
        song = UsdbSong.from_json(dict(request["song"]))
        with db.managed_connection(utils.AppPaths.db):
            with db.transaction():
                song.upsert()
            options = download_options.download_options()
            # Never download artwork from unneeded arbitrary URLs. Media transformations
            # and sync offsets remain owned by Syncer, not guessed by this adapter.
            options = dataclasses.replace(options, cover_options=None, background_options=None)
            if options.video_options:
                options = dataclasses.replace(
                    options, video_options=_bounded_video_options(options.video_options)
                )
            loader = _SongLoader(song, options, force_redownload=False)
            loader.logger = _ProgressLogger(loader.logger, progress)
            with _report_downloads(resource_dl, progress):
                finished = loader._run_inner()
            if not finished.sync_meta or not finished.sync_meta.audio:
                raise ValueError("Syncer no ha generado un paquete completo.")
            if finished.sync_meta.audio.status is db.JobStatus.FALLBACK:
                raise ValueError(
                    "Syncer utilizó un audio alternativo de los comentarios. Requiere comprobar GAP/BPM y grabación; no se marcará como lista automáticamente."
                )
        charts = list(Path(request["destination"]).rglob("*.txt"))
        if not charts:
            raise ValueError("La preparación no ha producido un mapa TXT.")
        progress.write("preparing", "Recursos preparados; validando paquete")
        return {"charts": [str(p) for p in charts]}
    raise ValueError("Operación de catálogo desconocida.")


def main():
    request = json.load(sys.stdin)
    try:
        result = run(request)
    except Exception as exc:
        # Passwords and cookies are never included in errors or on argv.
        from usdb_syncer.errors import UsdbLoginError

        message = (
            "Conecta tu cuenta USDB en Ajustes para consultar el catálogo."
            if isinstance(exc, UsdbLoginError)
            else str(exc)
        )
        result = {"error": message or type(exc).__name__}
    Path(request["response"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
