"""Resolve visible song thumbnails off the session thread, outside the song packages."""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import io
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import mutagen
from mutagen.flac import Picture
import requests
from PIL import Image, ImageOps

from .songs import normalize

LOG = logging.getLogger(__name__)
MISSING = {"path": "", "kind": "Icono", "credit": "", "url": "", "license": ""}
MAX_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 1024
CACHE_LIMIT = 64 * 1024 * 1024
USER_AGENT = "Karaoke/0.1 (https://github.com/AlexAmMo/karaoke)"
MBID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")


def _same(text):
    return " ".join(re.findall(r"\w+", normalize(text)))


def _artist(credits):
    return "".join(
        (x.get("name") or x.get("artist", {}).get("name", "")) + x.get("joinphrase", "")
        for x in credits
    )


def _release_choices(result, song):
    """Use an unambiguous release group within each artwork tier, never a compilation."""
    artist, title = _same(song["artist"]), _same(song["title"])
    matches = [
        r
        for r in result.get("recordings", [])
        if _same(r.get("title", "")) == title
        and _same(_artist(r.get("artist-credit", []))) == artist
    ]
    artists = {
        r["artist-credit"][0]["artist"]["id"]
        for r in matches
        if len(r.get("artist-credit", [])) == 1
        and MBID.fullmatch(r["artist-credit"][0].get("artist", {}).get("id", ""))
    }
    artist_id = next(iter(artists)) if len(artists) == 1 else ""
    length = song.get("duration")
    if length:
        matches = [r for r in matches if r.get("length") and abs(r["length"] / 1000 - length) <= 5]
    groups = {"Single": set(), "Album": set()}
    for recording in matches:
        for release in recording.get("releases", []):
            group = release.get("release-group", {})
            tier = group.get("primary-type")
            if (
                tier not in groups
                or group.get("secondary-types")
                or release.get("status") != "Official"
                or not MBID.fullmatch(group.get("id", ""))
            ):
                continue
            credits = release.get("artist-credit", [])
            if credits and _same(_artist(credits)) != artist:
                continue
            if tier == "Single" and _same(group.get("title", "")) != title:
                continue
            groups[tier].add(group["id"])
    return [(tier, next(iter(ids))) for tier, ids in groups.items() if len(ids) == 1], artist_id


def _embedded(audio):
    if not audio:
        return None
    try:
        media = mutagen.File(audio)
        if media is None:
            return None
        frames = list(getattr(media, "pictures", []))
        tags = media.tags
        if tags is not None and hasattr(tags, "getall"):
            frames.extend(tags.getall("APIC"))
        for frame in sorted(frames, key=lambda frame: frame.type != 3):
            if frame.type in (0, 3) and 0 < len(frame.data) <= MAX_BYTES:
                return frame.data
        if tags is not None:
            for encoded in tags.get("metadata_block_picture", []):
                if isinstance(encoded, str) and len(encoded) <= MAX_BYTES * 4 // 3:
                    frame = Picture(base64.b64decode(encoded, validate=True))
                    if frame.type in (0, 3) and len(frame.data) <= MAX_BYTES:
                        return frame.data
            for frame in tags.get("covr", []):
                if isinstance(frame, bytes) and len(frame) <= MAX_BYTES:
                    return frame
    except (OSError, ValueError, binascii.Error, mutagen.MutagenError):
        pass
    return None


