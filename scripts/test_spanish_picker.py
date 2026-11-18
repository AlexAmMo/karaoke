#!/usr/bin/env python3
"""Run the real Qt download picker against an isolated HTTP fixture in a desktop session."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlsplit
from zipfile import ZipFile

from karaoke import spanish_picker


def fixture_bytes(kind):
    if kind == "torrent":
        import libtorrent

        return libtorrent.bencode(
            {
                b"info": {
                    b"name": b"sample.txt",
                    b"piece length": 16384,
                    b"length": 3,
                    b"pieces": hashlib.sha1(b"abc").digest(),
                }
            }
        )
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr("sample.txt", "download picker test")
    return data.getvalue()


def run_case(case):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel
    from PySide6.QtWebEngineWidgets import QWebEngineView

    kind = "torrent" if case == "torrent" else "zip"
    mime = "application/x-bittorrent" if kind == "torrent" else "application/zip"
    payload = fixture_bytes(kind)
    requested = threading.Event()
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                page = b'<title>Picker fixture</title><a id="edition" href="/package">Descargar edicion</a>'
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif path == "/package":
                requested.set()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Content-Disposition", f'attachment; filename="fixture.{kind}"')
                self.end_headers()
                self.wfile.write(payload[:1])
                self.wfile.flush()
                if case == "cancel":
                    done.wait(timeout=15)
                    return
                self.wfile.write(payload[1:])
            else:
                self.send_error(404)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_port}/"
    app = QApplication([])
    clicked = False
    cancelled = False
    timed_out = False

    def drive():
        nonlocal clicked, cancelled
        window = next(
            (
                w
                for w in app.topLevelWidgets()
                if w.isVisible() and w.windowTitle() == "Karaoke · UltraStar España"
            ),
            None,
        )
        if window is None:
            return
        browser = window.findChild(QWebEngineView)
        if browser.title() == "Picker fixture" and not clicked:
            clicked = True
            browser.page().runJavaScript("document.querySelector('#edition').click()")
        if (
            case == "cancel"
            and requested.is_set()
            and not cancelled
            and window.findChild(QLabel).text() == "Recibiendo la edición en Karaoke…"
        ):
            cancelled = True
            window.close()

    def timeout():
        nonlocal timed_out
        timed_out = True
        app.quit()

    action_timer = QTimer()
    action_timer.timeout.connect(drive)
    action_timer.start(50)
    QTimer.singleShot(15000, timeout)
    try:
        with tempfile.TemporaryDirectory(prefix="karaoke-picker-qa-") as tmp:
            root = Path(tmp)
            request = {
                "song": {"artist": "Fixture", "title": "Package"},
                "destination": tmp,
                "profile": str(root / "profile"),
            }
            with (
                patch.object(spanish_picker, "search_url", return_value=origin),
                patch.object(spanish_picker, "publisher_url", lambda url: url.startswith(origin)),
            ):
                result = spanish_picker.show(request)
            assert not timed_out and clicked and requested.is_set(), (
                case,
                result,
                "fixture timeout",
            )
            file = root / ("edition." + kind)
            if case == "cancel":
                assert cancelled and result == {"status": "cancelled"} and not file.is_file(), (
                    result
                )
            else:
                assert result == {"status": "selected", "kind": kind}, result
                assert file.read_bytes() == payload, file
            print(
                json.dumps(
                    {
                        "case": case,
                        "request_received": True,
                        "status": result["status"],
                        "bytes_verified": len(payload) if not cancelled else 0,
                    }
                ),
                flush=True,
            )
    finally:
        done.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["torrent", "zip", "cancel"])
    opts = parser.parse_args()
    if opts.case:
        run_case(opts.case)
    else:
        for name in ("torrent", "zip", "cancel"):
            result = subprocess.run(
                [sys.executable, __file__, "--case", name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            if result.returncode or "Traceback (most recent call last)" in result.stderr:
                raise SystemExit(f"Qt picker failed during {name}")
