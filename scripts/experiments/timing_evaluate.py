"""Score frozen chart alternatives once against matching full human references; write numeric metrics."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import extract, score, passes
from timing_predict import METHODS
from timing_sylla import METHODS as SYLLABLE_METHODS


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def onset_coverage(reference, hypothesis, radius):
    ref = [n.start for n in reference if n.pitch is not None]
    hyp = [n.start for n in hypothesis if n.pitch is not None]
    matches = i = j = 0
    while i < len(ref) and j < len(hyp):
        if hyp[j] < ref[i] - radius:
            j += 1
        elif ref[i] < hyp[j] - radius:
            i += 1
        else:
            matches += 1
            i += 1
            j += 1
    return round(2 * matches / (len(ref) + len(hyp)), 4) if ref or hyp else None


def evaluate(song, baseline, folder, neural=None, fusion=None, sung=None):
    # The human chart is only opened in this evaluation command and never feeds
    # the predictors. Verify both its identity and each previously frozen file.
    tag = song["tag"]
    reference = Path(song["reference"])
    if digest(reference) != song["chart_sha"]:
        raise ValueError("Changed human reference for " + tag)
    certificate = json.loads((baseline.parent / "metrics.json").read_text())
    source = json.loads((folder / "source.json").read_text())
    hashes = json.loads((folder / "hashes.json").read_text())
    if certificate["audio_sha256"] != song["audio_sha"] or certificate["draft_sha256"] != digest(
        baseline
    ):
        raise ValueError("Changed baseline for " + tag)
    if (source["audio_sha256"], source["draft_sha256"]) != (
        song["audio_sha"],
        certificate["draft_sha256"],
    ):
        raise ValueError("Timing features do not belong to this baseline: " + tag)
    files = {method: folder / (method + ".txt") for method in METHODS}
    if neural:
        hashes.update(json.loads((neural / "hashes.json").read_text()))
        files.update({method: neural / (method + ".txt") for method in ("qwen", "qwen-consenso")})
    if fusion:
        hashes.update(json.loads((fusion / "hashes.json").read_text()))
        files["consenso-completo"] = fusion / "consenso-completo.txt"
    if sung:
        sung_hashes = json.loads((sung / "hashes.json").read_text())
        hashes.update(sung_hashes)
        for method in SYLLABLE_METHODS:
            files[method] = sung / (method + ".txt")
    files = {"base": baseline, **files}
    hashes["base"] = certificate["draft_sha256"]
    human, _ = extract(reference)
    human = [n for n in human if 0 <= n.start < song["duration"]]
    results = []
    for method, pred in files.items():
        actual_hash = digest(pred)
        if hashes[method] != actual_hash:
            raise ValueError(f"Changed candidate for {tag} {method}")
        metric = score(reference, pred, 0, song["duration"], False)
        notes, _ = extract(pred)
        notes = [n for n in notes if 0 <= n.start < song["duration"]]
        errors = metric.get("word_mae_p50_p90_s", [])
        p90 = round(1000 * errors[1]) if len(errors) == 2 else None
        passed = passes(metric)
        thirds = metric.get("signed_word_p50_by_third_s", [None, None, None])
        results.append(
            dict(
                id=tag,
                idioma=song["language"],
                metodo=method,
                wer=metric["wer"],
                palabras=metric["ref_words"],
                errores_palabra=metric.get("edits"),
                p90_ms=p90,
                clase=metric["correct_class_all"],
                f1_ataque_tono=metric["onset_pitch_f1_100ms"],
                f1_solo_ataque_50ms=onset_coverage(human, notes, 0.05),
                f1_solo_ataque_100ms=onset_coverage(human, notes, 0.10),
                ataques_tono=metric.get("matching_onsets"),
                notas_ref=metric["reference_notes"],
                notas_puntuadas=metric.get("generated_scored"),
                notas_libres=metric.get("generated_freestyle"),
                palabras_coincidentes=metric.get("exact", 0),
                mediana_inicio_ms=round(1000 * thirds[0]) if thirds[0] is not None else "",
                mediana_medio_ms=round(1000 * thirds[1]) if thirds[1] is not None else "",
                mediana_final_ms=round(1000 * thirds[2]) if thirds[2] is not None else "",
                supera_objetivos=int(passed),
                mezcla_sha256=song["audio_sha"],
                voz_sha256=source["vocal_sha256"],
                referencia_sha256=song["chart_sha"],
                borrador_sha256=actual_hash,
            )
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("charts", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--partial", action="store_true")
    parser.add_argument(
        "--cohort",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "docs/validation/generacion-muestra.json",
    )
    parser.add_argument(
        "--qwen", type=Path, help="Additional independent forced-alignment predictions"
    )
    parser.add_argument(
        "--fusion", type=Path, help="SOME/ROSVOT consensus pitches with verified word timings"
    )
    parser.add_argument("--sylla", type=Path, help="Sung character alignment variants")
    args = parser.parse_args()
    songs = json.loads(args.corpus.read_text())
    songs = sum(songs.values(), []) if isinstance(songs, dict) else songs
    prepared = {s["tag"]: s for s in songs}
    cohort = json.loads(args.cohort.read_text())
    songs = []
    for selected in cohort:
        song = prepared[selected["tag"]]
        if (song["audio_sha"], song["chart_sha"]) != (selected["audio_sha"], selected["chart_sha"]):
            raise ValueError("Wrong edition for " + selected["tag"])
        songs.append(song)
    charts = json.loads(args.charts.read_text())
    rows = []
    for song in songs:
        tag = song["tag"]
        folder = args.predictions / tag
        if args.partial and (tag not in charts or not (folder / "hashes.json").is_file()):
            continue
        neural = args.qwen / tag if args.qwen else None
        if args.partial and neural and not (neural / "hashes.json").is_file():
            continue
        fusion = args.fusion / tag if args.fusion else None
        if args.partial and fusion and not (fusion / "hashes.json").is_file():
            continue
        sung = args.sylla / tag if args.sylla else None
        if args.partial and sung and not (sung / "hashes.json").is_file():
            continue
        rows.extend(evaluate(song, Path(charts[tag]), folder, neural, fusion, sung))
        print(tag, flush=True)
    if not rows:
        raise ValueError("No complete predictions")
    if not args.partial and len(rows) != len(songs) * (
        1
        + len(METHODS)
        + (2 if args.qwen else 0)
        + bool(args.fusion)
        + len(SYLLABLE_METHODS) * bool(args.sylla)
    ):
        raise ValueError("Missing songs")
    temporary = args.output.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=tuple(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(args.output)


if __name__ == "__main__":
    main()