def _thumb(data):
    if not data or len(data) > MAX_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(data)) as pic:
            if pic.format not in {"PNG", "JPEG", "WEBP", "BMP"} or max(pic.size) > 4096:
                return None
            pic.thumbnail((600, 600), Image.Resampling.LANCZOS)
            pic = ImageOps.exif_transpose(pic)
            # Native renderer uses square frames. Letterbox rectangular artwork without cropping.
            square = Image.new("RGB", (max(pic.size),) * 2, "#202124")
            square.paste(
                pic.convert("RGB"),
                ((square.width - pic.width) // 2, (square.height - pic.height) // 2),
            )
            pic = square
            result = io.BytesIO()
            pic.save(result, "JPEG", quality=87)
            return result.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def _wanted_source(song):
    source = str(song.get("source") or "")
    if source:
        return source
    n = str(song.get("song_id") or "")
    return "usdb:" + n if n.isdecimal() else ""


def _clean_credit(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


class ArtworkResolver:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(exist_ok=True, parents=True)
        self.index = self.directory / "index.json"
        try:
            records = json.loads(self.index.read_text(encoding="utf-8"))
            self.records = OrderedDict(
                (key, value)
                for key, value in records.items()
                if isinstance(value, dict)
                and isinstance(value.get("until"), (int, float))
                and isinstance(value.get("art"), dict)
                and (
                    not value["art"].get("path")
                    or (
                        re.fullmatch(r"[0-9a-f]{64}\.jpg", Path(value["art"]["path"]).name)
                        and Path(value["art"]["path"]).parent == self.directory
                        and Path(value["art"]["path"]).is_file()
                    )
                )
            )
        except (OSError, ValueError, AttributeError, TypeError):
            self.records = OrderedDict()
        self.queue = OrderedDict()
        self.priority_keys = OrderedDict()
        self.priority_query = ""
        self.priority_streak = 0
        self.active = ""
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.worker = None
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": USER_AGENT})
        self.cooldown = {}
        self.throttled = False
        self.next_musicbrainz = 0

    def get(self, song, local_cover="", *, search=""):
        if local_cover:
            return {**MISSING, "kind": "Portada del paquete", "path": local_cover}
        if not song.get("artist") or not song.get("title") or self.stop.is_set():
            return MISSING.copy()
        source = _wanted_source(song)
        # A prepared song may supply embedded artwork absent on the earlier catalog entry.
        identity = [source, song.get("audio") or "", song["artist"], song["title"]]
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        with self.condition:
            record = self.records.get(key)
            if record and record["until"] > time.time():
                self.records.move_to_end(key)
                return record["art"].copy()
            if search and search != self.priority_query:
                self.priority_query = search
                self.priority_keys.clear()
            if self.active != key and search and key not in self.priority_keys:
                if key not in self.queue and len(self.queue) >= 32:
                    evict = next((k for k in reversed(self.queue) if k not in self.priority_keys), None)
                    if evict:
                        del self.queue[evict]
                if key in self.queue or len(self.queue) < 32:
                    self.priority_keys[key] = None
            if self.active != key and key not in self.queue and len(self.queue) < 32:
                self.queue[key] = dict(song)
                if self.worker is None:
                    self.worker = threading.Thread(
                        target=self._work, name="Karaoke artwork", daemon=True
                    )
                    self.worker.start()
                self.condition.notify()
            return record["art"].copy() if record else MISSING.copy()

    def close(self):
        with self.condition:
            self.stop.set()
            self.queue.clear()
            self.condition.notify()
        if self.worker:
            # Requests in progress time out independently. A slow image must not delay quitting.
            self.worker.join(timeout=0.25)
        else:
            self.http.close()

    def _work(self):
        try:
            while not self.stop.is_set():
                with self.condition:
                    self.condition.wait_for(lambda: self.queue or self.stop.is_set())
                    if self.stop.is_set():
                        break
                    # Give the current search first choice while admitting a waiting
                    # carousel or library thumbnail after each three search images.
                    if self.priority_keys and (self.priority_streak < 3 or len(self.priority_keys) == len(self.queue)):
                        key, _ = self.priority_keys.popitem(last=False)
                        self.priority_streak += 1
                    else:
                        key = next(k for k in self.queue if k not in self.priority_keys)
                        self.priority_streak = 0
                    song = self.queue.pop(key)
                    self.active = key
                try:
                    self.throttled = False
                    art = self._resolve(song)
                    if not self.stop.is_set():
                        self._save(key, art)
                except Exception:
                    LOG.debug("Thumbnail unavailable", exc_info=True)
                    with self.condition:
                        self.records[key] = {"art": MISSING.copy(), "until": time.time() + 300}
                        while len(self.records) > MAX_ENTRIES:
                            self.records.popitem(last=False)
                finally:
                    with self.condition:
                        self.active = ""
                        self.condition.notify_all()
        finally:
            self.http.close()

    def _save(self, key, art):
        now = time.time()
        with self.condition:
            old = self.records.get(key, {}).get("art")
            if not art and old and old.get("path"):
                art = old
            ttl = 30 * 86400 if art else (600 if self.throttled else 7 * 86400)
            self.records[key] = {"art": art or MISSING.copy(), "until": now + ttl}
            self.records.move_to_end(key)
            while len(self.records) > MAX_ENTRIES:
                self.records.popitem(last=False)
            snapshot = dict(self.records)
        # Deduplicate pictures shared by several songs. Evict oldest entries before unlinking
        # images; the renderer loads only content-addressed paths and never partially written files.
        live = {row["art"]["path"] for row in snapshot.values() if row["art"].get("path")}
        files = sorted(self.directory.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        used = sum(p.stat().st_size for p in files)
        removed = set()
        for path in files:
            if str(path) not in live or used > CACHE_LIMIT:
                used -= path.stat().st_size
                path.unlink(missing_ok=True)
                removed.add(str(path))
        if removed:
            with self.condition:
                for k, value in snapshot.items():
                    if value["art"]["path"] in removed:
                        self.records.pop(k, None)
                snapshot = dict(self.records)
        temp = self.index.with_suffix(".tmp")
        temp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.index)

    def _fetch(self, url, limit=MAX_BYTES):
        if self.stop.is_set():
            return None
        host = urlsplit(url).hostname
        now = time.monotonic()
        if self.cooldown.get(host, 0) > now:
            self.throttled = True
            return None
        if host == "musicbrainz.org":
            if self.stop.wait(max(0, self.next_musicbrainz - now)):
                return None
            self.next_musicbrainz = time.monotonic() + 1.05
        try:
            with self.http.get(url, stream=True, timeout=(2.5, 4)) as response:
                if response.status_code in (403, 429, 503) or response.status_code >= 500:
                    retry = response.headers.get("Retry-After", "")
                    self.cooldown[host] = time.monotonic() + (
                        min(int(retry), 86400) if retry.isdecimal() else 60
                    )
                    self.throttled = True
                    return None
                if (
                    response.status_code != 200
                    or int(response.headers.get("Content-Length", 0)) > limit
                ):
                    return None
                data = bytearray()
                for chunk in response.iter_content(32768):
                    data.extend(chunk)
                    if len(data) > limit or self.stop.is_set() or time.monotonic() - now > 12:
                        return None
                return data
        except (requests.RequestException, ValueError, OSError):
            self.throttled = True
            self.cooldown[host] = time.monotonic() + 30
            return None

    def _json(self, url, **params):
        data = self._fetch(url + ("?" + urlencode(params) if params else ""), 1024 * 1024)
        try:
            value = json.loads(data or b"{}")
            return value if isinstance(value, dict) else {}
        except (ValueError, UnicodeError):
            return {}

    def _store_image(self, image, kind, credit="", url="", license=""):
        data = _thumb(image)
        if not data or self.stop.is_set():
            return None
        file = self.directory / (hashlib.sha256(data).hexdigest() + ".jpg")
        if not file.is_file():
            temp = file.with_suffix(".part")
            temp.write_bytes(data)
            temp.replace(file)
        return dict(path=str(file), kind=kind, credit=credit, url=url, license=license)

    def _reuse(self, field, identifier):
        with self.condition:
            for record in reversed(self.records.values()):
                art = record["art"]
                if record["until"] > time.time() and art.get(field) == identifier and art["path"]:
                    return art.copy()
        return None

    def _portrait(self, mbid):
        cached = self._reuse("artist_id", mbid)
        if cached:
            return cached
        relations = self._json(
            f"https://musicbrainz.org/ws/2/artist/{mbid}", inc="url-rels", fmt="json"
        )
        for relation in relations.get("relations", []):
            if relation.get("type") != "wikidata":
                continue
            link = relation.get("url", {}).get("resource", "")
            match = re.fullmatch(r"https?://(?:www\.)?wikidata\.org/(?:wiki|entity)/(Q\d+)", link)
            if match:
                entity = match[1]
                break
        else:
            return None
        data = self._json(
            "https://www.wikidata.org/w/api.php",
            action="wbgetclaims",
            entity=entity,
            property="P18",
            format="json",
        )
        for claim in data.get("claims", {}).get("P18", []):
            name = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if not isinstance(name, str) or claim.get("rank") == "deprecated":
                continue
            info = self._json(
                "https://commons.wikimedia.org/w/api.php",
                action="query",
                titles="File:" + name,
                prop="imageinfo",
                iiprop="url|extmetadata",
                iiurlwidth=500,
                format="json",
            )
            for page in info.get("query", {}).get("pages", {}).values():
                for image in page.get("imageinfo", []):
                    meta = image.get("extmetadata", {})

                    def value(k):
                        return _clean_credit(meta.get(k, {}).get("value", ""))

                    url = image.get("thumburl", "")
                    credit = value("Attribution") or value("Artist") or value("Credit")
                    licence = value("LicenseShortName")
                    if (
                        urlsplit(url).scheme == "https"
                        and urlsplit(url).hostname == "upload.wikimedia.org"
                        and credit
                        and licence
                    ):
                        art = self._store_image(
                            self._fetch(url),
                            "Foto del artista",
                            credit,
                            image.get("descriptionurl", ""),
                            licence,
                        )
                        if art:
                            art["artist_id"] = mbid
                            return art
        return None

    def _resolve(self, song):
        art = self._store_image(_embedded(song.get("audio")), "Portada del audio")
        if art:
            return art
        source = _wanted_source(song)
        usdb = re.fullmatch(r"usdb:(\d+)", source)
        if usdb:
            url = f"https://usdb.animux.de/data/cover/{usdb[1]}.jpg"
            art = self._reuse("url", url) or self._store_image(
                self._fetch(url), "Portada de USDB", "USDB", url
            )
            if art:
                return art

        def quoted(text):
            return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

        artist = quoted(song["artist"])
        result = self._json(
            "https://musicbrainz.org/ws/2/recording/",
            query="recording:" + quoted(song["title"]) + " AND artist:" + artist,
            limit=20,
            fmt="json",
        )
        choices, artist_id = _release_choices(result, song)
        for tier, group_id in choices:
            front = f"https://coverartarchive.org/release-group/{group_id}/front-500"
            work = f"https://musicbrainz.org/release-group/{group_id}"
            art = self._reuse("url", work) or self._store_image(
                self._fetch(front),
                "Portada del sencillo" if tier == "Single" else "Portada del álbum",
                "Cover Art Archive",
                work,
            )
            if art:
                return art
        if not artist_id:
            found = self._json(
                "https://musicbrainz.org/ws/2/artist/",
                query="artist:" + artist,
                limit=10,
                fmt="json",
            )
            exact = {
                x["id"]
                for x in found.get("artists", [])
                if _same(x.get("name", "")) == _same(song["artist"])
                and MBID.fullmatch(x.get("id", ""))
            }
            if len(exact) == 1:
                artist_id = next(iter(exact))
        return self._portrait(artist_id) if artist_id else None
