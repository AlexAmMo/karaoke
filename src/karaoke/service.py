"""Application state and file-based IPC. Only the engine touches live game objects."""

from __future__ import annotations
import concurrent.futures
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import warnings
from pathlib import Path
from PIL import Image
from .songs import SongError, duration, import_package, normalize, read_chart, resource, validate
from .store import Store
from . import catalog
from .account import AccountSession, SessionExpired
from .artwork import ArtworkResolver
from .package_import import PackageImportMixin, prepare_local


def atomic_json(path: Path, value):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def child_command(module):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", module]
    return [sys.executable, "-m", module]


@functools.lru_cache(maxsize=256)
def _cover_name(chart: str, modified_ns: int, size: int) -> str:
    # Fingerprints invalidate metadata after local edits; do not parse every
    # chart or decode every image on each IPC refresh.
    return read_chart(Path(chart))[1].get("COVER", "")


@functools.lru_cache(maxsize=256)
def _valid_cover(path: str, modified_ns: int, size: int) -> bool:
    if size > 16 * 1024 * 1024:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in {"PNG", "JPEG", "BMP"}:
                    return False
                if not (0 < image.width <= 4096 and 0 < image.height <= 4096):
                    return False
                image.load()
                return True
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return False


def cover_path(song: dict) -> str:
    """Expose only a decodable local cover still contained in its song package."""
    try:
        chart = Path(song["chart"])
        stat = chart.stat()
        name = _cover_name(str(chart), stat.st_mtime_ns, stat.st_size)
        if not name:
            return ""
        image = resource(chart.parent, name)
        stat = image.stat()
        if _valid_cover(str(image), stat.st_mtime_ns, stat.st_size):
            return str(image)
    except (OSError, ValueError):
        pass
    return ""


