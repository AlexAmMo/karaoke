"""Host-side operations for the mobile remote. All domain operations run on Service.tick."""

from __future__ import annotations

from collections import Counter, OrderedDict
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import queue
import re
import time

from . import catalog
from .remote_server import RemoteError, RemoteServer, lan_addresses
from .service import CatalogueSearch, has_song_files, youtube_id, work_key, normalize, source_name, spanish_search_terms
from .songs import SongError


class PhoneSearch(CatalogueSearch):
    """One catalogue result set, shared only for identical queries and accounts."""

    def __init__(self, host, query):
        self.store = host.store
        self.root = host.root
        self.provider = host.provider
        self.catalogue_pool = host.catalogue_pool
        self.usdb_search_pool = host.usdb_search_pool
        self.futures = []
        self.init_search()
        self.search(query)
        self.created = time.monotonic()

    def collect(self):
        for task in list(self.futures):
            future, done = task
            if future.done():
                self.futures.remove(task)
                if not future.cancelled():
                    try:
                        done(future.result())
                    except Exception:
                        self.search_busy = False
                        self.catalogue_status["consulta"] = "No disponible"

    def cancel(self):
        for future, _ in self.futures:
            future.cancel()


@dataclass
class Guest:
    singer: str | None = None
    query: str | None = None
    account: int = -1
    selections: dict = field(default_factory=dict)
    replies: OrderedDict = field(default_factory=OrderedDict)
    instrumental_song: str = ""
    candidates: list = field(default_factory=list)
    task: Future | None = None
    candidate: dict | None = None
    message: str = ""
    prepared: str = ""


def names_for_turn(names, default):
    if names is None:
        names = [default]
    if (not isinstance(names, list) or not 1 <= len(names) <= 10 or
            any(not isinstance(n, str) or not n.strip() or len(n.strip()) > 40 or
                not n.strip().isprintable() for n in names)):
        raise RemoteError("Indica el nombre de uno a diez cantantes.")
    return [n.strip() for n in names]


