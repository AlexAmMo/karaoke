"""Freeze SwiftF0 0.3.0 candidates on the fixed 40 stems before measuring references.

Install the inspected source without changing production dependencies:
  uv pip install --python build/generation-bench/env/bin/python --no-deps \
    ./build/research-reuse/swift-f0
  build/generation-bench/env/bin/python scripts/experiments/swift_notes.py generate
  build/generation-bench/env/bin/python scripts/experiments/swift_notes.py evaluate

Source: https://github.com/lars76/swift-f0/tree/d1ba77fe5331310b778ebe126b6cb3656d41d24f
Generation receives stem paths, predicted charts and manifest identities only. The
separate evaluation command is the first operation that reads human reference charts.
"""

import argparse
import csv
from datetime import datetime, timezone
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import sys
import time
from types import SimpleNamespace

import numpy as np
import soundfile

from melody_compare import digest, generate as generate_variants, measure, publish_text

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import extract, passes  # noqa: E402
from karaoke.generation_verification import _measure, _mono_timeline  # noqa: E402


VERSION = "0.3.0"
REVISION = "d1ba77fe5331310b778ebe126b6cb3656d41d24f"
MODEL_SHA256 = "6385e8c2ebc3872e82c9ff5946228de44cd3be77a750ea53698b7dbfe94b0a22"


def save(path, value):
    publish_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def identities(manifest):
    rows = json.loads(manifest.read_text())
    ids = {row["tag"] for row in rows}
    if len(rows) != 40 or len(ids) != 40:
        raise ValueError("Expected the frozen 40 distinct recordings")
    return ids


def generate(args):
    import swift_f0

    if swift_f0.__version__ != VERSION:
        raise ValueError(f"Expected swift-f0=={VERSION}, found {swift_f0.__version__}")
    package = Path(swift_f0.__file__).parent
    model = package / "model.onnx"
    if digest(model) != MODEL_SHA256:
        raise ValueError("SwiftF0 model differs from inspected revision")
    if (args.output / "frozen.json").exists():
        raise ValueError("Candidates are already frozen; evaluate or use a fresh output directory")
    wanted = identities(args.manifest)
    sources = json.loads(args.stems.read_text())
    bases = json.loads(args.charts.read_text())
    stems = {tag: str(Path(sources[tag]).resolve()) for tag in sorted(wanted)}
    charts = {tag: str(Path(bases[tag]).resolve()) for tag in sorted(wanted)}
    args.output.mkdir(parents=True, exist_ok=True)
    events_dir, traces_dir = args.output / "events", args.output / "traces"
    events_dir.mkdir(exist_ok=True)
    traces_dir.mkdir(exist_ok=True)
    save(args.output / "stems.json", stems)
    save(args.output / "charts.json", charts)
    settings = dict(
        family="swift-f0",
        version=VERSION,
        revision=REVISION,
        model_sha256=MODEL_SHA256,
        threads=2,
        spin=False,
        pitch_hold_ms=80.0,
        fmin=None,
        fmax=None,
    )
    started = time.perf_counter()
    save(
        args.output / "run.json",
        dict(
            settings=settings,
            manifest_sha256=digest(args.manifest),
            script_sha256=digest(Path(__file__)),
            source_sha256={p.name: digest(p) for p in sorted(package.glob("*.py"))},
            dependencies={
                p: importlib.metadata.version(p)
                for p in ("swift-f0", "numpy", "onnxruntime", "soundfile", "soxr")
            },
            host=platform.platform(),
            python=sys.version,
            started_utc=datetime.now(timezone.utc).isoformat(),
        ),
    )
    detector = swift_f0.SwiftF0(threads=2, spin=False)
    for index, (tag, path) in enumerate(stems.items(), 1):
        source = Path(path)
        duration = soundfile.info(source).duration
        stem_sha = digest(source)
        raw, trace = events_dir / (tag + ".json"), traces_dir / (tag + ".npz")
        if raw.exists():
            old = json.loads(raw.read_text())
            if old["settings"] != dict(settings, source=path) or (
                old["provenance"]["stem_sha256"] != stem_sha
                or old["provenance"]["trace_sha256"] != digest(trace)
            ):
                raise ValueError(f"Cannot resume changed prediction for {tag}")
            continue
        before = time.perf_counter()
        result = detector.detect_file(source)
        notes = swift_f0.segment_notes(result, pitch_hold_ms=80.0)
        elapsed = time.perf_counter() - before
        events = [
            [
                round(max(0, n.start), 6),
                round(min(duration, n.end), 6),
                int(round(69 + 12 * math.log2(n.pitch_hz / 440))),
            ]
            for n in notes
            if max(0, n.start) < min(duration, n.end)
        ]
        if not events or any(a[1] > b[0] for a, b in zip(events, events[1:])):
            raise ValueError(f"Empty or overlapping SwiftF0 events for {tag}")
        np.savez_compressed(
            trace,
            timestamps=result.timestamps,
            pitch_hz=result.pitch_hz,
            confidence=result.confidence,
            loudness_db=result.loudness_db,
        )
        save(
            raw,
            dict(
                settings=dict(settings, source=path),
                seconds=elapsed,
                events=events,
                provenance=dict(
                    duration_s=duration,
                    stem_sha256=stem_sha,
                    trace_sha256=digest(trace),
                    host=platform.platform(),
                    source_frames=len(result.timestamps),
                ),
            ),
        )
        print(f"{index}/40 {tag}: {len(events)} events, {elapsed:.2f}s", flush=True)
    generate_variants(
        SimpleNamespace(
            charts=args.output / "charts.json",
            events=events_dir,
            output=args.output / "variants",
            agree_with=None,
        )
    )
    # The outer freeze also binds the bases and traces. Do not rewrite after metrics exist.
    tracked = [p for p in args.output.rglob("*") if p.is_file()]
    frozen = {str(p.relative_to(args.output)): digest(p) for p in sorted(tracked)}
    save(
        args.output / "frozen.json",
        dict(
            files=frozen,
            baseline_sha256={tag: digest(Path(p)) for tag, p in charts.items()},
            seconds=time.perf_counter() - started,
            frozen_utc=datetime.now(timezone.utc).isoformat(),
        ),
    )
    print(f"Frozen {len(charts)} songs in {time.perf_counter() - started:.2f}s", flush=True)


