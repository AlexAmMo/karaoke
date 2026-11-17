"""Local discovery, relevance and links to catalogues hosted by their operators."""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode

from .official_packs import (
    STARTERS as STARTERS,
    download_starter as download_starter,
    official_songs,
)
from .songs import SongError, normalize

# Pages on which these named entries were verified; the title fragment scrolls to
# the song in browsers that support text fragments. No credentials or media are fetched.
ASSISTED_ES = {
    "sigo-aqui": (
        "Álex Ubago",
        "Sigo Aquí",
        "https://ultrastar-es.org/es/canciones?artista=%C3%81lex+Ubago&cancion=Sigo+Aqu%C3%AD",
    ),
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
    return [song for song in official_songs() if matches(query, song)]


def assisted_url(provider, query):
    if provider == "eu":
        return "https://usdb.eu/search?" + urlencode({"keyword": query})
    artist, separator, title = query.partition(" - ")
    if provider == "es":
        return "https://ultrastar-es.org/es/canciones?" + urlencode(
            {"artista": artist, "cancion": title} if separator else {"busqueda": query}
        )
    raise SongError("Catálogo desconocido.")
