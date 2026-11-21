"""Predeclare, freeze and evaluate one cached SOME/ROSVOT note-release rule.

No inference, Torch or audio playback. Plan/generate never open reference charts;
evaluate uses the unchanged common evaluator and retains denominator forty.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_metrics import extract
from karaoke.songs import read_chart
import evaluate_generation_candidate as common

MODELS = {
    "some": "aa710fce920b4dae281b0e6cc2acba83345d82ee62d51f7bafeb29636f28f97c",
    "rosvot": "2b034b15126b21bd3f8ba7008f35aca51500f0443e5c36bdc85eba957c02ee38",
}
RULE = {"onset_tolerance_seconds": .08, "end_agreement_seconds": .04,
        "minimum_retained_seconds": .08, "same_class_modulo": 12,
        "matching": "chronological per pitch class; nearest onset then lowest original index; never reuse or move backwards",
        "release": "later of both ends, only when both precede the current end; nearest existing tick, ties to even",
        "trim_cap_seconds": None, "modify_freestyle": False,
        "change_lyrics_pitch_onsets": False, "ambiguous_or_ineligible": "keep original"}
ROW = re.compile(r"^([:*FRG])\s+(-?\d+)\s+(\d+)(\s+-?\d+ .*)$")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def check(item):
    if digest(item["path"]) != item["sha256"]:
        raise ValueError(f"Changed input: {item['path']}")
    return Path(item["path"])


def save(path, value):
    common.write_new(path, value)


def matched_events(notes, events):
    pools = [[(i, event) for i, event in enumerate(events) if int(event[2]) % 12 == p]
             for p in range(12)]
    starts = [[event[0] for _, event in pool] for pool in pools]
    cursors = [0] * 12
    result = {}
    for index, note in enumerate(notes):
        if note.pitch is None:
            continue
        pitch = note.pitch % 12
        pool = pools[pitch]
        left = bisect_left(starts[pitch], note.start - .08, lo=cursors[pitch])
        available = []
        for j in range(left, len(pool)):
            original, event = pool[j]
            if event[0] > note.start + .08:
                break
            available.append((abs(event[0] - note.start), original, j, event))
        if available:
            _, original, j, event = min(available)
            result[index] = (original, event)
            cursors[pitch] = j + 1
    return result


def propose(notes, events, tick, gap):
    matches = {name: matched_events(notes, rows) for name, rows in events.items()}
    edits = {}
    paired = 0
    for index, note in enumerate(notes):
        if index not in matches["some"] or index not in matches["rosvot"]:
            continue
        paired += 1
        ends = [matches[name][index][1][1] for name in MODELS]
        end = max(ends)
        if abs(ends[0] - ends[1]) > .04 or end >= note.end or end - note.start < .08:
            continue
        start_tick = round((note.start - gap) / tick)
        original_end_tick = round((note.end - gap) / tick)
        end_tick = round((end - gap) / tick)
        snapped = gap + end_tick * tick
        if snapped - note.start < .08 or end_tick >= original_end_tick or end_tick <= start_tick:
            continue
        edits[index] = {"end_tick": end_tick, "old_end_seconds": note.end,
                        "new_end_seconds": snapped,
                        "events": {name: matches[name][index][0] for name in MODELS}}
    return edits, paired


def candidate(chart, events):
    text, meta = read_chart(chart)
    notes, _ = extract(chart)
    tick = 15 / float(meta["BPM"].replace(",", "."))
    gap = float(meta.get("GAP", "0").replace(",", ".")) / 1000
    edits, paired = propose(notes, events, tick, gap)
    index, lines = 0, []
    for line in text.splitlines():
        match = ROW.match(line)
        if match:
            if index in edits:
                kind, start, _, remainder = match.groups()
                line = f"{kind} {start} {edits[index]['end_tick'] - int(start)}{remainder}"
            index += 1
        lines.append(line)
    assert index == len(notes)
    return "\n".join(lines) + "\n", {"paired_notes": paired, "changed_notes": len(edits),
        "trimmed_seconds": sum(e["old_end_seconds"] - e["new_end_seconds"] for e in edits.values()),
        "edits": edits}


def selftest():
    from karaoke.generation_metrics import Note

    notes = [Note(0, 1, 0, "test"), Note(1, 2, 0, "word"), Note(2, 3, None, "free")]
    events = {"some": [(0, .40, 60), (1, 1.50, 60), (2, 2.4, 60)],
              "rosvot": [(0, .42, 72), (1, 1.70, 72), (2, 2.42, 72)]}
    edits, paired = propose(notes, events, 1 / 60, 0)
    assert list(edits) == [0] and paired == 2 and edits[0]["end_tick"] == 25
    assert list(matched_events([notes[0], Note(.02, 1, 0, "again")], [(0, .5, 60)])) == [0]
    assert not propose(notes[:1], {k: [(0, .04, 60)] for k in MODELS}, 1 / 60, 0)[0]
    assert not propose(notes[:1], {k: [(0, 1.1, 60)] for k in MODELS}, 1 / 60, 0)[0]
    assert not propose(notes[:1], {k: [(.081, .4, 60)] for k in MODELS}, 1 / 60, 0)[0]
    boundary = [Note(4990 / 60, 4990 / 60 + 9 / 60, 0, "tick")]
    assert not propose(boundary, {k: [(4990 / 60, 83.316, 60)] for k in MODELS}, 1 / 60, 0)[0]
    assert "torch" not in sys.modules
    return {"one_to_one": True, "octave_equivalence": True, "later_agreed_end": True, "same_tick_not_counted": True,
            "short_or_extended_or_unmatched_kept": True, "freestyle_kept": True}


def prepare(args):
    if args.output.exists():
        raise ValueError("Use a new output directory")
    identities = common.unique_rows(load(args.identities), "identities")
    charts, stems = load(args.charts), load(args.stems)
    corpus = common.unique_rows(sum(load(args.corpus).values(), []), "corpus")
    verified = load(args.verified_stems)
    if len(identities) != 40 or set(charts) != set(identities) or set(stems) != set(identities):
        raise ValueError("Expected the fixed complete forty-recording cohort")
    entries = []
    for tag, identity in sorted(identities.items()):
        row = corpus[tag]
        if (row["audio_sha"], row["chart_sha"]) != (identity["audio_sha"], identity["chart_sha"]):
            raise ValueError("Different corpus master/reference identity")
        audio, stem = record(row["audio"]), record(stems[tag])
        if audio["sha256"] != identity["audio_sha"]:
            raise ValueError("Changed actual master")
        metadata = sf.info(stem["path"])
        if metadata.samplerate != 44100 or abs(metadata.duration - row["duration"]) > .12:
            raise ValueError("Stem clock/duration differs from the frozen recording")
        packet = args.incoming / (tag + ".json")
        numeric = args.numeric / tag / "provenance.json"
        if packet.is_file():
            provenance = load(packet)
            if (provenance["audio_sha256"], provenance["stem_sha256"], provenance["path"]) != (
                audio["sha256"], stem["sha256"], stem["path"]):
                raise ValueError("Runner master/stem provenance differs")
            link = {"kind": "runner_master_and_stem", "file": record(packet)}
        elif tag in verified:
            previous = verified[tag]
            if (previous["path"], previous["sha256"]) != (stem["path"], stem["sha256"]):
                raise ValueError("Previously verified local stem changed")
            link = {"kind": "previously_verified_local_stem", "file": record(args.verified_stems),
                    "note": "Historical forty-recording stem preparation links this ID to the master; no invented per-event stem hash."}
        else:
            provenance = load(numeric)
            if (provenance["audio_sha256"], provenance["stem_sha256"]) != (audio["sha256"], stem["sha256"]):
                raise ValueError("No compatible master/stem provenance")
            link = {"kind": "local_master_and_stem", "file": record(numeric)}
        event_files = {}
        for family, model_sha in MODELS.items():
            path = args.events / family / (tag + ".json")
            if not path.is_file():
                continue
            data = load(path)
            settings = data["settings"]
            if (settings["family"], settings["model_sha256"], settings["core"], settings["pad"], settings["source"]) != (
                family, model_sha, 18, 2, stem["path"]):
                raise ValueError(f"Incompatible event model/window/source: {tag}/{family}")
            stated_stem = data.get("provenance", {}).get("stem_sha256")
            if stated_stem and stated_stem != stem["sha256"]:
                raise ValueError("Event provenance names a different stem")
            events = data["events"]
            if not events or any(len(e) != 3 or not all(math.isfinite(v) for v in e)
                or not 0 <= e[0] < e[1] <= metadata.duration + 1e-6 or e[2] != round(e[2]) for e in events):
                raise ValueError("Invalid event units or boundaries")
            if any(a[1] > b[0] + 1e-6 for a, b in zip(events, events[1:])):
                raise ValueError("Events overlap or are not chronological")
            event_files[family] = record(path)
        entries.append({"id": tag, "language": identity["language"], "audio": audio, "stem": stem,
                        "stem_link": link, "duration_seconds": row["duration"], "baseline": record(charts[tag]),
                        "events": event_files, "status": "ready" if len(event_files) == 2 else "missing_events"})
    result = {"created_utc": datetime.now(timezone.utc).isoformat(), "cohort_size": 40,
              "development_cohort": True, "arms": ["baseline", "consensus"], "primary": "consensus",
              "rule": RULE, "models": MODELS, "gold_read": False,
              "script": record(__file__), "selftest": selftest(),
              "predeclared_description": record("docs/validation/generacion-game-ensamblado-2026-11-21.md"),
              "dependencies": [record(p) for p in (common.__file__, "src/karaoke/generation_metrics.py",
                                                  "src/karaoke/generation_verification.py", "src/karaoke/songs.py")],
              "identities": record(args.identities), "corpus": record(args.corpus),
              "charts": record(args.charts), "stems": record(args.stems), "entries": entries}
    args.output.mkdir(parents=True)
    save(args.output / "plan.json", result)
    print(json.dumps({"planned": len(entries), "status": dict(Counter(e["status"] for e in entries)),
                      "stem_links": dict(Counter(e["stem_link"]["kind"] for e in entries)),
                      "plan_sha256": digest(args.output / "plan.json")}))


def generate(args):
    started = time.monotonic()
    plan = load(args.output / "plan.json")
    check(plan["script"])
    for item in plan["dependencies"]:
        check(item)
    baseline, candidates, decisions = {}, {}, []
    for entry in plan["entries"]:
        tag = entry["id"]
        for key in ("audio", "stem", "baseline"):
            check(entry[key])
        check(entry["stem_link"]["file"])
        baseline[tag] = entry["baseline"]["path"]
        if entry["status"] != "ready":
            decisions.append({"id": tag, "status": entry["status"]})
            continue
        events = {name: load(check(item))["events"] for name, item in entry["events"].items()}
        text, decision = candidate(Path(baseline[tag]), events)
        path = args.output / "candidates" / (tag + ".txt")
        path.parent.mkdir(exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
        candidates[tag] = str(path.resolve())
        decisions.append({"id": tag, "status": "generated", "output_sha256": digest(path), **decision})
    save(args.output / "baseline.json", baseline)
    save(args.output / "consensus.json", candidates)
    save(args.output / "decisions.json", {"plan_sha256": digest(args.output / "plan.json"),
        "gold_read": False, "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seconds": time.monotonic() - started, "rows": decisions})
    for arm in plan["arms"]:
        frozen = common.freeze(args.output / (arm + ".json"), check(plan["corpus"]),
                               check(plan["identities"]), "consensus-releases-" + args.output.name + "-" + arm,
                               candidate_revision=plan["script"]["sha256"])
        save(args.output / arm / "frozen.json", frozen)
    save(args.output / "frozen.json", {"cohort_size": 40, "gold_read": False,
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "plan": record(args.output / "plan.json"), "decisions": record(args.output / "decisions.json"),
        "arms": {arm: record(args.output / arm / "frozen.json") for arm in plan["arms"]}})
    print(json.dumps({"generated": len(candidates), "changed_notes": sum(r.get("changed_notes", 0) for r in decisions),
                      "trimmed_seconds": sum(r.get("trimmed_seconds", 0) for r in decisions)}))


def evaluate(args):
    outer = load(args.output / "frozen.json")
    plan = load(check(outer["plan"]))
    check(outer["decisions"])
    for item in plan["dependencies"]:
        check(item)
    for arm, frozen in outer["arms"].items():
        measured = common.evaluate(check(frozen), near_perfect=True)
        save(args.output / arm / "evaluation.json", measured)
        print(json.dumps({"arm": arm, **measured["summary"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("selftest", "plan", "generate", "evaluate"))
    defaults = {"output": "build/generation-next/consensus-releases/v2",
        "identities": "docs/validation/generacion-muestra.json", "charts": "build/generation-v3/lyrics/final/charts.json",
        "stems": "build/generation-v3/shared/stems.json", "corpus": "build/generation-v2/corpus.json",
        "verified-stems": "build/generation-v3/melody/verified-stem-digests.json",
        "incoming": "build/generation-v3/shared/incoming", "numeric": "build/generation-v3/lead/numeric",
        "events": "build/generation-v3/melody"}
    for name, default in defaults.items():
        parser.add_argument("--" + name, type=Path, default=Path(default))
    args = parser.parse_args()
    if args.command == "selftest":
        print(json.dumps(selftest()))
    else:
        {"plan": prepare, "generate": generate, "evaluate": evaluate}[args.command](args)
