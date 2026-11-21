"""Freeze full-song lyric choices from existing Sylla emissions, then evaluate words.

Generation reads only predictions, emission caches and recording identity hashes.
It never runs a model or opens evaluation reference charts. All four fixed rules
are reported; reference WER must not select a rule or a candidate at generation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import inspect
import itertools
import json
import math
from pathlib import Path
import re
import sys
import time
import unicodedata

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.songs import read_chart


LEAD_SHA = "bc8d8e504eabec5538027623b376e3f560691c2fb134c1a8fc6081bd10e86716"
BG_SHA = "c6d939babc45e1770a9bdd7d12a811eecf7fcd82006163c50cd343d0856f7e9f"
MODEL_REVISION = "0a228acf0c1351ad0e2734604ee921d497d861e8"
METHODS = tuple(f"{head}-{denominator}" for head in ("lead", "pooled") for denominator in ("frame", "character"))
MIN_WORDS = 12
MIN_QWEN_RATIO = 0.78  # Existing generation_worker.choose_candidate lower bound.
WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)
ROW = re.compile(r"^[:*FRG]\s+-?\d+\s+\d+\s+-?\d+ (.*)$")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def chart_lyrics(path):
    chart, _ = read_chart(path)
    parts = []
    for line in chart.splitlines():
        match = ROW.match(line)
        if match:
            parts.append(match[1].replace("~", ""))
        elif line.startswith("-"):
            parts.append("\n")
    return "".join(parts).strip()


def encode(text, labels):
    """Keep lexical characters; explicitly record punctuation and reject unknowns."""
    normalized = unicodedata.normalize("NFKC", text.casefold()).replace("’", "'")
    chars, punctuation, unsupported = [], Counter(), set()
    for char in normalized:
        if char.isspace():
            chars.append(" ")
        elif char.isalnum() or char == "'":
            chars.append(char)
        elif unicodedata.category(char).startswith("P"):
            chars.append(" ")
            punctuation[char] += 1
        else:
            unsupported.add(char)
    words = WORD.findall("".join(chars))
    joined = "|".join(words)
    unsupported.update(set(joined) - set(labels))
    reasons = []
    if len(words) < MIN_WORDS:
        reasons.append("fewer_than_12_words")
    if unsupported:
        reasons.append("unrepresentable_characters")
    return {"words": len(words), "characters": len(joined), "invalid": reasons,
            "unsupported": sorted(unsupported), "removed_punctuation": dict(punctuation),
            "targets": [labels[c] for c in joined] if not unsupported else []}


def ctc_nll(logp, targets):
    """Exact CTC forward sum with O(target length) memory, blank index zero.

    A rolling pair of forward rows avoids allocating the whole T×(2U+1)
    lattice for long songs. The three allowed transitions are stay, advance
    one label, and skip a blank between different nonblank labels.
    """
    labels = np.zeros(2 * len(targets) + 1, dtype=np.int64)
    labels[1::2] = targets
    skip = np.zeros(len(labels), dtype=bool)
    skip[2:] = (labels[2:] != 0) & (labels[2:] != labels[:-2])
    previous = np.full(len(labels), -np.inf, dtype=np.float64)
    previous[0] = 0.0
    advance = np.full_like(previous, -np.inf)
    leap = np.full_like(previous, -np.inf)
    for frame in logp:
        advance[1:] = previous[:-1]
        leap[2:] = previous[:-2]
        leap[~skip] = -np.inf
        previous = np.logaddexp(np.logaddexp(previous, advance), leap) + frame[labels]
    total = np.logaddexp(previous[-1], previous[-2]) if targets else previous[0]
    return float(-total)


def selftest():
    # The fourth class is absent from the retained cache. Its probability must
    # not be redistributed over the retained classes before computing CTC.
    probabilities = np.array([[.45, .3, .15, .1], [.2, .5, .2, .1],
                              [.4, .25, .3, .05], [.3, .2, .4, .1]], dtype=np.float64)

    def collapse(path):
        return [value for i, value in enumerate(path) if value != 0 and (i == 0 or value != path[i - 1])]

    outcomes = []
    for target in ([1], [1, 1], [1, 2], [2, 1]):
        exact = sum(math.prod(probabilities[t, value] for t, value in enumerate(path))
                    for path in itertools.product(range(4), repeat=4) if collapse(path) == target)
        measured = ctc_nll(np.log(probabilities[:, :3]), target)
        assert math.isclose(measured, -math.log(exact), abs_tol=1e-12), (target, measured, exact)
        outcomes.append({"target": target, "nll_enumerated": -math.log(exact), "nll_ctc": measured})
    assert math.isclose(ctc_nll(np.log(probabilities[:, :3]), []),
                        -np.log(probabilities[:, 0]).sum(), abs_tol=1e-12)
    assert math.isinf(ctc_nll(np.log(probabilities[:1, :3]), [1, 1]))
    labels = {c: i for i, c in enumerate(["<blank>", "|", "'", *"abcdefghijklmnopqrstuvwxyz"])}
    assert encode("", labels)["invalid"] == ["fewer_than_12_words"]
    assert "unrepresentable_characters" in encode("word " * 12 + "Ж", labels)["invalid"]
    assert "unrepresentable_characters" in encode("word " * 12 + "🎵", labels)["invalid"]
    assert not encode("word " * 12, labels)["invalid"]
    return outcomes


def generate(args):
    equivalence = selftest()
    identities = json.loads(args.identities.read_text(encoding="utf-8"))
    charts = json.loads(args.charts.read_text(encoding="utf-8"))
    cohort = {row["tag"]: row for row in identities}
    if len(cohort) != 40 or set(cohort) != set(charts):
        raise ValueError("Expected the fixed complete 40-recording cohort")
    tags = args.ids or sorted(cohort)
    if not set(tags).issubset(cohort) or len(tags) != len(set(tags)):
        raise ValueError("Unknown or repeated pilot IDs")
    args.output.mkdir(parents=True, exist_ok=False)
    plan = {"created_utc": datetime.now(timezone.utc).isoformat(), "methods": METHODS,
            "primary_method": "lead-frame", "normalization": "NFKC/casefold; word delimiter |; retain apostrophes; no leading/trailing delimiter",
            "min_words": MIN_WORDS, "min_qwen_to_base_word_ratio": MIN_QWEN_RATIO,
            "invalid_candidate": "fallback_base_for_all_rules", "ties": "base",
            "model_revision": MODEL_REVISION, "model_sha256": LEAD_SHA, "background_sha256": BG_SHA,
            "cache_normalization": "global vocabulary softmax already applied; no renormalization of retained columns",
            "numpy": np.__version__, "workers": 1, "ctc_dtype": "float64",
            "ctc_memory": "rolling forward rows, O(target length); no Torch or model loading",
            "script_sha256": digest(__file__), "read_chart_module_sha256": digest(inspect.getsourcefile(read_chart)),
            "identities_sha256": digest(args.identities), "charts_manifest_sha256": digest(args.charts),
            "tags": tags, "cohort_size": 40, "reference_text_read": False,
            "ctc_enumeration_equivalence": equivalence}
    write_json(args.output / "plan.json", plan)
    results = []
    for tag in tags:
        started = time.monotonic()
        folder = args.output / tag
        folder.mkdir()
        chart = Path(charts[tag])
        qwen_folder = args.qwen / tag
        qwen_meta = json.loads((qwen_folder / "frozen.json").read_text(encoding="utf-8"))
        signature = qwen_meta["signature"]
        if (digest(chart) != signature["baseline_sha256"]
                or digest(qwen_folder / "lyrics.txt") != qwen_meta["text_sha256"]
                or signature["source_kind"] != "mix"
                or signature["stem_sha256"] != cohort[tag]["audio_sha"]):
            raise ValueError(f"Changed Qwen/base/recording provenance for {tag}")
        source = args.emissions / (tag + ".npz")
        texts = {"base": chart_lyrics(chart), "qwen": (qwen_folder / "lyrics.txt").read_text(encoding="utf-8").strip()}
        with np.load(source, allow_pickle=False) as cache:
            if (str(cache["model_sha256"]) != LEAD_SHA or str(cache["bg_sha256"]) != BG_SHA
                    or str(cache["audio_sha256"]) != cohort[tag]["audio_sha"]):
                raise ValueError(f"Unexpected Sylla cache for {tag}")
            labels = {str(label): i for i, label in enumerate(cache["labels"])}
            if labels.get("<blank>") != 0 or "|" not in labels:
                raise ValueError("Unexpected CTC vocabulary")
            encoded = {name: encode(text, labels) for name, text in texts.items()}
            if encoded["qwen"]["words"] < MIN_QWEN_RATIO * encoded["base"]["words"]:
                encoded["qwen"]["invalid"].append("below_existing_0.78_word_ratio_guard")
            valid = all(not item["invalid"] for item in encoded.values())
            nll, frames = {}, None
            for head in ("lead", "pooled"):
                matrix = cache[head].astype(np.float32)
                if matrix.ndim != 2 or matrix.shape[1] != len(labels) or not np.isfinite(matrix).all() or matrix.max() > .001:
                    raise ValueError(f"Invalid cached log probabilities: {tag}/{head}")
                if frames is not None and frames != len(matrix):
                    raise ValueError("Head frame counts differ")
                frames = len(matrix)
                nll[head] = {}
                if valid:
                    for name in texts:
                        value = ctc_nll(matrix, encoded[name]["targets"])
                        nll[head][name] = value if math.isfinite(value) else None
                del matrix
        valid = valid and all(value is not None for scores in nll.values() for value in scores.values())
        decisions, output_hashes = {}, {}
        for method in METHODS:
            head, denominator = method.split("-")
            selected = "base"
            scores = {}
            if valid:
                for name in texts:
                    divisor = frames if denominator == "frame" else encoded[name]["characters"]
                    scores[name] = -nll[head][name] / divisor
                if scores["qwen"] > scores["base"]:
                    selected = "qwen"
            target = folder / (method + ".txt")
            target.write_text(texts[selected] + "\n", encoding="utf-8")
            output_hashes[method] = digest(target)
            decisions[method] = {"selected": selected, "scores": scores}
        for name, text in texts.items():
            (folder / (name + ".txt")).write_text(text + "\n", encoding="utf-8")
        record = {"tag": tag, "language": cohort[tag]["language"], "valid_comparison": valid,
                  "frames": frames, "nll": nll, "decisions": decisions,
                  "encoding": {name: {k: v for k, v in value.items() if k != "targets"} for name, value in encoded.items()},
                  "audio_sha256": cohort[tag]["audio_sha"], "emissions_sha256": digest(source),
                  "base_chart_sha256": digest(chart), "qwen_freeze_sha256": digest(qwen_folder / "frozen.json"),
                  "candidate_text_sha256": {name: digest(folder / (name + ".txt")) for name in texts},
                  "output_sha256": output_hashes, "seconds": round(time.monotonic() - started, 3)}
        write_json(folder / "frozen.json", record)
        results.append(record)
        print(json.dumps({"tag": tag, "seconds": record["seconds"], "valid": valid,
                          "selected": {name: value["selected"] for name, value in decisions.items()}}), flush=True)
    write_json(args.output / "frozen.json", {
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "plan_sha256": digest(args.output / "plan.json"),
        "cohort_size": 40, "present": len(results), "missing": 40 - len(results), "reference_text_read": False,
        "predictions": {r["tag"]: digest(args.output / r["tag"] / "frozen.json") for r in results},
    })


def evaluate(args):
    from karaoke.generation_metrics import TOKEN, compare_words, extract

    freeze = json.loads((args.predictions / "frozen.json").read_text(encoding="utf-8"))
    plan = json.loads((args.predictions / "plan.json").read_text(encoding="utf-8"))
    if digest(args.predictions / "plan.json") != freeze["plan_sha256"] or digest(args.identities) != plan["identities_sha256"]:
        raise ValueError("Frozen plan or identities changed")
    identities = {r["tag"]: r for r in json.loads(args.identities.read_text(encoding="utf-8"))}
    corpus = {r["tag"]: r for group in json.loads(args.corpus.read_text(encoding="utf-8")).values() for r in group}
    if len(identities) != 40 or freeze["cohort_size"] != 40:
        raise ValueError("Expected denominator 40")
    rows = []
    for tag, identity in sorted(identities.items()):
        if tag not in freeze["predictions"]:
            rows.append({"tag": tag, "status": "missing"})
            continue
        folder = args.predictions / tag
        if digest(folder / "frozen.json") != freeze["predictions"][tag]:
            raise ValueError("Changed candidate freeze")
        record = json.loads((folder / "frozen.json").read_text(encoding="utf-8"))
        reference = Path(corpus[tag]["reference"])
        if digest(reference) != identity["chart_sha"] or corpus[tag]["audio_sha"] != record["audio_sha256"]:
            raise ValueError("Unexpected reference recording")
        _, gold = extract(reference)
        measured = {}
        for method in ("base", "qwen", *METHODS):
            path = folder / (method + ".txt")
            expected = (record["candidate_text_sha256"] if method in ("base", "qwen") else record["output_sha256"])[method]
            if digest(path) != expected:
                raise ValueError("Changed frozen words")
            words = [(m.group(), 0.0) for m in TOKEN.finditer(unicodedata.normalize("NFKC", path.read_text(encoding="utf-8").casefold()))]
            result = compare_words(gold, words)
            measured[method] = {"wer": float(result["wer"]), "edits": int(result["edits"]), "words": len(words)}
        rows.append({"tag": tag, "status": "measured", "language": identity["language"],
                     "valid_comparison": record["valid_comparison"], "metrics": measured, "decisions": record["decisions"]})
    summaries = {}
    for language in ("all", "es", "en"):
        subset = [r for r in rows if r["status"] == "measured" and (language == "all" or r["language"] == language)]
        summaries[language] = {}
        for method in ("base", "qwen", *METHODS):
            values = [r["metrics"][method]["wer"] for r in subset]
            deltas = [r["metrics"][method]["wer"] - r["metrics"]["base"]["wer"] for r in subset]
            summaries[language][method] = {"measured": len(values), "median_wer": float(np.median(values)) if values else None,
                "improved": sum(d < 0 for d in deltas), "regressed": sum(d > 0 for d in deltas), "equal": sum(d == 0 for d in deltas),
                "at_most_5_percent": sum(v <= .05 for v in values), "at_most_1_percent": sum(v <= .01 for v in values),
                "selected_qwen": sum(r["decisions"].get(method, {}).get("selected") == "qwen" for r in subset)}
    if args.output.exists():
        raise ValueError("Never overwrite an evaluation")
    write_json(args.output, {"scope": "Words only; complete development recordings; no timing or melody claim",
                            "prediction_freeze_sha256": digest(args.predictions / "frozen.json"),
                            "cohort_size": 40, "missing": sum(r["status"] == "missing" for r in rows),
                            "summaries": summaries, "rows": rows})
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("selftest")
    generation = commands.add_parser("generate")
    for name in ("identities", "charts", "qwen", "emissions", "output"):
        generation.add_argument("--" + name, type=Path, required=True)
    generation.add_argument("--ids", nargs="+")
    evaluation = commands.add_parser("evaluate")
    for name in ("identities", "corpus", "predictions", "output"):
        evaluation.add_argument("--" + name, type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "selftest":
        print(json.dumps(selftest(), indent=2))
    else:
        (generate if arguments.command == "generate" else evaluate)(arguments)
