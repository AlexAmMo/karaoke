"""Application state and file-based IPC. Only the engine touches live game objects."""

from __future__ import annotations
import concurrent.futures
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
from pathlib import Path
from .songs import SongError, duration, import_package, normalize, read_chart, validate
from .store import Store


def atomic_json(path: Path, value):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def child_command(module):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker", module]
    return [sys.executable, "-m", module]


class Service:
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
        self.message = "Importa una carpeta UltraStar o conecta USDB para empezar."
        self.results = []
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

    def provider(self, operation, **kwargs):
        response = self.root / ("response-" + uuid.uuid4().hex + ".json")
        request = {
            "root": str(self.root / "syncer"),
            "response": str(response),
            "operation": operation,
            "progress": str(self.root / "download-progress.json"),
            **self.credentials(),
            **kwargs,
        }
        # argv and logs contain no credentials. Use stdin, no persistent password file.
        log = tempfile.TemporaryFile()
        try:
            proc = subprocess.Popen(
                child_command("karaoke.provider"),
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
                text=True,
            )
            with self.children_lock:
                self.children.add(proc)
                if operation == "download":
                    self.download_process = proc
            deadline = time.monotonic() + (1800 if operation == "download" else 90)
            pending_input = json.dumps(request)
            while True:
                try:
                    proc.communicate(pending_input, timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    pending_input = None
                    if self.closing:
                        raise SongError("Preparación interrumpida; se reanudará al volver a abrir.")
                    if time.monotonic() > deadline:
                        raise SongError("La fuente ha tardado demasiado. Reintenta la operación.")
                    if (
                        operation == "download"
                        and shutil.disk_usage(self.root).free < 256 * 1024**2
                    ):
                        raise SongError("Descarga detenida: queda poco espacio disponible.")
            if proc.returncode or not response.exists():
                raise SongError("El servicio de catálogo ha fallado. Reintenta la operación.")
            result = json.loads(response.read_text(encoding="utf-8"))
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
                    if self.download_process is proc:
                        self.download_process = None
            response.unlink(missing_ok=True)
            log.close()

    def submit(self, work, callback):
        self.futures.append((self.pool.submit(work), callback))

    def search(self, query):
        self.query = query.strip()
        self.page = "Buscar"
        self.results = []
        self.pending_result = None
        self.search_generation += 1
        generation = self.search_generation
        query_snapshot = self.query
        if not self.query:
            self.message = "Escribe artista, título o un enlace de YouTube."
            return
        self.message = "Consultando mapas existentes en USDB…"

        def work():
            query = query_snapshot
            video_id = youtube_id(query)
            if query.startswith(("http://", "https://")) and not video_id:
                raise SongError("Introduce un enlace de YouTube válido.")
            if video_id:
                from yt_dlp import YoutubeDL

                with YoutubeDL(
                    {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20}
                ) as dl:
                    info = dl.extract_info(
                        "https://www.youtube.com/watch?v=" + video_id, download=False
                    )
                query = (
                    (info.get("artist") or info.get("creator") or "")
                    + " - "
                    + (info.get("track") or info.get("title", ""))
                )
                query = query.strip(" -")
            result = self.provider("search", query=query)
            items = result["songs"]
            # Even an associated URL isn't proof of musical compatibility. Surface candidates.
            for item in items:
                item["requested_video"] = video_id
                item["match"] = "Por comprobar" if video_id else "Mapa existente"
            return items

        def done(items):
            if generation != self.search_generation:
                return
            self.results = items
            self.message = (
                f"{len(items)} mapas encontrados. Revisa la versión antes de pedirla."
                if items
                else "No se han localizado mapas en USDB para esta búsqueda."
            )

        self.submit(work, done)
        self.futures[-1][0].search_generation = generation

    def prepare(self, job):
        payload = json.loads(job["payload"])
        if shutil.disk_usage(self.library).free < 512 * 1024**2:
            raise SongError("Preparación detenida: quedan menos de 512 MB libres.")
        if payload["kind"] == "import":
            return import_package(Path(payload["chart"]), self.library)
        target = self.root / "downloads" / job["id"]
        target.mkdir(parents=True, exist_ok=True)
        result = self.provider(
            "download",
            song=payload["song"],
            destination=str(target),
            video=self.store.setting("video", True),
            resolution=self.store.setting("resolution", "720p"),
        )
        failures = []
        for chart in result["charts"]:
            try:
                imported = import_package(Path(chart), self.library)
                shutil.rmtree(target)
                return imported
            except SongError as exc:
                failures.append(str(exc))
        raise SongError("; ".join(failures) or "No se encontró un paquete compatible.")

    def choose_folder(self):
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
            proc.communicate(json.dumps({"response": str(response)}))
            if not response.exists():
                return ""
            return json.loads(response.read_text(encoding="utf-8"))["folder"]
        finally:
            with self.children_lock:
                self.children.discard(proc)
            response.unlink(missing_ok=True)

    def add_import(self, value):
        folder = Path(value.strip().strip('"')).expanduser().resolve()
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
        song = dict(self.results[index])
        if song.get("requested_video"):
            # Require a deliberate selection, never replace the source media with pasted video.
            # Capture the actual song and intent. A later search can replace the
            # result array while this confirmation is still on screen.
            self.pending_result = {"song": song, "queue": bool(queue)}
            self.page = "Confirmar versión"
            return
        self._request_song(song, queue)

    def _request_song(self, song, queue):
        self.store.request(
            "usdb:" + str(song["song_id"]),
            {
                "kind": "usdb",
                "song": {k: v for k, v in song.items() if k not in ("requested_video", "match")},
            },
            self.names() if queue else None,
        )
        self.message = "Canción solicitada. Se preparará en segundo plano."

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
            self.message = "Comprobando acceso a USDB…"

            def work():
                self.provider("login", username=username, password=password)
                import keyring

                keyring.set_password("Karaoke/USDB", username, password)
                return username

            def done(user):
                self.store.configure("username", user)
                self.message = (
                    "USDB conectado. Contraseña guardada en el almacén seguro del sistema."
                )

            self.submit(work, done)
            return
        if action == "logout":
            import keyring

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
        if action.startswith("result:"):
            _, op, index = action.split(":")
            self.request_result(int(index), op == "queue")
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
            self.detail = action[5:]
            self.page = "Canción"
            self.confirm_delete = None
            self.candidate_audio = None
            self.candidate_generation += 1
            return
        if action == "enqueue":
            self.store.request(self.detail, {}, self.names())
            self.message = "Turno añadido a la cola."
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

        if self.page == "Terminar canción":
            text("¿Terminar esta interpretación?", "Se mostrarán los puntos obtenidos hasta ahora.")
            button("Continuar cantando", "page:Cola")
            button("Terminar y ver resultados", "confirm-end")
        elif self.page == "Biblioteca":
            songs = self.store.rows("SELECT * FROM songs ORDER BY artist,title,variant")
            text("Tu repertorio", f"{len(songs)} versiones guardadas · disponibles sin conexión")
            field("Filtrar biblioteca", "local")
            query = normalize(self.fields.get("local", ""))
            for song in songs:
                if query in normalize(song["artist"] + " " + song["title"]):
                    button(
                        song["title"],
                        "song:" + song["id"],
                        song["artist"]
                        + " · "
                        + (
                            "Instrumental confirmada"
                            if song["variant"] == "instrumental"
                            else "Audio original del paquete"
                        ),
                    )
            if not songs:
                text("Tu primera canción", "Importa un paquete o busca un mapa existente en USDB.")
            button("Elegir carpeta para importar", "choose-import")
            field("O pega una carpeta o archivo TXT", "import")
            button("Importar canciones", "import")
        elif self.page == "Buscar":
            text(
                "Encuentra tu próxima canción",
                "Artista, título, «artista - título» o enlace de YouTube",
            )
            field("Buscar en USDB", "query")
            button("Buscar mapas", "search")
            for index, song in enumerate(self.results):
                text(
                    song["title"],
                    song["artist"]
                    + " · "
                    + song.get("language", "")
                    + " · "
                    + song.get("match", ""),
                )
                button("Añadir a la cola", f"result:queue:{index}")
                button("Guardar sin turno", f"result:save:{index}")
        elif self.page == "Confirmar versión":
            text(
                "Comprueba la grabación",
                "El enlace pegado no demuestra compatibilidad con este mapa.",
            )
            selection = self.pending_result
            if selection:
                text(selection["song"]["title"], selection["song"].get("artist", ""))
            text(
                "Se usará el audio asociado por USDB",
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
            for index, turn in enumerate(turns):
                text(
                    f"{index + 1}. " + (turn["title"] or "Preparando canción"),
                    ", ".join(json.loads(turn["names"]))
                    + " · "
                    + (
                        "Lista"
                        if turn["song_id"]
                        else {
                            "waiting": "En espera",
                            "working": "Preparando",
                            "error": "Error",
                            "cancelled": "Cancelada",
                        }.get(turn["preparation"], "Pendiente")
                    ),
                )
                if turn["state"] == "queued":
                    if turn["song_id"]:
                        button(
                            "Empezar turno" if index == 0 else "Saltar a este turno",
                            "start:" + turn["id"],
                        )
                    button("Subir turno", "up:" + turn["id"])
                    button("Bajar turno", "down:" + turn["id"])
                    button("Quitar turno", "cancel:" + turn["id"])
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
        elif self.page == "Canción" and self.detail:
            song = self.song(self.detail)
            text(song["title"], song["artist"])
            text(
                "Instrumental confirmada por el anfitrión"
                if song["variant"] == "instrumental"
                else "Audio original del paquete",
                f"{round(song['duration'])} s · {song['language']}",
            )
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
        self.stop_preview()
        with self.children_lock:
            for child in self.children:
                if child.poll() is None:
                    child.terminate()
        self.pool.shutdown(wait=True, cancel_futures=True)
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
