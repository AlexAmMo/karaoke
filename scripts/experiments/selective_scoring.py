"""Freeze blind abstention decisions before opening human references. No audio or lyrics are exported.

Use the checked-in corpus identity manifest and the private chart, event and master paths from
the other two experiments. Independent note events need no lyrics, quantised score or gold map.
"""

import argparse
from bisect import bisect_left
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import extract, compare_notes  # noqa: E402


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def supports(notes, events):
    """Require a same-class attack within 80ms and support over half the predicted bar.

    Match a single independently predicted event to at most one bar. The chronological
    traversal prevents a sustained vowel from endorsing a string of separate syllables.
    """
    by_pitch = [[e for e in events if int(e[2]) % 12 == pitch] for pitch in range(12)]
    starts = [[e[0] for e in pool] for pool in by_pitch]
    next_index = [0] * 12
    supported = set()
    for i, note in enumerate(notes):
        pitch = note.pitch % 12
        pool = by_pitch[pitch]
        left = bisect_left(starts[pitch], note.start - 0.08, lo=next_index[pitch])
        candidates = []
        for j in range(left, len(pool)):
            a, b, _ = pool[j]
            if a > note.start + 0.08:
                break
            overlap = min(b, note.end) - max(a, note.start)
            if overlap >= 0.5 * (note.end - note.start):
                candidates.append((abs(a - note.start), j))
        if candidates:
            supported.add(i)
            next_index[pitch] = min(candidates)[1] + 1
    return supported


def freeze(args):
    charts = json.loads(args.charts.read_text())
    ids = {r["tag"] for r in json.loads(args.manifest.read_text())}
    if not (set(charts) == ids and len(ids) == 40):
        raise ValueError("Both chart lists must contain the same 40 recording IDs.")
    decisions = {}
    for tag in sorted(ids):
        path = Path(charts[tag])
        notes = [n for n in extract(path)[0] if n.pitch is not None]
        masks = []
        for directory in (args.some, args.rosvot):
            data = json.loads((directory / f"{tag}.json").read_text())
            masks.append(supports(notes, data["events"]))
        keep = sorted(masks[0] & masks[1])
        # Even passing this necessary acoustic condition does not independently verify text.
        # Require broad temporal coverage in the beginning, middle and end of the performance.
        cut = [(n.start - notes[0].start) / (notes[-1].end - notes[0].start) for n in notes]
        spans = [set(i for i, x in enumerate(cut) if min(2, int(x * 3)) == t) for t in range(3)]
        candidate = all(span and len(span.intersection(keep)) >= 0.9 * len(span) for span in spans)
        decisions[tag] = dict(
            output_sha256=digest(path),
            both=keep,
            some=sorted(masks[0]),
            rosvot=sorted(masks[1]),
            song_candidate=candidate,
        )
    args.decisions.write_text(json.dumps(decisions))


def evaluate(args):
    corpus = sum(json.loads(args.corpus.read_text()).values(), [])
    manifest = {r["tag"]: r for r in json.loads(args.manifest.read_text())}
    corpus = [r for r in corpus if r["tag"] in manifest]
    decisions = json.loads(args.decisions.read_text())
    charts = json.loads(args.charts.read_text())
    if set(decisions) != set(manifest) or set(manifest) != {r["tag"] for r in corpus}:
        raise ValueError("Unpaired corpus/decision IDs.")
    rows = []
    for row in sorted(corpus, key=lambda r: r["tag"]):
        tag = row["tag"]
        path = Path(charts[tag])
        reference = Path(row["reference"])
        decision = decisions[tag]
        if (
            digest(reference) != manifest[tag]["chart_sha"]
            or digest(path) != decision["output_sha256"]
        ):
            raise ValueError(f"Reference or frozen candidate changed for {tag}")
        notes = [n for n in extract(path)[0] if n.pitch is not None]
        gold = extract(reference)[0]
        for mode in ("all", "some", "rosvot", "both"):
            kept = notes if mode == "all" else [notes[i] for i in decision[mode]]
            matched = compare_notes(gold, kept)["matching_onsets"] if kept else 0
            rows.append(
                dict(
                    id=tag,
                    language=row["language"],
                    mask=mode,
                    emitted=len(notes),
                    kept=len(kept),
                    matched=matched,
                    fraction_kept=round(len(kept) / len(notes), 4),
                    precision=round(matched / len(kept), 4) if kept else None,
                    acoustic_candidate=decision["song_candidate"],
                )
            )
    with args.output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["freeze", "evaluate"])
    p.add_argument("--manifest", type=Path, default=Path("docs/validation/generacion-muestra.json"))
    for flag in ("charts", "decisions", "some", "rosvot", "corpus", "output"):
        p.add_argument("--" + flag, type=Path)
    args = p.parse_args()
    (freeze if args.command == "freeze" else evaluate)(args)
