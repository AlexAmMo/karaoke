"""Loopback-only review of the exact recording and its generated UltraStar events."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .songs import SongError, read_chart, resource, validate

WEB = Path(__file__).with_name("review_web")


class DraftEditor:
    def __init__(self, lab, uid):
        if lab.row(uid)["state"] != "review":
            raise SongError("Elige un borrador que esté listo para revisar.")
        self.lab, self.uid = lab, uid
        self.chart = lab.root / uid / "draft" / "song.txt"
        manifest = self.chart.with_name("generation.json")
        metadata = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        self.review_regions = metadata.get("diagnostics", {}).get("review_regions", [])
        self.key = secrets.token_urlsafe(24)
        self.lock = threading.RLock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ReviewHandler)
        self.server.editor = self
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)
        self.url = self.origin + "/" + self.key + "/"
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        self.thread.start()

    def chart_data(self):
        text, meta = read_chart(self.chart)
        events = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
        return {
            "body": events,
            "revision": hashlib.sha256(text.encode()).hexdigest(),
            "bpm": meta["BPM"],
            "gap": meta.get("GAP", "0"),
            "title": meta["TITLE"],
            "artist": meta["ARTIST"],
            "state": self.lab.row(self.uid)["state"],
            "regions": self.review_regions,
        }

    def change(self, data):
        with self.lock:
            old = self.chart_data()
            if old["state"] != "review" or old["revision"] != data.get("revision"):
                raise SongError("El borrador cambió. Recarga la página antes de guardarlo.")
            body = data.get("body")
            if not isinstance(body, str):
                raise SongError("Falta el contenido del mapa.")
            rows = [line for line in body.splitlines() if line.strip()]
            if not rows or rows[-1].strip() != "E":
                raise SongError("El mapa debe terminar con E.")
            last_end = None
            for line in rows[:-1]:
                if re.fullmatch(r"-\s+-?\d+(?:\s+-?\d+)?", line):
                    continue
                note = re.fullmatch(r"[:*FRG]\s+(-?\d+)\s+(\d+)\s+-?\d+\s+([^\x00-\x08]+)", line)
                if not note:
                    raise SongError("Revisa las filas de notas y saltos de frase del mapa.")
                start, length = int(note[1]), int(note[2])
                if last_end is not None and start < last_end:
                    raise SongError("Dos notas se solapan. Revisa su inicio y duración.")
                last_end = start + length
            text, _ = read_chart(self.chart)
            headers = "\n".join(line for line in text.splitlines() if line.startswith("#"))
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.chart.parent, delete=False
            ) as file:
                file.write(headers + "\n" + body.strip("\r\n") + "\n")
                stage = Path(file.name)
            try:
                validate(stage)
                os.replace(stage, self.chart)
            finally:
                stage.unlink(missing_ok=True)
            if data.get("approve") is True:
                self.lab.approve(self.uid)
            return self.chart_data()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


class ReviewHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def answer(self, code, body, mime="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def media(self, path):
        size = path.stat().st_size
        end = size - 1
        start = 0
        request = self.headers.get("Range", "")
        if request:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", request)
            if not match:
                return self.answer(416, {"error": "Rango inválido."})
            start = int(match[1])
            end = min(end, int(match[2])) if match[2] else end
            if not 0 <= start <= end:
                return self.answer(416, {"error": "Rango fuera de la grabación."})
        self.send_response(206 if request else 200)
        self.send_header(
            "Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        )
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        if request:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                block = f.read(min(left, 65536))
                if not block:
                    break
                self.wfile.write(block)
                left -= len(block)

    def handle_request(self):
        editor = self.server.editor
        path = urlsplit(self.path).path
        prefix = "/" + editor.key + "/"
        if self.headers.get_all("Host") != [editor.origin[7:]] or not path.startswith(prefix):
            return self.answer(404, {})
        item = path[len(prefix) :]
        try:
            if self.command == "POST":
                if (
                    item != "chart"
                    or self.headers.get_all("Origin") != [editor.origin]
                    or self.headers.get_content_type() != "application/json"
                ):
                    return self.answer(403, {})
                length = int(self.headers.get("Content-Length", -1))
                if not 0 <= length <= 2_000_000:
                    return self.answer(413, {})
                data = json.loads(self.rfile.read(length))
                return self.answer(200, editor.change(data))
            if item == "chart":
                return self.answer(200, editor.chart_data())
            if item == "audio":
                _, meta = read_chart(editor.chart)
                return self.media(resource(editor.chart.parent, meta.get("AUDIO") or meta["MP3"]))
            if item in ("", "editor.js", "editor.css"):
                file = WEB / (item or "index.html")
                return self.answer(
                    200, file.read_bytes(), mimetypes.guess_type(file.name)[0] + "; charset=utf-8"
                )
            return self.answer(404, {})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            return self.answer(400, {"error": str(error)})

    do_GET = do_POST = handle_request
