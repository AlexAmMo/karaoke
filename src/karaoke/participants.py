"""Identity, reusable input preferences and exclusive live reservations."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path

from .songs import SongError

MAX_SINGERS = 10


def backup_legacy(db, path, original_version):
    if 0 < original_version < 3:
        backup = path.with_name(path.name + ".before-v3")
        if not backup.exists():
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
                stage = Path(temp.name)
            try:
                dest = sqlite3.connect(stage)
                try:
                    db.backup(dest)
                finally:
                    dest.close()
                os.replace(stage, backup)
            finally:
                stage.unlink(missing_ok=True)


def migrate(db, original_version):
    if original_version >= 3:
        return
    # Legacy names are kept as immutable snapshots. Do not infer identical people from text.
    db.executescript("""BEGIN IMMEDIATE;
        CREATE TABLE singers(id TEXT PRIMARY KEY, name TEXT NOT NULL, preferred TEXT,
          client TEXT UNIQUE, archived INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE turn_voices(turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
          slot INTEGER NOT NULL, singer TEXT REFERENCES singers(id), input TEXT,
          PRIMARY KEY(turn_id,slot), UNIQUE(turn_id,singer));
        CREATE TABLE reservations(input TEXT PRIMARY KEY, turn_id TEXT NOT NULL REFERENCES turns(id));
        CREATE TRIGGER release_inputs AFTER UPDATE OF state ON turns
          WHEN NEW.state NOT IN ('starting','singing') BEGIN
          DELETE FROM reservations WHERE turn_id=NEW.id; END;
        PRAGMA user_version=3;
        COMMIT;""")


def clean_name(name):
    if (
        not isinstance(name, str)
        or not 0 < len(name.strip()) <= 40
        or not name.strip().isprintable()
    ):
        raise SongError("Escribe un nombre de hasta 40 caracteres.")
    return name.strip()


def physical_inputs(engine):
    devices = engine.get("devices", [])
    result = {}
    for device in devices:
        name = device.get("name", "")
        ident = device.get("uid") or name
        if sum((d.get("uid") or d.get("name", "")) == ident for d in devices) != 1:
            continue  # A name shared by two physical devices cannot safely survive a rescan.
        prefix = "wire:" + hashlib.sha256(ident.encode()).hexdigest()[:20]
        for channel in range(min(32, max(0, device.get("channels", 0)))):
            players = device.get("players", [])
            result[f"{prefix}:{channel}"] = dict(
                name=name,
                label=f"{name} · canal {channel + 1}",
                device=device["index"],
                channel=channel,
                assigned=players[channel] if channel < len(players) else 0,
            )
    return result


class VoiceNames(list):
    """Names expected by legacy callers plus the explicit identities chosen for this turn."""

    def __init__(self, choices, people):
        super().__init__(
            [
                people[c["singer"]]["name"] if c.get("singer") else clean_name(c.get("name"))
                for c in choices
            ]
        )
        self.choices = choices


class Participants:
    def __init__(self, store):
        self.store = store

    def list(self):
        return self.store.rows(
            "SELECT id,name,preferred FROM singers WHERE archived=0 ORDER BY rowid"
        )

    def create(self, name, client=None):
        name = clean_name(name)
        db = self.store.db
        with self.store.lock, db:
            if client:
                row = db.execute(
                    "SELECT id FROM singers WHERE client=? AND archived=0", (client,)
                ).fetchone()
                if row:
                    return row[0]
            if (
                db.execute("SELECT count(*) FROM singers WHERE archived=0").fetchone()[0]
                >= MAX_SINGERS
            ):
                raise SongError("Ya hay diez cantantes. Retira uno desde Sesión para hacer sitio.")
            uid = uuid.uuid4().hex
            db.execute("INSERT INTO singers(id,name,client) VALUES(?,?,?)", (uid, name, client))
            return uid

    def configure(self, uid, *, input_key):
        with self.store.lock, self.store.db:
            if not self.store.db.execute(
                "UPDATE singers SET preferred=? WHERE id=? AND archived=0", (input_key, uid)
            ).rowcount:
                raise SongError("Ese cantante ya no está en la sesión.")

    def retire(self, uid):
        db = self.store.db
        with self.store.lock, db:
            if db.execute(
                "SELECT 1 FROM turn_voices JOIN turns ON turns.id=turn_id WHERE singer=? AND state IN ('queued','starting','singing')",
                (uid,),
            ).fetchone():
                raise SongError("Cambia primero el cantante de sus turnos pendientes.")
            db.execute("UPDATE singers SET archived=1,client=NULL WHERE id=?", (uid,))

    def voices(self, turn):
        names = json.loads(turn["names"])
        rows = self.store.rows(
            "SELECT slot,singer,input,preferred FROM turn_voices LEFT JOIN singers ON singers.id=singer WHERE turn_id=?",
            (turn["id"],),
        )
        by_slot = {r["slot"]: r for r in rows}
        return [
            dict(
                name=name,
                singer=by_slot.get(slot, {}).get("singer"),
                input=by_slot.get(slot, {}).get("input"),
                preferred=by_slot.get(slot, {}).get("preferred"),
            )
            for slot, name in enumerate(names)
        ]

    def set_voices(self, turn_id, choices):
        """Use snapshots for names even if the profile is subsequently archived."""
        with self.store.lock, self.store.db:
            self.set_in_transaction(self.store.db, turn_id, choices)

    @staticmethod
    def set_in_transaction(db, turn_id, choices):
        if not isinstance(choices, list) or not 1 <= len(choices) <= MAX_SINGERS:
            raise SongError("Elige de uno a diez cantantes.")
        row = db.execute("SELECT state FROM turns WHERE id=?", (turn_id,)).fetchone()
        if not row or row[0] != "queued":
            raise SongError("Este turno ya no se puede editar.")
        names, resolved, ids, used = [], [], set(), set()
        for slot, choice in enumerate(choices):
            if not isinstance(choice, dict):
                raise SongError("Participante no válido.")
            uid, override = choice.get("singer"), choice.get("input")
            preferred = None
            if uid is None:
                name = clean_name(choice.get("name"))
            else:
                if not isinstance(uid, str) or uid in ids:
                    raise SongError("Cada persona solo puede cantar una vez en este turno.")
                person = db.execute(
                    "SELECT name,preferred FROM singers WHERE id=? AND archived=0", (uid,)
                ).fetchone()
                if not person:
                    raise SongError("Elige un cantante actual.")
                name, preferred = person
                ids.add(uid)
            if override is not None and not isinstance(override, str):
                raise SongError("Entrada de audio no válida.")
            effective = override or preferred
            if effective and effective in used:
                raise SongError(
                    "Dos cantantes comparten el mismo micrófono en este turno. Elige otra entrada."
                )
            used.add(effective)
            resolved.append((turn_id, slot, uid, override))
            names.append(name)
        db.execute("DELETE FROM turn_voices WHERE turn_id=?", (turn_id,))
        db.executemany("INSERT INTO turn_voices VALUES(?,?,?,?)", resolved)
        db.execute("UPDATE turns SET names=? WHERE id=?", (json.dumps(names), turn_id))

    def reserve(self, turn, inputs, maximum, synthetic=False, profile_key=""):
        """Reserve all voices before publishing the start request, or roll back all of them."""
        voices = self.voices(turn)
        if len(voices) > maximum:
            raise SongError(f"El motor conectado admite {maximum} voces a la vez.")
        selected = [v["input"] or v["preferred"] for v in voices]
        explicit = [item for item in selected if item]
        if len(set(explicit)) != len(explicit):
            raise SongError(
                "Dos cantantes tienen el mismo micro. Cambia una entrada en este turno."
            )
        routes = []
        occupied = set(explicit)
        for slot, key in enumerate(selected):
            if key and key not in inputs:
                raise SongError(
                    f"La entrada de {voices[slot]['name']} se ha desconectado. Elige otra."
                )
            if not key:
                available = [k for k in inputs if k not in occupied and not inputs[k].get("mobile")]
                key = next((k for k in available if inputs[k].get("assigned") == slot + 1), None)
                if not key and not synthetic:
                    key = next(iter(available), None)
                if not key and not explicit and (synthetic or (not inputs and len(voices) <= 2)):
                    key = f"auto:{slot}"
                if not key:
                    raise SongError(
                        "Falta una entrada independiente. Asigna un micrófono por voz en este turno."
                    )
            selected[slot] = key
            occupied.add(key)
            route = inputs.get(key, {})
            calibration = self.store.setting("route:" + profile_key + ":" + key, {})
            routes.append({**route, **calibration})
        db = self.store.db
        with self.store.lock, db:
            if db.execute("SELECT 1 FROM turns WHERE state IN ('starting','singing')").fetchone():
                raise SongError("Hay una interpretación en curso.")
            if not db.execute(
                "UPDATE turns SET state='starting' WHERE id=? AND state='queued'", (turn["id"],)
            ).rowcount:
                raise SongError("Este turno ya no está pendiente.")
            db.executemany(
                "INSERT INTO reservations VALUES(?,?)", ((key, turn["id"]) for key in selected)
            )
        return [] if any(key.startswith("auto:") for key in selected) else routes
