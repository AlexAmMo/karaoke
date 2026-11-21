"""Consider manual captions only when their words and timing match the recording."""

from difflib import SequenceMatcher
import html
import json
import math
import re
import unicodedata
from urllib.parse import urlsplit


def _words(text):
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+", text)


def _cues(payload, duration):
    events = payload.get("events", []) if isinstance(payload, dict) else []
    if not isinstance(events, list) or len(events) > 5000:
        return []
    cues = []
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            start = int(event["tStartMs"]) / 1000
            end = start + int(event["dDurationMs"]) / 1000
            text = html.unescape("".join(s["utf8"] for s in event["segs"]))
        except (TypeError, KeyError, ValueError, OverflowError):
            continue
        text = re.sub(r"\[[^\]]*\]|【[^】]*】|<[^>]*>|[♪♫]", " ", text)
        text = " ".join(text.split())
        if 0 <= start < end <= duration + 2 and end - start <= 15 and _words(text):
            cues.append([start, end, text])
    return sorted(cues)


def manual_tracks(info, language, fetch):
    """Fetch at most one JSON3 authored caption per EN/ES language from this video's metadata."""
    tracks = []
    subtitles = info.get("subtitles") or {}
    duration = info.get("duration") or 0
    if not isinstance(subtitles, dict) or not isinstance(duration, (int, float)):
        return tracks
    for wanted in ("es", "en") if language == "auto" else (language,):
        tags = sorted(k for k in subtitles if isinstance(k, str) and k.split("-")[0] == wanted)
        if wanted in tags:
            tags.remove(wanted)
            tags.insert(0, wanted)
        for tag in tags:
            options = [s for s in subtitles[tag] if isinstance(s, dict) and s.get("ext") == "json3"]
            if not options:
                continue
            url = options[0].get("url") or ""
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname not in {
                "www.youtube.com",
                "youtube.com",
            }:
                continue
            with fetch(url) as response:
                data = response.read(512001)
            if len(data) <= 512000:
                cues = _cues(json.loads(data), duration)
                if len(cues) >= 3:
                    tracks.append({"language": wanted, "video_id": info["id"], "cues": cues})
            break
    return tracks


def _span_agreement(matcher, recognized, signed, phonetic=False):
    counts = [0, 0, 0]
    on_time = [0, 0, 0]
    literal = [0, 0, 0]
    distinct = [set() for _ in counts]
    for i, j, size in matcher.get_matching_blocks():
        for k in range(size):
            word, when = recognized[i + k]
            target, start, end = signed[j + k]
            third = 3 * (i + k) // len(recognized)
            counts[third] += 1
            if word == target:
                literal[third] += 1
                distinct[third].add(word)
            if math.isfinite(when) and start - 0.8 <= when <= end + 0.8:
                on_time[third] += 1
    for t, count in enumerate(counts):
        if count < 3 or on_time[t] / count < (0.90 if phonetic else 0.75):
            return None
        if phonetic:
            # Demand literal, diverse anchors and good coverage throughout the song.
            size = ((t + 1) * len(recognized) + 2) // 3 - (t * len(recognized) + 2) // 3
            if count / size < 0.85 or literal[t] / size < 0.60 or len(distinct[t]) < 8:
                return None
    return sum(on_time) / sum(counts)


def _spanish_variant(word):
    # Used exclusively for matching. Preserve the author's spelling for forced alignment.
    if word in {"ye", "yea", "yeh", "yeah", "yeahh"}:
        return "yeah"
    return word[:-1] if len(word) > 1 and word.endswith("s") else word


def matching_lyrics(tracks, transcript, language):
    """Check ordered words and their absolute timing in all thirds of the sung passage."""
    recognized = [
        (word, row["start"]) for line in transcript for row in line for word in _words(row["word"])
    ]
    if not 12 <= len(recognized) <= 4000:
        return None
    heard = [w for w, _ in recognized]
    for track in tracks:
        if track["language"] != language:
            continue
        signed = [(word, start, end) for start, end, text in track["cues"] for word in _words(text)]
        ratio = len(signed) / len(recognized)
        if not 0.78 <= ratio <= 1.25:
            continue
        written = [w for w, _, _ in signed]
        matcher = SequenceMatcher(None, heard, written, autojunk=False)
        agreement = matcher.ratio()
        coverage = None
        details = {}
        if agreement >= 0.79:
            coverage = _span_agreement(matcher, recognized, signed)
        elif language == "es" and len(heard) >= 60 and 0.93 <= ratio <= 1.07 and agreement >= 0.68:
            folded = SequenceMatcher(
                None,
                list(map(_spanish_variant, heard)),
                list(map(_spanish_variant, written)),
                autojunk=False,
            )
            if folded.ratio() >= 0.90:
                coverage = _span_agreement(folded, recognized, signed, phonetic=True)
                details["variant_agreement"] = round(folded.ratio(), 3)
        if coverage is not None:
            return "\n".join(c[2] for c in track["cues"]), {
                "kind": "youtube-manual-subtitles",
                "language": language,
                "video_id": track["video_id"],
                "agreement": round(agreement, 3),
                "time_coverage": round(coverage, 3),
                **details,
            }
    return None
