"""Cross the fixed ornament rule with previously frozen independent pitch votes."""

import argparse
import csv
from dataclasses import replace
import json
from pathlib import Path

from timing_evaluate import digest
from timing_predict import parse, remove_ornaments, serialize
from karaoke.generation_metrics import compare_notes, compare_words, extract, passes
from karaoke.songs import read_chart

METHODS = ("base", "consenso", "ornamentos", "consenso-ornamentos")


def generate(args, charts):
    for tag, file in charts.items():
        base = Path(file)
        # The two revised lyric texts have their own consensus certificates.
        selected = None
        for root in args.consensus:
            certificate = root / tag / "frozen.json"
            if not certificate.is_file():
                continue
            frozen = json.loads(certificate.read_text())
            if frozen["baseline_sha256"] == digest(base):
                selected = certificate.parent / "consensus.txt"
                if digest(selected) != frozen["charts"]["consensus"]:
                    raise ValueError(f"Pitch prediction changed for {tag}")
                break
        if selected is None:
            if args.partial:
                continue
            raise ValueError(f"Missing pitch consensus on the specified text for {tag}")
        headers, raw = parse(base)
        _, tuned = parse(selected)
        if [(x.start, x.end, x.lyric, x.kind, x.line) for x in raw] != [
            (x.start, x.end, x.lyric, x.kind, x.line) for x in tuned
        ]:
            raise ValueError(f"Consensus modified the clock or words in {tag}")
        output = args.variants / tag
        output.mkdir(parents=True, exist_ok=True)
        signatures = {}
        for name, notes in zip(
            METHODS, (raw, tuned, remove_ornaments(raw), remove_ornaments(tuned)), strict=True
        ):
            path = output / (name + ".txt")
            temp = path.with_suffix(".tmp")
            temp.write_text(serialize(headers, notes), encoding="utf-8")
            temp.replace(path)
            signatures[name] = digest(path)
        temp = output / "frozen.tmp"
        temp.write_text(json.dumps({"base_sha256": digest(base), "maps": signatures}))
        temp.replace(output / "frozen.json")


def bounds(notes, duration):
    return [replace(n, end=min(n.end, duration)) for n in notes if 0 <= n.start < duration]


def measure(args, charts):
    corpus = {s["tag"]: s for cases in json.loads(args.corpus.read_text()).values() for s in cases}
    fixed = {s["tag"]: s for s in json.loads(args.cohort.read_text())}
    if not args.partial and set(charts) != set(fixed):
        raise ValueError("The complete experiment requires every frozen chart exactly once")
    out = []
    for tag, file in charts.items():
        case, pub = corpus[tag], fixed[tag]
        ref, baseline = Path(case["reference"]), Path(file)
        dest = args.variants / tag
        if args.partial and not (dest / "frozen.json").is_file():
            continue
        certified = json.loads((dest / "frozen.json").read_text())
        if (digest(ref), case["audio_sha"], digest(baseline)) != (
            pub["chart_sha"],
            pub["audio_sha"],
            certified["base_sha256"],
        ):
            raise ValueError(f"Wrong chart or recording for {tag}")
        human, words = extract(ref)
        base_notes, original_words = extract(baseline)
        duration = float(case["duration"])
        gold = bounds(human, duration)
        language_scores = compare_words(
            [(w, t) for w, t in words if 0 <= t < duration],
            [(w, t) for w, t in original_words if 0 <= t < duration],
        )
        earlier = {}
        for name in METHODS:
            path = dest / (name + ".txt")
            key = digest(path)
            if certified["maps"][name] != key:
                raise ValueError(f"Modified prediction {tag} {name}")
            notes, recognized = extract(path)
            if recognized != original_words:
                raise ValueError(f"Words or their start times changed for {tag} {name}")
            text, _ = read_chart(path)
            equal = earlier.setdefault(text, name)
            hypothesis = bounds(notes, duration)
            values = {**language_scores, **compare_notes(gold, hypothesis)}
            starts = [n.start for n in hypothesis]
            overlaps = sum(a.end - b.start > 1e-6 for a, b in zip(hypothesis, hypothesis[1:]))
            if starts != sorted(starts):
                raise ValueError(f"Unordered generated map {tag} {name}")
            out.append(
                dict(
                    id=tag,
                    artista=pub["artist"],
                    idioma=pub["language"],
                    metodo=name,
                    wer=values["wer"],
                    p90_ms=round(1000 * values["word_mae_p50_p90_s"][1]),
                    clase=values["correct_class_all"],
                    f1_ataque_tono=values["onset_pitch_f1_100ms"],
                    supera_objetivos=int(passes(values)),
                    notas_absorbidas=len(base_notes) - len(notes),
                    inicios_duplicados=len(starts) - len(set(starts)),
                    barras_solapadas=overlaps,
                    mapa_identico_a=equal if equal != name else "",
                    mezcla_sha256=case["audio_sha"],
                    referencia_sha256=pub["chart_sha"],
                    entrada_sha256=certified["base_sha256"],
                    salida_sha256=key,
                )
            )
    if not out:
        raise ValueError("No frozen predictions")
    tmp = args.output.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    tmp.replace(args.output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate_cmd = sub.add_parser("generate")
    measure_cmd = sub.add_parser("measure")
    for command in (generate_cmd, measure_cmd):
        command.add_argument(
            "charts", type=Path, help="Frozen chart index after the lyric treatment"
        )
        command.add_argument("variants", type=Path)
        command.add_argument("--partial", action="store_true")
    generate_cmd.add_argument("consensus", type=Path, nargs="+", help="Frozen model output roots")
    measure_cmd.add_argument("corpus", type=Path)
    measure_cmd.add_argument("output", type=Path)
    measure_cmd.add_argument(
        "--cohort",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "docs/validation/generacion-muestra.json",
    )
    args = parser.parse_args()
    charts = json.loads(args.charts.read_text())
    (generate if args.command == "generate" else measure)(args, charts)


if __name__ == "__main__":
    main()
