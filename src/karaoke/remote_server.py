"""A temporary, authenticated remote control on one interface of the host's LAN."""

from __future__ import annotations

import ipaddress
import os
import ssl
import json
import re
import secrets
import socket
import threading
import time
from collections import deque
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import unquote, urlsplit

import ifaddr
import qrcode

WEB = Path(__file__).with_name("remote_web")
ASSETS = {
    "/voice-capture.js": ("voice-capture.js", "text/javascript; charset=utf-8"),
    "/people.js": ("people.js", "text/javascript; charset=utf-8"),
    "/": ("index.html", "text/html; charset=utf-8"),
    "/instrument-sans.woff2": ("instrument-sans.woff2", "font/woff2"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/palette.css": ("palette.css", "text/css; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
MAX_BODY = 8192
CLOSE_NOTICE_SECONDS = 45
SESSION_LIFETIME = 12 * 60 * 60
LAN_NETWORKS = tuple(map(ipaddress.ip_network, (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10",
)))


class RemoteError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def lan_addresses():
    """Offer reachable IPv4 interfaces, prioritising the usual Wi-Fi/Ethernet route."""
    preferred = ""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # UDP connect asks the kernel which local address it would use. No data is sent.
            probe.connect(("192.0.2.1", 9))
            preferred = probe.getsockname()[0]
    except OSError:
        pass
    candidates = {}
    for adapter in ifaddr.get_adapters():
        name = adapter.nice_name.casefold()
        virtual = any(word in name for word in ("vpn", "utun", "veth", "vmnet", "virtual", "docker", "wsl", "tunnel"))
        for address in adapter.ips:
            if address.is_IPv4 and any(ipaddress.ip_address(address.ip) in net for net in LAN_NETWORKS):
                candidates[address.ip] = (virtual, address.ip != preferred, address.ip)
    return sorted(candidates, key=candidates.get)


class _Listener(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32

    def __init__(self, host, dispatch):
        self.dispatch = dispatch
        self.slots = threading.BoundedSemaphore(32)
        self.lock = threading.Lock()
        self.sessions = {}
        self.failures = deque(maxlen=128)
        self.code = f"{secrets.randbelow(1_000_000):06d}"
        self.secret = secrets.token_urlsafe(24)
        self.expires = time.monotonic() + SESSION_LIFETIME
        self.closed = False
        super().__init__((host, 0), _Handler)
        self.authority = f"{host}:{self.server_port}"
        self.url = "http://" + self.authority
        self.cookie_name = f"karaoke_{self.server_port}"

    def server_bind(self):
        # HTTPServer's default reverse-DNS lookup can stall startup on offline LANs.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        request.settimeout(8)
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def join(self, address, data):
        now = time.monotonic()
        with self.lock:
            if self.closed or now >= self.expires:
                raise RemoteError("La invitación ha caducado. Vuelve a conectar los móviles desde el ordenador.", 410)
            while self.failures and now - self.failures[0][0] >= 60:
                self.failures.popleft()
            if len(self.failures) >= 100 or sum(ip == address for _, ip in self.failures) >= 6:
                raise RemoteError("Demasiados intentos. Espera un minuto.", 429)
            secret, code = data.get("secret"), data.get("code")
            valid = (isinstance(secret, str) and secret.isascii() and secrets.compare_digest(secret, self.secret))
            valid = valid or (isinstance(code, str) and code.isascii() and secrets.compare_digest(code, self.code))
            if not valid:
                self.failures.append((now, address))
                raise RemoteError("Revisa el código que aparece en Karaoke.", 403)
            name = data.get("name")
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40 or not name.strip().isprintable():
                raise RemoteError("Escribe un nombre de hasta 40 caracteres.")
            if len(self.sessions) >= 64:
                raise RemoteError("La sesión está llena.", 409)
            token = secrets.token_urlsafe(32)
            name = name.strip()
            self.sessions[token] = (secrets.token_hex(12), name, now)
            return name, token

    def identify(self, header):
        cookie = SimpleCookie()
        try:
            cookie.load(header)
        except CookieError:
            pass
        entry = cookie.get(self.cookie_name)
        with self.lock:
            guest = self.sessions.get(entry.value) if entry else None
            if self.closed or not guest:
                raise RemoteError("Entra con el QR o el código de Karaoke.", 401)
            client_id, name, _ = guest
            self.sessions[entry.value] = (client_id, name, time.monotonic())
            return client_id, name


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Guest input, cookies and invitation material never enter application logs.

    def reply(self, status, body, mime="application/json; charset=utf-8", headers=(), cache="no-store"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self, limit=MAX_BODY):
        if self.headers.get_content_type() != "application/json":
            raise RemoteError("Se esperaba una petición JSON.", 415)
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if self.headers.get("Transfer-Encoding") or not 0 <= length <= limit:
            raise RemoteError("Tamaño de petición no admitido.", 413)
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeError, ValueError, RecursionError):
            value = None
        if not isinstance(value, dict):
            raise RemoteError("Petición no válida.")
        return value

    def serve_request(self):
        server = self.server
        if self.headers.get_all("Host") != [server.authority]:
            raise RemoteError("Dirección de sesión incorrecta.", 403)
        origin = self.headers.get("Origin")
        if origin is not None and self.headers.get_all("Origin") != [server.url]:
            raise RemoteError("Origen no permitido.", 403)
        path = urlsplit(self.path).path
        if self.command == "GET" and path in ASSETS:
            file, mime = ASSETS[path]
            return self.reply(200, (WEB / file).read_bytes(), mime)
        if server.closed:
            return self.reply(410, {"error": "La sala se ha cerrado.", "room_closed": True})
        if self.command == "POST" and path == "/api/join":
            name, token = server.join(self.client_address[0], self.read_payload())
            cookie = f"{server.cookie_name}={token}; HttpOnly; SameSite=Strict; Path=/api"
            if server.url.startswith("https://"):
                cookie += "; Secure"
            return self.reply(200, {"name": name}, headers=(("Set-Cookie", cookie),))

        guest, name = server.identify(self.headers.get("Cookie", ""))
        if self.command == "POST" and path in ("/api/mic-offer", "/api/mic-stop"):
            return self.reply(200, server.dispatch(guest,name,path[5:],self.read_payload(40000)))
        if self.command == "GET" and path == "/api/me":
            return self.reply(200, {"name": name})
        if self.command == "GET" and path.startswith("/api/cover/"):
            identifier = unquote(path.removeprefix("/api/cover/"))
            if not re.fullmatch(r"[\w.:-]{1,192}", identifier):
                raise RemoteError("Portada desconocida.", 404)
            file = server.dispatch(guest, name, "cover", {"id": identifier})
            if not isinstance(file, Path) or not file.is_file():
                raise RemoteError("Portada no disponible.", 404)
            types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".bmp": "image/bmp", ".webp": "image/webp"}
            mime = types.get(file.suffix.lower())
            if not mime or file.stat().st_size > 16 * 1024**2:
                raise RemoteError("Portada no disponible.", 404)
            return self.reply(200, file.read_bytes(), mime, cache="private, max-age=300")
        if self.command == "POST" and path in ("/api/state", "/api/search", "/api/library", "/api/action"):
            return self.reply(200, server.dispatch(guest, name, path[5:], self.read_payload()))
        raise RemoteError("Esta opción no está disponible.", 404)

    def do_GET(self):
        try:
            self.serve_request()
        except RemoteError as error:
            # An in-flight operation can be revoked while dispatching to Deluxe.
            if self.server.closed:
                self.reply(410, {"error": "La sala se ha cerrado.", "room_closed": True})
            else:
                self.reply(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            self.reply(500, {"error": "No se pudo completar la petición. Vuelve a intentarlo."})

    do_POST = do_GET


class RemoteServer:
    def __init__(self, dispatch, directory):
        self.dispatch = dispatch
        self.directory = Path(directory)
        self.listener = None
        self.thread = None
        self.qr_path = None
        self.retired = None
        self.retire_lock = threading.Lock()

    @property
    def url(self):
        return self.listener.url if self.listener else ""

    @property
    def code(self):
        return self.listener.code if self.listener else ""

    @property
    def invite_url(self):
        return self.url + "/#join=" + self.listener.secret if self.listener else ""

    @property
    def connected_count(self):
        if not self.listener:
            return 0
        with self.listener.lock:
            return sum(time.monotonic() - seen <= 45 for _, _, seen in self.listener.sessions.values())

    def has_guest(self, client_id):
        listener = self.listener
        if listener is None:
            return False
        with listener.lock:
            return not listener.closed and any(guest == client_id for guest, _, _ in listener.sessions.values())

    def start(self, host=None):
        if self.listener:
            return self.url
        if not host:
            addresses = lan_addresses()
            if not addresses:
                raise RemoteError("Conecta el ordenador a la red wifi o Ethernet de tus amigos.")
            host = addresses[0]
        address = ipaddress.IPv4Address(host)
        if not address.is_loopback and not any(address in network for network in LAN_NETWORKS):
            raise RemoteError("Elige una dirección de tu red local.")
        listener = _Listener(str(address), self.dispatch)
        qr_path = self.directory / ("invite-" + secrets.token_hex(8) + ".png")
        try:
            cert = os.environ.get('KARAOKE_TLS_CERT')
            key = os.environ.get('KARAOKE_TLS_KEY')
            if cert or key:
                if not cert or not key:
                    raise RemoteError('Configura los dos archivos de certificado y clave TLS.')
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(cert, key)
                listener.socket = context.wrap_socket(listener.socket, server_side=True, do_handshake_on_connect=False)
                hostname = os.environ.get('KARAOKE_TLS_HOST', str(address))
                if not re.fullmatch(r'[a-zA-Z0-9.-]{1,253}',hostname):
                    raise RemoteError('El nombre del certificado TLS no es válido.')
                listener.authority = f'{hostname}:{listener.server_port}'
                listener.url = 'https://' + listener.authority
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            with qr_path.open("xb") as target:
                qrcode.make(listener.url + "/#join=" + listener.secret).save(target, format="PNG")
            self.thread = threading.Thread(target=listener.serve_forever, args=(0.05,), daemon=True)
            self.thread.start()
        except BaseException:
            listener.server_close()
            qr_path.unlink(missing_ok=True)
            raise
        self.qr_path = qr_path
        self.listener = listener
        return self.url

    def stop(self):
        listener = self.listener
        if not listener:
            return
        with listener.lock:
            listener.closed = True
            listener.sessions.clear()
        # Revoke immediately, then let polling guests receive a terminal HTTP
        # response. Keep at most one retired socket across rapid room changes.
        with self.retire_lock:
            if self.retired:
                old, timer = self.retired
                timer.cancel()
                old.shutdown()
                old.server_close()
            timer = threading.Timer(CLOSE_NOTICE_SECONDS, self._finish_notice, args=(listener,))
            timer.daemon = True
            self.retired = listener, timer
            timer.start()
        self.thread = None
        self.listener = None
        self.qr_path.unlink(missing_ok=True)
        self.qr_path = None

    def _finish_notice(self, listener):
        with self.retire_lock:
            if self.retired and self.retired[0] is listener:
                listener.shutdown()
                listener.server_close()
                self.retired = None
