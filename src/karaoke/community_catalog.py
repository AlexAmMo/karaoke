"""Discover community charts by publisher and title. Only the user opens the source site."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from xml.etree import ElementTree

import requests

from . import catalog
from .songs import SongError


_FEEDS = {
    "es": ("https://usdb.hehoe.de/", 16_000_000),
    "eu": ("https://usdb.eu/sitemap/songfile.php", 5_000_000),
}
_PUBLISHERS = {"es": "UltraStar España", "eu": "USDB.eu"}
_REFRESH = 7 * 24 * 3600
_RETRY = 10 * 60
_LOCKS = {provider: threading.Lock() for provider in _FEEDS}
_LOG = logging.getLogger(__name__)


def _names(label):
    artist, sep, title = label.partition(" - ")
    artist, title = artist.strip(), title.strip()
    if sep and artist and title and max(len(artist), len(title)) <= 300:
        return artist, title
    return None


class _SpanishCharts(HTMLParser):
    """Use the individual source attribution rather than the aggregate display label."""

    def __init__(self):
        super().__init__()
        self.entries = set()

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        link = dict(attrs)
        if not (link.get("href") or "").startswith(
            (
                "https://ultrastar-es.org/en/canciones/descargar/txt/",
                "https://www.ultrastar-es.org/en/canciones/descargar/txt/",
            )
        ):
            return
        pair = _names(link.get("title") or "")
        if pair:
            # Numeric IDs and encoded download links age poorly. Re-resolve by name.
            self.entries.add((*pair, ""))


def _parse(provider, body):
    if provider == "es":
        if b"</html>" not in body[-1024:].lower():
            raise ValueError("Descarga incompleta del índice de UltraStar España")
        parser = _SpanishCharts()
        parser.feed(body.decode("utf-8-sig"))
        parser.close()
        return parser.entries

    root = ElementTree.fromstring(body)
    entries = set()
    for item in root.findall("{*}url"):
        link = (item.findtext("{*}loc") or "").strip()
        target = urlsplit(link)
        # Current, human-readable artist/title index only, never a mutable numeric map ID.
        parts = target.path.strip("/").split("/")
        if not (
            target.scheme == "https"
            and target.netloc == "usdb.eu"
            and len(parts) == 2
            and all(parts)
            and not target.query
            and not target.fragment
        ):
            continue
        pair = _names(item.findtext("{*}image/{*}caption") or "")
        if pair:
            entries.add((*pair, link))
    return entries


def _fetch(provider):
    url, limit = _FEEDS[provider]
    body = bytearray()
    started = time.monotonic()
    with requests.get(url, stream=True, timeout=(4, 8), allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Respuesta inesperada para el índice")
        for chunk in response.iter_content(32_768):
            if len(body) + len(chunk) > limit or time.monotonic() - started > 25:
                raise ValueError("El índice comunitario supera los límites de descarga")
            body.extend(chunk)
    entries = _parse(provider, body)
    if not entries:
        raise ValueError("El índice comunitario no contiene fichas válidas")
    return entries


def _refresh(db, provider):
    with _LOCKS[provider]:
        now = int(time.time())
        state = db.execute(
            "SELECT refreshed,attempted FROM feeds WHERE provider=?", (provider,)
        ).fetchone()
        if state and (now - state[0] < _REFRESH or now - state[1] < _RETRY):
            return
        with db:
            db.execute(
                "INSERT INTO feeds VALUES (?,0,?) ON CONFLICT(provider) DO UPDATE SET "
                "attempted=excluded.attempted",
                (provider, now),
            )
        try:
            entries = _fetch(provider)
        except (OSError, ValueError, requests.RequestException, ElementTree.ParseError) as error:
            _LOG.info("No se pudo actualizar el índice %s: %s", _PUBLISHERS[provider], error)
            return
        with db:
            db.execute("DELETE FROM entries WHERE provider=?", (provider,))
            db.executemany(
                "INSERT INTO entries VALUES (?,?,?,?,?)",
                (
                    (provider, artist, title, url, " ".join(catalog.tokens(artist + " " + title)))
                    for artist, title, url in entries
                ),
            )
            db.execute("UPDATE feeds SET refreshed=? WHERE provider=?", (now, provider))


def search(query: str, cache_dir: Path) -> list[dict]:
    """Return discovery-only editions. Run on a worker, never the display/event thread."""
    words = catalog.tokens(query)
    if not words or len(words) > 30:
        return []
    cache_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(cache_dir / "community-v1.sqlite3", timeout=12)) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS feeds(
                provider TEXT PRIMARY KEY, refreshed INTEGER NOT NULL, attempted INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS entries(
                provider TEXT, artist TEXT, title TEXT, url TEXT, searchable TEXT,
                PRIMARY KEY(provider,artist,title,url));
        """)
        for provider in _FEEDS:
            _refresh(db, provider)
        if not db.execute("SELECT 1 FROM feeds WHERE refreshed>0 LIMIT 1").fetchone():
            raise SongError("Los índices comunitarios no están disponibles en este momento.")
        where = " AND ".join("searchable LIKE ?" for _ in words)
        rows = db.execute(
            "SELECT provider,artist,title,url FROM entries WHERE " + where,
            tuple(f"%{word}%" for word in words),
        ).fetchall()

    # Opening the search while offline may already have shown a curated entry.
    # Reuse that source identity when the very same publisher and names arrive.
    curated = {
        (tuple(catalog.tokens(artist)), tuple(catalog.tokens(title))): "espana:" + slug
        for slug, (artist, title, _) in catalog.ASSISTED_ES.items()
    }
    results = []
    for provider, artist, title, url in rows:
        key = hashlib.sha256("\0".join((artist, title, url)).encode()).hexdigest()[:24]
        source = f"community-{provider}:{key}"
        if provider == "es":
            source = curated.get(
                (tuple(catalog.tokens(artist)), tuple(catalog.tokens(title))), source
            )
            url = "https://ultrastar-es.org/es/canciones?" + urlencode(
                {"artista": artist, "cancion": title}
            )
        results.append(
            {
                "source": source,
                "artist": artist,
                "title": title,
                "publisher": _PUBLISHERS[provider],
                "catalogue_url": url,
                "match": "Ficha para importar",
                "language": "",
            }
        )
    return sorted(results, key=lambda row: catalog.rank(query, row))[:500]