class RemoteSession:
    def __init__(self, host):
        self.host = host
        self.server = RemoteServer(self.dispatch, host.root / "mobile-session")
        from .mobile_voice import MobileVoices
        self.mics = MobileVoices()
        self.inbox = queue.Queue(maxsize=96)
        self.guests = {}
        self.searches = OrderedDict()
        self.covers = OrderedDict()
        self.addresses = []
        self.epoch = 0

    def start(self, address=None):
        if not self.server.url:
            self.addresses = lan_addresses()
            self.server.start(address)
        return self.server.url

    def stop(self):
        self.epoch += 1
        self.server.stop()
        self.mics.stop()
        for lookup in self.searches.values():
            lookup.cancel()
        for guest in self.guests.values():
            if guest.task:
                guest.task.cancel()
        self.searches.clear()
        self.covers.clear()
        self.guests.clear()
        self._drain(closing=True)

    def desktop_action(self, action):
        if action == "remote:start":
            self.host.page = "Móviles"
            self.start()
        elif action == "remote:stop":
            self.stop()
            self.host.page = "Móviles"
        elif action.startswith("remote:bind:"):
            address = action.split(":", 2)[2]
            if address not in lan_addresses():
                raise SongError("La conexión de red ha cambiado.")
            self.stop()
            self.start(address)
        elif action.startswith("remote:assist:"):
            pending = next((t for t in self.host.store.queue()
                            if t["id"] == action.split(":", 2)[2] and t["preparation"] == "host"), None)
            if pending:
                payload = json.loads(pending["job_payload"])
                song = payload.get("host_song") or payload["song"]
                self.host.obtain_spanish(song, pending=pending["source"])
        else:
            raise SongError("Opción de mando desconocida.")

    def desktop_view(self, rows, text, button):
        if self.server.url:
            text("Escanea el QR con tu móvil", "Conecta el móvil a la misma red que el ordenador.")
            rows.append({"kind": "qr", "path": str(self.server.qr_path)})
            text(self.server.url, "Código de acceso: " + self.server.code)
            count = self.server.connected_count
            text(f"{count} " + ("móvil conectado" if count == 1 else "móviles conectados"))
            for address in self.addresses:
                if f"//{address}:" not in self.server.url:
                    button("Usar red " + address, "remote:bind:" + address,
                           "Cambia la invitación y desconecta los mandos actuales.", style="link")
            button("Desconectar móviles", "remote:stop")
        else:
            button("Conectar móviles", "remote:start", "Comparte la cola en tu red wifi.", style="primary")
        button("Volver a la cola", "page:Cola", style="back")

    def dispatch(self, client, name, operation, payload):
        if operation in ("mic-offer", "mic-stop"):
            epoch = self.mics.epoch
            if not self.server.has_guest(client):
                raise RemoteError("La sala se ha cerrado.", 410)
            return self.mics.submit(client, name, operation, payload, epoch=epoch)
        reply = Future()
        try:
            self.inbox.put_nowait((self.epoch, reply, client, name, operation, payload))
        except queue.Full:
            raise RemoteError("Karaoke está atendiendo otras peticiones. Reintenta.", 503) from None
        try:
            return reply.result(timeout=6)
        except TimeoutError:
            reply.cancel()
            raise RemoteError("El ordenador tarda en responder. Reintenta.", 503) from None

    def _drain(self, closing=False):
        for _ in range(96 if closing else 16):
            try:
                epoch, reply, client, name, operation, payload = self.inbox.get_nowait()
            except queue.Empty:
                break
            if not reply.set_running_or_notify_cancel():
                continue
            try:
                if closing or epoch != self.epoch or not self.server.has_guest(client):
                    raise RemoteError("El anfitrión ha cerrado la sesión.", 410)
                reply.set_result(self.operate(client, name, operation, payload))
            except RemoteError as exc:
                reply.set_exception(exc)
            except SongError as exc:
                # These domain errors can contain local paths or downloader diagnostics.
                public = str(exc)
                if any(x in public for x in ("/", "\\", "Traceback", "://")):
                    public = "Revisa esta operación en el ordenador."
                reply.set_exception(RemoteError(public, 409))
            except Exception:
                reply.set_exception(RemoteError("No se pudo completar la operación en Karaoke.", 500))

    def tick(self):
        if self.server.url:
            for search in self.searches.values():
                search.collect()
            for guest in self.guests.values():
                self.finish_instrumental(guest)
            self._drain()

    def cover(self, song, query=""):
        art = self.host.cover(song, search=query)
        if not art["path"]:
            return ""
        path = Path(art["path"])
        identifier = hashlib.sha256(str(path).encode()).hexdigest()[:32]
        self.covers[identifier] = path
        self.covers.move_to_end(identifier)
        if len(self.covers) > 1024:
            self.covers.popitem(last=False)
        return "/api/cover/" + identifier

    def turn_rows(self):
        return self.host.store.queue()

    @staticmethod
    def revision(rows):
        # Playback progress and cover downloads must not invalidate a reorder.
        relevant = [(t["id"], t["state"], t["song_id"], t["names"], t["preparation"], t.get("voices_revision")) for t in rows]
        return hashlib.sha256(json.dumps(relevant).encode()).hexdigest()[:16]

    def state(self, name):
        rows = self.turn_rows()
        turns = []
        for t in rows:
            song = ({"title": t["title"], "artist": t["artist"], "chart": t["chart"]} if t["song_id"]
                    else json.loads(t["job_payload"] or "{}").get("song", {}))
            status = t["state"] if t["state"] != "queued" else (
                "ready" if t["song_id"] else t["preparation"] or "waiting")
            if status == "ready" and not has_song_files(t):
                status = "missing"
            if status == "cancelled":
                status = "error"
            turns.append({"id": t["id"], "title": song.get("title") or "Preparando canción",
                          "artist": song.get("artist") or "", "names": json.loads(t["names"]),
                          "voices": self.host.people.voices(t), "status": status, "cover": self.cover(song),
                          "message": {"error": "Preparación fallida. Puedes reintentar.",
                                      "missing": "Vuelve a importar el mapa y el audio en el ordenador.",
                                      "host": "Elige la edición en el ordenador."}.get(status, "")})
        preparations = []
        for job in self.host.independent_preparations():
            song = json.loads(job['payload']).get('song') or {}
            preparations.append({'id': job['id'], 'title': song.get('title') or 'Paquete local', 'state': job['state']})
        library = self.host.store.rows('SELECT count(*) AS count,max(created) AS updated FROM songs')[0]
        return {"revision": self.revision(rows), "queue": turns, "preparations": preparations, "library_revision": library, "name": name, **self.host.party_state(),
                "active": self.host.active, "paused": bool(self.host.engine.get("paused")),
                "music": self.host.store.setting("music", 65),
                "pitch_precision": self.host.pitch_precision,
                "previewing": bool(self.host.preview and self.host.preview.poll() is None)}

    @staticmethod
    def page(payload):
        page = payload.get("page", 0)
        query = payload.get("q", "")
        if type(page) is not int or not 0 <= page <= 10000 or not isinstance(query, str) or len(query) > 240:
            raise RemoteError("Consulta no válida.")
        return page, query.strip()

    def library_row(self, song, family=False):
        result = {"id": "lib:" + song["id"], "title": song["title"], "artist": song["artist"],
                  "variant": song["variant"], "duration": song["duration"], "language": song["language"],
                  "cover": self.cover(song), "available": True, "assisted": False,
                  "saved": True, "availability": "saved", "status_label": "Descargada",
                  "library_id": "lib:" + song["id"], "source": "En este equipo", "editions": []}
        if family:
            root = song["parent"] or song["id"]
            variants = self.host.store.rows("SELECT * FROM songs WHERE (id=? OR parent=?) AND id!=?",
                                           (root, root, song["id"]))
            result["editions"] = [self.library_row(v) for v in variants if has_song_files(v)]
        return result

    def library(self, payload):
        page, query = self.page(payload)
        video = youtube_id(query)
        if video:
            rows = self.host.store.rows("""SELECT DISTINCT s.* FROM drafts d JOIN songs s ON s.id=d.song_id
                                          WHERE d.video=? AND d.state='approved' ORDER BY s.artist,s.title,s.id""", (video,))
        else:
            rows = self.host.store.rows("SELECT * FROM songs ORDER BY artist,title,variant,id")
        words = [] if video else catalog.tokens(query)
        songs = [s for s in rows if all(w in normalize(s["artist"] + " " + s["title"]) for w in words)
                 and has_song_files(s)]
        start = page * 12
        return {"items": [self.library_row(s, family=True) for s in songs[start:start+12]],
                "page": page, "more": len(songs) > start + 12, "busy": False}

    def search(self, guest, payload):
        if payload.get("saved_only") is True:
            return self.library(payload)
        page, query = self.page(payload)
        query = spanish_search_terms(query) or query
        account = self.host.account.generation
        key = (account, query)
        previous = (guest.account, guest.query)
        if previous != key:
            guest.query, guest.account = query, account
            guest.selections.clear()
            stale = self.searches.get(previous)
            if stale and stale.futures and not any(
                    (other.account, other.query) == previous for other in self.guests.values()):
                # Later keystrokes should not leave slow USDB requests queued ahead of a finished title.
                self.searches.pop(previous).cancel()
        lookup = self.searches.get(key)
        if lookup and time.monotonic() - lookup.created > 300 and not lookup.futures:
            self.searches.pop(key)
            lookup = None
        if not lookup:
            if len(self.searches) >= 32:
                _, old = self.searches.popitem(last=False)
                old.cancel()
            lookup = self.searches[key] = PhoneSearch(self.host, query)
        self.searches.move_to_end(key)
        lookup.collect()
        groups = lookup.grouped_results()
        start = page * 12
        if start >= len(groups) and lookup.search_cursor and not lookup.search_busy:
            lookup.search(query, more=True)
        items = []
        visible = groups[start:start+12]
        work_counts = Counter(work_key(group[0]) for group in groups)
        states = lookup.result_states(visible)
        for group in visible:
            def describe(editions, grouped=False):
                item, info = lookup.describe_result(editions, states)
                source = catalog.source_key(item)
                identity = json.dumps(work_key(item), ensure_ascii=False) if grouped else source
                if grouped and work_counts[work_key(item)] > 1:
                    identity += "/" + (item.get("language") or "")
                uid = ("group:" if grouped else "edition:") + hashlib.sha256(
                    (query + "\0" + identity).encode()).hexdigest()[:32]
                guest.selections[uid] = (lookup, source, grouped)
                return {**info, "id": uid, "title": item["title"], "artist": item["artist"],
                        "language": item.get("language", ""), "variant": item.get("variant", ""),
                        "cover": self.cover(item, query) if grouped else "", "source": source_name(source),
                        "edition": item.get("edition") or "",
                        "library_id": ("lib:" + info["library_id"]) if info["library_id"] else ""}
            row = describe(group, True)
            row["editions"] = [describe([item]) for item in group]
            items.append(row)
        return {"items": items, "page": page, "busy": lookup.search_busy or "Consultando" in lookup.catalogue_status.values(),
                "more": len(groups) > start + 12 or bool(lookup.search_cursor)}

    def add(self, guest, item_id, names, key, *, queue=True):
        previous = self.host.store.rows("SELECT turn_id FROM mobile_requests WHERE key=?", (key,))
        if previous:
            return previous[0]["turn_id"]
        if item_id.startswith("lib:"):
            return self.host.enqueue_song(item_id[4:], names=names, key=key) if queue else None
        selection = guest.selections.get(item_id)
        if not selection or guest.account != self.host.account.generation:
            raise RemoteError("Vuelve a buscar la edición que quieres cantar.", 409)
        lookup, source, grouped = selection
        group = lookup.editions_for(source)
        if not grouped:
            group = [s for s in group if catalog.source_key(s) == source]
        possible = lookup.auto_choices(group)
        if possible:
            return self.host.request_choices(possible, names=names, key=key, search=lookup, queue=queue,
                                             assisted=lookup.spanish_choice(group) if grouped else None)
        song = lookup.spanish_choice(group)
        if not song:
            raise RemoteError("Esta edición no ofrece una descarga integrada.", 409)
        source = "host:" + catalog.source_key(song)
        self.host.message = "Hay una edición pendiente en Cola para elegir en el ordenador."
        return self.host.store.request_host(source, song, names if queue else None, key)

    def finish_instrumental(self, guest):
        if not guest.task or not guest.task.done():
            return
        task, guest.task = guest.task, None
        try:
            value = task.result()
            if guest.candidate is None:
                guest.candidates = value
                guest.message = "" if value else "Sin instrumentales disponibles."
            else:
                self.host.song(guest.instrumental_song)
                if value["id"] == guest.instrumental_song:
                    raise SongError("La pista es la misma grabación.")
                self.host.store.save_song(value, guest.candidate["url"] + ":" + guest.instrumental_song,
                                          "instrumental", guest.instrumental_song, True)
                guest.prepared = "lib:" + value["id"]
                guest.message = "Instrumental descargada."
        except Exception:
            guest.message = "La instrumental no está disponible o no coincide con el mapa."
        finally:
            guest.candidate = None

    def instrumentals(self, guest, song, op, payload):
        if song["variant"] != "original":
            raise RemoteError("Selecciona la versión original.")
        if guest.instrumental_song != song["id"] or payload.get("refresh") is True:
            if guest.task:
                raise RemoteError("Espera a que termine la búsqueda actual.", 409)
            guest.instrumental_song = song["id"]
            guest.candidates = []
            guest.prepared = ""
            guest.message = ""
            guest.task = self.host.pool.submit(self.host.find_instrumentals, song)
        if op == "prepare-instrumental":
            i = payload.get("candidate")
            if guest.task or not isinstance(i, str) or not i.isdigit() or not 0 <= int(i) < len(guest.candidates):
                raise RemoteError("Elige de nuevo una instrumental.", 409)
            candidate = guest.candidate = guest.candidates[int(i)]
            epoch = self.epoch
            guest.task = self.host.pool.submit(self.host.prepare_instrumental, song, candidate, lambda: self.epoch != epoch)
            guest.message = "Comprobando grabación y sincronía…"
        return {"busy": guest.task is not None, "message": guest.message, "prepared": guest.prepared,
                "items": [{"id": str(i), "title": v["title"]} for i, v in enumerate(guest.candidates)]}

    def operate(self, client, name, operation, payload):
        if operation == "state":
            guest = self.guests.get(client)
            return {**self.state(name), "my_singer": guest.singer if guest else None}
        if operation == "cover":
            return self.covers.get(payload["id"])
        if operation == "library":
            return self.library(payload)
        guest = self.guests.setdefault(client, Guest())
        if operation == "search":
            return self.search(guest, payload)
        if operation != "action":
            raise RemoteError("Acción desconocida.")
        request = payload.get("request_id")
        if request is not None and (not isinstance(request, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", request)):
            raise RemoteError("Identificador de petición no válido.")
        if request and request in guest.replies:
            return guest.replies[request]
        result = self.action(client, guest, name, payload, request)
        if request and payload.get("op") != "instrumentals":
            guest.replies[request] = result
            if len(guest.replies) > 200:
                guest.replies.popitem(last=False)
        return result

    def action(self, client, guest, name, payload, request):
        op, item = payload.get("op"), payload.get("id", "")
        if not isinstance(item, str) or len(item) > 200:
            raise RemoteError("Selección no válida.")
        if op in ("cancel-preparation", "retry-preparation"):
            job = next((j for j in self.host.independent_preparations() if j['id'] == item), None)
            allowed = ('error', 'cancelled') if op == 'retry-preparation' else ('waiting', 'working', 'host')
            if not job or job['state'] not in allowed:
                raise RemoteError('La preparación ha cambiado. Revisa su estado.', 409)
            self.host.handle({'action': ('retry:' if op == 'retry-preparation' else 'cancel-job:') + item})
            return {'ok': True}
        if op == "save":
            self.add(guest, item, None, None, queue=False)
            return {"ok": True}
        if op == "singer-select":
            uid = payload.get("id") or None
            if uid is not None and not any(p["id"] == uid for p in self.host.people.list()):
                raise RemoteError("Actualiza la lista de cantantes.")
            guest.singer = uid
            return {"ok": True}
        if op in ("singer-create", "singer-input", "singer-me"):
            if op == "singer-create":
                self.host.people.create(payload.get("name"))
            elif op == "singer-me":
                key = "mobile:" + client
                if key not in self.mics.inputs():
                    raise RemoteError("Activa primero el micrófono de este móvil.", 409)
                uid = guest.singer or self.host.people.create(name, client)
                self.host.people.configure(uid, input_key=key)
                guest.singer = uid
            else:
                key = payload.get("input") or None
                if key is not None and (not isinstance(key, str) or key not in self.host.input_options()):
                    raise RemoteError("Elige una entrada conectada.")
                self.host.people.configure(item, input_key=key)
            return {"ok": True}
        if op == "add":
            if not request:
                raise RemoteError("Falta el identificador de petición.")
            names = names_for_turn(payload.get('names'),name)
            if 'voices' in payload:
                names = self.host.voice_names(payload['voices'])
            elif names == [name]:
                uid = guest.singer or self.host.people.create(name, client)
                names = self.host.voice_names([{"singer": uid}])
                guest.singer = uid
            turn = self.add(guest,item,names,client+':'+request)
            return {"ok": True, "id": turn}
        if op == "music":
            value = payload.get("value")
            if type(value) is not int or not 0 <= value <= 100:
                raise RemoteError("Volumen no válido.")
            self.host.handle({"action": "music", "value": value})
        elif op == "settings":
            # Send only controls edited on this phone: another guest may have
            # changed the remaining settings while this sheet was open.
            changes = payload.get("changes")
            if not isinstance(changes, dict) or not changes or changes.keys() - {"music", "pitch_precision"}:
                raise RemoteError("Ajustes no válidos.")
            for key, limit in (("pitch_precision", 2), ("music", 100)):
                if key in changes and (type(changes[key]) is not int or not 0 <= changes[key] <= limit):
                    raise RemoteError("Valor de ajuste no válido.")
            if "pitch_precision" in changes:
                self.host.handle({"action": f"pitch:{changes['pitch_precision']}"})
            if "music" in changes:
                self.host.handle({"action": "music", "value": changes["music"]})
        elif op == "stop-preview":
            self.host.stop_preview()
        elif op in ("preview", "delete", "instrumentals", "prepare-instrumental"):
            if not item.startswith("lib:"):
                raise RemoteError("Elige una canción de la biblioteca.")
            song = self.host.song(item[4:])
            if op == "preview":
                if self.host.active:
                    raise RemoteError("Espera a que termine el turno actual.", 409)
                self.host.listen(song["audio"])
            elif op == "delete":
                if payload.get("confirm") is not True:
                    raise RemoteError("Confirma que quieres borrar la copia de la biblioteca.")
                self.host.delete_song(song["id"])
            else:
                return self.instrumentals(guest, song, op, payload)
        elif op in ("pause", "resume", "end"):
            if (not item or item != self.host.active or self.host.engine.get("token") != item
                    or self.host.engine.get("state") != "singing"):
                raise RemoteError("La canción en curso ha cambiado.", 409)
            if op == "end":
                self.host.command("end", token=item)
            else:
                self.host.command("set-paused", token=item, paused=op == "pause")
        elif op in ("up", "down", "remove", "rename", "start", "retry"):
            rows = self.turn_rows()
            if payload.get("revision") != self.revision(rows):
                raise RemoteError("La cola ha cambiado. Revisa el orden actualizado.", 409)
            turn = next((t for t in rows if t["id"] == item and t["state"] == "queued"), None)
            if not turn:
                raise RemoteError("El turno ya no está pendiente.", 409)
            if op in ("up", "down"):
                self.host.store.reorder(item, -1 if op == "up" else 1)
            elif op == "remove":
                self.host.handle({"action": "cancel:" + item})
            elif op == "rename":
                names = names_for_turn(payload.get("names"), name)
                voices = payload.get('voices', [{'name':n} for n in names])
                self.host.voice_names(voices)
                self.host.people.set_voices(item,voices)
            elif op == "start":
                self.host.start(item)
            else:
                jobs = self.host.store.rows("SELECT id FROM jobs WHERE source=? AND state IN ('error','cancelled')",
                                           (turn["source"],))
                if not jobs:
                    raise RemoteError("Este turno no necesita reintento.", 409)
                self.host.handle({"action": "retry:" + jobs[0]["id"]})
        else:
            raise RemoteError("Acción desconocida.")
        return {"ok": True}
