"""Exercise candidate search and actual preparation on a fresh, anonymous temporary library."""

import argparse
import csv
import json
import re
import tempfile
import time
from pathlib import Path

from karaoke import catalog
from karaoke.remote_session import PhoneSearch
from karaoke.service import Service, work_key
from karaoke.songs import validate

ROOT = Path(__file__).resolve().parents[1]


def try_title(host, artist, title):
    search = PhoneSearch(host, artist + " " + title)
    started = time.monotonic()
    while search.futures and time.monotonic() - started < 75:
        search.collect()
        time.sleep(0.03)
    groups = [
        g
        for g in search.grouped_results()
        if work_key(g[0]) == work_key(dict(artist=artist, title=title))
    ]
    choices = next((direct for g in groups if (direct := search.auto_choices(g))), [])
    if not choices:
        return {
            "outcome": "assisted"
            if any(search.spanish_choice(g) for g in groups)
            else "reference"
            if groups
            else "absent"
        }
    group = next(g for g in groups if search.auto_choices(g))
    turn = host.request_choices(
        choices, names=["Prueba"], search=search, assisted=search.spanish_choice(group)
    )
    try:
        while time.monotonic() - started < 200:
            host.tick()
            item = next(t for t in host.store.queue() if t["id"] == turn)
            if item["song_id"]:
                info = validate(Path(item["chart"]))
                return {
                    "outcome": "ready",
                    "source": host.song(item["song_id"])["source"],
                    "seconds": round(info["duration"], 2),
                    "elapsed": round(time.monotonic() - started, 2),
                }
            if item["preparation"] == "host":
                return {
                    "outcome": "assisted-after-check",
                    "source": catalog.source_key(choices[0]),
                    "reason": item.get("message", ""),
                    "elapsed": round(time.monotonic() - started, 2),
                }
            if item["preparation"] in ("error", "cancelled"):
                break
            time.sleep(0.12)
        message = re.sub(
            r"https?://\S+",
            "[URL]",
            str(item.get("preparation_message", "") or item.get("message", "")),
        )
        return {
            "outcome": "unavailable",
            "source": catalog.source_key(choices[0]),
            "reason": message[:300],
            "elapsed": round(time.monotonic() - started, 2),
        }
    finally:
        host.store.cancel_turn(turn)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a new evidence path.")
    evidence = []
    with tempfile.TemporaryDirectory(prefix="karaoke-search-qa-") as work:
        host = Service(Path(work))
        try:
            with (ROOT / "docs/REPERTORIO-VALIDACION.csv").open(encoding="utf-8-sig") as source:
                sample = list(csv.DictReader(source))
            sample.append(dict(artista="Álex Ubago", titulo="Sigo Aquí", idioma="español"))
            for row in sample:
                record = {
                    "artist": row["artista"],
                    "title": row["titulo"],
                    "language": row["idioma"],
                }
                try:
                    record.update(try_title(host, record["artist"], record["title"]))
                except (ValueError, OSError) as exc:
                    record.update(outcome="error", reason=str(exc)[:200])
                print(json.dumps(record, ensure_ascii=False), flush=True)
                evidence.append(record)
                args.output.write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                for song in host.store.rows("SELECT id FROM songs"):
                    host.delete_song(song["id"])
        finally:
            host.close()


if __name__ == "__main__":
    main()
