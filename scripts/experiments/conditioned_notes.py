"""Compare free and lyric-conditioned GAME inference on frozen complete recordings.

Generation sees only an existing prediction and its vocal audio. Reference charts
are deliberately absent from this command; evaluate the frozen outputs separately.
The existing package's weights and ONNX adapter are reused without modification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import onnxruntime as ort
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import ROW
from karaoke.generation_worker import NOTE_SEED, load_engine
from karaoke.songs import read_chart
from karaoke import generation_worker, songs
import melody_compare
from melody_compare import transform


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def predicted_anchors(chart):
    text, meta = read_chart(chart)
    tick = 15 / float(meta["BPM"].replace(",", "."))
    gap = float(meta.get("GAP", "0").replace(",", ".")) / 1000
    syllables, word_starts = [], []
    new_word = True
    for line in text.splitlines():
        match = ROW.match(line)
        if not match:
            if line.startswith("-"):
                new_word = True
            continue
        _, beat, length, _, lyric = match.groups()
        a = gap + int(beat) * tick
        b = a + int(length) * tick
        if lyric.strip() == "~" and syllables:
            syllables[-1][1] = b
        else:
            syllables.append([a, b])
            if new_word:
                word_starts.append(a)
        new_word = lyric.endswith(" ")
    return syllables, word_starts, meta


def durations_for(mode, syllables, words, start, stop):
    if mode == "free":
        return []
    anchors = words if mode == "words" else [s[0] for s in syllables]
    if mode == "spans":
        anchors += [s[1] for s in syllables]
    cuts = sorted({0.0, stop - start, *(a - start for a in anchors if start < a < stop)})
    # Preserve supplied boundaries exactly; do not tune them against a reference.
    return [b - a for a, b in zip(cuts, cuts[1:]) if b > a]


def infer(stem, syllables, words, mode, language, backend, folder):
    chunks = []
    with sf.SoundFile(stem) as stream:
        sr = stream.samplerate
        if sr != backend.SAMPLE_RATE:
            raise ValueError(f"Expected {backend.SAMPLE_RATE} Hz, received {sr}: {stem}")
        duration = len(stream) / sr
        for core in range(0, math.ceil(duration), 12):
            left, right = max(0, core - 1.5), min(duration, core + 13.5)
            if not any(a < right and b > left for a, b in syllables):
                continue
            stream.seek(round(left * sr))
            signal = stream.read(round((right - left) * sr), dtype="float32", always_2d=True)
            known = durations_for(mode, syllables, words, left, right)
            for a, b, voiced, midi in backend.extract(folder, signal.mean(axis=1), known, language):
                midpoint = left + (a + b) / 2
                if voiced and core <= midpoint < core + 12 and b > a:
                    chunks.append((max(0, left + a), min(duration, left + b), round(midi)))
    events = []
    for a, b, midi in sorted(chunks):
        if events and a < events[-1][1]:
            previous_a, previous_b, previous_pitch = events[-1]
            if midi == previous_pitch:
                events[-1] = (previous_a, max(b, previous_b), midi)
                continue
            seam = (a + previous_b) / 2
            events[-1] = (previous_a, seam, previous_pitch)
            a = seam
        if b > a:
            events.append((a, b, midi))
    return events, duration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("charts", "stems", "cache", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--modes", nargs="+", choices=("free", "syllables", "spans", "words"),
                        default=["free", "syllables", "spans", "words"])
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    charts = json.loads(args.charts.read_text())
    if args.overlay:
        charts.update(json.loads(args.overlay.read_text()))
    stems = json.loads(args.stems.read_text())
    if set(charts) != set(stems):
        raise ValueError("Prediction and vocal manifest cohorts differ")
    if args.ids and not set(args.ids).issubset(charts):
        raise ValueError("Requested recording is outside frozen cohort")
    load_engine(args.cache.resolve())
    from services import game_notes

    folder = game_notes.model_folder(str(args.cache.resolve()))
    expected = game_notes.MODEL_FILES
    if any(digest(Path(folder) / name) != info[1] for name, info in expected.items()):
        raise ValueError("GAME weights differ from the released pinned model")
    options = ort.SessionOptions()
    options.intra_op_num_threads = args.threads
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")

    def session(name):
        return ort.InferenceSession(str(Path(folder) / (name + ".onnx")),
                                   sess_options=options, providers=["CPUExecutionProvider"])

    game_notes._sessions[folder] = {name: session(name) for name in
                                   ("encoder", "estimator", "dur2bd", "bd2dur")}
    for tag in args.ids or sorted(charts):
        chart, stem = Path(charts[tag]), Path(stems[tag])
        spans, words, meta = predicted_anchors(chart)
        if not spans:
            raise ValueError(f"No predicted syllables in {tag}")
        language = meta.get("LANGUAGE", "").lower()
        language = {"english": "en", "spanish": "es"}.get(language, language)
        for mode in args.modes:
            output = args.output / mode / tag
            output.mkdir(parents=True, exist_ok=True)
            provenance = {"stem_sha256": digest(stem), "baseline_sha256": digest(chart),
                          "mode": mode, "seed": NOTE_SEED, "language": language,
                          "model_sha256": {name: info[1] for name, info in expected.items()},
                          "implementation_sha256": digest(__file__),
                          "adapter_sha256": digest(game_notes.__file__),
                          "dependencies_sha256": {
                              "melody_compare": digest(melody_compare.__file__),
                              "generation_worker": digest(generation_worker.__file__),
                              "songs": digest(songs.__file__),
                          }, "onnxruntime": ort.__version__, "threads": args.threads}
            frozen = output / "frozen.json"
            if frozen.exists():
                previous = json.loads(frozen.read_text())
                if previous["provenance"] != provenance:
                    raise ValueError(f"Incompatible cached experiment: {output}")
                if any(digest(output / (method + ".txt")) != sha
                       for method, sha in previous["charts"].items()):
                    raise ValueError(f"Frozen output modified: {output}")
                continue
            ort.set_seed(NOTE_SEED)
            game_notes._sessions[folder]["segmenter"] = session("segmenter")
            start = time.monotonic()
            events, duration = infer(stem, spans, words, mode, language, game_notes, folder)
            candidates = transform(chart, events, duration)
            hashes = {}
            for method, text in candidates.items():
                path = output / (method + ".txt")
                path.write_text(text, encoding="utf-8")
                hashes[method] = digest(path)
            write_json(output / "events.json", {"events": events, "provenance": provenance})
            elapsed = round(time.monotonic() - start, 2)
            write_json(frozen, {"provenance": provenance, "charts": hashes,
                                "seconds": elapsed, "duration_s": duration})
            print(tag, mode, len(events), elapsed, flush=True)


if __name__ == "__main__":
    main()
