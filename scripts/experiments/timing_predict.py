"""Generate alternative timings on a fixed production chart. This program has no human chart input."""

import argparse
from collections import defaultdict
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import sys
import unicodedata

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import ROW, TOKEN
from karaoke.songs import read_chart

METHODS = ("pulso", "ataque", "doble", "palabra", "ornamentos")


@dataclass
class Row:
    start: int
    end: int
    kind: str
    pitch: int
    lyric: str
    line: int


def parse(path):
    headers, rows, line = [], [], 0
    chart_text, _ = read_chart(path)
    for text in chart_text.splitlines():
        if text.startswith("#"):
            headers.append(text)
        elif text.startswith("-"):
            line += 1
        elif match := ROW.fullmatch(text):
            kind, start, duration, pitch, lyric = match.groups()
            rows.append(Row(int(start), int(start) + int(duration), kind, int(pitch), lyric, line))
        elif text.strip() not in ("", "E"):
            raise ValueError("Expected a generated solo chart")
    if "#BPM:900" not in headers or "#GAP:0" not in headers or not rows:
        raise ValueError("The frozen generation benchmark uses a 1/60-second grid")
    return headers, rows


def serialize(headers, rows):
    output = headers.copy()
    for i, row in enumerate(rows):
        if i and row.line != rows[i - 1].line:
            output.append(f"- {rows[i - 1].end}")
        output.append(f"{row.kind} {row.start} {row.end - row.start} {row.pitch} {row.lyric}")
    return "\n".join([*output, "E", ""])


def lexical_anchors(rows, checkpoint):
    # Map matching words in order. A repeated chorus in another part of the song
    # cannot supply its timestamps because each pair must agree on the clock too.
    flat, owner = [], []
    for i, row in enumerate(rows):
        if i and row.line != rows[i - 1].line:
            flat.append(" ")
            owner.append(i)
        text = unicodedata.normalize("NFKC", row.lyric.casefold()).replace("~", "")
        flat.extend(text)
        owner.extend([i] * len(text))
    words = [(m.group(), owner[m.start()]) for m in TOKEN.finditer("".join(flat))]
    asr = []
    for segment in checkpoint["words"]:
        for word in segment:
            value = unicodedata.normalize("NFKC", word["word"].strip().casefold())
            parts = list(TOKEN.finditer(value))
            # Whisper provides one time for the entire item, including contractions.
            if len(parts) == 1:
                asr.append((parts[0].group(), word["start"]))
    corrections = defaultdict(list)
    matching = SequenceMatcher(None, [s for s, _ in words], [s for s, _ in asr], autojunk=False)
    for i, j, length in matching.get_matching_blocks():
        for k in range(length):
            idx = words[i + k][1]
            delta = asr[j + k][1] - rows[idx].start / 60
            if abs(delta) <= 0.14:
                corrections[idx].append(0.4 * delta)
    return {idx: float(np.median(values)) for idx, values in corrections.items()}


def grid(beats):
    points = np.asarray(beats, dtype=float)
    if points.size < 2:
        return np.empty(0)
    # Limit to intervals with musical support. Skipped beats and strange meters
    # in the detector must not establish subdivisions across long silent gaps.
    intervals = np.diff(points)
    valid = (intervals >= 0.22) & (intervals <= 1.25)
    return np.unique(
        np.r_[points, *(points[:-1][valid] + intervals[valid] * f for f in (0.25, 0.5, 0.75))]
    )


def nearest(values, point, radius, strength=None):
    a, b = np.searchsorted(values, [point - radius, point + radius], side="left")
    if b <= a:
        return None
    distance = np.abs(values[a:b] - point)
    if strength is not None:
        # A much louder consonant should only win within a narrow local window.
        distance = distance - 0.012 * strength[a:b]
    return float(values[a + np.argmin(distance)])


def apply_offsets(rows, offsets):
    starts = np.array([r.start for r in rows])
    requested = starts + np.rint(60 * np.asarray(offsets)).astype(int)
    # Fixed half-way separations preserve ordering even when adjacent events are
    # pulled in opposite directions by different pieces of evidence.
    seams = (starts[:-1] + starts[1:]) // 2
    proposed = np.maximum(requested, np.r_[0, seams + 1])
    proposed[:-1] = np.minimum(proposed[:-1], seams)
    result = []
    for i, row in enumerate(rows):
        end = row.end
        if i + 1 < len(rows):
            if starts[i + 1] == end:
                end = proposed[i + 1]
            else:
                end = min(end, proposed[i + 1])
        result.append(replace(row, start=int(proposed[i]), end=int(max(proposed[i] + 1, end))))
    return result


def remove_ornaments(rows):
    result = []
    for i, row in enumerate(rows):
        # Only a melisma can disappear. Preserve its word-end marker on the
        # preceding syllable and the end of the originally sung interval.
        previous = result[-1] if result else None
        if (
            row.kind == ":"
            and row.lyric.strip() == "~"
            and previous
            and previous.kind == ":"
            and row.line == previous.line
            and row.end - row.start <= 5
            and 0 <= row.start - previous.end <= 1
            and abs(previous.pitch - row.pitch) <= 2
        ):
            previous.end = row.end
            if row.lyric.endswith(" ") and not previous.lyric.endswith(" "):
                previous.lyric += " "
        else:
            result.append(replace(row))
    return result


def predictions(rows, beats, attack_times, strength, words):
    subdivisions = grid(beats)
    norm = (
        np.clip(strength / max(0.001, np.percentile(strength, 90)), 0, 1)
        if strength.size
        else strength
    )
    offsets = {method: [] for method in METHODS if method != "ornamentos"}
    for i, row in enumerate(rows):
        t = row.start / 60
        beat = nearest(subdivisions, t, 0.065)
        attack = nearest(attack_times, t, 0.065, norm)
        offsets["pulso"].append(beat - t if beat is not None else 0.0)
        offsets["ataque"].append(attack - t if attack is not None else 0.0)
        dual = (
            (beat + attack) * 0.5 - t
            if beat is not None and attack is not None and abs(beat - attack) <= 0.035
            else 0.0
        )
        offsets["doble"].append(dual)
        offsets["palabra"].append(words.get(i, 0.0))
    return {
        **{name: apply_offsets(rows, shifts) for name, shifts in offsets.items()},
        "ornamentos": remove_ornaments(rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("charts", type=Path, help="Private generated draft index")
    parser.add_argument("beats", type=Path)
    parser.add_argument("features", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for tag, filename in json.loads(args.charts.read_text()).items():
        chart = Path(filename)
        beat_file, fx = args.beats / (tag + ".json"), args.features / (tag + ".npz")
        if not beat_file.is_file() or not fx.is_file():
            continue
        results = args.output / tag
        results.mkdir(exist_ok=True)
        header, rows = parse(chart)
        words = json.loads((chart.parent / "acoustics.json").read_text())
        beats = json.loads(beat_file.read_text())
        if words["signature"][0] != beats["audio_sha256"]:
            raise ValueError(f"Beat and vocal clocks differ for {tag}")
        with np.load(fx) as data:
            alternatives = predictions(
                rows, beats["beats"], data["times"], data["strengths"], lexical_anchors(rows, words)
            )
        audit = {}
        for method, alternative in alternatives.items():
            private = results / f"{method}.txt"
            temporary = private.with_suffix(".tmp")
            temporary.write_text(serialize(header, alternative))
            temporary.replace(private)
            audit[method] = hashlib.sha256(private.read_bytes()).hexdigest()
        (results / "hashes.json").write_text(json.dumps(audit))
        print(tag, len(alternatives), flush=True)


if __name__ == "__main__":
    main()
