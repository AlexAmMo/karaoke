"""Application state and file-based IPC. Only the engine touches live game objects."""

from __future__ import annotations
import concurrent.futures
import functools
import hashlib
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
from . import acoustic, allkaraoke, catalog
from .account import AccountSession, SessionExpired
from .artwork import ArtworkResolver
from .package_import import PackageImportMixin, prepare_local, import_pair, signature


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
        self.added_token = ""
        self.page = "Buscar"
        if self.store.rows("SELECT 1 FROM songs LIMIT 1"):
            self.page = "Biblioteca"
        elif self.store.queue():
            self.page = "Cola"
        self.query = ""
        self.message = ""
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
        self.instrumental_busy = False
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
        self.catalogue_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="indices")
        self.usdb_search_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="usdb-search")
        self.catalogue_status = {}
        self.edition_group = None
        self.edition_page = 0
        self.grouped_source = None
        self.grouped_cache = []
        self.clean_catalogue_reviews()
        self.account = AccountSession()
        self.account_workers = set()
        self.children = set()
        self.download_process = None
        self.cancelled_jobs = set()
        self.children_lock = threading.Lock()
        self.closing = False
        self.preview = None
        self.confirm_delete = None
        self.candidate_generation = 0
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

    def cover(self, song, *, search=""):
        return self.artwork.get(song, local_cover=cover_path(song) if song.get("chart") else "", search=search)

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
        self.result_detail = None
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
                    if not source.startswith(("usdb:", "deluxe:", "allkaraoke:")):
                        source = "local:" + saved["id"]
                    items[source] = {**saved, "source": source, "library_id": saved["id"]}
        return sorted(items.values(), key=lambda s: catalog.rank(query, s))

    def grouped_results(self):
        if self.grouped_source is not self.results:
            self.grouped_source = self.results
            self.grouped_cache = group_results(self.results)
        return self.grouped_cache

    def brief_search_status(self):
        if self.page != "Buscar":
            return
        # The results and the empty/loading state already explain the search.
        # Preserve feedback from queue actions if an index arrives afterwards.
        if self.message in ("Consultando USDB…", "Buscando más mapas en USDB…"):
            self.message = ""

    def search_indices(self, query):
        from . import community_catalog

        generation = self.search_generation
        video = youtube_id(query)
        directory = self.root / "catalogues"
        sources = {"AllKaraoke": lambda: allkaraoke.search(query, directory, video)}
        if not video:
            sources["España y USDB.eu"] = lambda: community_catalog.search(query, directory)
        self.catalogue_status = {name: "Consultando" for name in sources}

        def request(name, fetch):
            try:
                return name, fetch(), ""
            except Exception:
                return name, [], "No disponible"

        def done(value):
            name, rows, error = value
            self.catalogue_status[name] = error or ""
            combined = {catalog.source_key(row): row for row in rows}
            combined.update({catalog.source_key(row): row for row in self.results})
            self.results = sorted(combined.values(), key=lambda row: catalog.rank(self.lookup_query, row))
            self.brief_search_status()

        for name, fetch in sources.items():
            future = self.catalogue_pool.submit(request, name, fetch)
            future.search_generation = generation
            future.catalogue_search = True
            self.futures.append((future, done))

    def search(self, query, *, more=False):
        if more and (self.search_busy or not self.search_cursor):
            return
        if not more:
            self.query = query.strip()
            self.page = "Buscar"
            self.results = self.local_results(self.query)
            self.result_page = 0
            self.edition_group = None
            self.result_detail = None
            self.search_generation += 1
            self.search_cursor = None
            self.search_busy = False
            self.lookup_query = self.query
            self.catalogue_status = {}
            for future, _ in self.futures:
                if getattr(future, "catalogue_search", False):
                    future.cancel()
            if self.query and (not self.query.startswith(("http://", "https://")) or youtube_id(self.query)):
                self.search_indices(self.query)
        if not self.query:
            self.message = ""
            return
        if not self.store.setting("username", ""):
            self.message = ""
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
                self.catalogue_status["USDB"] = error
                self.brief_search_status()
                return
            self.search_cursor = result.get("next_cursor") or None
            previous = self.results
            combined = {catalog.source_key(item): item for item in
                        (previous if more else [*self.local_results(lookup), *previous])}
            for item in result["songs"]:
                item = {**item, "requested_video": video_id,
                        "match": "Por comprobar" if video_id else "Mapa existente"}
                key = catalog.source_key(item)
                if key not in combined or not combined[key].get("library_id"):
                    combined[key] = item
            if video_id:
                for key, item in combined.items():
                    if key.startswith(("local:", "usdb:", "deluxe:")):
                        item["requested_video"] = video_id
            if more:
                prior_keys = {catalog.source_key(x) for x in previous}
                # Keep displayed pages in place when another remote batch arrives.
                additions = sorted((item for key, item in combined.items()
                                    if key not in prior_keys),
                                   key=lambda item: catalog.rank(lookup, item))
                self.results = previous + additions
                if additions:
                    self.result_page = min(len(group_results(previous)) // 12, (len(group_results(self.results)) - 1) // 12)
            else:
                self.results = sorted(combined.values(), key=lambda item: catalog.rank(lookup, item))
            self.brief_search_status()

        # Keep slow remote lookups off the queue that prepares songs for playback.
        # A later keystroke cancels any old query still waiting for this worker.
        future = self.usdb_search_pool.submit(work)
        future.search_generation = generation
        future.catalogue_search = True
        self.futures.append((future, done))

    def prepare(self, job):
        payload = json.loads(job["payload"])
        if shutil.disk_usage(self.library).free < 512 * 1024**2:
            raise SongError("Preparación detenida: quedan menos de 512 MB libres.")
        if payload["kind"] in ("archive", "paired"):
            return prepare_local(payload, self.library)
        if payload["kind"] == "import":
            return import_package(Path(payload["chart"]), self.library)
        (self.root / "downloads").mkdir(exist_ok=True)
        candidates = [payload["song"], *payload.get("alternatives", [])]
        errors = []
        for song in candidates:
            if self.closing or job["id"] in self.cancelled_jobs:
                raise SongError("Preparación cancelada.")
            source = catalog.source_key(song) if song.get("source") or song.get("song_id") else job["source"]
            try:
                with tempfile.TemporaryDirectory(dir=self.root / "downloads") as stage:
                    info = self.prepare_edition(song, source, Path(stage), job, payload)
                return {**info, "edition_source": job["source"] if payload.get("local_audio") else source}
            except Exception as exc:
                if self.closing or job["id"] in self.cancelled_jobs:
                    raise SongError("Preparación cancelada.") from exc
                if isinstance(exc, SongError):
                    errors.append(str(exc))
                else:
                    errors.append("La grabación de esta edición no está disponible.")
        raise SongError(errors[0])

    def prepare_edition(self, song, source, target, job, payload):
        def progress(_):
            self.space_guard(None)
            if job["id"] in self.cancelled_jobs:
                raise SongError("Preparación cancelada.")

        if source.startswith("allkaraoke:"):
            local = payload.get("local_audio")
            if local and signature(Path(local)) != payload.get("audio_signature"):
                raise SongError("Tu archivo de audio ha cambiado. Vuelve a elegirlo.")
            chart, audio = allkaraoke.prepare_review(song, target, progress, local)
            if local and signature(Path(local)) != payload["audio_signature"]:
                raise SongError("Tu archivo de audio ha cambiado durante la preparación.")
            acoustic.require_alignment(chart, audio)
            progress(None)
            return import_pair(chart, audio, self.library)
        if source.startswith("deluxe:"):
            result = self.provider("starter", key=source.partition(":")[2], destination=str(target))
        elif source.startswith("usdb:"):
            record = {k: v for k, v in song.items() if k not in ("requested_video", "source", "match")}
            result = self.provider(
                "download", song=record, destination=str(target),
                video=self.store.setting("video", True),
                resolution=self.store.setting("resolution", "720p"),
            )
        else:
            raise SongError("Esta fuente requiere importar el paquete original.")
        chart = Path(result["charts"][0])
        if source.startswith("usdb:"):
            desired = payload.get("exact_video")
            if desired and result.get("audio_resource") != desired:
                raise SongError("El mapa corresponde a otra grabación.")
            _, meta = read_chart(chart)
            if (catalog.tokens(meta["ARTIST"]), catalog.tokens(meta["TITLE"])) != (
                catalog.tokens(song["artist"]), catalog.tokens(song["title"])
            ):
                raise SongError("Los datos del mapa difieren de la edición elegida.")
            audio = resource(chart.parent, meta.get("AUDIO") or meta.get("MP3", ""))
            acoustic.require_alignment(chart, audio)
        progress(None)
        imported = import_package(chart, self.library)
        if source.startswith("deluxe:"):
            shutil.copy2(chart.parent / "license.txt", Path(imported["chart"]).parent / "license.txt")
        return imported

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

    def clean_catalogue_reviews(self):
        # Keep the input of persistent jobs across retries and application restarts.
        root = self.root / "catalogue-review"
        if not root.is_dir():
            return
        keep = set()
        for row in self.store.rows("SELECT payload FROM jobs WHERE state!='ready' AND source LIKE 'allkaraoke:%'"):
            chart = json.loads(row["payload"]).get("chart")
            if chart:
                keep.add(Path(chart).parent)
        for stage in root.glob("edition-*"):
            if stage not in keep and not stage.is_symlink():
                shutil.rmtree(stage, ignore_errors=True)

    def auto_choices(self, group):
        """Return playable candidates for this search, preferring the original studio cut."""
        selected_video = youtube_id(self.query)
        choices = []
        for song in group:
            key = catalog.source_key(song)
            required = song.get("requested_video") or selected_video
            if required and song.get("video_id") != required:
                continue
            if not song.get("library_id") and (not key.startswith(("usdb:", "allkaraoke:", "deluxe:"))
                                                or (song.get("tracks") or 1) > 1):
                continue
            choices.append(song)
        def preference(song):
            key = catalog.source_key(song)
            variant = bool(re.search(r"\b(live|directo|remix|instrumental|duet|dueto|radio edit)\b",
                                     normalize(song["title"] + " " + str(song.get("edition") or ""))))
            return (song.get("variant") == "instrumental", variant, not bool(song.get("library_id")),
                    not key.startswith("deluxe:"), not key.startswith("allkaraoke:"),
                    catalog.rank(self.lookup_query, song))
        return sorted(choices, key=preference)

    def add_best(self, item):
        group = next((g for g in self.grouped_results() if work_key(g[0]) == work_key(item)), [])
        choices = self.auto_choices(group)
        if not choices:
            raise SongError("Esta canción requiere el paquete de su edición.")
        def identity(song):
            return (tuple(catalog.tokens(song["artist"])), tuple(catalog.tokens(song["title"])))
        first = choices[0]
        # A completed download becomes playable immediately, even when this search
        # was opened before it existed in the library. Reuse the same recording.
        for candidate in choices:
            if candidate is not first and (not first.get("video_id")
                    or candidate.get("video_id") != first["video_id"] or identity(candidate) != identity(first)):
                continue
            if candidate.get("library_id"):
                self.enqueue_song(candidate["library_id"])
                return
            saved = self.store.rows("SELECT song_id FROM song_sources WHERE source=?",
                                    (catalog.source_key(candidate),))
            if saved:
                self.enqueue_song(saved[0]["song_id"])
                return

        # A common title is only a grouping hint. A fallback must use the very same
        # recording. USDB's media identity is checked after its worker resolves it.
        video = first.get("video_id")
        alternatives = []
        if video and not first.get("library_id"):
            for candidate in choices[1:]:
                if identity(candidate) != identity(first):
                    continue
                if candidate.get("video_id") == video or allkaraoke.source_usdb_id(first) == catalog.source_key(candidate):
                    alternatives.append(candidate)
        self._request_song(first, True, alternatives)

    def request_result(self, index, queue):
        self._request_song(self.results[index] if isinstance(index, int) else index, queue)

    def _request_song(self, song, queue, alternatives=(), local_audio=None):
        if not self.auto_choices([song]):
            raise SongError("Esta edición requiere otro mapa compatible con la grabación.")
        source = catalog.source_key(song)
        if song.get("library_id"):
            if queue:
                self.enqueue_song(song["library_id"])
            else:
                self.message = "Esta versión ya está en tu biblioteca."
            return
        payload = {"kind": source.partition(":")[0], "song": dict(song)}
        if alternatives:
            payload.update(alternatives=list(alternatives), exact_video=song["video_id"])
            source = "selection:" + source
        if local_audio:
            path = Path(local_audio).expanduser().resolve()
            stamp = signature(path)
            token = hashlib.sha256(f"{source}:{path}:{stamp}".encode()).hexdigest()
            source = "pair:" + token
            payload.update(local_audio=str(path), audio_signature=stamp)
        # An explicit retry with a fresh file or complete catalogue result replaces
        # the failed input, while waiting/in-flight jobs remain idempotent.
        previous = self.store.rows("SELECT id FROM jobs WHERE source=? AND state='cancelled'", (source,))
        if previous and self.download and self.download[1]["id"] == previous[0]["id"]:
            raise SongError("La preparación anterior se está cancelando. Vuelve a añadirla en unos segundos.")
        if previous:
            self.cancelled_jobs.discard(previous[0]["id"])
        self.store.request(source, payload, self.names() if queue else None)
        self.message = "Añadida a la cola." if queue else "Preparando la canción."

    def choose_catalogue_audio(self, song):
        def done(path):
            if path:
                self._request_song(song, False, local_audio=path)
        self.submit(lambda: self.choose_folder("audio"), done)

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
        self.instrumental_busy = True
        self.candidate_generation += 1
        generation = self.candidate_generation
        self.message = "Buscando instrumentales…"

        def work():
            from yt_dlp import YoutubeDL

            with YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True,
                            "socket_timeout": 20}) as dl:
                result = dl.extract_info("ytsearch8:" + song["artist"] + " " + song["title"]
                                         + " instrumental karaoke", download=False)
            return [{"url": "https://www.youtube.com/watch?v=" + e["id"],
                     "title": e.get("title", ""), "duration": e.get("duration")}
                    for e in result.get("entries", []) if e and e.get("id")]

        def done(items):
            self.instrumental_busy = False
            self.candidates = items
            self.message = "Elige una instrumental." if items else "Sin instrumentales disponibles."

        self.submit(work, done)
        self.futures[-1][0].candidate_generation = generation

    def candidate(self, index):
        if self.page != "Instrumental" or not 0 <= index < len(self.candidates):
            raise SongError("Vuelve a elegir una instrumental.")
        candidate = self.candidates[index]
        song = self.song(self.detail)
        self.stop_preview()
        self.candidate_generation += 1
        generation = self.candidate_generation
        self.instrumental_busy = True
        self.message = "Preparando la instrumental…"

        def work():
            video_id = youtube_id(candidate["url"])
            if not video_id:
                raise SongError("La pista seleccionada no tiene un vídeo disponible.")
            with tempfile.TemporaryDirectory(dir=self.library) as temp:
                stage = Path(temp)
                audio = allkaraoke.download_recording({"video_id": video_id}, stage, self.space_guard)
                if abs(duration(audio) - song["duration"]) > 2:
                    raise SongError("La instrumental tiene un montaje distinto.")
                chart = Path(song["chart"])
                acoustic.require_alignment(chart, audio)
                if self.closing or self.candidate_generation != generation:
                    raise SongError("Selección cancelada.")
                return import_pair(chart, audio, self.library)

        def done(info):
            self.instrumental_busy = False
            if info["id"] == song["id"]:
                raise SongError("Esta grabación ya es la versión original.")
            self.store.save_song(info, candidate["url"] + ":" + song["id"], "instrumental",
                                 song["id"], True)
            self.message = "Instrumental disponible."
            self.detail = info["id"]
            self.page = "Canción"

        self.submit(work, done)
        self.futures[-1][0].candidate_generation = generation

    def space_guard(self, _):
        if self.closing or shutil.disk_usage(self.root).free < 256 * 1024**2:
            raise SongError("Descarga detenida por cierre o espacio insuficiente.")

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

    def confirm_added(self, token):
        if token:
            # Native controls acknowledge this exact click in place. A second
            # announcement in the footer would also resize a scrolled list.
            self.added_token = token
            self.message = ""

    def handle(self, event):
        action = event.get("action", "")
        value = str(event.get("value", ""))[:4096]
        if action.startswith("import:") and self.import_action(action):
            return
        if action.startswith("field:"):
            field = action.split(":", 1)[1]
            self.fields[field] = value
            if field in ("player1", "player2"):
                self.store.configure(field, value)
            if field == "query":
                self.search(value)
            return
        if action.startswith("page:"):
            self.message = ""
            destination = action[5:]
            if destination == "Otros catálogos":
                self.catalogue_return_page = self.page
            if destination != "Opciones de canción":
                self.confirm_delete = None
            self.page = destination
            return
        if action == "carousel:enqueue":
            if not self.carousel_selected:
                raise SongError("Selecciona una canción de tu biblioteca.")
            self.enqueue_song(self.carousel_selected)
            self.confirm_added(value)
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
        if action in ("editions:previous", "editions:next"):
            editions = [song for song in self.results if work_key(song) == self.edition_group]
            self.edition_page = min(max(0, (len(editions) - 1) // 12),
                                    max(0, self.edition_page + (1 if action.endswith(":next") else -1)))
            return
        if action in ("search:previous", "search:next"):
            self.result_page = min(max(0, (len(self.grouped_results())-1) // 12),
                                   max(0, self.result_page + (1 if action == "search:next" else -1)))
            return
        if action == "options:more":
            self.page = "Buscar"
            self.search(self.query, more=True)
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
            self.confirm_added(value)
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
            if op == "best":
                self.add_best(item)
                self.confirm_added(value)
                return
            if op == "editions":
                self.edition_group = work_key(item)
                self.edition_page = 0
                self.page = "Ediciones"
                return
            if op in ("recording", "file") and key.startswith("allkaraoke:"):
                if self.page != "Versión" or self.result_detail != item:
                    raise SongError("Vuelve a elegir la edición que quieres revisar.")
                if op == "file":
                    self.choose_catalogue_audio(item)
                else:
                    self._request_song(item, True)
                return
            if op == "open" and key.startswith(("espana:", "community-")):
                import webbrowser
                if not webbrowser.open(item.get("catalogue_url") or catalog.assisted_entry_url(key)):
                    raise SongError("No se ha podido abrir la ficha en el navegador.")
                return
            if op == "detail":
                saved = self.store.rows("SELECT song_id FROM song_sources WHERE source=?", (key,))
                if saved and not item.get("requested_video"):
                    self.detail = saved[0]["song_id"]
                    self.carousel_selected = self.detail
                    self.page = "Canción"
                    return
                self.result_detail = item
                self.page = "Versión"
            elif op in ("save", "queue"):
                self.request_result(item, op == "queue")
                if op == "queue":
                    self.confirm_added(value)
            return
        if action.startswith("song:"):
            self.song(action[5:])
            self.detail = action[5:]
            self.carousel_selected = self.detail
            self.page = "Canción"
            self.confirm_delete = None
            self.candidate_generation += 1
            return
        if action == "enqueue":
            self.enqueue_song(self.detail)
            self.confirm_added(value)
            return
        if action == "instrumental":
            self.instrumental_search()
            return
        if action.startswith("candidate:"):
            self.candidate(int(action[10:]))
            return
        if action == "listen-original":
            self.listen(self.song(self.detail)["audio"])
            return
        if action == "stop-preview":
            self.stop_preview()
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
                    if hasattr(future, "candidate_generation"):
                        self.instrumental_busy = False
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
                if not self.was_singing:
                    self.store.execute("UPDATE turns SET state='singing' WHERE id=?", (self.active,))
                    self.was_singing = True
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
                actual_source = info.get("edition_source", job["source"])
                self.store.finish_job(job, info, actual_source)
                payload = json.loads(job["payload"])
                if job["source"].startswith("allkaraoke:") and payload.get("chart"):
                    stage = Path(payload["chart"]).parent
                    if stage.parent == self.root / "catalogue-review" and stage.name.startswith("edition-"):
                        shutil.rmtree(stage, ignore_errors=True)
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
                    message = value.get("message", "Preparando recursos")
                    self.store.execute(
                        "UPDATE jobs SET message=? WHERE id=? AND message IS NOT ?",
                        (message, self.download[1]["id"], message),
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

        def button(label, action, sub="", *, style=""):
            row = {"kind": "button", "label": label, "action": action, "sub": sub}
            if style:
                row["style"] = style
            rows.append(row)

        def song_row(song, label, sub, action="", add_action=""):
            rows.append({"kind": "song", "label": label, "sub": sub, "action": action,
                         "add_action": add_action, "artist": song.get("artist") or "",
                         "cover": self.cover(song, search=self.query if self.page == "Buscar" else "")["path"]})

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
            if self.library_count:
                field("Filtrar canciones guardadas", "local")
                for song in songs:
                    artist = song["artist"]
                    if song["variant"] == "instrumental":
                        artist += " · Instrumental"
                    song_row(song, song["title"], artist, "song:" + song["id"], "enqueue:" + song["id"])
                if not songs:
                    text("Sin coincidencias", "Prueba otro artista o título.")
                if total > 5:
                    button("Canción anterior", "carousel:previous", style="link")
                    button("Canción siguiente", "carousel:next", style="link")
            else:
                text("Tu biblioteca está vacía", "Aquí tendrás las canciones que prepares para cantar.")
                button("Buscar una canción", "page:Buscar", style="primary")
            button("Importar canciones", "import:open", style="link")
        elif self.page == "Buscar":
            field("Artista, canción o enlace de YouTube", "query")
            grouped = self.grouped_results()
            start = self.result_page * 12
            visible = grouped[start:start + 12]
            loading = self.search_busy or "Consultando" in self.catalogue_status.values()
            if not self.query:
                text("Para empezar", "Canciones con voz listas para descargar.")
            elif not visible:
                if loading:
                    text("Buscando…")
                else:
                    if any(self.catalogue_status.values()):
                        text("Búsqueda incompleta", "Algún catálogo está sin conexión.")
                        button("Reintentar búsqueda", "search", style="link")
                    else:
                        text("Sin coincidencias", "Prueba con el nombre del artista o una parte del título.")
                    button("Otras formas de buscar", "page:Otros catálogos", style="link")
            keys = [catalog.source_key(item) for group in visible for item in group]
            saved_keys = set()
            for i in range(0, len(keys), 500):
                batch = keys[i:i + 500]
                params = ",".join("?" for _ in batch)
                saved_keys.update(row["source"] for row in self.store.rows(
                    f"SELECT source FROM song_sources WHERE source IN ({params})", batch))
            for group in visible:
                song = group[0]
                key = catalog.source_key(song)
                token = f"{self.search_generation}:{key}"
                local = next((item for item in group if item.get("library_id")), None)
                sub = song["artist"]
                possible = self.auto_choices(group)
                if local or any(catalog.source_key(item) in saved_keys for item in possible):
                    sub += " · En biblioteca"
                elif not possible:
                    sub += " · Necesita importar" if all(is_assisted(catalog.source_key(i)) for i in group) else " · Ver edición"
                detail_action = "result:editions:" + token if len(group) > 1 else "result:detail:" + token
                song_row(local or song, song["title"], sub, detail_action,
                         "result:best:" + token if possible else "")
            if start:
                button("Resultados anteriores", "search:previous", style="link")
            if start + len(visible) < len(grouped):
                button("Más resultados", "search:next", style="link")
            elif self.search_cursor and not self.search_busy and (len(grouped) != 1):
                button("Más resultados", "search:more", style="link")
        elif self.page == "Otros catálogos":
            if self.search_cursor and not self.search_busy:
                button("Más resultados de USDB", "options:more", style="link")
            button("UltraStar España", "external:es", "Abrir el catálogo", style="link")
            button("USDB.eu", "external:eu", "Abrir el catálogo", style="link")
            if getattr(self, "catalogue_return_page", "Buscar") == "Descargas":
                button("Volver a descargas", "page:Descargas", style="back")
            else:
                button("Volver a buscar", "page:Buscar", style="back")
        elif self.page == "Ediciones":
            editions = [song for song in self.results if work_key(song) == self.edition_group]
            start = self.edition_page * 12
            for song in editions[start:start + 12]:
                key = catalog.source_key(song)
                details = [song["artist"], source_name(key)]
                details.extend(str(song[x]) for x in ("edition", "language", "creator") if song.get(x))
                local_id = song.get("library_id")
                if not local_id:
                    saved = self.store.rows("SELECT song_id FROM song_sources WHERE source=?", (key,))
                    local_id = saved[0]["song_id"] if saved else None
                if local_id:
                    details.append("En biblioteca")
                action = f"result:detail:{self.search_generation}:{key}"
                if local_id and not song.get("requested_video"):
                    song_row(song, song["title"], " · ".join(details), "song:" + local_id, "enqueue:" + local_id)
                else:
                    possible = self.auto_choices([song])
                    song_row(song, song["title"], " · ".join(details), action,
                             f"result:queue:{self.search_generation}:{key}" if possible else "")
            if start:
                button("Ediciones anteriores", "editions:previous")
            if start + 12 < len(editions):
                button("Más ediciones", "editions:next")
            button("Volver a los resultados", "page:Buscar", style="back")
        elif self.page == "Versión" and self.result_detail:
            song = self.result_detail
            key = catalog.source_key(song)
            token = f"{self.search_generation}:{key}"
            song_row(song, song["title"], song["artist"])
            if key.startswith("allkaraoke:") and not song.get("library_id"):
                text("Edición de AllKaraoke", " · ".join(filter(None, (song.get("language"), song.get("creator")))))
                if (song.get("tracks") or 1) > 1:
                    text("Esta edición requiere varias melodías", "Elige un mapa de una sola voz.")
                else:
                    button("Añadir a la cola", "result:queue:" + token, style="primary")
                    button("Guardar en biblioteca", "result:save:" + token, style="link")
                    if song.get("reference_duration"):
                        button("Usar mi copia de esta edición", "result:file:" + token, style="link")
            elif key.startswith(("espana:", "community-")):
                text(source_name(key), "Obtén el material de esta edición e importa el paquete o el mapa con su audio.")
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
                if self.auto_choices([song]):
                    button("Añadir a la cola", "result:queue:" + token, style="primary")
                    button("Guardar en biblioteca", "result:save:" + token, style="link")
                else:
                    text("La grabación del enlace no coincide con esta edición.")
            if self.edition_group == work_key(song):
                button("Ver otras ediciones", "page:Ediciones")
            button("Volver a los resultados", "page:Buscar", style="back")
        elif self.page == "Cola":
            turns = self.store.queue()
            next_ready = next((turn for turn in turns if turn["state"] == "queued" and turn["song_id"]), None)
            if next_ready and not self.active:
                button("Empezar a cantar", "start:" + next_ready["id"], next_ready["title"], style="primary")
            if not turns:
                text("La cola está vacía", "Elige qué canción quieres cantar primero.")
                button("Buscar una canción", "page:Buscar", style="primary")
            self.queue_page = min(self.queue_page, max(0, (len(turns) - 1) // 12))
            start = self.queue_page * 12
            for index, turn in enumerate(turns[start:start + 12], start):
                original = json.loads(turn["job_payload"] or "{}").get("song", {})
                song = self.song(turn["song_id"]) if turn["song_id"] else original
                title = song.get("title") or "Preparando canción"
                status = {"singing": "Cantando", "starting": "Empezando"}.get(turn["state"], "Lista") if turn["song_id"] else {
                    "waiting": "En espera", "working": "Preparando", "error": "Error",
                    "cancelled": "Cancelada"}.get(turn["preparation"], "Pendiente")
                sub = " · ".join(filter(None, (song.get("artist"), ", ".join(json.loads(turn["names"])), status)))
                song_row(song, f"{index + 1}. {title}", sub, "turn:" + turn["id"])
            if start:
                button("Turnos anteriores", "queue:previous")
            if start + 12 < len(turns):
                button("Más turnos", "queue:next")
            pending = self.store.rows("""SELECT 1 FROM jobs j WHERE j.state!='ready' AND NOT EXISTS
                (SELECT 1 FROM turns t WHERE t.source=j.source AND t.state IN ('queued','starting','singing')) LIMIT 1""")
            if pending:
                button("Ver preparaciones", "page:Preparaciones", style="link")
        elif self.page == "Preparaciones":
            jobs = self.store.rows("SELECT * FROM jobs WHERE state!='ready' ORDER BY created")
            if not jobs:
                text("Preparaciones terminadas")
            for job in jobs:
                payload = json.loads(job["payload"])
                label = payload.get("song", {}).get("title") or Path(payload.get("chart", "")).parent.name
                text(label or "Canción", job["message"] or "En espera")
                if job["state"] in ("error", "cancelled"):
                    button("Reintentar", "retry:" + job["id"], style="link")
                else:
                    button("Cancelar preparación", "cancel-job:" + job["id"], style="link")
            button("Volver a la cola", "page:Cola", style="back")
        elif self.page == "Turno":
            turns = self.store.queue()
            turn = next((t for t in turns if t["id"] == self.turn_detail), None)
            if turn:
                text(turn["title"] or json.loads(turn["job_payload"] or "{}").get("song", {}).get("title")
                     or "Preparando canción", ", ".join(json.loads(turn["names"])))
                if turn["state"] == "queued":
                    if turn["song_id"] and not self.active:
                        button("Empezar este turno", "start:" + turn["id"], style="primary")
                    elif turn["preparation"] in ("error", "cancelled"):
                        text("No se ha podido preparar", turn["message"] or "")
                        jobs = self.store.rows("SELECT id FROM jobs WHERE source=?", (turn["source"],))
                        if jobs:
                            button("Reintentar", "retry:" + jobs[0]["id"], style="primary")
                    pending = [t for t in turns if t["state"] == "queued"]
                    if turn != pending[0]:
                        button("Subir turno", "up:" + turn["id"], style="link")
                    if turn != pending[-1]:
                        button("Bajar turno", "down:" + turn["id"], style="link")
                    button("Quitar de la cola", "cancel:" + turn["id"], style="link")
            button("Volver a la cola", "page:Cola", style="back")
        elif self.page == "Canción" and self.detail:
            song = self.song(self.detail)
            song_row(song, song["title"], song["artist"])
            button("Añadir a la cola", "enqueue", ", ".join(self.names()), style="primary")
            if self.preview and self.preview.poll() is None:
                button("Detener preescucha", "stop-preview", style="link")
            else:
                button("Escuchar un fragmento", "listen-original", style="link")
            button("Opciones de la canción", "page:Opciones de canción", style="link")
        elif self.page == "Opciones de canción" and self.detail:
            song = self.song(self.detail)
            text(song["title"], " · ".join(filter(None, (song["artist"], song["language"], f"{round(song['duration'])} s"))))
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
            if self.confirm_delete == self.detail:
                button("Confirmar borrado", "delete-confirm", "Se eliminará la copia de la biblioteca.")
            else:
                button("Borrar de la biblioteca", "delete", style="link")
            button("Volver a la canción", "page:Canción", style="back")
        elif self.page == "Instrumental":
            if self.instrumental_busy:
                text("Preparando instrumental…")
            elif not self.candidates and not self.message:
                text("No se han encontrado instrumentales.")
            for index, item in enumerate(self.candidates):
                button(item["title"], "candidate:" + str(index), style="link")
            button("Volver a la canción", "page:Canción", style="back")
        elif self.page == "Ajustes":
            field("Primer cantante", "player1", "Cantante 1")
            field("Segundo cantante (opcional)", "player2")
            slider("Volumen de música", "music", 65)
            slider("Volumen de mi voz", "gain:0", 0)
            if self.fields.get("player2", "").strip():
                slider("Volumen de la segunda voz", "gain:1", 0)
            button("Micrófonos", "page:Micrófonos", style="link")
            button("Biblioteca y descargas", "page:Descargas", style="link")
            button("Cuenta USDB", "page:Cuenta USDB", style="link")
        elif self.page == "Micrófonos":
            devices = self.engine.get("devices", [])
            for player, name in enumerate(self.names(), 1):
                current_input = next((
                    f"{device['name']} · Canal {channel + 1}"
                    for device in devices
                    for channel, assigned in enumerate(device.get("players", []))
                    if assigned == player
                ), "Elegir entrada")
                button(name, f"page:Entrada {player}", current_input, style="link")
            if self.engine.get("testing"):
                button("Detener prueba", "testinput", style="link")
                for index, level in enumerate(self.engine.get("levels", [])[:len(self.names())]):
                    text(f"Señal de {self.names()[index]}", f"{min(100, round(level * 100))}%")
            else:
                button("Probar señal", "testinput", style="link")
            field(
                "Corrección de sincronía · ms (-500 a 500)",
                "latency",
                str(self.store.setting("latency", 0)),
            )
            if self.fields.get("latency", str(self.store.setting("latency", 0))) != str(self.store.setting("latency", 0)):
                button("Aplicar sincronía", "latency")
            button("Volver a ajustes", "page:Ajustes", style="back")
        elif self.page in ("Entrada 1", "Entrada 2"):
            player = 0 if self.page == "Entrada 1" else 1
            devices = self.engine.get("devices", [])
            if not devices:
                text("Sin micrófonos detectados", "Conecta el micrófono y actualiza las entradas.")
            for device in devices:
                for channel in range(min(device["channels"], 8)):
                    selected = device.get("players", [])[channel:channel + 1] == [player + 1]
                    button(device["name"], f"device:{player}:{device['index']}:{channel}",
                           f"Canal {channel + 1}" + (" · Seleccionado" if selected else ""), style="link")
            button("Detectar micrófonos", "scan", style="link")
            button("Volver a micrófonos", "page:Micrófonos", style="back")
        elif self.page == "Descargas":
            button("Importar canciones", "import:open", style="link")
            field("Carpeta de canciones", "library", str(self.library))
            if self.fields.get("library", str(self.library)).strip() != str(self.library):
                button("Aplicar carpeta", "save-settings")
            button("Vídeo activado" if self.store.setting("video", True) else "Solo audio", "video")
            if self.store.setting("video", True):
                button("Calidad máxima · " + self.store.setting("resolution", "720p"), "resolution", style="link")
            button("Otros catálogos", "page:Otros catálogos", style="link")
            button("Volver a ajustes", "page:Ajustes", style="back")
        elif self.page == "Cuenta USDB":
            account = self.store.setting("username", "")
            if account:
                text("Cuenta conectada", account)
                button("Desconectar cuenta", "logout", style="link")
            else:
                text("Amplía tu catálogo", "Conecta tu cuenta gratuita de USDB para buscar más canciones.")
                field("Usuario", "username")
                field("Contraseña", "password", secret=True)
                button("Conectar cuenta", "login", style="primary")
            button("Volver a ajustes", "page:Ajustes", style="back")
        queue = self.store.queue()
        next_turn = next((turn for turn in queue if turn["state"] == "queued"), None)
        return {
            "carousel": self.carousel_view(),
            "next": ("Después: " + (next_turn["title"] or "Preparando canción"))
            if next_turn
            else "",
            "page": self.page,
            "rows": rows,
            "message": self.message,
            "queue_count": len(queue),
            "added_token": self.added_token,
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
        self.usdb_search_pool.shutdown(wait=True, cancel_futures=True)
        self.catalogue_pool.shutdown(wait=True, cancel_futures=True)
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.artwork.close()
        self.clean_catalogue_reviews()
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


def source_name(key):
    return {"usdb": "USDB", "deluxe": "Deluxe", "espana": "UltraStar España",
            "community-es": "UltraStar España", "community-eu": "USDB.eu",
            "allkaraoke": "AllKaraoke"}.get(key.partition(":")[0], "Biblioteca")


def is_assisted(key):
    return key.startswith(("allkaraoke:", "community-", "espana:"))


def work_key(song):
    # Loose grouping for display only. Queue and preparation always use the edition source ID.
    artist = re.split(r"\s+(?:feat\.?|ft\.?|featuring)\s+", normalize(song["artist"]), maxsplit=1)[0]
    title = re.sub(r"\s*[([](?:live|directo|studio|remix|radio edit|duet|duett|dueto|instrumental)\b[^)\]]*[)\]]",
                   "", normalize(song["title"]))
    return tuple(catalog.tokens(artist.replace("&", " y "))), tuple(catalog.tokens(title))


def group_results(results):
    groups = {}
    for song in results:
        groups.setdefault(work_key(song), []).append(song)
    return list(groups.values())
