"""Choose charts in a local ZIP or pair an existing chart with the user's recording."""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import acoustic
from .songs import SongError, import_package, read_chart, resource

MAX_BYTES = 2 * 1024**3
MAX_MEMBERS = 4096


def signature(path):
    info = path.stat()
    return f"{info.st_size}:{info.st_mtime_ns}"


def safe_name(name):
    parts = PurePosixPath(name).parts
    if (
        not parts
        or name.startswith("/")
        or "\\" in name
        or any(
            p in {".", ".."}
            or p.endswith((".", " "))
            or ":" in p
            or PureWindowsPath(p).is_reserved()
            for p in parts
        )
    ):
        raise SongError("El ZIP contiene un nombre de archivo no válido.")
    return PurePosixPath(*parts).as_posix()


def zip_members(archive):
    entries = archive.infolist()
    if len(entries) > MAX_MEMBERS or sum(i.file_size for i in entries) > MAX_BYTES:
        raise SongError("El ZIP supera el límite de 4096 archivos o 2 GB descomprimidos.")
    files, seen = {}, set()
    for entry in entries:
        name = safe_name(entry.filename)
        if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
            raise SongError("El ZIP contiene archivos cifrados o enlaces.")
        if name.casefold() in seen:
            raise SongError("Hay nombres de archivo duplicados en el ZIP.")
        seen.add(name.casefold())
        if not entry.is_dir():
            files[name] = entry
    return files


def chart_index(path):
    if path.stat().st_size > MAX_BYTES:
        raise SongError("El ZIP supera los 2 GB.")
    choices = []
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as temp:
        files = zip_members(archive)
        scratch = Path(temp) / "candidate.txt"
        for name, entry in files.items():
            if not name.lower().endswith(".txt") or entry.file_size > 8_000_000:
                continue
            scratch.write_bytes(archive.read(entry))
            try:
                _, meta = read_chart(scratch)
            except (SongError, UnicodeError):
                continue
            choices.append((name, f"{meta['ARTIST']} — {meta['TITLE']}"))
    if not choices:
        raise SongError("El ZIP no contiene mapas UltraStar compatibles.")
    return choices


def prepare_local(payload, library):
    if payload["kind"] == "paired":
        chart, audio = Path(payload["chart"]), Path(payload["audio"])
        stamps = payload.get("review_signatures")
        if stamps and stamps != [signature(chart), signature(audio)]:
            raise SongError("El mapa o el audio han cambiado desde la revisión.")
        acoustic.require_alignment(chart, audio)
        return import_pair(chart, audio, library, stamps)
    path = Path(payload["archive"])
    if signature(path) != payload["signature"]:
        raise SongError("El ZIP ha cambiado. Vuelve a elegir los mapas.")
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(dir=library) as temp:
        files = zip_members(archive)
        name = payload["member"]
        entry = files[name]
        if entry.file_size > 8_000_000:
            raise SongError("El mapa supera el tamaño permitido.")
        chart = Path(temp) / "song.txt"
        chart.write_bytes(archive.read(entry))
        _, meta = read_chart(chart)
        names = {meta.get("AUDIO") or meta.get("MP3", "")}
        names.update(meta[key] for key in ("COVER", "VIDEO", "BACKGROUND") if meta.get(key))
        referenced = {}
        for raw in names:
            local = safe_name(raw)
            entry = files.get(str(PurePosixPath(name).parent / local))
            if not entry or local.casefold() == "song.txt":
                raise SongError("Falta un recurso en el ZIP: " + raw)
            referenced[local] = entry
        if (
            sum(i.file_size for i in referenced.values()) * 2 + 256 * 1024**2
            > shutil.disk_usage(temp).free
        ):
            raise SongError("No hay espacio suficiente para preparar el ZIP.")
        for local, entry in referenced.items():
            dst = Path(temp) / local
            dst.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, dst.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        return import_package(chart, library)


def import_pair(chart, audio, library, expected_signatures=None):
    text, meta = read_chart(chart)
    if not audio.is_file():
        raise SongError("Selecciona un archivo de audio.")
    audio_name = "recording" + audio.suffix.lower()
    with tempfile.TemporaryDirectory(dir=library) as temp:
        dest = Path(temp)
        # Use deterministic names so the same pair can be reimported without duplicates.
        media = [(audio, audio_name)]
        fields = []
        for key in ("COVER", "VIDEO", "BACKGROUND"):
            if not meta.get(key):
                continue
            try:
                src = resource(chart.parent, meta[key])
            except SongError:
                continue
            name = key.lower() + src.suffix.lower()
            media.append((src, name))
            fields.append(f"#{key}:{name}")
        needed = sum(src.stat().st_size for src, _ in media) * 2 + 256 * 1024**2
        if shutil.disk_usage(dest).free < needed:
            raise SongError("No hay espacio suficiente para asociar la grabación.")
        for src, name in media:
            shutil.copyfile(src, dest / name)
        if expected_signatures and expected_signatures != [signature(chart), signature(audio)]:
            raise SongError("El mapa o el audio han cambiado durante la importación.")
        text = re.sub(
            r"^#(?:AUDIO|MP3|COVER|VIDEO|BACKGROUND):[^\n]*(?:\n|$)", "", text, flags=re.M | re.I
        )
        (dest / "song.txt").write_text(
            "\n".join([f"#MP3:{audio_name}", *fields, text]), encoding="utf-8"
        )
        return import_package(dest / "song.txt", library)