def evaluate(args):
    frozen = json.loads((args.output / "frozen.json").read_text())
    for relative, sha in frozen["files"].items():
        if digest(args.output / relative) != sha:
            raise ValueError(f"Frozen prediction changed: {relative}")
    bases = json.loads((args.output / "charts.json").read_text())
    wanted = identities(args.manifest)
    if set(bases) != wanted:
        raise ValueError("Frozen predictions do not match the 40-song manifest")
    for tag, sha in frozen["baseline_sha256"].items():
        if digest(Path(bases[tag])) != sha:
            raise ValueError(f"Frozen baseline changed: {tag}")
    measure(
        SimpleNamespace(
            charts=args.output / "charts.json",
            events=args.output / "events",
            variants=args.output / "variants",
            corpus=args.corpus,
            baseline_scores=args.baseline_scores,
            output=args.output / "metrics.csv",
            agree_with=None,
            verified_stems=None,
            partial=False,
        )
    )
    corpus = {
        row["tag"]: row for group in json.loads(args.corpus.read_text()).values() for row in group
    }
    manifest = {row["tag"]: row for row in json.loads(args.manifest.read_text())}
    detailed, rows = {}, []
    for tag in sorted(wanted):
        case = corpus[tag]
        reference = Path(case["reference"])
        if digest(reference) != manifest[tag]["chart_sha"]:
            raise ValueError(f"Changed independent reference for {tag}")
        gold = extract(reference)
        candidates = {
            "baseline": Path(bases[tag]),
            **{
                method: args.output / "variants" / tag / (method + ".txt")
                for method in ("pitch", "events")
            },
        }
        detailed[tag] = {}
        for method, path in candidates.items():
            metrics = _measure(gold, extract(path))
            valid = _mono_timeline(path, case["duration"]) is not None
            accepted = bool(passes(metrics) and metrics["scored_frame_precision"] >= 0.90 and valid)
            detailed[tag][method] = dict(metrics, timeline_valid=valid, passes_five=accepted)
            rows.append(
                dict(
                    id=tag,
                    language=case["language"],
                    variant=method,
                    chart_sha256=digest(path),
                    reference_sha256=digest(reference),
                    wer=metrics["wer"],
                    word_p90_s=metrics["word_mae_p50_p90_s"][1],
                    correct_class_all=metrics["correct_class_all"],
                    onset_pitch_f1_100ms=metrics["onset_pitch_f1_100ms"],
                    scored_frame_precision=metrics["scored_frame_precision"],
                    passes_four=passes(metrics),
                    timeline_valid=valid,
                    passes_five=accepted,
                )
            )
    save(args.output / "metrics-five.json", detailed)
    with (args.output / "metrics-five.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    for method in ("baseline", "pitch", "events"):
        subset = [r for r in rows if r["variant"] == method]
        print(
            method,
            dict(
                songs=len(subset),
                passes_five=sum(r["passes_five"] for r in subset),
                median={
                    key: float(np.median([r[key] for r in subset]))
                    for key in (
                        "wer",
                        "word_p90_s",
                        "correct_class_all",
                        "onset_pitch_f1_100ms",
                        "scored_frame_precision",
                    )
                },
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "evaluate"))
    for name, default in (
        ("manifest", "docs/validation/generacion-muestra.json"),
        ("stems", "build/generation-v3/shared/stems.json"),
        ("charts", "build/generation-v3/lyrics/final/charts.json"),
        ("output", "build/generation-next/swift"),
        ("corpus", "build/generation-v2/corpus.json"),
        ("baseline-scores", "docs/validation/generacion-resultados.csv"),
    ):
        parser.add_argument("--" + name, type=Path, default=Path(default))
    args = parser.parse_args()
    (generate if args.command == "generate" else evaluate)(args)


if __name__ == "__main__":
    main()
