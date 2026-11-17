"""Durable library, preparation jobs and independent singing turns."""

from __future__ import annotations
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS songs(id TEXT PRIMARY KEY, source TEXT UNIQUE,
          title TEXT NOT NULL, artist TEXT NOT NULL, language TEXT DEFAULT '',
          chart TEXT NOT NULL, audio TEXT NOT NULL, duration REAL NOT NULL,
          variant TEXT NOT NULL DEFAULT 'original', parent TEXT, verified INTEGER DEFAULT 0,
          freestyle INTEGER DEFAULT 0, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, source TEXT NOT NULL UNIQUE,
          payload TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
          song_id TEXT REFERENCES songs(id) ON DELETE SET NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, source TEXT NOT NULL,
          song_id TEXT REFERENCES songs(id) ON DELETE SET NULL, names TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'queued', position INTEGER NOT NULL,
          scores TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS song_sources(source TEXT PRIMARY KEY,
          song_id TEXT NOT NULL REFERENCES songs(id) ON DELETE CASCADE);
        INSERT OR IGNORE INTO song_sources SELECT source,id FROM songs WHERE source IS NOT NULL;
        PRAGMA user_version=1;
        """)
        # A crash never starts playback on the next launch.
        with self.db:
            self.db.execute("UPDATE turns SET state='queued' WHERE state IN ('starting','singing')")
            self.db.execute(
                "UPDATE jobs SET state='waiting', message='Reanudando preparación' WHERE state IN ('working','waiting')"
            )

    def rows(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def execute(self, sql, args=()):
        with self.lock, self.db:
            return self.db.execute(sql, args)

    def setting(self, key, default=None):
        rows = self.rows("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def configure(self, key, value):
        self.execute(
            "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    def save_song(self, song, source=None, variant="original", parent=None, verified=False):
        with self.lock, self.db:
            if source:
                self.db.execute(
                    "UPDATE songs SET source=NULL WHERE source=? AND id!=?",
                    (source, song["id"]),
                )
            self.db.execute(
                """INSERT INTO songs(id,source,title,artist,language,chart,audio,duration,variant,parent,verified,freestyle,created)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                source=coalesce(songs.source,excluded.source)""",
                tuple(song.get(k, "") for k in ("id",))
                + (source,)
                + tuple(
                    song.get(k, "")
                    for k in ("title", "artist", "language", "chart", "audio", "duration")
                )
                + (variant, parent, int(verified), int(song.get("freestyle", False)), time.time()),
            )
            if source:
                self.db.execute(
                    "INSERT INTO song_sources VALUES (?,?) ON CONFLICT(source) DO UPDATE SET song_id=excluded.song_id",
                    (source, song["id"]),
                )
                self.db.execute(
                    "UPDATE turns SET song_id=? WHERE source=? AND state='queued'",
                    (song["id"], source),
                )

    def request(self, source: str, payload: dict, names: list[str] | None):
        with self.lock, self.db:
            found = self.db.execute(
                "SELECT id FROM songs WHERE id=? UNION SELECT song_id FROM song_sources WHERE source=?",
                (source, source),
            ).fetchone()
            song_id = found[0] if found else None
            if not song_id:
                self.db.execute(
                    "INSERT OR IGNORE INTO jobs(id,source,payload,state,created) VALUES (?,?,?,'waiting',?)",
                    (uuid.uuid4().hex, source, json.dumps(payload), time.time()),
                )
            if names is not None:
                if not 1 <= len(names) <= 2 or any(not n.strip() for n in names):
                    raise ValueError("Indica uno o dos cantantes.")
                position = self.db.execute(
                    "SELECT coalesce(max(position),0)+1 FROM turns"
                ).fetchone()[0]
                turn_id = uuid.uuid4().hex
                self.db.execute(
                    "INSERT INTO turns(id,source,song_id,names,position,created) VALUES (?,?,?,?,?,?)",
                    (turn_id, source, song_id, json.dumps(names), position, time.time()),
                )
                return turn_id

    def queue(self):
        return self.rows("""SELECT t.*,s.title,s.artist,s.variant,s.chart,j.state AS preparation,j.message,j.payload AS job_payload
          FROM turns t LEFT JOIN songs s ON t.song_id=s.id LEFT JOIN jobs j ON t.source=j.source
          WHERE t.state IN ('queued','starting','singing') ORDER BY t.position,t.created""")

    def reorder(self, turn_id, direction):
        with self.lock, self.db:
            rows = [r for r in self.queue() if r["state"] == "queued"]
            index = next(i for i, r in enumerate(rows) if r["id"] == turn_id)
            other = max(0, min(len(rows) - 1, index + direction))
            self.db.execute(
                "UPDATE turns SET position=? WHERE id=?",
                (rows[other]["position"], rows[index]["id"]),
            )
            self.db.execute(
                "UPDATE turns SET position=? WHERE id=?",
                (rows[index]["position"], rows[other]["id"]),
            )

    def close(self):
        self.db.close()
