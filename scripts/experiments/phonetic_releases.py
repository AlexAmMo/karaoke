"""Freeze release candidates from two sung grapheme alignments before comparing with human notes."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from timing_predict import parse, serialize


def endings(spans):
    owners = defaultdict(list)
    for owner, first, end, vowel, peak in spans:
        owners[owner].append((end, peak))
    return {owner: max(chars)[0] * 0.02 for owner, chars in owners.items() if max(chars)[1] >= -4.6}


def predict(charts, observations, private):
    for tag, filename in sorted(charts.items()):
        base = Path(filename)
        signed = json.loads((observations / tag / "grapheme-bounds.json").read_text())
        if signed["hop_ms"] != 20:
            raise ValueError(f"Unexpected emission clock for {tag}")
        lead = endings(signed["lead"])
        pooled = endings(signed["pooled"])
        headers, rows = parse(base)
        for i, row in enumerate(rows):
            # A grapheme cannot establish the end of a following wordless melisma.
            if row.kind not in ":*" or i not in lead or i not in pooled:
                continue
            if i + 1 < len(rows) and rows[i + 1].lyric.strip() == "~":
                continue
            if abs(lead[i] - pooled[i]) > 0.06:
                continue
            # Leave at least half of the original sustain and permit at most 120ms of trim.
            end = round(60 * max(lead[i], pooled[i]))
            if row.start < end < row.end and row.end - end <= min(7, (row.end - row.start) / 2):
                row.end = end
        folder = private / tag
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "two_grapheme_ends.txt"
        path.write_text(serialize(headers, rows), encoding="utf-8")
        frozen = {
            k: hashlib.sha256(v.read_bytes()).hexdigest()
            for k, v in (("base", base), ("two_grapheme_ends", path))
        }
        (folder / "frozen.json").write_text(json.dumps(frozen), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("charts", "observations", "private"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    predict(json.loads(args.charts.read_text()), args.observations, args.private)
