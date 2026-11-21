"""Attribute frozen GAME/join timing differences without inference or new predictions.

Replay only the two existing conditioned-GAME pilot cases. Reference charts enter
the subsequent diagnostic partition, never transform or its input reconstruction.
The cached GAME events already include window ownership and overlap resolution;
they are not the original per-window neural outputs or the original 40-song traces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke import generation_worker as worker
from karaoke.generation_metrics import extract
from melody_compare import transform


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def painted(intervals, mids):
    result = np.full(len(mids), -1, dtype=np.int16)
    for start, end, pitch in intervals:
        if pitch is not None:
            result[(mids >= start) & (mids < end)] = int(pitch) % 12
    return result


def partition(raw, joined, serialized, gold):
    boundaries = sorted({float(t) for notes in (raw, joined, serialized, gold)
                         for start, end, _ in notes for t in (start, end)})
    widths = np.diff(boundaries)
    mids = (np.asarray(boundaries[:-1]) + np.asarray(boundaries[1:])) / 2
    r, j, q, g = [painted(notes, mids) for notes in (raw, joined, serialized, gold)]

    def seconds(mask):
        return float(widths[mask].sum())

    error = (q >= 0) & (q != g)
    bridge_seconds, bridge_count = 0.0, 0
    for previous, following in zip(raw, raw[1:]):
        gap = following[0] - previous[1]
        if previous[2] == following[2] and 1e-6 < gap < .045:
            covered = seconds((mids >= previous[1]) & (mids < following[0])
                              & (j == int(previous[2]) % 12))
            if covered > 1e-9:
                bridge_count += 1
                bridge_seconds += covered
    added = seconds((j >= 0) & (r < 0))
    assert abs(added - bridge_seconds) < 1e-6, (added, bridge_seconds)
    buckets = {
        "same_class_already_in_cached_game": seconds(error & (r == q)),
        "no_cached_game_event": seconds(error & (r < 0)),
        "different_class_in_cached_game": seconds(error & (r >= 0) & (r != q)),
    }
    assert abs(sum(buckets.values()) - seconds(error)) < 1e-7
    return {
        "raw_scored_seconds": seconds(r >= 0),
        "joined_scored_seconds": seconds(j >= 0),
        "serialized_scored_seconds": seconds(q >= 0),
        "raw_error_seconds": seconds((r >= 0) & (r != g)),
        "serialized_error_seconds": seconds(error),
        "serialized_error_partition_seconds": buckets,
        "serialized_error_without_scored_reference_seconds": seconds(error & (g < 0)),
        "joined_added_union_seconds": added,
        "joined_removed_union_seconds": seconds((r >= 0) & (j < 0)),
        "joined_changed_class_seconds": seconds((r >= 0) & (j >= 0) & (r != j)),
        "same_pitch_gaps_bridged_count": bridge_count,
        "same_pitch_gaps_bridged_seconds": bridge_seconds,
        "serialization_added_union_seconds": seconds((q >= 0) & (j < 0)),
        "serialization_removed_union_seconds": seconds((j >= 0) & (q < 0)),
        "serialization_changed_class_seconds": seconds((q >= 0) & (j >= 0) & (q != j)),
    }


def diagnose(output):
    identities = {r["tag"]: r for r in load("docs/validation/generacion-muestra.json")}
    charts = load("build/generation-v3/lyrics/final/charts.json")
    corpus = {r["tag"]: r for rows in load("build/generation-v2/corpus.json").values() for r in rows}
    source = Path("build/generation-next/conditioned")
    results = []
    for tag in ("bad-bunny-amorfoda", "northern-star"):
        for mode in ("free", "syllables", "spans", "words"):
            folder = source / mode / tag
            freeze = load(folder / "frozen.json")
            event_data = load(folder / "events.json")
            assert event_data["provenance"] == freeze["provenance"]
            assert digest(charts[tag]) == freeze["provenance"]["baseline_sha256"]
            raw = event_data["events"]
            assert all(a < b for a, b, _ in raw)
            assert all(previous[1] <= following[0] + 1e-8 for previous, following in zip(raw, raw[1:]))
            captured = {}
            original = worker.join_syllables_and_notes

            def capture(syllables, events, pitch, duration):
                notes = original(syllables, events, pitch, duration)
                captured["notes"] = notes
                captured["syllables"] = len(syllables)
                return notes

            worker.join_syllables_and_notes = capture
            try:
                replay = transform(Path(charts[tag]), raw, freeze["duration_s"])
            finally:
                worker.join_syllables_and_notes = original
            for method, text in replay.items():
                assert hashlib.sha256(text.encode("utf-8")).hexdigest() == freeze["charts"][method]
                assert digest(folder / (method + ".txt")) == freeze["charts"][method]
            joined = [(n["start"], n["end"], n["pitch"]) for n in captured["notes"]]
            serialized = [(n.start, n.end, n.pitch) for n in extract(folder / "events.txt")[0]]
            # Gold is read only after exact frozen-output replay has completed.
            reference = Path(corpus[tag]["reference"])
            assert digest(reference) == identities[tag]["chart_sha"]
            gold = [(n.start, n.end, n.pitch) for n in extract(reference)[0]]
            results.append({
                "tag": tag, "mode": mode, "exact_frozen_replay": True,
                "source_events_sha256": digest(folder / "events.json"),
                "source_freeze_sha256": digest(folder / "frozen.json"),
                "baseline_sha256": digest(charts[tag]), "reference_sha256": digest(reference),
                "source_events": len(raw), "reconstructed_syllables": captured["syllables"],
                "joined_notes": len(joined), "serialized_notes": len(serialized),
                **partition(raw, joined, serialized, gold),
            })
    result = {
        "scope": "Diagnostic replay of two existing development cases, all four frozen GAME modes; no new inference, predictors or metric changes.",
        "limits": ["Cached events already include the 12-second-window overlap resolver.",
                   "Syllables are reconstructed from a post-GAME chart, not original CTC traces.",
                   "No conclusion about the missing original 40-song GAME traces.",
                   "A reference gap is not proof of acoustic silence.",
                   "Continuous interval accounting is diagnostic and does not replace admission metrics."],
        "script_sha256": digest(__file__),
        "worker_sha256": digest(worker.__file__),
        "transform_sha256": digest(Path(__file__).with_name("melody_compare.py")),
        "rows": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    for row in results:
        print(json.dumps({k: row[k] for k in ("tag", "mode", "raw_scored_seconds",
            "joined_added_union_seconds", "same_pitch_gaps_bridged_count", "serialized_error_seconds",
            "serialized_error_partition_seconds")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path("build/generation-next/error-diagnosis/game-join-diagnosis.json"))
    diagnose(parser.parse_args().output)
