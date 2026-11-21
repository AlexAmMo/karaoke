import hashlib
import struct
import threading
import time
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import libtorrent as lt
import numpy as np
import pytest

from karaoke import torrent_package as provider
from karaoke.songs import SongError


SONG = {"artist": "Fixture", "title": "Canción de prueba"}


def test_zip_keeps_edition_and_checks_matched_audio(tmp_path, package, monkeypatch):
    checked = []
    monkeypatch.setattr(
        provider.acoustic, "require_alignment", lambda chart, audio: checked.append(audio)
    )
    archive = tmp_path / "one.zip"
    with zipfile.ZipFile(archive, "w") as f:
        f.write(package, "edición/map.txt")
        f.write(package.parent / "audio.wav", "edición/audio.wav")
        f.writestr("otro/map.txt", package.read_text().replace("Canción de prueba", "Otra canción"))
    chart = provider.prepare_zip(archive, tmp_path, SONG)
    assert chart.read_bytes() == package.read_bytes()
    assert checked == [chart.parent / "audio.wav"]
    with pytest.raises(SongError, match="edición elegida"):
        provider.prepare_zip(archive, tmp_path, {**SONG, "artist": "Otro cantante"})


def test_torrent_rejects_invalid_descriptor(tmp_path):
    bad = tmp_path / "download.torrent"
    bad.write_bytes(b"<html>login</html>")
    with pytest.raises(SongError, match="torrent"):
        provider.prepare_torrent(bad, tmp_path, SONG)


def test_web_zip_rejects_duplicate_editions(tmp_path, package):
    archive = tmp_path / "multi.zip"
    with zipfile.ZipFile(archive, "w") as f:
        for directory in ("directo", "estudio"):
            f.write(package, directory + "/song.txt")
    with pytest.raises(SongError, match="único mapa"):
        provider.prepare_zip(archive, tmp_path, SONG)


def test_receive_real_multifile_torrent_from_local_peer(tmp_path, package):
    """Only tracker and peer are loopback. Transfer pieces through the native BitTorrent engine."""
    seed = lt.session(
        {
            "listen_interfaces": "127.0.0.1:0",
            "enable_dht": False,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
            "stop_tracker_timeout": 1,
            "allow_multiple_connections_per_ip": True,
        }
    )

    class Tracker(BaseHTTPRequestHandler):
        def do_GET(self):
            peer = bytes([127, 0, 0, 1]) + struct.pack(">H", seed.listen_port())
            if parse_qs(urlsplit(self.path).query).get("left") == ["0"]:
                peer = b""
            response = lt.bencode({b"complete": 1, b"interval": 1, b"peers": peer})
            self.send_response(200)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *args):
            pass

    tracker = ThreadingHTTPServer(("127.0.0.1", 0), Tracker)
    thread = threading.Thread(target=tracker.serve_forever, daemon=True)
    thread.start()
    # An original changing melody supplies enough pitch evidence in each third
    # for the production verifier; silence would correctly reject this package.
    lines = ["#TITLE:Canción de prueba", "#ARTIST:Fixture", "#BPM:120", "#MP3:audio.wav"]
    rate = 11025
    signal = np.zeros(rate * 56)
    for index, pitch in enumerate(np.random.default_rng(31).integers(0, 12, size=100)):
        start = 24 + index * 4
        lines.append(f": {start} 3 {pitch} la")
        samples = round(0.375 * rate)
        phase = np.arange(samples) * (2 * np.pi * 440 * 2 ** ((60 + pitch - 69) / 12) / rate)
        at = round(start * 0.125 * rate)
        signal[at : at + samples] = (np.sin(phase) + 0.26 * np.sin(4 * phase)) * np.hanning(samples)
    package.write_text("\n".join([*lines, "E"]), encoding="utf-8")
    with wave.open(str(package.parent / "audio.wav"), "wb") as writer:
        writer.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes((signal * 16000).astype("<i2").tobytes())
    try:
        # Ordinary v1 multi-file torrent, canonical bencoded metainfo and piece digests.
        files = [package, package.parent / "audio.wav"]
        data = b"".join(f.read_bytes() for f in files)
        size = 16384
        metainfo = lt.bencode(
            {
                b"announce": f"http://127.0.0.1:{tracker.server_port}/announce".encode(),
                b"info": {
                    b"name": package.parent.name.encode(),
                    b"piece length": size,
                    b"private": 1,
                    b"pieces": b"".join(
                        hashlib.sha1(data[i : i + size]).digest() for i in range(0, len(data), size)
                    ),
                    b"files": [
                        {b"length": f.stat().st_size, b"path": [f.name.encode()]} for f in files
                    ],
                },
            }
        )
        torrent = tmp_path / "edition.torrent"
        torrent.write_bytes(metainfo)
        params = lt.load_torrent_buffer(metainfo)
        params.save_path = str(package.parent.parent)
        handle = seed.add_torrent(params)
        # A new Windows runner can still be checking the seed when the socket opens.
        deadline = time.monotonic() + 30
        while True:
            status = handle.status()
            port = seed.listen_port()
            if status.is_seeding and port:
                break
            assert time.monotonic() < deadline, f"Local seed state={status.state}, port={port}"
            time.sleep(0.05)
        messages = []
        chart = provider.prepare_torrent(torrent, tmp_path, SONG, messages.append)
        assert chart.parent != package.parent and chart.read_bytes() == package.read_bytes()
        assert (chart.parent / "audio.wav").read_bytes() == (
            package.parent / "audio.wav"
        ).read_bytes()
        assert messages
    finally:
        tracker.shutdown()
        tracker.server_close()
        thread.join(2)


@pytest.mark.parametrize("cancel", (True, False))
def test_unseeded_package_can_be_cancelled_or_retried(tmp_path, monkeypatch, cancel):
    payload = b"an unseeded chart"
    torrent = tmp_path / "private.torrent"
    torrent.write_bytes(
        lt.bencode(
            {
                b"announce": b"http://127.0.0.1:1/announce?passkey=private",
                b"info": {
                    b"name": b"song.txt",
                    b"piece length": 16384,
                    b"private": 1,
                    b"pieces": hashlib.sha1(payload).digest(),
                    b"length": len(payload),
                },
            }
        )
    )
    monkeypatch.setattr(provider, "STALL_SECONDS", 0.40)

    def report(_):
        if cancel:
            raise SongError("Preparación cancelada.")

    with pytest.raises(SongError, match="cancelada" if cancel else "fuentes") as error:
        provider.prepare_torrent(torrent, tmp_path, SONG, report)
    assert "passkey" not in str(error.value)
