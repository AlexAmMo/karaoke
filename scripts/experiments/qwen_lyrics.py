"""Freeze Qwen3-ASR lyrics from complete audio, without reference text.

Uses the existing CrispASR CLI and a pinned 1.7B Q4_K conversion. This is a
transcription experiment, not a timed karaoke chart or a production dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.songs import read_chart
from karaoke.generation_metrics import TOKEN, compare_words, extract

MODEL_SHA = "ec197cef7ccc589fdcae1becc3f4a3de119d0a41e790b898b519b1a048dad8d4"
MODEL_REVISION = "674df5d44b50a63e7102a18895ed20e3f91de301"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def implementation_hash(functions, dependencies):
    """Hash one stage and its helpers without coupling it to the other stage."""
    sources = [inspect.getsource(function) for function in functions]
    files = {str(Path(path).resolve()): digest(path) for path in dependencies}
    return hashlib.sha256(json.dumps({"sources": sources, "files": files},
                                    sort_keys=True).encode()).hexdigest()


def generation_implementation():
    return implementation_hash(
        (generate, generation_implementation, implementation_hash, digest, write_json),
        (inspect.getsourcefile(read_chart),),
    )


def evaluation_implementation():
    return implementation_hash(
        (evaluate, evaluation_implementation, implementation_hash, digest, write_json,
         transcript_words, lyric_metrics),
        (inspect.getsourcefile(compare_words), inspect.getsourcefile(read_chart)),
    )


def transcript_words(text):
    # Keep repeated words: repetitions are part of the sung text, not duplicates.
    normalized = unicodedata.normalize("NFKC", text.casefold())
    return [(match.group(), 0.0) for match in TOKEN.finditer(normalized)]


def lyric_metrics(reference, words):
    measured = compare_words(reference, words)
    # compare_words uses NumPy. Freeze public JSON using native Python scalars.
    return {"wer": float(measured["wer"]), "edits": int(measured["edits"]),
            "ref_words": int(measured["ref_words"]), "hyp_words": int(measured["hyp_words"])}


def generate(args):
    charts = json.loads(args.charts.read_text())
    stems = json.loads(args.stems.read_text())
    if set(charts) != set(stems) or (args.ids and not set(args.ids).issubset(charts)):
        raise ValueError("Prediction and vocal manifests do not match the requested cohort")
    if digest(args.model) != MODEL_SHA:
        raise ValueError("Qwen3-ASR weights do not match the pinned conversion")
    binary_hash, script_hash = digest(args.binary), generation_implementation()
    for tag in args.ids or sorted(stems):
        stem, baseline = Path(stems[tag]), Path(charts[tag])
        _, meta = read_chart(baseline)
        language = {"english": "en", "spanish": "es"}.get(
            meta.get("LANGUAGE", "").lower(), meta.get("LANGUAGE", "auto").lower()
        )
        output = args.output / tag
        output.mkdir(parents=True, exist_ok=True)
        signature = {
            "stem": str(stem.resolve()), "stem_sha256": digest(stem),
            "baseline": str(baseline.resolve()), "baseline_sha256": digest(baseline),
            "model_sha256": MODEL_SHA, "model_revision": MODEL_REVISION,
            "binary_sha256": binary_hash, "implementation_sha256": script_hash,
            "implementation_scope": "generation-v1",
            "language": language, "threads": args.threads,
            "chunk_seconds": 28, "chunk_overlap": 0, "lcs_dedup": "off",
            "max_new_tokens": 512, "device": args.device, "reference_used": False,
            "source_kind": args.source_kind,
        }
        frozen = output / "frozen.json"
        if frozen.exists():
            previous = json.loads(frozen.read_text())
            if (previous["signature"] != signature
                    or previous["text_sha256"] != digest(output / "lyrics.txt")
                    or previous["raw_sha256"] != digest(output / "raw.json")):
                raise ValueError(f"Frozen input or result changed for {tag}")
            continue
        started = time.monotonic()
        command = [
            str(args.binary.resolve()), "--backend", "qwen3", "-m", str(args.model.resolve()),
            "-f", str(stem.resolve()), "-l", language, "-t", str(args.threads),
            "--chunk-seconds", "28", "--chunk-overlap", "0", "--lcs-dedup", "off",
            "--max-new-tokens", "512", "--output-json", "--output-file", str((output / "raw").resolve()),
        ]
        command += ["--no-gpu"] if args.device == "cpu" else ["--gpu-backend", "metal"]
        env = dict(os.environ, OMP_NUM_THREADS=str(args.threads), CRISPASR_GGUF_MMAP="1")
        with (output / "inference.log").open("w") as log:
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=1800)
        raw = json.loads((output / "raw.json").read_text())
        segments = raw["transcription"]
        text = " ".join(segment["text"].strip() for segment in segments).strip()
        if not text:
            raise ValueError(f"Empty transcription for {tag}")
        (output / "lyrics.txt").write_text(text + "\n")
        result = {"signature": signature, "seconds": round(time.monotonic() - started, 2),
                  "text_sha256": digest(output / "lyrics.txt"),
                  "raw_sha256": digest(output / "raw.json"), "segments": len(segments)}
        write_json(frozen, result)
        print(json.dumps({"tag": tag, "seconds": result["seconds"], "segments": len(segments)}), flush=True)


def evaluate(args):
    import numpy as np

    identities = json.loads(args.identities.read_text())
    tags = [row["tag"] for row in identities]
    identity_map = {row["tag"]: row for row in identities}
    if len(tags) != 40 or len(set(tags)) != 40:
        raise ValueError("Expected the fixed 40-recording cohort")
    corpus = json.loads(args.corpus.read_text())
    records = {row["tag"]: row for group in corpus.values() for row in group}
    rows = []
    for tag in tags:
        row = records[tag]
        if any(row[field] != identity_map[tag][field] for field in ("audio_sha", "chart_sha")):
            raise ValueError(f"Corpus identity differs from the official master: {tag}")
        frozen = args.predictions / tag / "frozen.json"
        if not frozen.exists():
            rows.append({"tag": tag, "status": "missing"})
            continue
        frozen_value = json.loads(frozen.read_text())
        signature = frozen_value["signature"]
        for path, expected in ((row["audio"], row["audio_sha"]),
                               (row["reference"], row["chart_sha"]),
                               (signature["stem"], signature["stem_sha256"]),
                               (signature["baseline"], signature["baseline_sha256"]),
                               (frozen.parent / "lyrics.txt", frozen_value["text_sha256"]),
                               (frozen.parent / "raw.json", frozen_value["raw_sha256"])):
            if digest(path) != expected:
                raise ValueError(f"Frozen input or result changed: {path}")
        _, reference = extract(Path(row["reference"]))
        _, baseline = extract(Path(signature["baseline"]))
        text = (frozen.parent / "lyrics.txt").read_text()
        words = transcript_words(text)
        if not reference:
            raise ValueError(f"Empty independent reference for {tag}")
        measured = lyric_metrics(reference, words)
        before = lyric_metrics(reference, baseline)
        rows.append({"tag": tag, "status": "measured", "language": row["language"],
                     "wer": measured["wer"], "baseline_wer": before["wer"],
                     "edits": measured["edits"], "ref_words": measured["ref_words"],
                     "hyp_words": measured["hyp_words"], "seconds": float(frozen_value["seconds"]),
                     "prediction_sha256": frozen_value["text_sha256"],
                     "freeze_sha256": digest(frozen)})
    measured = [row for row in rows if row["status"] == "measured"]
    at_one = sum(row["wer"] <= .01 for row in measured)
    at_five = sum(row["wer"] <= .05 for row in measured)
    output = {
        "scope": "Lyrics only, no timing or melody claim. Development corpus, not unseen holdout.",
        "evaluation_implementation_sha256": evaluation_implementation(),
        "cohort_size": len(tags), "measured": len(measured),
        "missing": len(tags) - len(measured),
        "missing_are_failures": True,
        "wer_at_most_1_percent": at_one,
        "wer_at_most_5_percent": at_five,
        "fraction_of_full_cohort_at_most_1_percent": at_one / len(tags),
        "fraction_of_full_cohort_at_most_5_percent": at_five / len(tags),
        "median_wer": float(np.median([row["wer"] for row in measured])) if measured else None,
        "baseline_median_wer_same_subset": float(np.median([row["baseline_wer"] for row in measured])) if measured else None,
        "rows": rows,
    }
    if args.output.exists():
        raise ValueError("Use a new evaluation filename; do not overwrite evidence")
    write_json(args.output, output)
    print(json.dumps({k: v for k, v in output.items() if k != "rows"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("generate")
    for name in ("charts", "stems", "binary", "model", "output"):
        first.add_argument("--" + name, type=Path, required=True)
    first.add_argument("--ids", nargs="*")
    first.add_argument("--threads", type=int, default=2)
    first.add_argument("--device", choices=("cpu", "gpu"), default="cpu")
    first.add_argument("--source-kind", choices=("vocals", "mix"), default="vocals")
    second = commands.add_parser("evaluate")
    for name in ("predictions", "corpus", "output"):
        second.add_argument("--" + name, type=Path, required=True)
    second.add_argument("--identities", type=Path, default=Path("docs/validation/generacion-muestra.json"))
    args = parser.parse_args()
    (generate if args.command == "generate" else evaluate)(args)


if __name__ == "__main__":
    main()
