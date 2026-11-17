"""Local discovery, relevance and links to catalogues hosted by their operators."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

from .songs import SongError, normalize

REVISION = "c9246c799050acec96a03183df4b85493d283d51"
RAW_URL = f"https://raw.githubusercontent.com/UltraStar-Deluxe/songs/{REVISION}/Creative%20Commons/"
STARTERS = {
    "on-the-run": ("Joshua Morin", "On the run", "CC BY-SA 2.5"),
    "northern-star": ("Steven Dunston", "Northern Star", "CC BY-NC-SA 2.5"),
}


# Pages on which these named entries were verified; the title fragment scrolls to
# the song in browsers that support text fragments. No credentials or media are fetched.
ASSISTED_ES = {
    "caminando-por-la-vida": (
        "Melendi",
        "Caminando por la vida",
        "https://ultrastar-es.org/es/canciones?artista=Melendi",
    ),
    "soldadito-marinero": (
        "Fito y Fitipaldis",
        "Soldadito marinero",
        "https://ultrastar-es.org/es/canciones?artista=Fito+Y+Fitipaldis&orden=3",
    ),
    "devuelveme-a-mi-chica": (
        "Hombres G",
        "Devuélveme a mi chica",
        "https://ultrastar-es.org/es/canciones?idioma=es&orden=3&tipo=a",
    ),
    "libre": ("Nino Bravo", "Libre", "https://ultrastar-es.org/es/canciones?lista=10687&orden=13"),
    "mediterraneo": (
        "Joan Manuel Serrat",
        "Mediterráneo",
        "https://ultrastar-es.org/es/canciones?lista=11027&orden=2",
    ),
    "efectos-vocales": (
        "Nach",
        "Efectos vocales",
        "https://tr.ultrastar-es.org/es/canciones?artista=Nach",
    ),
}


def assisted_songs(query):
    if not tokens(query):
        return []
    return [
        {"source": "espana:" + slug, "artist": artist, "title": title, "language": "Español"}
        for slug, (artist, title, _) in ASSISTED_ES.items()
        if matches(query, {"artist": artist, "title": title})
    ]


def assisted_entry_url(key):
    _, title, url = ASSISTED_ES[key.removeprefix("espana:")]
    return url + "#:~:text=" + quote(title, safe="")


def tokens(value):
    return re.findall(r"[^\W_]+", normalize(value or ""))


def search_filters(query):
    artist, separator, title = query.partition(" - ")
    if separator and artist.strip() and title.strip():
        return [{"interpret": artist.strip(), "title": title.strip()}]
    filters = [{"interpret": query}, {"title": query}]
    # The common unseparated forms are Artist Title and Title Artist.
    # Anchor both ends in the remote filters and verify all terms locally.
    words = re.findall(r"[^\W_]+", query)
    if len(words) > 1:
        for left, right in [(words[0], words[-1]), (words[-1], words[0])]:
            pair = {"interpret": left, "title": right}
            if pair not in filters:
                filters.append(pair)
    return filters


def recovery_filters(query):
    """Additional source queries for accent-sensitive matches and full artist names."""
    artist, sep, title = query.partition(" - ")
    words = query.split()
    possibilities = []
    if sep:
        possibilities.extend(({"interpret": artist.strip()}, {"title": title.strip()}))
    else:
        # Try actual artist/title boundaries, including accented original spelling.
        for split in sorted(range(1, min(len(words), 9)), key=lambda n: abs(n - len(words) / 2)):
            possibilities.append(
                {"interpret": " ".join(words[:split]), "title": " ".join(words[split:])}
            )
        # If one side has a missing accent, the other side can still retrieve
        # candidates. Verification uses all normalized tokens locally.
        if words:
            possibilities.extend(({"interpret": words[0]}, {"title": words[-1]}))
        if len(words) == 1 and len(words[0]) >= 5:
            possibilities.extend(({"interpret": words[0][:4]}, {"title": words[0][:4]}))
    base = search_filters(query)
    unique = []
    for candidate in possibilities:
        if candidate not in base and candidate not in unique:
            unique.append(candidate)
    return unique


def matches(query, item):
    text = " ".join(tokens(item["artist"] + " " + item["title"]))
    return all(word in text for word in tokens(query))


def rank(query, item):
    artist, title = (" ".join(tokens(item[key])) for key in ("artist", "title"))
    words = " ".join(tokens(query))
    return (
        words not in (title, artist + " " + title, title + " " + artist),
        words != artist,
        words not in title,
        -float(item.get("rating") or 0),
        artist,
        title,
        str(item.get("song_id") or item.get("source")),
    )


def source_key(song):
    return song.get("source") or f"usdb:{int(song['song_id'])}"


def starter_songs(query=""):
    return [
        {
            "source": "deluxe:" + key,
            "title": title,
            "artist": artist,
            "language": "English",
            "license": license_name,
            "match": "Paquete con voz original",
        }
        for key, (artist, title, license_name) in STARTERS.items()
        if matches(query, {"title": title, "artist": artist})
    ]


def assisted_url(provider, query):
    if provider == "eu":
        return "https://usdb.eu/search?" + urlencode({"keyword": query})
    artist, separator, title = query.partition(" - ")
    if provider == "es":
        return "https://ultrastar-es.org/es/canciones?" + urlencode(
            {"artista": artist, "cancion": title} if separator else {"busqueda": query}
        )
    raise SongError("Catálogo desconocido.")


def download_starter(key: str, destination: Path, progress):
    if key not in STARTERS:
        raise SongError("Este paquete ya no está en el catálogo de inicio.")
    artist, title, _ = STARTERS[key]
    directory = f"{artist} - {title}"
    package = destination / key
    package.mkdir(parents=True, exist_ok=True)
    for filename, (size, expected) in PACKAGE_FILES[directory].items():
        progress.check_space()
        progress.write("downloading", f"Descargando {title} · {filename}")
        target = package / filename
        digest = hashlib.sha256()
        received = 0
        url = RAW_URL + quote(directory + "/" + filename)
        with requests.get(url, stream=True, timeout=(8, 20)) as response:
            response.raise_for_status()
            with target.open("wb") as out:
                for block in response.iter_content(128 * 1024):
                    received += len(block)
                    if received > size:
                        raise SongError("El tamaño del recurso difiere de la edición publicada.")
                    out.write(block)
                    digest.update(block)
        if received != size or digest.hexdigest() != expected:
            raise SongError("El paquete descargado está incompleto. Reintenta la preparación.")
    return package / "song.txt"


# Content and credits are downloaded together from the immutable upstream revision.
PACKAGE_FILES = {
    "Joshua Morin - On the run": {
        "audio.ogg": (3769247, "5ba89ddf982ee0144b6977c813b86e0f69d773e6593bf0e444ed2349f517a2a8"),
        "background.jpg": (
            144066,
            "9c52cb758d41b496655e14f6a2c65f379cac2e114f6c1f68a59839cebe8b1f7c",
        ),
        "cover.jpg": (42672, "8ab4efab3043df80acb6b64b9fe1832f16f1e4179f91bba2b683a322e17ad4c8"),
        "license.txt": (1794, "c46831d76c79fc917a40e940d5b20fb29f59d733a2fa74c94b051888dd376630"),
        "song.txt": (6068, "4d05f5070b8755e2bbae267db1eda9cc94bddc429f0a7ee4ab479e3d55a316fb"),
    },
    "Steven Dunston - Northern Star": {
        "audio.ogg": (2241910, "6b0556b54099ee33a7977aeef2b7a90cea116f1780668fedfab6bc78149a0afe"),
        "background.jpg": (
            155975,
            "609808a6f2a10b62c15d45f8d74ddfbd239ccdc1f613ef57df4d1cc420c1677f",
        ),
        "cover.jpg": (67234, "e00fffb87eb1d4a08a0b82958975a6e0cc251f3eb8445373c5045abe659ba88d"),
        "license.txt": (1159, "4c472b28ae06676b622ba6ae5e4278efdd32b202e6dc0ea9ca4806d535d0e2d1"),
        "song.txt": (4280, "a875a0e8d895f15201271c88e351a1eee6118907589d071362dd90dbb9588d4f"),
    },
}
