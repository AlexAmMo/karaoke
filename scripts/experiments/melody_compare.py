"""Project independent sung-note events onto existing predicted lyrics, then measure frozen charts.

The "generate" command has no gold chart input. The "measure" command runs separately,
on the exact private benchmark masters and includes baseline, acoustic-only diagnosis,
and both karaoke-chart variants. Only hashes, counts and metrics are exported publicly.
"""

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import Note, ROW, compare_notes, extract, passes, score  # noqa: E402
from karaoke.songs import read_chart  # noqa: E402


def publish_text(path, text):
    """Allow follow-up experiments to read only fully serialized candidates."""
    if path.is_file() and path.read_text() == text:
        return
    with tempfile.NamedTemporaryFile(
        dir=path.parent, mode="w", encoding="utf-8", delete=False
    ) as f:
        f.write(text)
        temporary = Path(f.name)
    temporary.replace(path)


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def transform(base, events, duration):
    from karaoke.generation_worker import chart_text, join_syllables_and_notes

    text, meta = read_chart(base)
    tick = 15 / float(meta["BPM"].replace(",", "."))
    gap = float(meta.get("GAP", "0").replace(",", ".")) / 1000
    starts, ends = [e[0] for e in events], [e[1] for e in events]
    syllables, vote_chart, line_index = [], [], 0
    for line in text.splitlines():
        match = ROW.match(line)
        if match:
            kind, beat, length, pitch, lyric = match.groups()
            a = gap + int(beat) * tick
            b = a + int(length) * tick
            # Every emitted melisma continuation belongs to the source syllable.
            if lyric.strip() == "~" and syllables and syllables[-1]["line_index"] == line_index:
                last = syllables[-1]
                last["end"] = b
                if lyric.endswith(" ") and not last["syllable"].endswith(" "):
                    last["syllable"] += " "
            else:
                syllables.append(dict(start=a, end=b, syllable=lyric, line_index=line_index))
            weights = Counter()
            for left, right, midi in events[bisect_right(ends, a) : bisect_left(starts, b)]:
                weights[int(midi)] += min(b, right) - max(a, left)
            # Preserve the release chart's rhythm and freestyle choices. Change
            # pitch only when one candidate covers at least half the note's time.
            if kind in ":*" and weights:
                midi, weight = weights.most_common(1)[0]
                if weight >= (b - a) / 2:
                    line = f"{kind} {beat} {length} {midi - 60} {lyric}"
        elif line.startswith("-"):
            line_index += 1
        vote_chart.append(line)
    new_notes = join_syllables_and_notes(
        syllables, events, {"times": [], "frequencies": []}, duration
    )
    rebuilt = chart_text(
        new_notes, meta["TITLE"], meta["ARTIST"], meta.get("LANGUAGE", ""), duration
    )
    return {"pitch": "\n".join(vote_chart) + "\n", "events": rebuilt}


def consensus(base, first, second):
    """Change only a pitch class independently supported by both alternative models."""
    original, _ = read_chart(base)
    output = []
    for line, a, b in zip(
        original.splitlines(), first.splitlines(), second.splitlines(), strict=True
    ):
        note = ROW.match(line)
        if note and note[1] in ":*":
            pitches = [int(ROW.match(v)[4]) for v in (a, b)]
            original_pitch = int(note[4])
            if pitches[0] % 12 == pitches[1] % 12 != original_pitch % 12:
                chosen = min(pitches, key=lambda p: abs(p - original_pitch))
                line = f"{note[1]} {note[2]} {note[3]} {chosen} {note[5]}"
        output.append(line)
    return "\n".join(output) + "\n"