class Service(PackageImportMixin):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = Store(root / "library.sqlite3")
        self.library = Path(self.store.setting("library", str(root / "Songs")))
        self.library.mkdir(parents=True, exist_ok=True)
        self.ipc = root / "ipc"
        self.ipc.mkdir(mode=0o700, exist_ok=True)
        for name in ("events", "commands"):
            (self.ipc / name).mkdir(exist_ok=True)
            for p in (self.ipc / name).glob("*.json"):
                p.unlink()
        for name in ("engine.json", "view.json"):
            (self.ipc / name).unlink(missing_ok=True)
        self.page = "Biblioteca"
        self.query = ""
        self.message = ("Elige una canción para la cola." if self.store.rows("SELECT 1 FROM songs LIMIT 1")
                        else "Busca tu primera canción o importa un paquete UltraStar.")
        self.results = catalog.starter_songs()
        self.result_page = 0
        self.search_cursor = None
        self.search_busy = False
        self.lookup_query = ""
        self.result_detail = None
        self.turn_detail = None
        self.queue_page = 0
        self.artwork = ArtworkResolver(root / "artwork")
        self.candidates = []
        self.detail = None
        self.fields = {
            "player1": self.store.setting("player1", "Cantante 1"),
            "player2": self.store.setting("player2", ""),
            "username": self.store.setting("username", ""),
        }
        self.engine = {}
        self.active = None
        self.started_at = 0
        self.was_singing = False
        self.pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="karaoke"
        )
        self.futures = []
        self.download = None
        self.search_generation = 0
        self.account = AccountSession()
        self.account_workers = set()
        self.children = set()
        self.download_process = None
        self.cancelled_jobs = set()
        self.children_lock = threading.Lock()
        self.closing = False
        self.preview = None
        self.confirm_delete = None
        self.candidate_audio = None
        self.candidate_generation = 0
        self.pending_result = None
        self.last_view = None
        self.pending_start = None
        self.sent_audio = None
        self.command_sequence = 0
        self.carousel_selected = None
        self.library_cache_key = None
        self.library_cache = []
        self.library_count = 0

    def library_entries(self):
        query = normalize(self.fields.get("local", ""))
        with self.store.lock:
            key = (self.store.db.total_changes, query)
            if self.library_cache_key != key:
                songs = self.store.rows(
                    "SELECT id,title,artist,variant,chart,audio,source FROM songs ORDER BY artist,title,variant,id"
                )
                self.library_count = len(songs)
                self.library_cache = [
                    song for song in songs
                    if query in normalize(song["artist"] + " " + song["title"])
                ]
                self.library_cache_key = key
        return self.library_cache

    def library_window(self):
        songs = self.library_entries()
        selected = next(
            (index for index, song in enumerate(songs) if song["id"] == self.carousel_selected),
            0,
        )
        self.carousel_selected = songs[selected]["id"] if songs else None
        start = max(0, min(selected - 2, len(songs) - 5))
        return songs[start:start + 5], selected - start if songs else 0, len(songs)

    def cover(self, song):
        return self.artwork.get(song, local_cover=cover_path(song) if song.get("chart") else "")

    def carousel_view(self):
        window, index, total = self.library_window()
        songs = self.library_entries()
        return {
            "songs": [
                {"id": song["id"], "title": song["title"], "artist": song["artist"],
                 "cover": self.cover(song)["path"]}
                for song in window
            ],
            "index": index,
            "total": total,
            "has_previous": bool(window and window[index]["id"] != songs[0]["id"]),
            "has_next": bool(window and window[index]["id"] != songs[-1]["id"]),
        }

    def enqueue_song(self, song_id):
        self.song(song_id)  # A stale carousel selection must not create a preparation job.
        self.store.request(song_id, {}, self.names())
        self.message = "Turno añadido a la cola."

    def command(self, op, **kwargs):
        self.command_sequence += 1
        filename = f"{self.command_sequence:020d}-{uuid.uuid4().hex}.json"
        atomic_json(self.ipc / "commands" / filename, {"op": op, **kwargs})

    def names(self):
        return [self.fields.get("player1", "").strip() or "Cantante 1"] + (
            [self.fields["player2"].strip()] if self.fields.get("player2", "").strip() else []
        )

    def credentials(self):
        import keyring

        user = self.store.setting("username", "")
        return (
            {"username": user, "password": keyring.get_password("Karaoke/USDB", user) or ""}
            if user
            else {}
        )

    def _login_cookies(self, username, password):
        result = self._provider_worker("login", private_login=True, username=username, password=password)
        return result["cookies"]

    def _change_account(self, *, pending=False):
        generation = self.account.begin_change(pending)
        self.search_generation += 1
        self.search_busy = False
        self.search_cursor = None
        self.results = self.local_results(self.query)
        self.result_detail = self.pending_result = None
        with self.children_lock:
            for child in self.account_workers:
                if child.poll() is None:
                    child.terminate()
        return generation

    def provider(self, operation, **kwargs):
        if operation == "starter":
            return self._provider_worker(operation, **kwargs)
        generation = self.account.generation
        cookies = self.account.acquire(generation, self.credentials, self._login_cookies)
        try:
            result = self._provider_worker(operation, generation=generation, session_cookies=cookies, **kwargs)
        except SessionExpired:
            cookies = self.account.acquire(generation, self.credentials, self._login_cookies, expired=cookies)
            result = self._provider_worker(operation, generation=generation, session_cookies=cookies, **kwargs)
        self.account.check(generation)
        return result

    def _provider_worker(self, operation, *, generation=None, **kwargs):
        response = self.root / ("response-" + uuid.uuid4().hex + ".json")
        request = {
            "root": str(self.root / "syncer"),
            "response": str(response),
            "operation": operation,
            "progress": str(self.root / "download-progress.json"),
            **kwargs,
        }
        # argv and logs contain no credentials. Use stdin, no persistent password file.
        private_login = bool(kwargs.get("private_login"))
        if private_login:
            del request["response"]
        try:
            proc = subprocess.Popen(
                child_command("karaoke.provider"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE if private_login else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
            )
            with self.children_lock:
                self.children.add(proc)
                if operation != "starter":
                    self.account_workers.add(proc)
                    if generation is not None:
                        self.account.check(generation)
                if operation in ("download", "starter"):
                    self.download_process = proc
            deadline = time.monotonic() + (1800 if operation in ("download", "starter") else 90)
            pending_input = json.dumps(request)
            while True:
                try:
                    output, _ = proc.communicate(pending_input, timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
                    if self.closing:
                        raise SongError("Preparación interrumpida; se reanudará al volver a abrir.")
                    if time.monotonic() > deadline:
                        raise SongError("La fuente ha tardado demasiado. Reintenta la operación.")
                    if (
                        operation in ("download", "starter")
                        and shutil.disk_usage(self.root).free < 256 * 1024**2
                    ):
                        raise SongError("Descarga detenida: queda poco espacio disponible.")
            if proc.returncode:
                raise SongError("El servicio de catálogo se ha interrumpido. Reintenta la operación.")
            if private_login:
                marker = "KARAOKE_LOGIN "
                line = next((line[len(marker):] for line in reversed((output or "").splitlines())
                             if line.startswith(marker)), "")
                try:
                    result = json.loads(line)
                except ValueError:
                    raise SongError("No se ha podido verificar la sesión USDB.") from None
            else:
                if not response.exists():
                    raise SongError("El servicio de catálogo ha fallado. Reintenta la operación.")
                result = json.loads(response.read_text(encoding="utf-8"))
            if result.get("expired"):
                raise SessionExpired(result["error"])
            if result.get("error"):
                raise SongError(result["error"])
            return result
        finally:
            if "proc" in locals():
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                with self.children_lock:
                    self.children.discard(proc)
                    self.account_workers.discard(proc)
                    if self.download_process is proc:
                        self.download_process = None
            response.unlink(missing_ok=True)

    def submit(self, work, callback):
        self.futures.append((self.pool.submit(work), callback))

    def local_results(self, query):
        items = {catalog.source_key(s): s for s in catalog.starter_songs(query) + catalog.assisted_songs(query)}
        if query and not youtube_id(query):
            for saved in self.store.rows("SELECT * FROM songs ORDER BY artist,title,id"):
                if catalog.matches(query, saved):
                    source = saved.get("source") or ""
                    if not source.startswith(("usdb:", "deluxe:")):
                        source = "local:" + saved["id"]
                    items[source] = {**saved, "source": source, "library_id": saved["id"]}
        return sorted(items.values(), key=lambda s: catalog.rank(query, s))

    def search(self, query, *, more=False):
        if more and (self.search_busy or not self.search_cursor):
            return
        if not more:
            self.query = query.strip()
            self.page = "Buscar"
            self.results = self.local_results(self.query)
            self.result_page = 0
            self.result_detail = None
            self.pending_result = None
            self.search_generation += 1
            self.search_cursor = None
            self.search_busy = False
            self.lookup_query = self.query
        if not self.query:
            self.message = "Elige una canción de inicio o busca en el catálogo."
            return
        if not self.store.setting("username", ""):
            self.message = "Conecta USDB en Ajustes o consulta los otros catálogos."
            return
        self.search_busy = True
        self.message = "Buscando más mapas en USDB…" if more else "Consultando USDB…"
        generation = self.search_generation
        query_snapshot = self.lookup_query
        cursor = self.search_cursor if more else None
        video_id = youtube_id(self.query)

        def work():
            lookup = query_snapshot
            try:
                if not more and lookup.startswith(("http://", "https://")) and not video_id:
                    raise SongError("Introduce un enlace de YouTube válido.")
                if video_id and not more:
                    from yt_dlp import YoutubeDL

                    with YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                                    "socket_timeout": 20}) as dl:
                        info = dl.extract_info(
                            "https://www.youtube.com/watch?v=" + video_id, download=False
                        )
                    lookup = " - ".join(filter(None, (info.get("artist") or info.get("creator"),
                                                        info.get("track") or info.get("title"))))
                    if not lookup:
                        raise SongError("No se ha podido identificar la canción del vídeo.")
                result = self.provider("search", query=lookup, cursor=cursor)
                return lookup, result, ""
            except Exception as exc:
                return lookup, {}, str(exc) or "No se pudo consultar USDB."

        def done(response):
            self.search_busy = False
            lookup, result, error = response
            self.lookup_query = lookup
            if error:
                self.message = "USDB: " + error
                return
            self.search_cursor = result.get("next_cursor") or None
            previous = self.results
            combined = {catalog.source_key(item): item for item in
                        (previous if more else self.local_results(lookup))}
            for item in result["songs"]:
                item = {**item, "requested_video": video_id,
                        "match": "Por comprobar" if video_id else "Mapa existente"}
                key = catalog.source_key(item)
                if key not in combined or not combined[key].get("library_id"):
                    combined[key] = item
            if video_id:
                for key, item in combined.items():
                    if not key.startswith("espana:"):
                        item["requested_video"] = video_id
            if more:
                prior_keys = {catalog.source_key(x) for x in previous}
                # Keep displayed pages in place when another remote batch arrives.
                additions = sorted((item for key, item in combined.items()
                                    if key not in prior_keys),
                                   key=lambda item: catalog.rank(lookup, item))
                self.results = previous + additions
                if additions:
                    self.result_page = len(previous) // 12
            else:
                self.results = sorted(combined.values(), key=lambda item: catalog.rank(lookup, item))
            self.message = (f"{len(self.results)} versiones encontradas." if self.results else
                            "Sin coincidencias en esta página." if self.search_cursor else
                            "No se han encontrado mapas en estas fuentes.")

        self.submit(work, done)
        self.futures[-1][0].search_generation = generation

    def prepare(self, job):
        payload = json.loads(job["payload"])
        if shutil.disk_usage(self.library).free < 512 * 1024**2:
            raise SongError("Preparación detenida: quedan menos de 512 MB libres.")
        if payload["kind"] in ("archive", "paired"):
            return prepare_local(payload, self.library)
        if payload["kind"] == "import":
            return import_package(Path(payload["chart"]), self.library)
        target = self.root / "downloads" / job["id"]
        target.mkdir(parents=True, exist_ok=True)
        if payload["kind"] == "deluxe":
            result = self.provider("starter", key=job["source"].split(":", 1)[1],
                                   destination=str(target))
        else:
            result = self.provider(
                "download", song=payload["song"], destination=str(target),
                video=self.store.setting("video", True),
                resolution=self.store.setting("resolution", "720p"),
            )
        failures = []
        for chart in result["charts"]:
            try:
                imported = import_package(Path(chart), self.library)
                if payload["kind"] == "deluxe":
                    shutil.copy2(Path(chart).parent / "license.txt",
                                 Path(imported["chart"]).parent / "license.txt")
                shutil.rmtree(target)
                return imported
            except SongError as exc:
                failures.append(str(exc))
        raise SongError("; ".join(failures) or "No se encontró un paquete compatible.")

    def choose_folder(self, mode="folder"):
        response = self.root / ("picker-" + uuid.uuid4().hex + ".json")
        proc = subprocess.Popen(
            child_command("karaoke.picker"),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        with self.children_lock:
            self.children.add(proc)
        try:
            proc.communicate(json.dumps({"response": str(response), "mode": mode}))
            if not response.exists():
                return ""
            return json.loads(response.read_text(encoding="utf-8"))["folder"]
        finally:
            with self.children_lock:
                self.children.discard(proc)
            response.unlink(missing_ok=True)

    def add_import(self, value):
        if not value.strip():
            raise SongError("Elige una carpeta, un mapa TXT o un ZIP.")
        folder = Path(value.strip().strip('"')).expanduser().resolve()
        if folder.is_file() and folder.suffix.lower() == ".zip":
            self.open_zip(folder)
            return
        if folder.is_file() and folder.suffix.lower() == ".txt":
            _, meta = read_chart(folder)
            try:
                resource(folder.parent, meta.get("AUDIO") or meta.get("MP3", ""))
            except SongError:
                self.open_pair(folder)
                return
        charts = (
            [folder]
            if folder.is_file() and folder.suffix.lower() == ".txt"
            else sorted(folder.rglob("*.txt"))
            if folder.is_dir()
            else []
        )
        if not charts:
            raise SongError(
                "No hay mapas TXT en esa carpeta. Introduce una carpeta UltraStar preparada."
            )
        for chart in charts:
            fingerprint = str(chart.stat().st_mtime_ns) + ":" + str(chart.stat().st_size)
            source = "import:" + str(chart) + ":" + fingerprint
            self.store.request(source, {"kind": "import", "chart": str(chart)}, None)
        self.message = f"{len(charts)} paquetes pendientes de validación e importación."
        self.page = "Cola"

    def request_result(self, index, queue):
        song = dict(self.results[index] if isinstance(index, int) else index)
        if song.get("requested_video"):
            # Require a deliberate selection, never replace the source media with pasted video.
            # Capture the actual song and intent. A later search can replace the
            # result array while this confirmation is still on screen.
            self.pending_result = {"song": song, "queue": bool(queue)}
            self.page = "Confirmar versión"
            return
        self._request_song(song, queue)

    def _request_song(self, song, queue):
        if catalog.source_key(song).startswith("espana:"):
            raise SongError("Abre la ficha e importa el mapa antes de añadir un turno.")
        if song.get("library_id"):
            if queue:
                self.enqueue_song(song["library_id"])
            else:
                self.song(song["library_id"])
                self.message = "Esta versión ya está en la biblioteca."
            return
        source = catalog.source_key(song)
        self.store.request(
            source,
            {"kind": source.split(":", 1)[0],
             "song": {k: v for k, v in song.items()
                      if k not in ("requested_video", "match", "source")}},
            self.names() if queue else None,
        )
        self.message = "Turno añadido a la cola." if queue else "Canción solicitada para la biblioteca."

    def start(self, turn_id):
        if self.active or self.engine.get("state") == "singing":
            raise SongError("Espera a que termine la interpretación actual.")
        turn = next((r for r in self.store.queue() if r["id"] == turn_id), None)
        if not turn or not turn["song_id"]:
            raise SongError("Este turno todavía no está preparado.")
        validate(Path(turn["chart"]))
        if not self.engine:
            raise SongError("El motor de canto todavía se está iniciando.")
        self.stop_preview()
        self.store.execute("UPDATE turns SET state='starting' WHERE id=?", (turn_id,))
        self.active = turn_id
        self.started_at = time.monotonic()
        self.was_singing = False
        self.command("start", chart=turn["chart"], names=json.loads(turn["names"]), token=turn_id)
        self.message = "Preparando micrófonos e interpretación…"

    def instrumental_search(self):
        song = self.song(self.detail)
        self.page = "Instrumental"
        self.candidates = []
        self.candidate_audio = None
        self.candidate_generation += 1
        generation = self.candidate_generation
        self.message = "Buscando pistas instrumentales existentes…"

        def work():
            from yt_dlp import YoutubeDL

            with YoutubeDL(
                {"quiet": True, "no_warnings": True, "extract_flat": True, "socket_timeout": 20}
            ) as dl:
                result = dl.extract_info(
                    "ytsearch8:" + song["artist"] + " " + song["title"] + " instrumental karaoke",
                    download=False,
                )
            return [
                {
                    "url": "https://www.youtube.com/watch?v=" + e["id"],
                    "title": e.get("title", ""),
                    "duration": e.get("duration"),
                }
                for e in result.get("entries", [])
                if e
            ]

        self.submit(
            work,
            lambda items: (
                self.set_candidates(items)
                if self.detail == song["id"] and generation == self.candidate_generation
                else None
            ),
        )
        self.futures[-1][0].candidate_generation = generation

    def set_candidates(self, items):
        self.candidates = items
        self.message = (
            "Candidatos sin verificar: escucha y comprueba estructura, tono y tiempos."
            if items
            else "No se han encontrado candidatos. Sigue disponible la versión original."
        )

    def candidate(self, index):
        self.stop_preview()
        candidate = self.candidates[index]
        song = self.song(self.detail)
        # Once another candidate is chosen, the previous pre-listen/confirmation
        # is no longer valid, even when both belong to the same song.
        self.candidate_audio = None
        self.candidate_generation += 1
        generation = self.candidate_generation
        self.message = "Preparando preescucha; no sustituye la voz original…"

        def work():
            from yt_dlp import YoutubeDL

            target = self.root / "previews" / uuid.uuid4().hex
            target.mkdir(parents=True)
            options = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "format": "bestaudio/best",
                "outtmpl": str(target / "audio.%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
                "socket_timeout": 20,
                "progress_hooks": [self.space_guard],
            }
            with YoutubeDL(options) as dl:
                dl.download([candidate["url"]])
            audio = target / "audio.mp3"
            seconds = duration(audio)
            if abs(seconds - song["duration"]) > 3:
                raise SongError(
                    "La duración difiere más de 3 segundos. Busca otra edición compatible."
                )
            return {"path": str(audio), "source": candidate["url"], "song": song["id"]}

        def done(value):
            if self.detail != value["song"] or generation != self.candidate_generation:
                return
            self.candidate_audio = value
            self.message = "Preescucha principio, centro y final. Confirma solo si notas, estructura y tono coinciden."

        self.submit(work, done)
        self.futures[-1][0].candidate_generation = generation

    def space_guard(self, _):
        if self.closing or shutil.disk_usage(self.root).free < 256 * 1024**2:
            raise SongError("Descarga detenida por cierre o espacio insuficiente.")

    def confirm_instrumental(self):
        if not self.candidate_audio or not self.candidate_audio.get("listened"):
            raise SongError("Preescucha la instrumental antes de confirmarla.")
        song = self.song(self.candidate_audio["song"])
        with tempfile.TemporaryDirectory(dir=self.library) as tmp:
            target = Path(tmp)
            text, meta = read_chart(Path(song["chart"]))
            shutil.copy2(self.candidate_audio["path"], target / "audio.mp3")
            text = re.sub(
                r"^#(MP3|AUDIO|VIDEO|COVER|BACKGROUND|VIDEOGAP):.*\n?", "", text, flags=re.M
            )
            text = "#MP3:audio.mp3\n" + text
            (target / "song.txt").write_text(text, encoding="utf-8")
            info = import_package(target / "song.txt", self.library)
        self.store.save_song(
            info,
            self.candidate_audio["source"] + ":" + song["id"],
            "instrumental",
            song["id"],
            True,
        )
        self.message = "Instrumental guardada con tu confirmación. El original sigue disponible."
        self.detail = info["id"]
        self.page = "Canción"
        self.stop_preview()

    def song(self, song_id):
        rows = self.store.rows("SELECT * FROM songs WHERE id=?", (song_id,))
        if not rows:
            raise SongError("La canción ya no está en la biblioteca.")
        return rows[0]

    def stop_preview(self):
        if self.preview and self.preview.poll() is None:
            self.preview.terminate()
            try:
                self.preview.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.preview.kill()
                self.preview.wait()
        self.preview = None

    def listen(self, path, fraction=0):
        if self.engine.get("state") == "singing":
            raise SongError("La preescucha estará disponible al terminar la canción actual.")
        self.stop_preview()
        self.preview = subprocess.Popen(
            [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "-volume",
                "30",
                "-ss",
                str(duration(Path(path)) * fraction),
                "-t",
                "20",
                str(path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def handle(self, event):
        action = event.get("action", "")
        value = str(event.get("value", ""))[:4096]
        if action.startswith("import:") and self.import_action(action):
            return
        if action.startswith("field:"):
            field = action.split(":", 1)[1]
            self.fields[field] = value
            if field == "query":
                self.search(value)
            return
        if action.startswith("page:"):
            self.pending_result = None
            self.page = action[5:]
            return
        if action == "carousel:enqueue":
            if not self.carousel_selected:
                raise SongError("Selecciona una canción de tu biblioteca.")
            self.enqueue_song(self.carousel_selected)
            return
        if action.startswith("carousel:"):
            window, index, _ = self.library_window()
            songs = self.library_entries()
            if action.startswith("carousel:select:"):
                selected = action[len("carousel:select:"):]
                if not any(song["id"] == selected for song in songs):
                    raise SongError("La canción ya no está en esta selección de la biblioteca.")
                self.carousel_selected = selected
            elif window and action in ("carousel:next", "carousel:previous"):
                selected = next(i for i, song in enumerate(songs) if song["id"] == window[index]["id"])
                direction = 1 if action == "carousel:next" else -1
                self.carousel_selected = songs[max(0, min(len(songs) - 1, selected + direction))]["id"]
            return
        if action == "search":
            self.search(self.fields.get("query", ""))
            return
        if action == "import":
            self.add_import(self.fields.get("import", ""))
            return
        if action == "choose-import":
            self.submit(
                self.choose_folder, lambda folder: self.add_import(folder) if folder else None
            )
            return
        if action == "login":
            username, password = self.fields.get("username", ""), self.fields.pop("password", "")
            if not username or not password:
                raise SongError("Introduce usuario y contraseña de USDB.")
            generation = self._change_account(pending=True)
            self.message = "Comprobando acceso a USDB…"

            def work():
                try:
                    cookies = self.account.authenticate(generation, username, password, self._login_cookies)
                    return cookies, ""
                except Exception as exc:
                    return None, str(exc) or "USDB no está disponible."

            def done(response):
                if self.account.generation != generation:
                    return
                cookies, error = response
                if error:
                    self.account.finish_change(generation)
                    raise SongError(error)
                import keyring
                try:
                    keyring.set_password("Karaoke/USDB", username, password)
                    self.store.configure("username", username)
                except Exception:
                    self.account.finish_change(generation)
                    raise
                self.account.finish_change(generation, username, cookies)
                self.message = "USDB conectado. Contraseña guardada en el almacén seguro del sistema."

            self.submit(work, done)
            return
        if action == "logout":
            import keyring

            self._change_account()
            user = self.store.setting("username", "")
            if user:
                try:
                    keyring.delete_password("Karaoke/USDB", user)
                except keyring.errors.PasswordDeleteError:
                    pass
            self.store.configure("username", "")
            self.message = "Cuenta USDB desconectada."
            return
        if action == "save-settings":
            for key in ("player1", "player2"):
                self.store.configure(key, self.fields.get(key, ""))
            folder = self.fields.get("library", "").strip()
            if folder:
                new = Path(folder).expanduser().resolve()
                new.mkdir(parents=True, exist_ok=True)
                self.library = new
                self.store.configure("library", str(new))
            self.message = "Ajustes guardados. La nueva carpeta se aplica a futuras canciones."
            return
        if action == "video":
            self.store.configure("video", not self.store.setting("video", True))
            return
        if action == "resolution":
            choices = ["480p", "720p", "1080p"]
            current = self.store.setting("resolution", "720p")
            self.store.configure("resolution", choices[(choices.index(current) + 1) % 3])
            return
        if action == "testinput":
            if self.engine.get("state") == "singing":
                raise SongError("La prueba de señal se hace entre canciones.")
            self.command("testinput")
            return
        if action == "scan":
            if self.engine.get("state") == "singing":
                raise SongError("Detecta los micrófonos entre canciones.")
            self.command("scan")
            return
        if action.startswith("device:"):
            if self.engine.get("state") == "singing":
                raise SongError("Cambia las entradas entre canciones.")
            _, player, device, channel = action.split(":")
            self.command("device", player=int(player), device=int(device), channel=int(channel))
            return
        if action.startswith("gain:"):
            index = int(action[5:])
            gain = min(100, max(0, int(float(value))))
            self.store.configure("gain" + str(index), gain)
            self.command("gain", player=index, value=gain / 100)
            return
        if action == "music":
            gain = min(100, max(0, int(float(value))))
            self.store.configure("music", gain)
            self.command("music", value=gain)
            return
        if action == "latency":
            if self.engine.get("state") == "singing":
                raise SongError("Ajusta la sincronía entre canciones.")
            milliseconds = max(-500, min(500, int(self.fields.get("latency", "0"))))
            self.command("latency", value=milliseconds)
            self.store.configure("latency", milliseconds)
            return
        if action in ("search:previous", "search:next"):
            self.result_page = min(max(0, (len(self.results)-1) // 12),
                                   max(0, self.result_page + (1 if action == "search:next" else -1)))
            return
        if action == "search:more":
            self.search(self.query, more=True)
            return
        if action.startswith("external:"):
            import webbrowser
            link = catalog.assisted_url(action.split(":", 1)[1], self.lookup_query)
            if not webbrowser.open(link):
                raise SongError("No se ha podido abrir el navegador.")
            return
        if action.startswith("enqueue:"):
            self.enqueue_song(action.split(":", 1)[1])
            return
        if action in ("queue:next", "queue:previous"):
            self.queue_page = max(0, self.queue_page + (1 if action == "queue:next" else -1))
            return
        if action.startswith("turn:"):
            self.turn_detail = action.split(":", 1)[1]
            self.page = "Turno"
            return
        if action.startswith("result:"):
            _, op, generation, key = action.split(":", 3)
            item = next((x for x in self.results if catalog.source_key(x) == key), None)
            if str(self.search_generation) != generation or item is None:
                raise SongError("La búsqueda ha cambiado. Selecciona de nuevo la canción.")
            if op == "open" and key.startswith("espana:"):
                import webbrowser
                if not webbrowser.open(catalog.assisted_entry_url(key)):
                    raise SongError("No se ha podido abrir la ficha en el navegador.")
                return
            if op == "detail":
                self.result_detail = item
                self.page = "Versión"
            elif op in ("save", "queue"):
                self.request_result(item, op == "queue")
            return
        if action == "confirm-version":
            if not self.pending_result:
                raise SongError("Vuelve a seleccionar la versión que quieres preparar.")
            selection = self.pending_result
            self.pending_result = None
            self._request_song(selection["song"], selection["queue"])
            self.page = "Cola" if selection["queue"] else "Biblioteca"
            return
        if action.startswith("song:"):
            self.song(action[5:])
            self.detail = action[5:]
            self.carousel_selected = self.detail
            self.page = "Canción"
            self.confirm_delete = None
            self.candidate_audio = None
            self.candidate_generation += 1
            return
        if action == "enqueue":
            self.enqueue_song(self.detail)
            return
        if action == "instrumental":
            self.instrumental_search()
            return
        if action.startswith("candidate:"):
            self.candidate(int(action[10:]))
            return
        if action.startswith("listen:"):
            if self.candidate_audio:
                self.listen(self.candidate_audio["path"], float(action[7:]))
                self.candidate_audio["listened"] = True
            return
        if action == "listen-original":
            self.listen(self.song(self.detail)["audio"])
            return
        if action == "stop-preview":
            self.stop_preview()
            return
        if action == "confirm-instrumental":
            self.confirm_instrumental()
            return
        if action.startswith("start:"):
            self.start(action[6:])
            return
        if action.startswith("cancel:"):
            self.store.execute(
                "UPDATE turns SET state='cancelled' WHERE id=? AND state='queued'", (action[7:],)
            )
            return
        if action.startswith("up:") or action.startswith("down:"):
            op, turn_id = action.split(":")
            self.store.reorder(turn_id, -1 if op == "up" else 1)
            return
        if action.startswith("cancel-job:"):
            job_id = action[11:]
            self.cancelled_jobs.add(job_id)
            self.store.execute(
                "UPDATE jobs SET state='cancelled',message='Preparación cancelada. Puedes reintentarla.' WHERE id=?",
                (job_id,),
            )
            if self.download and self.download[1]["id"] == job_id:
                with self.children_lock:
                    if self.download_process and self.download_process.poll() is None:
                        self.download_process.terminate()
            return
        if action.startswith("retry:"):
            self.cancelled_jobs.discard(action[6:])
            self.store.execute(
                "UPDATE jobs SET state='waiting',message='' WHERE id=? AND state IN ('error','cancelled')",
                (action[6:],),
            )
            return
        if action == "pause":
            self.command("pause")
            return
        if action == "end":
            self.page = "Terminar canción"
            return
        if action == "confirm-end":
            self.command("end")
            self.page = "Cola"
            return
        if action == "delete":
            self.confirm_delete = self.detail
            return
        if action == "delete-confirm":
            if self.confirm_delete != self.detail:
                return
            song = self.song(self.detail)
            if self.store.rows(
                "SELECT id FROM turns WHERE song_id=? AND state IN ('queued','starting','singing')",
                (self.detail,),
            ):
                raise SongError("Quita primero los turnos de esta canción de la cola.")
            folder = Path(song["chart"]).parent
            # Only packages created by this app, never user-provided source folders.
            if folder.name != song["id"]:
                raise SongError("No se puede borrar una carpeta externa.")
            self.command("forget", chart=song["chart"])
            shutil.rmtree(folder)
            self.store.execute("DELETE FROM jobs WHERE song_id=?", (song["id"],))
            self.store.execute("DELETE FROM songs WHERE id=?", (song["id"],))
            self.detail = None
            self.page = "Biblioteca"
            self.message = "Canción borrada de la biblioteca."
            return
        raise SongError("Esta acción ya no está disponible.")

    def tick(self):
        for path in sorted((self.ipc / "events").glob("*.json")):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
                path.unlink()
                self.handle(event)
            except Exception as exc:
                path.unlink(missing_ok=True)
                self.message = str(exc)
        for future, callback in list(self.futures):
            if future.done():
                self.futures.remove((future, callback))
                if (
                    getattr(future, "search_generation", self.search_generation)
                    != self.search_generation
                ):
                    continue
                if (
                    getattr(future, "candidate_generation", self.candidate_generation)
                    != self.candidate_generation
                ):
                    continue
                try:
                    callback(future.result())
                except Exception as exc:
                    self.message = str(exc)
        state = self.ipc / "engine.json"
        if state.exists():
            try:
                self.engine = json.loads(state.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, PermissionError):
                pass
        if self.engine and self.sent_audio is None:
            for i in range(2):
                self.command("gain", player=i, value=self.store.setting("gain" + str(i), 0) / 100)
            self.command("music", value=self.store.setting("music", 65))
            self.command("latency", value=self.store.setting("latency", 0))
            self.sent_audio = True
        if self.active:
            if self.engine.get("state") == "singing" and self.engine.get("token") == self.active:
                if (
                    not self.was_singing
                    and self.message == "Preparando micrófonos e interpretación…"
                ):
                    self.message = "Cantando. Puedes buscar y preparar los próximos turnos."
                self.was_singing = True
                self.store.execute("UPDATE turns SET state='singing' WHERE id=?", (self.active,))
            elif self.was_singing and self.engine.get("state") != "singing":
                self.store.execute(
                    "UPDATE turns SET state='finished', scores=? WHERE id=?",
                    (json.dumps(self.engine.get("scores", [])), self.active),
                )
                self.message = "Interpretación terminada. Elige cuándo empezar el siguiente turno."
                self.active = None
            elif not self.was_singing and time.monotonic() - self.started_at > 15:
                self.store.execute("UPDATE turns SET state='queued' WHERE id=?", (self.active,))
                self.active = None
                self.message = (
                    self.engine.get("error")
                    or "No se pudo iniciar. Revisa las entradas de micrófono en Ajustes."
                )
        if self.download and self.download[0].done():
            future, job = self.download
            self.download = None
            try:
                info = future.result()
                if job["id"] in self.cancelled_jobs:
                    raise SongError("Preparación cancelada.")
                self.store.save_song(info, job["source"])
                self.store.execute(
                    "UPDATE jobs SET state='ready',song_id=?,message='' WHERE id=?",
                    (info["id"], job["id"]),
                )
                self.message = info["title"] + " está lista para cantar."
            except Exception as exc:
                if job["id"] not in self.cancelled_jobs:
                    self.store.execute(
                        "UPDATE jobs SET state='error',message=? WHERE id=?", (str(exc), job["id"])
                    )
        if self.download:
            progress = self.root / "download-progress.json"
            if progress.exists():
                try:
                    value = json.loads(progress.read_text(encoding="utf-8"))
                    self.store.execute(
                        "UPDATE jobs SET message=? WHERE id=?",
                        (value.get("message", "Preparando recursos"), self.download[1]["id"]),
                    )
                except (json.JSONDecodeError, OSError):
                    pass
        if not self.download and not self.closing:
            jobs = self.store.rows(
                "SELECT * FROM jobs WHERE state='waiting' ORDER BY created LIMIT 1"
            )
            if jobs:
                job = jobs[0]
                (self.root / "download-progress.json").unlink(missing_ok=True)
                self.store.execute(
                    "UPDATE jobs SET state='working',message='Preparando mapa y medios' WHERE id=?",
                    (job["id"],),
                )
                self.download = (self.pool.submit(self.prepare, job), job)
        view = self.view()
        if view != self.last_view:
            atomic_json(self.ipc / "view.json", view)
            self.last_view = view

    def view(self):
        rows = []

        def text(label, sub=""):
            rows.append({"kind": "text", "label": str(label), "sub": str(sub)})

        def button(label, action, sub=""):
            rows.append({"kind": "button", "label": label, "action": action, "sub": sub})

        def song_row(song, label, sub, action="", add_action=""):
            rows.append({"kind": "song", "label": label, "sub": sub, "action": action,
                         "add_action": add_action, "artist": song.get("artist") or "",
                         "cover": self.cover(song)["path"]})

        def field(label, key, default="", secret=False):
            rows.append(
                {
                    "kind": "input",
                    "label": label,
                    "action": "field:" + key,
                    "value": "" if secret else self.fields.get(key, default),
                    "secret": secret,
                }
            )

        def slider(label, action, default):
            rows.append(
                {
                    "kind": "slider",
                    "label": label,
                    "action": action,
                    "value": self.store.setting(action.replace(":", ""), default),
                }
            )

        if self.import_rows(text, button, field):
            pass
        elif self.page == "Terminar canción":
            text("¿Terminar esta interpretación?", "Se mostrarán los puntos obtenidos hasta ahora.")
            button("Continuar cantando", "page:Cola")
            button("Terminar y ver resultados", "confirm-end")
        elif self.page == "Biblioteca":
            songs, _, total = self.library_window()
            text("Tu repertorio", f"{self.library_count} versiones guardadas · disponibles sin conexión")
            field("Filtrar biblioteca", "local")
            for song in songs:
                sub = song["artist"]
                if song["variant"] == "instrumental":
                    sub += " · Instrumental"
                song_row(song, song["title"], sub, "song:" + song["id"], "enqueue:" + song["id"])
            if total > 5:
                button("Canción anterior", "carousel:previous")
                button("Canción siguiente", "carousel:next")
            if not self.library_count:
                text("Tu primera canción", "Importa un paquete o busca un mapa existente en USDB.")
            elif not songs:
                text("Sin coincidencias", "Prueba otro título o artista.")
            button("Importar TXT, audio o ZIP", "import:open")
        elif self.page == "Buscar":
            field("Artista, canción o enlace de YouTube", "query")
            button("Buscar canciones", "search")
            if not self.query:
                text("Canciones para empezar", "Incluyen voz original y notas.")
            start = self.result_page * 12
            visible = self.results[start:start + 12]
            keys = [catalog.source_key(x) for x in visible]
            saved = {row["matched_source"]: row for row in self.store.rows(
                f"SELECT s.*,ss.source AS matched_source FROM songs s JOIN song_sources ss ON ss.song_id=s.id WHERE ss.source IN ({','.join('?' for _ in keys)})",
                keys,
            )} if keys else set()
            for song, key in zip(visible, keys):
                local = saved.get(key) or (song if song.get("library_id") else None)
                source = ("Deluxe" if key.startswith("deluxe:") else
                          "USDB" if key.startswith("usdb:") else "Biblioteca")
                status = "Lista para cantar" if local else "Preparar"
                token = f"{self.search_generation}:{key}"
                if key.startswith("espana:"):
                    song_row(song, song["title"], song["artist"] + " · Necesita importar",
                             "result:detail:" + token)
                    continue
                detail_action = ("song:" + local["id"]) if local and not song.get("requested_video") else ("result:detail:" + token)
                song_row(local or song, song["title"], f"{song['artist']} · {source} · {status}",
                         detail_action, "result:queue:" + token)
            if start:
                button("Página anterior", "search:previous")
            if start + len(visible) < len(self.results):
                button("Página siguiente", "search:next")
            elif self.search_cursor and not self.search_busy:
                button("Buscar más en USDB", "search:more")
            if self.query and not self.search_busy:
                button("Consultar UltraStar España", "external:es", "Abrir catálogo en el navegador")
                button("Consultar USDB.eu", "external:eu", "Abrir catálogo en el navegador")
            button("Importar TXT, audio o ZIP", "import:open")
        elif self.page == "Versión" and self.result_detail:
            song = self.result_detail
            key = catalog.source_key(song)
            token = f"{self.search_generation}:{key}"
            song_row(song, song["title"], song["artist"])
            if key.startswith("espana:"):
                text("UltraStar España", "Obtén el material de esta edición e importa el paquete o el mapa con su audio.")
                button("Abrir ficha", "result:open:" + token)
                button("Importar TXT, audio o ZIP", "import:open")
            else:
                if key.startswith("deluxe:"):
                    license_name = catalog.STARTERS[key.partition(":")[2]][2]
                    text("UltraStar Deluxe Songs", "Audio original, mapa y licencia " + license_name)
                elif key.startswith("usdb:"):
                    text("Mapa USDB", " · ".join(str(song[k]) for k in
                                                ("language", "edition", "creator") if song.get(k)))
                else:
                    text("Versión de la biblioteca")
                button("Añadir a la cola", "result:queue:" + token)
                button("Guardar sin turno", "result:save:" + token)
            button("Volver a los resultados", "page:Buscar")
        elif self.page == "Confirmar versión":
            text(
                "Comprueba la grabación",
                "El enlace pegado no demuestra compatibilidad con este mapa.",
            )
            selection = self.pending_result
            if selection:
                text(selection["song"]["title"], selection["song"].get("artist", ""))
            text(
                "Se usará la grabación asociada al mapa",
                "No se sustituirá automáticamente por el vídeo pegado.",
            )
            if selection:
                button(
                    "Añadir esta versión a la cola"
                    if selection["queue"]
                    else "Guardar esta versión",
                    "confirm-version",
                )
            button("Volver a los resultados", "page:Buscar")
        elif self.page == "Cola":
            turns = self.store.queue()
            text("Próximos turnos", "El siguiente empieza cuando tú lo decidas.")
            if not turns:
                text("La cola está libre", "Añade una canción desde la biblioteca o el buscador.")
            self.queue_page = min(self.queue_page, max(0, (len(turns) - 1) // 12))
            start = self.queue_page * 12
            for index, turn in enumerate(turns[start:start + 12], start):
                original = json.loads(turn["job_payload"] or "{}").get("song", {})
                song = self.song(turn["song_id"]) if turn["song_id"] else original
                title = song.get("title") or "Preparando canción"
                status = "Lista" if turn["song_id"] else {
                    "waiting": "En espera", "working": "Preparando", "error": "Error",
                    "cancelled": "Cancelada"}.get(turn["preparation"], "Pendiente")
                sub = " · ".join(filter(None, (song.get("artist"), ", ".join(json.loads(turn["names"])), status)))
                song_row(song, f"{index + 1}. {title}", sub, "turn:" + turn["id"])
            if start:
                button("Turnos anteriores", "queue:previous")
            if start + 12 < len(turns):
                button("Más turnos", "queue:next")
            next_ready = next((t for t in turns if t["state"] == "queued"), None)
            if next_ready and next_ready["song_id"] and not self.active:
                button("Empezar turno", "start:" + next_ready["id"])
            text("Preparación de biblioteca")
            for job in self.store.rows("SELECT * FROM jobs WHERE state!='ready' ORDER BY created"):
                payload = json.loads(job["payload"])
                label = (
                    payload.get("song", {}).get("title")
                    or Path(payload.get("chart", "")).parent.name
                )
                text(label, job["message"] or "En espera")
                if job["state"] in ("error", "cancelled"):
                    button("Reintentar preparación", "retry:" + job["id"])
                if job["state"] in ("working", "waiting"):
                    button("Cancelar preparación", "cancel-job:" + job["id"])
        elif self.page == "Turno":
            turn = next((t for t in self.store.queue() if t["id"] == self.turn_detail), None)
            if turn:
                text(turn["title"] or json.loads(turn["job_payload"] or "{}").get("song", {}).get("title")
                     or "Preparando canción", ", ".join(json.loads(turn["names"])))
                if turn["state"] == "queued":
                    if turn["song_id"]:
                        button("Empezar este turno", "start:" + turn["id"])
                    button("Subir turno", "up:" + turn["id"])
                    button("Bajar turno", "down:" + turn["id"])
                    button("Quitar turno", "cancel:" + turn["id"])
            button("Volver a la cola", "page:Cola")
        elif self.page == "Canción" and self.detail:
            song = self.song(self.detail)
            text(song["title"], song["artist"])
            text(
                "Instrumental confirmada por el anfitrión"
                if song["variant"] == "instrumental"
                else "Audio original del paquete",
                f"{round(song['duration'])} s · {song['language']}",
            )
            art = self.cover(song)
            text(art["kind"], " · ".join(filter(None, (art["credit"], art["license"], art["url"]))))
            if (song.get("source") or "").startswith("deluxe:"):
                key = song["source"].partition(":")[2]
                if key in catalog.STARTERS:
                    text("UltraStar Deluxe Songs", catalog.STARTERS[key][2] + " · Créditos en license.txt")
            if song["freestyle"]:
                text(
                    "Contiene partes libres o rap",
                    "La puntuación depende del tipo de nota del mapa.",
                )
            button("Añadir a la cola", "enqueue", ", ".join(self.names()))
            button("Escuchar audio", "listen-original")
            button("Detener preescucha", "stop-preview")
            if song["variant"] == "original":
                button("Buscar instrumental existente", "instrumental")
            family = song["parent"] or song["id"]
            for variant in self.store.rows(
                "SELECT * FROM songs WHERE (id=? OR parent=?) AND id!=?",
                (family, family, song["id"]),
            ):
                button(
                    "Elegir "
                    + ("instrumental" if variant["variant"] == "instrumental" else "voz original"),
                    "song:" + variant["id"],
                )
            button("Borrar de la biblioteca", "delete")
            if self.confirm_delete == self.detail:
                button(
                    "Confirmar borrado de estos archivos",
                    "delete-confirm",
                    "No se borrará la carpeta de origen importada.",
                )
        elif self.page == "Instrumental":
            text(
                "Instrumentales existentes",
                "Los resultados son candidatos, no versiones certificadas.",
            )
            for index, item in enumerate(self.candidates):
                button(item["title"], "candidate:" + str(index), "Preparar para preescucha")
            if self.candidate_audio:
                for fraction, title in ((0, "principio"), (0.45, "centro"), (0.85, "final")):
                    button("Escuchar " + title, "listen:" + str(fraction))
                button("Escuchar referencia original", "listen-original")
                button("Detener preescucha", "stop-preview")
                button(
                    "Confirmar estructura, tono y sincronía",
                    "confirm-instrumental",
                    "Solo tras revisar que coincide con este mapa.",
                )
        elif self.page == "Ajustes":
            text("Cantantes y sonido", "Retorno a cero inicialmente; súbelo de forma gradual.")
            field("Nombre · jugador 1", "player1", "Cantante 1")
            field("Jugador 2 · vacío para cantar solo", "player2")
            slider("Música", "music", 65)
            slider("Escuchar mi voz · jugador 1", "gain:0", 0)
            slider("Escuchar mi voz · jugador 2", "gain:1", 0)
            text(
                "Entradas de micrófono", "Asigna un dispositivo y canal diferente a cada cantante."
            )
            button("Detectar micrófonos", "scan")
            button(
                "Detener prueba de señal"
                if self.engine.get("testing")
                else "Probar señal de micrófonos",
                "testinput",
            )
            for index, level in enumerate(self.engine.get("levels", [])):
                text(f"Señal jugador {index + 1}: {min(100, round(level * 100))}%")
            for device in self.engine.get("devices", []):
                for channel in range(min(device["channels"], 8)):
                    for player in range(2):
                        button(
                            f"Jugador {player + 1}: "
                            + device["name"]
                            + (
                                " · seleccionado"
                                if device.get("players", [])[channel : channel + 1] == [player + 1]
                                else ""
                            ),
                            f"device:{player}:{device['index']}:{channel}",
                            "Canal " + str(channel + 1),
                        )
            field(
                "Corrección de sincronía · ms (-500 a 500)",
                "latency",
                str(self.store.setting("latency", 0)),
            )
            button("Aplicar sincronía", "latency")
            text("Biblioteca y descargas")
            field("Carpeta para futuras canciones", "library", str(self.library))
            button(
                "Vídeo: " + ("activado" if self.store.setting("video", True) else "solo audio"),
                "video",
            )
            button("Calidad máxima: " + self.store.setting("resolution", "720p"), "resolution")
            button("Guardar ajustes", "save-settings")
            text("Cuenta USDB", "Necesaria para consultar y descargar mapas del catálogo.")
            field("Usuario USDB", "username")
            field("Contraseña · almacén seguro del sistema", "password", secret=True)
            button("Conectar USDB", "login")
            button("Desconectar cuenta", "logout")
            text(
                "Karaoke 0.1.0 · software libre",
                "UltraStar Deluxe + USDB Syncer · sin generación de notas por IA",
            )
        queue = self.store.queue()
        next_turn = next((turn for turn in queue if turn["state"] == "queued"), None)
        return {
            "carousel": self.carousel_view(),
            "next": ("Después: " + (next_turn["title"] or "Preparando canción"))
            if next_turn
            else "Sin próximos turnos",
            "page": self.page,
            "rows": rows,
            "message": self.message,
            "queue_count": len(self.store.queue()),
            "singing": self.engine.get("state") == "singing",
            "title": self.engine.get("title", ""),
            "names": self.names(),
            "scores": self.engine.get("scores", []),
            "synthetic": os.environ.get("KARAOKE_TEST_INPUT") == "1",
        }

    def close(self):
        self.closing = True
        self.account.begin_change()
        self.stop_preview()
        with self.children_lock:
            for child in self.children:
                if child.poll() is None:
                    child.terminate()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.artwork.close()
        self.store.close()


def youtube_id(url):
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        candidate = (
            parse_qs(parsed.query).get("v", [""])[0]
            if parsed.path == "/watch"
            else parsed.path.split("/")[-1]
            if parsed.path.startswith(("/shorts/", "/embed/", "/live/"))
            else ""
        )
    else:
        return None
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None