class PackageImportMixin:
    def open_pair(self, path):
        self.stop_preview()
        self.pair_chart = path
        self.pair_chart_stamp = signature(path)
        self.fields["pair_audio"] = ""
        self.page = "Asociar grabación"
        self.message = "Elige el archivo de audio correspondiente a este mapa."

    def queue_file_pair(self, audio):
        chart = self.pair_chart
        if not audio.is_file() or signature(chart) != self.pair_chart_stamp:
            raise SongError("El archivo ha cambiado. Vuelve a elegir el mapa y el audio.")
        stamps = [self.pair_chart_stamp, signature(audio)]
        source = hashlib.sha256(f"{chart}:{stamps[0]}:{audio}:{stamps[1]}".encode()).hexdigest()
        self.store.request("pair:" + source, dict(kind="paired", chart=str(chart), audio=str(audio),
                           review_signatures=stamps), None)
        self.page, self.message = "Cola", "Preparando la canción."

    def open_zip(self, path):
        stamp = signature(path)
        self.import_request = getattr(self, "import_request", 0) + 1
        generation = self.import_request
        self.page = "Importar paquete"
        self.message = "Leyendo mapas del ZIP…"

        def done(items):
            if generation != self.import_request or self.page != "Importar paquete":
                return
            self.zip_choices = items
            self.zip_path, self.zip_stamp = path, stamp
            self.zip_selected = set(range(len(items)))
            self.page = "Elegir mapas"
            self.message = "Elige las canciones que quieres guardar."

        self.submit(lambda: chart_index(path), done)

    def import_action(self, action):
        if action == "import:open":
            self.import_request = getattr(self, "import_request", 0) + 1
            self.page = "Importar paquete"
        elif action == "import:file":
            self.submit(
                lambda: self.choose_folder("package"), lambda p: self.add_import(p) if p else None
            )
        elif (
            action == "import:audio"
            and self.page == "Asociar grabación"
        ):
            chart = self.pair_chart

            def done(p):
                if p and self.page == "Asociar grabación" and self.pair_chart == chart:
                    self.queue_file_pair(Path(p).resolve())

            self.submit(lambda: self.choose_folder("audio"), done)
        elif action.startswith("import:toggle:") and self.page == "Elegir mapas":
            i = int(action.rsplit(":", 1)[1])
            if 0 <= i < len(self.zip_choices):
                self.zip_selected.symmetric_difference_update([i])
        elif action == "import:zip" and self.page == "Elegir mapas":
            if not self.zip_selected:
                raise SongError("Selecciona al menos un mapa.")
            for i in sorted(self.zip_selected):
                member = self.zip_choices[i][0]
                payload = dict(
                    kind="archive",
                    archive=str(self.zip_path),
                    signature=self.zip_stamp,
                    member=member,
                )
                self.store.request(f"zip:{self.zip_path}:{self.zip_stamp}:{member}", payload, None)
            self.page, self.message = "Cola", "Preparando las canciones elegidas."
        elif action == "import:pair" and self.page == "Asociar grabación":
            self.queue_file_pair(Path(self.fields.get("pair_audio", "")).expanduser().resolve())
        else:
            return False
        return True

    def import_rows(self, text, button, field):
        if self.page == "Importar paquete":
            button("Elegir archivo TXT o ZIP", "import:file")
            button("Elegir carpeta", "choose-import")
            field("Ruta de la carpeta, TXT o ZIP", "import")
            button("Abrir", "import")
        elif self.page == "Elegir mapas":
            for i, (_, title) in enumerate(self.zip_choices):
                button(
                    title,
                    f"import:toggle:{i}",
                    "Seleccionada" if i in self.zip_selected else "Sin seleccionar",
                )
            button(f"Importar selección ({len(self.zip_selected)})", "import:zip")
        elif self.page == "Asociar grabación":
            _, meta = read_chart(self.pair_chart)
            text(meta["TITLE"], meta["ARTIST"])
            button("Elegir archivo de audio", "import:audio")
        else:
            return False
        button("Volver a la biblioteca", "page:Biblioteca")
        return True
