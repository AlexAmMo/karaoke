"""Validate and stage untrusted UltraStar packages without changing their timing."""

from __future__ import annotations

import errno
import hashlib
import math
import ntpath
import re
import shutil
import subprocess
import uuid
from pathlib import Path


class SongError(ValueError):
    pass


def normalize(value: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)
    )


def headers(text: str) -> dict[str, str]:
    return dict(
        (k.upper(), v.strip()) for k, v in re.findall(r"^#([A-Za-z0-9]+):(.*)$", text, re.M)
    )


def read_chart(path: Path, *, expected_sha256: str | None = None) -> tuple[str, dict]:
    if path.stat().st_size > 8_000_000:
        raise SongError("El mapa supera el tamaño permitido.")
    raw = path.read_bytes()
    if expected_sha256 and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise SongError("El mapa ha cambiado desde la verificación.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    meta = headers(text)
    for key in ("TITLE", "ARTIST", "BPM"):
        if not meta.get(key):
            raise SongError(f"Falta #{key} en el mapa.")
    try:
        bpm = float(meta["BPM"].replace(",", "."))
        gap = float(meta.get("GAP", "0").replace(",", "."))
        if not math.isfinite(bpm) or not 0 < bpm < 2000 or not math.isfinite(gap):
            raise ValueError
    except ValueError:
        raise SongError("BPM o GAP no válidos.") from None
    if re.search(r"^P\s*[23]", text, re.M) or meta.get("DUETSINGERP2"):
        raise SongError("Este mapa es un dúo con partes distintas; V1 usa una melodía común.")
    if meta.get("RELATIVE", "NO").upper() == "YES":
        raise SongError("Convierte este mapa de tiempos relativos a absolutos antes de importarlo.")
    # This Deluxe release explicitly ignores B rows during playback. A tempo
    # change would therefore move every subsequent note away from the recording.
    for raw_bpm in re.findall(r"^B\s+[^\n]*?\s+([^\s]+)[ \t]*$", text, re.M):
        try:
            change = float(raw_bpm.replace(",", "."))
        except ValueError:
            raise SongError("Cambio de tempo no válido en el mapa.") from None
        if not math.isclose(change, bpm):
            raise SongError(
                "Esta edición cambia de tempo durante la canción. Elige un mapa de tempo fijo compatible con Deluxe."
            )
    notes = []
    for line in text.splitlines():
        if line[:1] in (":", "*", "F", "R", "G"):
            match = re.match(r"^[:*FRG]\s+(-?\d+)\s+(\d+)\s+(-?\d+)(?:\s|$)", line)
            if not match:
                raise SongError("Hay una nota con formato incorrecto.")
            start, length, pitch = map(int, match.groups())
            if length <= 0 or abs(pitch) > 127:
                raise SongError("Hay una nota con duración o tono no válidos.")
            notes.append((start, length))
    if not notes or not re.search(r"^E\s*$", text, re.M):
        raise SongError("El mapa no contiene notas o le falta el final E.")
    meta["end_seconds"] = gap / 1000 + max(s + d for s, d in notes) * 60 / (4 * bpm)
    meta["freestyle"] = bool(re.search(r"^[FRG] ", text, re.M))
    return text, meta


def resource(folder: Path, name: str) -> Path:
    # Reject absolute paths even if they currently point inside the source folder:
    # joining one to the staging directory would otherwise write outside staging.
    if not name or "\\" in name or Path(name).is_absolute() or ntpath.splitdrive(name)[0]:
        raise SongError("El paquete contiene una ruta de archivo no válida.")
    candidate = (folder / name).resolve()
    if not candidate.is_relative_to(folder.resolve()) or not candidate.is_file():
        raise SongError(f"No se encuentra un recurso del paquete: {name}")
    return candidate


def duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        value = float(result.stdout.strip())
        if result.returncode or not math.isfinite(value) or value <= 0:
            raise ValueError
        return value
    except ValueError:
        raise SongError(
            "El audio no se puede leer. Revisa el archivo o vuelve a descargarlo."
        ) from None


def validate(path: Path) -> dict:
    _, meta = read_chart(path)
    audio = resource(path.parent, meta.get("AUDIO") or meta.get("MP3", ""))
    seconds = duration(audio)
    if meta["end_seconds"] > seconds + 2:
        raise SongError("El audio acaba antes de las últimas notas. No es una versión compatible.")
    for key in ("VIDEO", "COVER", "BACKGROUND"):
        if meta.get(key):
            resource(path.parent, meta[key])
    return {
        "title": meta["TITLE"],
        "artist": meta["ARTIST"],
        "language": meta.get("LANGUAGE", ""),
        "duration": seconds,
        "freestyle": meta["freestyle"],
        "chart": str(path.resolve()),
        "audio": str(audio),
    }


def import_package(
    chart: Path,
    library: Path,
    *,
    expected_audio_sha256: str | None = None,
    expected_chart_sha256: str | None = None,
) -> dict:
    validate(chart)
    text, meta = read_chart(chart, expected_sha256=expected_chart_sha256)
    names = {meta.get("AUDIO") or meta.get("MP3", "")}
    names.update(meta[k] for k in ("VIDEO", "COVER", "BACKGROUND") if meta.get(k))
    # Canonical encoding makes reimporting our own prepared package idempotent.
    text = re.sub(r"^#ENCODING:.*\n?", "", text, flags=re.M | re.I)
    text = "#ENCODING:UTF8\n" + text
    digest = hashlib.sha256(text.encode())
    for name in sorted(names):
        verify_audio = expected_audio_sha256 and name == (meta.get("AUDIO") or meta["MP3"])
        audio_hash = hashlib.sha256() if verify_audio else None
        with resource(chart.parent, name).open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
                if audio_hash is not None:
                    audio_hash.update(block)
        if audio_hash is not None and audio_hash.hexdigest() != expected_audio_sha256:
            raise SongError("El audio ha cambiado. Revisa esta edición antes de cantar.")
    song_id = digest.hexdigest()[:32]
    library.mkdir(parents=True, exist_ok=True)
    target = library / song_id

    def check_installed(folder):
        path = folder / "song.txt"
        info = validate(path)
        if expected_chart_sha256 and read_chart(path)[0] != text:
            raise SongError("La copia de la biblioteca ya no coincide con el mapa verificado.")
        if expected_audio_sha256:
            with Path(info["audio"]).open("rb") as audio:
                if hashlib.file_digest(audio, "sha256").hexdigest() != expected_audio_sha256:
                    raise SongError(
                        "La copia del audio ya no coincide con la grabación verificada."
                    )
        return info

    if target.exists():
        info = check_installed(target)
    else:
        required = sum(resource(chart.parent, n).stat().st_size for n in names)
        if shutil.disk_usage(library).free < required + 256 * 1024**2:
            raise SongError(
                "No hay espacio suficiente. Libera espacio o cambia la carpeta de biblioteca."
            )
        staging = library / (".import-" + uuid.uuid4().hex)
        try:
            staging.mkdir()
            for name in names:
                dest = staging / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(resource(chart.parent, name), dest)
            (staging / "song.txt").write_text(text, encoding="utf-8")
            info = check_installed(staging)
            try:
                staging.rename(target)
            except OSError as exc:
                if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY) or not target.is_dir():
                    raise
                info = check_installed(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return {
        **info,
        "id": song_id,
        "chart": str(target / "song.txt"),
        "audio": str(target / (meta.get("AUDIO") or meta["MP3"])),
    }
