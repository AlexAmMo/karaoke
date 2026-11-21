"""Explicit, resumable draft generation. Only a reviewed draft can enter the song library."""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .songs import SongError, import_package, validate

HERE = Path(__file__).parent
WORKER = HERE / "generation_worker.py"


class GenerationLab:
    def __init__(self, host):
        self.host = host
        self.root = host.root / "generation"
        self.root.mkdir(exist_ok=True, mode=0o700)
        self.models = Path(os.environ.get("KARAOKE_GENERATION_CACHE", self.root / "models"))
        self.db = host.store
        self.db.execute("""CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,video TEXT NOT NULL,profile TEXT NOT NULL,
          title TEXT NOT NULL,artist TEXT NOT NULL,language TEXT NOT NULL,lookup INTEGER NOT NULL,lyrics TEXT,
          state TEXT NOT NULL,message TEXT NOT NULL,created REAL NOT NULL, song_id TEXT)""")
        self.db.execute(
            "UPDATE drafts SET state='waiting', message='Reanudando al abrir Karaoke' WHERE state='working'"
        )
        self.pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="borradores"
        )
        self.future = self.current = self.process = self.editor = None
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.closing = False
        self.analyzing = self.paused = False
        self.stage = ""

    @property
    def python(self):
        override = os.environ.get("KARAOKE_GENERATION_PYTHON")
        return (
            Path(override)
            if override
            else self.root / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )

    def rows(self):
        return self.db.rows(
            "SELECT id,title,artist,state,message,video,profile FROM drafts ORDER BY created DESC"
        )

    def row(self, uid):
        rows = self.db.rows("SELECT * FROM drafts WHERE id=?", (uid,))
        if not rows:
            raise SongError("Ese borrador ya no existe.")
        return rows[0]

    def enqueue(self, video, title, artist, language, profile, lookup=False, lyrics=None):
        if (
            not re.fullmatch("[a-zA-Z0-9_-]{11}", video or "")
            or language not in ("auto", "en", "es")
            or profile not in ("standard", "quality")
        ):
            raise SongError("Comprueba el enlace de YouTube, el idioma y el método.")

        def clean(value):
            return " ".join(str(value or "").split())[:160]

        if lyrics and (not Path(lyrics).is_file() or Path(lyrics).stat().st_size > 128_000):
            raise SongError("Selecciona un TXT de letra de menos de 128 KB.")
        title, artist = clean(title), clean(artist)
        text = Path(lyrics).read_text(encoding="utf-8-sig") if lyrics else None
        prior = self.db.rows(
            """SELECT id FROM drafts WHERE video=? AND profile=? AND language=? AND lookup=?
            AND lyrics IS ? AND title=? AND artist=? AND state IN ('waiting','working')""",
            (video, profile, language, int(lookup), text, title, artist),
        )
        if prior:
            return prior[0]["id"]
        uid = uuid.uuid4().hex
        self.db.execute(
            "INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uid,
                video,
                profile,
                title,
                artist,
                language,
                int(lookup),
                text,
                "waiting",
                "Pendiente",
                time.time(),
                None,
            ),
        )
        return uid

    def report(self, uid, message):
        self.db.execute(
            "UPDATE drafts SET message=? WHERE id=? AND state='working'", (message, uid)
        )

    def run(self, command, job, log):
        if self.cancelled.is_set():
            raise SongError("Generación cancelada.")
        env = os.environ.copy()
        env.update(
            {
                "OMP_NUM_THREADS": "4",
                "VECLIB_MAXIMUM_THREADS": "4",
                "HF_HOME": os.environ.get("HF_HOME", str(self.models / "huggingface")),
                "TORCH_HOME": os.environ.get("TORCH_HOME", str(self.models / "torch")),
                "UV_NO_PROGRESS": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        # Frozen launcher envs may point child processes at the embedded Python libs.
        env.pop("PYTHONPATH", None)
        if "LD_LIBRARY_PATH_ORIG" in env:
            env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
        with self.lock:
            if self.cancelled.is_set():
                raise SongError("Generación cancelada.")
            flags = (
                subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
                if os.name == "nt"
                else 0
            )
            process = subprocess.Popen(
                [str(x) for x in command],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=flags,
                start_new_session=os.name != "nt",
            )
            self.process = process
            self.analyzing = WORKER in command
            self.stage = "Generando el borrador"
            if os.name != "nt":
                with contextlib.suppress(OSError):
                    os.setpriority(os.PRIO_PROCESS, process.pid, 10)
        try:
            last_error = ""
            with log.open("ab") as dest, process.stdout as pipe:
                while chunk := pipe.readline(8192):
                    dest.write(chunk)
                    if chunk.startswith(b"{"):
                        try:
                            item = json.loads(chunk)
                        except (ValueError, UnicodeDecodeError):
                            continue
                        stage = item.get("stage") if isinstance(item, dict) else None
                        if isinstance(stage, str):
                            with self.lock:
                                self.stage = stage[:180]
                                if not self.paused:
                                    self.report(job["id"], self.stage)
                        if isinstance(item, dict) and isinstance(item.get("error"), str):
                            last_error = item["error"][:260]
            code = process.wait()
        finally:
            with self.lock:
                self.process = None
                self.paused = self.analyzing = False
        if self.cancelled.is_set():
            raise SongError("Generación cancelada.")
        if code:
            if last_error:
                raise SongError(last_error)
            raise SongError(
                f"Falló la preparación local. Puedes reintentar. Detalles en {log.name}."
            )

    def bootstrap(self, job, log):
        requirements = HERE / "generation_assets" / "requirements.txt"
        digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
        marker = self.root / "env-ready"
        if os.environ.get("KARAOKE_GENERATION_PYTHON") or (
            self.python.is_file() and marker.exists() and marker.read_text() == digest
        ):
            return
        import uv

        uv_exe = (
            Path(getattr(sys, "_MEIPASS", HERE)) / "tools" / ("uv.exe" if os.name == "nt" else "uv")
        )
        if not uv_exe.exists():
            uv_exe = Path(uv.find_uv_bin())
        self.report(job["id"], "Instalando el entorno de generación · primera vez")
        if not self.python.is_file():
            self.run([uv_exe, "venv", "--python", "3.12", self.root / "env"], job, log)
        self.run([uv_exe, "pip", "install", "--python", self.python, "-r", requirements], job, log)
        marker.write_text(digest)

    def generate(self, job):
        uid = job["id"]
        home = self.root / uid
        home.mkdir(exist_ok=True, mode=0o700)
        target = home / "draft"
        log = home / "generation.log"
        # A forced quit may leave a private, uncommitted staging directory for this job.
        for attempt in home.glob("attempt-*"):
            if attempt.is_dir() and not attempt.is_symlink():
                shutil.rmtree(attempt)
        self.check_resources(home)
        if (target / "generation.json").is_file() and (target / "song.txt").is_file():
            validate(target / "song.txt")
            return
        with tempfile.TemporaryDirectory(prefix="attempt-", dir=home) as temporary:
            stage = Path(temporary)
            self.bootstrap(job, log)
            self.report(uid, "Obteniendo la grabación exacta de YouTube")
            from yt_dlp import YoutubeDL

            def guard(_):
                self.check_resources(home)

            options = {
                "quiet": True,
                "no_warnings": True,
                "noprogress": True,
                "noplaylist": True,
                "format": "bestaudio/best",
                "outtmpl": str(stage / "source.%(ext)s"),
                "max_filesize": 200 * 1024**2,
                "socket_timeout": 12,
                "retries": 1,
                "progress_hooks": [guard],
                "match_filter": lambda info, *, incomplete=False: (
                    "Elige una canción de menos de 15 minutos."
                    if info.get("is_live") or (info.get("duration") or 0) > 900
                    else None
                ),
            }
            with YoutubeDL(options) as dl:
                info = dl.extract_info(
                    "https://www.youtube.com/watch?v=" + job["video"], download=True
                )
                if not info or info.get("id") != job["video"]:
                    raise SongError("YouTube no ha entregado esta grabación.")
                audio = Path(dl.prepare_filename(info))
                tracks = []
                if job["profile"] == "quality" and not job["lyrics"]:
                    from .generation_assets.captions import manual_tracks
                    from yt_dlp.networking.exceptions import RequestError

                    # Authored subtitles are optional. Unavailable subtitles should fall back to ASR.
                    with contextlib.suppress(
                        OSError, ValueError, TypeError, KeyError, RequestError
                    ):
                        tracks = manual_tracks(info, job["language"], dl.urlopen)
            if not audio.is_file():
                raise SongError("No se pudo obtener el audio de esta edición.")
            title = job["title"] or info.get("track") or info.get("title") or job["video"]
            artist = (
                job["artist"] or info.get("artist") or info.get("uploader") or "Artista desconocido"
            )
            command = [
                self.python,
                WORKER,
                "--audio",
                audio,
                "--output",
                stage / "draft",
                "--title",
                title,
                "--artist",
                artist,
                "--profile",
                job["profile"],
                "--language",
                job["language"],
                "--cache",
                self.models,
            ]
            if tracks:
                captions = stage / "captions.json"
                captions.write_text(json.dumps(tracks, ensure_ascii=False), encoding="utf-8")
                command.extend(["--captions", captions])
            if job["lookup"]:
                command.append("--lookup-lyrics")
            if job["lyrics"]:
                file = stage / "lyrics.txt"
                file.write_text(job["lyrics"], encoding="utf-8")
                command.extend(["--lyrics", file])
            self.report(
                uid, "Generando letra, notas y tiempos. Los modelos se descargan la primera vez."
            )
            self.run(command, job, log)
            self.check_resources(home)
            validate(stage / "draft" / "song.txt")
            manifest = stage / "draft" / "generation.json"
            provenance = json.loads(manifest.read_text(encoding="utf-8"))
            provenance.update(video_id=job["video"], automatically_verified=False, state="draft")
            manifest.write_text(
                json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(stage / "draft", target)
            self.db.execute("UPDATE drafts SET title=?,artist=? WHERE id=?", (title, artist, uid))

    def check_resources(self, path):
        if self.cancelled.is_set():
            raise SongError("Generación cancelada.")
        if shutil.disk_usage(path).free < 512 * 1024**2:
            raise SongError("Falta espacio para generar el borrador.")

    def pause_analysis(self, pause):
        with self.lock:
            if not self.analyzing or self.paused == pause or self.process.poll() is not None:
                return
            if os.name == "nt":
                import psutil

                try:
                    process = psutil.Process(self.process.pid)
                    if pause:
                        process.suspend()
                    else:
                        process.resume()
                except psutil.Error:
                    return
            else:
                import signal

                try:
                    os.killpg(self.process.pid, signal.SIGSTOP if pause else signal.SIGCONT)
                except ProcessLookupError:
                    return
            self.paused = pause
            self.report(self.current, "En pausa mientras se canta" if pause else self.stage)

    def tick(self):
        self.pause_analysis(bool(self.host.active))
        if self.future and self.future.done():
            try:
                self.future.result()
                self.db.execute(
                    "UPDATE drafts SET state='review',message='Listo para revisar' WHERE id=? AND state='working'",
                    (self.current,),
                )
            except Exception as exc:
                self.db.execute(
                    "UPDATE drafts SET state='error',message=? WHERE id=? AND state='working'",
                    (str(exc)[:480], self.current),
                )
            self.future = self.current = None
        if self.future or self.host.active or self.closing:
            return
        rows = self.db.rows("SELECT * FROM drafts WHERE state='waiting' ORDER BY created LIMIT 1")
        if rows:
            job = rows[0]
            self.cancelled.clear()
            self.current = job["id"]
            self.db.execute(
                "UPDATE drafts SET state='working',message='Iniciando' WHERE id=?", (self.current,)
            )
            self.future = self.pool.submit(self.generate, job)

    def cancel(self, uid):
        if uid == self.current:
            self.cancelled.set()
            self.pause_analysis(False)
            with self.lock:
                process = self.process
                if process and process.poll() is None:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                    else:
                        import signal

                        with contextlib.suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGTERM)
        self.db.execute(
            "UPDATE drafts SET state='cancelled',message='Cancelado' WHERE id=? AND state IN ('waiting','working')",
            (uid,),
        )

    def approve(self, uid):
        row = self.row(uid)
        if row["state"] == "approved":
            return row["song_id"]
        if row["state"] != "review":
            raise SongError("La generación aún no está lista para revisar.")
        info = import_package(self.root / uid / "draft" / "song.txt", self.host.library)
        manifest = self.root / uid / "draft" / "generation.json"
        if manifest.exists():
            provenance = json.loads(manifest.read_text(encoding="utf-8"))
            source_hash = hashlib.sha256((manifest.parent / "song.txt").read_bytes()).hexdigest()
            provenance["review"] = {
                "chart_sha256": source_hash,
                "library_chart_sha256": hashlib.sha256(
                    Path(info["chart"]).read_bytes()
                ).hexdigest(),
                "edited": source_hash != provenance.get("chart_sha256"),
                "approved_at": time.time(),
            }
            provenance["state"] = "reviewed"
            dest = Path(info["chart"]).with_name("generation.json")
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=dest.parent, delete=False
            ) as f:
                json.dump(provenance, f, ensure_ascii=False, indent=2)
            os.replace(f.name, dest)
        with self.db.lock, self.db.db:
            self.db._save_song(info, "reviewed:" + uid, "original", None, True)
            self.db.db.execute(
                "UPDATE drafts SET state='approved',message='Revisada por el anfitrión',song_id=? WHERE id=?",
                (info["id"], uid),
            )
        return info["id"]

    def close(self):
        self.closing = True
        if self.editor:
            self.editor.close()
        if self.current:
            uid = self.current
            self.cancel(uid)
            self.db.execute(
                "UPDATE drafts SET state='waiting',message='Pendiente de reanudar' WHERE id=? AND state='cancelled'",
                (uid,),
            )
        self.pool.shutdown(wait=True, cancel_futures=True)

    def display(self, view, text, button, field):
        if view.page == "Generar":
            field("Enlace de YouTube", "generate_url", view.query if "youtu" in view.query else "")
            title = view.fields.get("generate_title", "")
            field("Título (opcional)", "generate_title", title)
            field("Artista (opcional)", "generate_artist")
            language = view.store.setting("draft_language", "auto")
            profile = view.store.setting("draft_profile", "quality")
            button(
                "Idioma · " + {"auto": "Detectar", "en": "Inglés", "es": "Español"}[language],
                "lab:language",
                style="link",
            )
            button(
                "Método · " + ("Alineación cantada" if profile == "quality" else "Estándar"),
                "lab:profile",
                style="link",
            )
            button(
                "Letra · "
                + (
                    "Archivo seleccionado"
                    if view.fields.get("draft_lyrics")
                    else "Añadir un TXT propio"
                ),
                "lab:lyrics",
                style="link",
            )
            if view.fields.get("draft_lyrics"):
                button("Usar transcripción automática", "lab:clear", style="link")
            elif profile == "quality":
                button(
                    "Consultar LRCLIB · "
                    + ("Sí" if view.store.setting("draft_lookup", False) else "No"),
                    "lab:lookup",
                    style="link",
                )
            if profile == "quality":
                text(
                    "Modelos de uso no comercial. La primera generación instala varios GB en este ordenador."
                )
            else:
                text("Descarga los modelos una vez. Los borradores se revisan antes de cantar.")
            button("Generar borrador", "lab:enqueue", style="primary")
            for row in self.rows():
                button(
                    row["title"] or row["video"],
                    "lab:detail:" + row["id"],
                    row["message"],
                    style="link",
                )
            button("Volver a buscar", "page:Buscar", style="back")
        elif view.page == "Borrador" and getattr(view, "draft_id", None):
            row = self.row(view.draft_id)
            text(row["title"] or row["video"], row["artist"])
            text(row["message"])
            if row["state"] == "review":
                button("Escuchar y revisar", "lab:review", style="primary")
            elif row["state"] in ("waiting", "working"):
                button("Cancelar generación", "lab:cancel")
            elif row["state"] in ("cancelled", "error"):
                button("Reintentar", "lab:retry")
            elif row["state"] == "approved":
                button("Añadir a la cola", "enqueue:" + row["song_id"], style="primary")
            button("Volver a borradores", "page:Generar", style="back")
        else:
            return False
        return True

    def action(self, view, op):
        if op == "language":
            langs = ("auto", "es", "en")
            view.store.configure(
                "draft_language",
                langs[(langs.index(view.store.setting("draft_language", "auto")) + 1) % 3],
            )
        elif op == "profile":
            view.store.configure(
                "draft_profile",
                "standard"
                if view.store.setting("draft_profile", "quality") == "quality"
                else "quality",
            )
        elif op == "lookup":
            view.store.configure("draft_lookup", not view.store.setting("draft_lookup", False))
        elif op == "lyrics":

            def chosen(path):
                if path:
                    view.fields["draft_lyrics"] = path

            view.submit(lambda: view.choose_folder("lyrics"), chosen)
        elif op == "clear":
            view.fields.pop("draft_lyrics", None)
        elif op == "enqueue":
            from .service import youtube_id

            url = view.fields.get("generate_url", view.query).strip()
            view.draft_id = self.enqueue(
                youtube_id(url),
                view.fields.get("generate_title", ""),
                view.fields.get("generate_artist", ""),
                view.store.setting("draft_language", "auto"),
                view.store.setting("draft_profile", "quality"),
                view.store.setting("draft_lookup", False),
                view.fields.get("draft_lyrics"),
            )
            view.page = "Borrador"
        elif op.startswith("detail:"):
            view.draft_id = self.row(op.split(":", 1)[1])["id"]
            view.page = "Borrador"
        elif op == "cancel":
            self.cancel(view.draft_id)
        elif op == "retry":
            self.db.execute(
                "UPDATE drafts SET state='waiting',message='Pendiente' WHERE id=? AND state IN ('error','cancelled')",
                (view.draft_id,),
            )
        elif op == "review":
            import webbrowser
            from .draft_review import DraftEditor

            if self.editor:
                self.editor.close()
            self.editor = DraftEditor(self, view.draft_id)
            webbrowser.open(self.editor.url)
        else:
            raise SongError("Acción de generación desconocida.")
