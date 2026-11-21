"""Compare note releases with frozen melodic attacks on the same 40-song corpus."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import compare_notes, extract  # noqa: E402
from karaoke.songs import read_chart  # noqa: E402
from chart_disagreements import releases  # noqa: E402

ROW = re.compile(r"^([:*FRG])\s+(-?\d+)\s+(\d+)(\s+-?\d+ .*)$")


def vocal_energy(stem):
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(stem),
            "-vn",
            "-ar",
            "8000",
            "-ac",
            "1",
            "-f",
            "f32le",
            "-",
        ]
    )
    x = np.frombuffer(raw, dtype="<f4")
    bins = x[: len(x) // 80 * 80].reshape(-1, 80)
    return 10 * np.log10(np.mean(bins * bins, axis=1) + 1e-11)


def acoustic_release(start, end, envelope):
    # Leave a sustain intact unless the final voiced energy falls at least 8 dB
    # below its own preceding vowel for at least 30 ms. Never trim an entire short syllable.
    center = int(round(100 * start))
    limit = min(len(envelope), int(round(end * 100)))
    window = min(12, (limit - center) // 3)
    if window < 3:
        return end
    preceding = envelope[max(center, limit - window - 15) : limit - window]
    tail = envelope[limit - window : limit]
    if not len(preceding):
        return end
    quiet = tail < max(-67.0, float(np.median(preceding) - 8))
    length = 0
    for bit in quiet[::-1]:
        if not bit:
            break
        length += 1
    return min(end, (limit - length) * 0.01) if length >= 3 else end


def variants(base, stem):
    chart, meta = read_chart(base)
    lines = chart.splitlines()
    rows = [(i, m) for i, line in enumerate(lines) if (m := ROW.match(line))]
    tick = 15 / float(meta["BPM"].replace(",", "."))
    gap = float(meta.get("GAP", "0").replace(",", ".")) / 1000
    outputs = {name: list(lines) for name in ("short_gate", "medium_gate", "vowel_release")}
    envelope = vocal_energy(stem)
    for (i, m), (_, nxt) in zip(rows, rows[1:]):
        kind, beat, length, remainder = m.groups()
        start, ticks = int(beat), int(length)
        if kind not in ":*" or ticks < 3:
            continue
        a, d = gap + start * tick, ticks * tick
        b = a + d
        # Gate trials separate two currently touching bars, preserving genuine rests.
        space = (int(nxt[2]) - start - ticks) * tick
        options = {"vowel_release": acoustic_release(a, b, envelope)}
        if -1e-7 <= space <= 0.025:
            for policy, fraction, cap in (("short_gate", 0.17, 0.075), ("medium_gate", 0.33, 0.12)):
                options[policy] = b - min(d * fraction, cap)
        for policy, stop in options.items():
            k = max(1, min(ticks, round((stop - a) / tick)))
            outputs[policy][i] = f"{kind} {start} {k}{remainder}"
    return {k: "\n".join(v) + "\n" for k, v in outputs.items()}


def predict(args):
    charts = json.loads(args.charts.read_text())
    stems = json.loads(args.stems.read_text())
    args.private.mkdir(exist_ok=True, parents=True)
    for tag in sorted(set(charts) & set(stems)):
        folder = args.private / tag
        folder.mkdir(exist_ok=True)
        if (folder / "frozen.json").is_file():
            continue
        base = Path(charts[tag])
        data = variants(base, Path(stems[tag]))
        body = {"base": hashlib.sha256(base.read_bytes()).hexdigest()}
        for name, text in data.items():
            path = folder / (name + ".txt")
            path.write_text(text, encoding="utf-8")
            body[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (folder / "frozen.json").write_text(json.dumps(body))


def evaluate(args):
    corpus = {r["tag"]: r for g in json.loads(args.corpus.read_text()).values() for r in g}
    wanted = {r["tag"]: r["chart_sha"] for r in json.loads(args.manifest.read_text())}
    bases = json.loads(args.charts.read_text())
    if set(bases) != set(wanted) or len(bases) != 40:
        raise ValueError("Expected the same 40 masters")
    data = []
    for tag in sorted(wanted):
        reference = Path(corpus[tag]["reference"])
        if hashlib.sha256(reference.read_bytes()).hexdigest() != wanted[tag]:
            raise ValueError(f"Changed reference for {tag}")
        gold, _ = extract(reference)
        folder = args.private / tag
        frozen = json.loads((folder / "frozen.json").read_text())
        for policy, sha in frozen.items():
            pred = Path(bases[tag]) if policy == "base" else folder / (policy + ".txt")
            if hashlib.sha256(pred.read_bytes()).hexdigest() != sha:
                raise ValueError(f"Changed prediction for {tag}")
            notes, _ = extract(pred)
            m = compare_notes(gold, notes)
            precision = compare_notes(notes, gold)["correct_class_all"]
            data.append(
                dict(
                    id=tag,
                    language=corpus[tag]["language"],
                    method=policy,
                    pitch_recall=m["correct_class_all"],
                    pitch_precision=precision,
                    onset_f1=m["onset_pitch_f1_100ms"],
                    **releases(gold, notes),
                )
            )
    with args.output.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["predict", "evaluate"])
    p.add_argument("--manifest", type=Path, default=Path("docs/validation/generacion-muestra.json"))
    for flag in ("charts", "stems", "private", "corpus", "output"):
        p.add_argument("--" + flag, type=Path)
    args = p.parse_args()
    (predict if args.command == "predict" else evaluate)(args)