def generate(args):
    source = json.loads(args.charts.read_text())
    for raw in sorted(args.events.glob("*.json")):
        if raw.stem not in source:
            continue
        payload = json.loads(raw.read_text())
        base = Path(source[raw.stem])
        provenance = payload.get("provenance", {})
        if "duration_s" in provenance:
            duration = float(provenance["duration_s"])
        else:
            import soundfile

            duration = soundfile.info(payload["settings"]["source"]).duration
        dest = args.output / raw.stem
        dest.mkdir(exist_ok=True, parents=True)
        frozen = {}
        candidates = transform(base, payload["events"], duration)
        secondary_sha = None
        if args.agree_with:
            secondary = args.agree_with / raw.name
            if not secondary.is_file():
                continue
            other = json.loads(secondary.read_text())
            if other["settings"]["source"] != payload["settings"]["source"]:
                raise ValueError(f"Different stem in ensemble: {raw.stem}")
            secondary_sha = digest(secondary)
            other_pitch = transform(base, other["events"], duration)["pitch"]
            candidates["consensus"] = consensus(base, candidates["pitch"], other_pitch)
        for method, txt in candidates.items():
            path = dest / f"{method}.txt"
            publish_text(path, txt)
            frozen[method] = digest(path)
        publish_text(
            dest / "frozen.json",
            json.dumps(
                {
                    "charts": frozen,
                    "events_sha256": digest(raw),
                    "baseline_sha256": digest(base),
                    "secondary_sha256": secondary_sha,
                }
            ),
        )


def onset_ceiling(gold, predicted):
    """Maximum one-to-one time matches in ±100 ms if pitch is entirely ignored."""
    a = sorted(n.start for n in gold if n.pitch is not None)
    b = sorted(n.start for n in predicted if n.pitch is not None)
    i = j = matched = 0
    while i < len(a) and j < len(b):
        if a[i] < b[j] - 0.1:
            i += 1
        elif b[j] < a[i] - 0.1:
            j += 1
        else:
            i += 1
            j += 1
            matched += 1
    return round(2 * matched / (len(a) + len(b)), 4) if a or b else None


def row_metrics(m):
    return dict(
        reference_notes=m["reference_notes"],
        scored_notes=m.get("generated_scored"),
        matched_attacks=m.get("matching_onsets"),
        coverage=m.get("covered_frames"),
        correct_class_all=m.get("correct_class_all"),
        correct_when_covered=m.get("correct_when_covered"),
        onset_f1_ignoring_pitch=m["onset_f1_ignoring_pitch"],
        within_one_semitone=m.get("within_one_semitone_all"),
        onset_pitch_f1_100ms=m.get("onset_pitch_f1_100ms"),
        wer=m.get("wer"),
        word_p90_s=m.get("word_mae_p50_p90_s", [None, None])[1],
        passes_all=passes(m) if "wer" in m else None,
    )


