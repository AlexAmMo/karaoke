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


def matching_lyrics(tracks, transcript, language):
    """Check ordered words and their absolute timing in all thirds of the sung passage."""
    recognized = [
        (word, row["start"]) for line in transcript for row in line for word in _words(row["word"])
    ]
    if not 12 <= len(recognized) <= 4000:
        return None
    for track in tracks:
        if track["language"] != language:
            continue
        signed = [(word, start, end) for start, end, text in track["cues"] for word in _words(text)]
        if not 0.78 <= len(signed) / len(recognized) <= 1.25:
            continue
        matcher = SequenceMatcher(
            None, [w[0] for w in recognized], [w[0] for w in signed], autojunk=False
        )
        agreement = matcher.ratio()
        if agreement < 0.79:
            continue
        matched = [0, 0, 0]
        totals = [0, 0, 0]
        for block in matcher.get_matching_blocks():
            for i in range(block.size):
                index = block.a + i
                when = recognized[index][1]
                _, start, end = signed[block.b + i]
                third = min(2, 3 * index // len(recognized))
                totals[third] += 1
                if math.isfinite(when) and start - 0.8 <= when <= end + 0.8:
                    matched[third] += 1
        if all(n >= 3 and m / n >= 0.75 for m, n in zip(matched, totals)):
            return "\n".join(c[2] for c in track["cues"]), {
                "kind": "youtube-manual-subtitles",
                "language": language,
                "video_id": track["video_id"],
                "agreement": round(agreement, 3),
                "time_coverage": round(sum(matched) / sum(totals), 3),
            }
    return None
