"""Check a bar's harmonic spectrum at three instants, with and without stereo side energy.

The cheap acoustic hypothesis is frozen without seeing a reference. It does not load neural
networks. Input is streamed per bar so resource use is independent of recording duration.
"""

import argparse
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import compare_notes, extract, passes  # noqa: E402

SIZE = 4096
FFT = 8192
RATE = 44100
CANDIDATES = np.arange(39, 86)
HARMONICS = np.arange(1, 9)
WEIGHT = 1 / np.sqrt(HARMONICS)
WINDOW = np.hanning(SIZE + 1)[:-1].astype(np.float32)


def positions(rate):
    f = 440 * 2 ** ((CANDIDATES - 69) / 12)
    # A fixed natural-tuning range covers small deviations from equal temperament.
    centers = (
        f[:, None, None]
        * 2 ** (np.array([-0.22, 0, 0.22])[None, :, None] / 12)
        * HARMONICS[None, None, :]
    )

    def bins(hz):
        return np.clip(hz * FFT / rate, 0, FFT // 2 - 0.001)

    # Contrast harmonic peaks with the energy on either side of their expected locations.
    spacing = f[:, None, None] * 0.32
    return [
        (np.floor(x).astype(int), x % 1)
        for x in (bins(centers), bins(centers - spacing), bins(centers + spacing))
    ]


def vote(power, lookup):
    def at(pair):
        i, frac = pair
        return power[i] * (1 - frac) + power[i + 1] * frac

    peak, lo, hi = [at(pair) for pair in lookup]
    floor = max(float(np.max(power)) * 0.0001, 1e-12)
    contrast = np.log1p(np.maximum(0, peak - 0.5 * (lo + hi)) / floor)
    salience = (contrast * WEIGHT).sum(axis=2).max(axis=1)
    scores = np.array([np.max(salience[CANDIDATES % 12 == c]) for c in range(12)])
    best, second = np.argsort(scores)[-2:][::-1]
    if scores[best] < 4 or scores[best] < 1.22 * max(1, scores[second]):
        return None
    return int(best)


def estimate(f, note, lookup):
    duration = note.end - note.start
    if note.pitch is None or duration < 0.12:
        return None, None
    raw, center = [], []
    for fraction in (0.27, 0.50, 0.73):
        pos = round((note.start + fraction * duration) * f.samplerate) - SIZE // 2
        if pos < 0 or pos + SIZE > len(f):
            return None, None
        f.seek(pos)
        stereo = f.read(SIZE, dtype="float32", always_2d=True)
        spectra = np.fft.rfft(stereo * WINDOW[:, None], n=FFT, axis=0)
        mid = abs((spectra[:, 0] + spectra[:, -1]) * 0.5) ** 2
        side = abs((spectra[:, 0] - spectra[:, -1]) * 0.5) ** 2
        mask = mid / np.maximum(mid + 8 * side, 1e-18)
        raw.append(vote(mid, lookup))
        center.append(vote(mid * np.maximum(0.2, mask) ** 2, lookup))

    def consensus(frame_votes):
        return frame_votes[0] if all(v == frame_votes[0] for v in frame_votes) else None

    return consensus(raw), consensus(center)


def predict(args):
    charts = json.loads(args.charts.read_text())
    sources = json.loads(args.stems.read_text())
    if len(charts) != 40 or set(charts) != set(sources):
        raise ValueError("Need the frozen 40 master pairs")
    args.predictions.mkdir(exist_ok=True, parents=True)
    lookup = positions(RATE)
    for tag in sorted(charts):
        base = Path(charts[tag])
        wav = Path(sources[tag])
        dest = args.predictions / (tag + ".json")
        with wav.open("rb") as stream:
            stem_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        chart_sha = hashlib.sha256(base.read_bytes()).hexdigest()
        if dest.exists():
            old = json.loads(dest.read_text())
            if old["stem_sha256"] == stem_sha and old["generated_sha256"] == chart_sha:
                continue
        started = time.monotonic()
        notes, _ = extract(base)
        with sf.SoundFile(wav) as f:
            if f.channels != 2 or f.samplerate != RATE:
                raise ValueError("Expected stereo 44.1 kHz vocal stem")
            votes = [estimate(f, n, lookup) for n in notes]
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                dict(
                    stem_sha256=stem_sha,
                    generated_sha256=chart_sha,
                    seconds=round(time.monotonic() - started, 3),
                    votes=votes,
                )
            )
        )
        tmp.replace(dest)
        print(tag, round(time.monotonic() - started, 2), flush=True)


def evaluate(args):
    paths = json.loads(args.charts.read_text())
    corpus = {v["tag"]: v for g in json.loads(args.corpus.read_text()).values() for v in g}
    cases = {r["tag"]: r for r in json.loads(args.manifest.read_text())}
    words = {r["id"]: r for r in csv.DictReader(args.text_scores.open())}
    out = []
    for tag, path in sorted(paths.items()):
        row = corpus[tag]
        obs = json.loads((args.predictions / (tag + ".json")).read_text())
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != obs["generated_sha256"]:
            raise ValueError("Frozen chart changed")
        original, _ = extract(Path(path))
        ref = Path(row["reference"])
        if hashlib.sha256(ref.read_bytes()).hexdigest() != cases[tag]["chart_sha"]:
            raise ValueError("Wrong reference")
        gt, _ = extract(ref)
        for method in ("baseline", "raw", "center", "both", "center_rescue"):
            pred = []
            for n, (a, b) in zip(original, obs["votes"], strict=True):
                value = {
                    "baseline": None,
                    "raw": a,
                    "center": b,
                    "both": a if a == b else None,
                    "center_rescue": b if a is None else None,
                }[method]
                if value is not None and n.pitch is not None:
                    delta = (value - n.pitch + 6) % 12 - 6
                    n = replace(n, pitch=n.pitch + delta)
                pred.append(n)

            def bounded(notes):
                return [
                    replace(n, end=min(n.end, row["duration"]))
                    for n in notes
                    if 0 <= n.start < row["duration"]
                ]

            m = compare_notes(bounded(gt), bounded(pred))
            m.update(
                wer=float(words[tag]["wer"]),
                word_mae_p50_p90_s=[0, float(words[tag]["word_p90_s"])],
            )
            if method == "baseline" and m["correct_class_all"] != float(words[tag]["pitch"]):
                raise ValueError("Baseline changed")
            out.append(
                dict(
                    id=tag,
                    language=row["language"],
                    strategy=method,
                    master_sha256=cases[tag]["audio_sha"],
                    generated_sha256=obs["generated_sha256"],
                    stem_sha256=obs["stem_sha256"],
                    seconds=obs["seconds"],
                    changes=sum(
                        i.pitch != j.pitch for i, j in zip(bounded(original), bounded(pred))
                    ),
                    wer=m["wer"],
                    word_p90_s=m["word_mae_p50_p90_s"][1],
                    pitch=m["correct_class_all"],
                    attacks=m["onset_pitch_f1_100ms"],
                    passes=passes(m),
                )
            )
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("predict", "evaluate"))
    for arg in ("charts", "stems", "corpus", "manifest", "text-scores", "out", "predictions"):
        p.add_argument("--" + arg, type=Path)
    args = p.parse_args()
    (predict if args.command == "predict" else evaluate)(args)