def measure(args):
    bases = json.loads(args.charts.read_text())
    cases = sum(json.loads(args.corpus.read_text()).values(), [])
    selected = {
        r["id"]: r
        for r in csv.DictReader(args.baseline_scores.open())
        if r["revision"] == "produccion" and r["muestra"] in ("completa-ES", "completa-EN")
    }
    if len(selected) != 40:
        raise ValueError("Expected the frozen 40-song benchmark.")
    valid = [r for r in cases if r["tag"] in selected]
    verified = json.loads(args.verified_stems.read_text()) if args.verified_stems else {}
    rows = []
    for r in sorted(valid, key=lambda r: r["tag"]):
        tag = r["tag"]
        raw = args.events / f"{tag}.json"
        frozen_file = args.variants / tag / "frozen.json"
        if not raw.is_file() or not frozen_file.is_file():
            if args.partial:
                continue
            raise ValueError(f"Missing frozen candidate for {tag}")
        base = Path(bases[tag])
        frozen = json.loads(frozen_file.read_text())
        if digest(raw) != frozen["events_sha256"] or digest(base) != frozen["baseline_sha256"]:
            raise ValueError(f"Frozen acoustic predictions or baseline changed for {tag}")
        if args.agree_with and digest(args.agree_with / raw.name) != frozen.get("secondary_sha256"):
            raise ValueError(f"Secondary model events changed for {tag}")
        if not args.agree_with and frozen.get("secondary_sha256"):
            raise ValueError("Supply the second model to validate consensus results")
        paths = {method: args.variants / tag / f"{method}.txt" for method in frozen["charts"]}
        if any(digest(path) != frozen["charts"][method] for method, path in paths.items()):
            raise ValueError(f"Frozen chart changed for {tag}")
        ref = Path(r["reference"])
        if digest(ref) != r["chart_sha"] or r["audio_sha"] != selected[tag]["audio_sha256"]:
            raise ValueError(f"Different reference or master for {tag}")
        payload = json.loads(raw.read_text())
        family = payload["settings"]["family"]
        cached = verified.get(tag, {})
        stem = Path(payload["settings"]["source"])
        stem_hash = payload.get("provenance", {}).get("stem_sha256")
        if not stem_hash and cached:
            stat = stem.stat()
            if (str(stem), stat.st_mtime_ns, stat.st_size) != (
                cached["path"],
                cached["mtime_ns"],
                cached["size"],
            ):
                raise ValueError(f"Previously verified WAV changed for {tag}")
            stem_hash = cached["sha256"]
        info = dict(
            id=tag,
            language=r["language"],
            duration_s=r["duration"],
            audio_sha256=r["audio_sha"],
            reference_sha256=r["chart_sha"],
            baseline_sha256=frozen["baseline_sha256"],
            acoustic_model=family,
            acoustic_model_sha256=payload["settings"]["model_sha256"],
            acoustic_host=payload.get("provenance", {}).get("host", "local"),
            stem_sha256=stem_hash or digest(stem),
            acoustic_seconds=payload["seconds"],
        )
        notes, _ = extract(ref)
        gold = [
            replace(n, end=min(n.end, r["duration"])) for n in notes if 0 <= n.start < r["duration"]
        ]
        for method, path in {"baseline": base, **paths}.items():
            m = score(ref, path, 0, r["duration"], False)
            predicted, _ = extract(path)
            bounded = [n for n in predicted if 0 <= n.start < r["duration"]]
            m["onset_f1_ignoring_pitch"] = onset_ceiling(gold, bounded)
            rows.append(dict(**info, variant=method, chart_sha256=digest(path), **row_metrics(m)))
        # This diagnostic isolates segmentation/pitch quality before lyrics are
        # added. It cannot pass the four-part karaoke acceptance test by itself.
        pred = [
            Note(a, min(b, r["duration"]), p - 60, "")
            for a, b, p in payload["events"]
            if 0 <= a < r["duration"]
        ]
        m = compare_notes(gold, pred)
        m["onset_f1_ignoring_pitch"] = onset_ceiling(gold, pred)
        rows.append(dict(**info, variant="acoustic_only", chart_sha256="", **row_metrics(m)))
    if not rows:
        raise ValueError("No frozen pairs available")
    args.output.parent.mkdir(exist_ok=True, parents=True)
    with args.output.open("w") as f:
        out = csv.DictWriter(f, fieldnames=rows[0])
        out.writeheader()
        out.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="command", required=True)
    gen = cmds.add_parser("generate")
    met = cmds.add_parser("measure")
    for sub in (gen, met):
        sub.add_argument("events", type=Path)
        sub.add_argument("charts", type=Path)
        sub.add_argument(
            "--agree-with",
            type=Path,
            help="Independent second event directory for the fixed consensus rule",
        )
    gen.add_argument("output", type=Path)
    met.add_argument("variants", type=Path)
    met.add_argument("corpus", type=Path)
    met.add_argument("baseline_scores", type=Path)
    met.add_argument("output", type=Path)
    met.add_argument("--partial", action="store_true")
    met.add_argument(
        "--verified-stems",
        type=Path,
        help="Reuse already measured digests bound to unchanged local WAV paths, mtimes and sizes",
    )
    args = parser.parse_args()
    (generate if args.command == "generate" else measure)(args)


if __name__ == "__main__":
    main()
