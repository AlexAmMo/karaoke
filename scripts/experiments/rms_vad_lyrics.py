"""Original RMS segmentation experiment: plans and cuts only, no ASR or models.

Inspired by arXiv:2506.15514v1 II-F. Window, hop, channel energy, padding,
tie-breaking and protected long silences are explicit experimental choices;
this is not an exact reproduction of the paper or an import of its code.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import resource
import sys
import time

import numpy as np
import soundfile as sf


PARAMETERS = {
    "window_seconds": .04, "hop_seconds": .01, "block_seconds": 4,
    "channel_energy": "mean squared amplitude over channels; no phase-cancelling waveform downmix",
    "normalization": "RMS divided by its maximum over this recording; exact zero stays zero",
    "threshold": .1, "threshold_equality": "active",
    "minimum_silence_seconds": 1, "minimum_activity_seconds": 0,
    "padding_seconds": .1, "maximum_segment_seconds": 30,
    "rms_clock": "trailing rectangular window at each hop end, zero before sample zero; final partial hop ends at the last sample",
    "activity_clock": "each score owns its half-open hop bin, including final partial bin",
    "close_gap": "only internal inactive runs strictly shorter than one second",
    "long_silences": "protected barriers; never merge islands across a gap of at least one second",
    "split": "minimum normalized RMS at hop ends in the latter half of the next 30 seconds; last minimum wins",
    "after_split": "adjacent slices share the exact integer cut; no new padding or merging",
    "rounding": "seconds to samples use nearest integer; all slices are half-open sample intervals",
    "asr_enabled": False,
}
PILOT = ("bad-bunny-amorfoda", "fito-paez-11-y-6",
         "jonathan-coulton-mr-fancy-pants", "northern-star")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path):
    return {"path": str(Path(path).resolve()), "sha256": digest(path)}


def check(item):
    if digest(item["path"]) != item["sha256"]:
        raise ValueError(f"Input changed: {item['path']}")
    return Path(item["path"])


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def frame_ends(length, hop):
    return np.minimum(np.arange(1, math.ceil(length / hop) + 1, dtype=np.int64) * hop, length)


def rms_blocks(blocks, length, window, hop):
    """One pass, with only a window of history and compact per-hop output."""
    if min(length, window, hop) <= 0:
        raise ValueError("Positive sample count, window and hop required")
    carry = np.empty(0, dtype=np.float64)
    position, answers = 0, []
    for block in blocks:
        block = np.asarray(block)
        if block.ndim == 1:
            block = block[:, None]
        if block.ndim != 2 or not block.shape[1] or not len(block) or not np.isfinite(block).all():
            raise ValueError("Empty, non-finite or invalid audio block")
        energy = np.mean(np.square(block, dtype=np.float64), axis=1)
        stop = position + len(energy)
        if stop > length:
            raise ValueError("Audio blocks exceed declared sample count")
        history_start = position - len(carry)
        combined = np.concatenate((carry, energy))
        cumulative = np.concatenate(([0.], np.cumsum(combined, dtype=np.float64)))
        ends = np.arange((position // hop + 1) * hop, stop + 1, hop, dtype=np.int64)
        if stop == length and stop % hop:
            ends = np.append(ends, stop)
        starts = np.maximum(0, ends - window)
        if np.any(starts < history_start):
            raise ValueError("Missing RMS history")
        squares = (cumulative[ends - history_start] - cumulative[starts - history_start]) / window
        answers.append(np.sqrt(np.maximum(0, squares)))
        carry = combined[-window:].copy()
        position = stop
    if position != length:
        raise ValueError("Audio blocks do not cover declared sample count")
    rms = np.concatenate(answers)
    if len(rms) != math.ceil(length / hop):
        raise ValueError("RMS frame count does not cover the final partial hop")
    return rms


def intervals(mask, length, hop):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    return [[int(a * hop), min(int(b * hop), length)] for a, b in edges.reshape(-1, 2)]


def segmentation(rms, length, rate):
    hop = round(PARAMETERS["hop_seconds"] * rate)
    silence = round(PARAMETERS["minimum_silence_seconds"] * rate)
    padding = round(PARAMETERS["padding_seconds"] * rate)
    maximum = round(PARAMETERS["maximum_segment_seconds"] * rate)
    if len(rms) != math.ceil(length / hop) or not np.isfinite(rms).all() or np.any(rms < 0):
        raise ValueError("Invalid RMS geometry or values")
    peak = float(np.max(rms))
    scores = rms / peak if peak else np.zeros_like(rms)
    active = intervals(scores >= PARAMETERS["threshold"], length, hop)
    islands = []
    for first, last in active:
        if islands and first - islands[-1][1] < silence:
            islands[-1][1] = last
        else:
            islands.append([first, last])
    barriers = [[a[1], b[0]] for a, b in zip(islands, islands[1:])]
    ends = frame_ends(length, hop)
    segments, forced = [], []
    for owner, (first, last) in enumerate(islands):
        start, stop = max(0, first - padding), min(length, last + padding)
        while stop - start > maximum:
            low = int(np.searchsorted(ends, start + maximum // 2, side="left"))
            high = int(np.searchsorted(ends, start + maximum, side="right"))
            choices = scores[low:high]
            if not len(choices):
                raise ValueError("No legal bounded cut")
            selected = low + int(np.flatnonzero(choices == np.min(choices))[-1])
            cut = int(ends[selected])
            forced.append({"sample": cut, "island": owner, "score": float(scores[selected]),
                           "score_is_active": bool(scores[selected] >= PARAMETERS["threshold"])})
            segments.append({"start_sample": start, "end_sample": cut, "island": owner})
            start = cut
        segments.append({"start_sample": start, "end_sample": stop, "island": owner})
    cursor, excluded = 0, []
    for segment in segments:
        first, last = segment["start_sample"], segment["end_sample"]
        if not 0 <= cursor <= first < last <= length or last - first > maximum:
            raise ValueError("Overlapping, out-of-range or oversized segment")
        if cursor < first:
            excluded.append([cursor, first])
        cursor = last
    if cursor < length:
        excluded.append([cursor, length])
    included_samples = sum(s["end_sample"] - s["start_sample"] for s in segments)
    excluded_samples = sum(b - a for a, b in excluded)
    assert included_samples + excluded_samples == length
    uncovered = 0
    for first, last in active:
        covered = sum(max(0, min(last, s["end_sample"]) - max(first, s["start_sample"])) for s in segments)
        uncovered += last - first - covered
    assert uncovered == 0
    for first, last in barriers:
        assert last - first >= silence
        assert all(not (s["start_sample"] < first and s["end_sample"] > last) for s in segments)
        kept_outside_margins = sum(max(0, min(last - padding, b) - max(first + padding, a))
                                  for a, b in excluded)
        assert kept_outside_margins == max(0, last - first - 2 * padding)
    return {"peak_rms": peak, "zero_energy": peak == 0, "active_intervals": active,
            "closed_islands": islands, "protected_silences": barriers,
            "segments": segments, "forced_cuts": forced, "excluded_intervals": excluded,
            "excluded_reason": "outside retained RMS activity and its declared padding; not proof of absent lyrics",
            "included_samples": included_samples, "excluded_samples": excluded_samples,
            "uncovered_active_samples": uncovered, "sample_partition_verified": True}


def selftest():
    rate, window, hop = 1000, 40, 10
    cases = {}
    for name, signal in {
        "silence": np.zeros((1001, 2)),
        "first_and_last_sample": np.eye(1, 1001, 0).ravel() + np.eye(1, 1001, 1000).ravel(),
        "shorter_than_window": np.ones(7),
        "long_uniform": np.ones(61007),
        "opposite_phase_stereo": np.tile([1., -1.], (1001, 1)),
    }.items():
        sample = signal if signal.ndim == 2 else signal[:, None]
        before = rms_blocks([sample[i:i + 73] for i in range(0, len(sample), 73)], len(sample), window, hop)
        after = rms_blocks([sample[i:i + 4000] for i in range(0, len(sample), 4000)], len(sample), window, hop)
        direct = np.array([np.sqrt(np.square(sample[max(0, e - window):e], dtype=np.float64).sum()
                                   / (window * sample.shape[1])) for e in frame_ends(len(sample), hop)])
        assert np.allclose(before, direct, rtol=1e-12, atol=1e-12)
        assert np.allclose(after, direct, rtol=1e-12, atol=1e-12)
        result = segmentation(before, len(sample), rate)
        assert result["sample_partition_verified"] and result["uncovered_active_samples"] == 0
        cases[name] = True
        if name == "silence":
            assert not result["segments"] and result["excluded_samples"] == len(sample)
        if name == "first_and_last_sample":
            assert result["segments"][0]["start_sample"] == 0 and result["segments"][-1]["end_sample"] == len(sample)
        if name == "long_uniform":
            assert [r["sample"] for r in result["forced_cuts"]] == [30000, 60000]
            assert result["included_samples"] == len(sample)
    for gap_frames in (99, 100, 101):
        scores = np.r_[np.ones(100), np.zeros(gap_frames), np.ones(100)]
        result = segmentation(scores, len(scores) * hop, rate)
        assert len(result["closed_islands"]) == (1 if gap_frames == 99 else 2)
        assert len(result["protected_silences"]) == (0 if gap_frames == 99 else 1)
        cases[f"silence_{gap_frames / 100:g}s_not_remerged"] = True
    scores = np.r_[np.ones(15), np.zeros(150), np.ones(15)]
    scaled = segmentation(scores * .0001, len(scores) * hop, rate)
    assert segmentation(scores, len(scores) * hop, rate) == (scaled | {"peak_rms": 1.})
    cases["gain_invariance"] = True
    assert segmentation(np.array([1., .1, .09]), 30, rate)["active_intervals"] == [[0, 20]]
    cases["threshold_equality_active"] = True
    valley = np.ones(6100)
    valley[2000:2002] = .2
    bounded = segmentation(valley, len(valley) * hop, rate)
    assert bounded["forced_cuts"][0]["sample"] == 20020
    assert bounded["segments"][0]["end_sample"] == bounded["segments"][1]["start_sample"]
    assert bounded["included_samples"] == len(valley) * hop
    cases["latest_minimum_and_exact_boundary"] = True
    for bad in (np.array([np.nan]), np.array([np.inf])):
        try:
            rms_blocks([bad], 1, window, hop)
        except ValueError:
            pass
        else:
            raise AssertionError("Non-finite audio accepted")
    cases["nonfinite_rejected"] = True
    assert "torch" not in sys.modules and "faster_whisper" not in sys.modules
    return cases


def plan(args):
    if args.output.exists():
        raise ValueError("Use a new output directory")
    identities = {r["tag"]: r for r in load(args.identities)}
    provenance = load(args.provenance)
    previous = {r["id"]: r for r in provenance["entries"]}
    stems = load(args.stems)
    if len(identities) != 40 or set(identities) != set(previous) or set(identities) != set(stems):
        raise ValueError("Expected the fixed forty-recording cohort")
    entries = []
    for tag, identity in sorted(identities.items()):
        source = previous[tag]
        audio, stem = check(source["audio"]), check(source["stem"])
        if source["audio"]["sha256"] != identity["audio_sha"] or str(stem) != stems[tag]:
            raise ValueError("Master or stem identity differs")
        check(source["stem_link"]["file"])
        info = sf.info(stem)
        if info.samplerate != 44100 or not info.frames or abs(info.duration - source["duration_seconds"]) > .12:
            raise ValueError("Unexpected source clock")
        entries.append({"id": tag, "language": identity["language"], "audio": record(audio),
            "stem": record(stem), "stem_link": source["stem_link"], "sample_rate": info.samplerate,
            "samples": info.frames, "channels": info.channels,
            "master_duration_seconds": source["duration_seconds"], "stem_duration_seconds": info.duration,
            "window_samples": 1764, "hop_samples": 441})
    primary_sources = load(args.sources)
    for item in primary_sources["sources"]:
        if digest(args.sources.parent / item["file"]) != item["sha256"]:
            raise ValueError("Primary-source snapshot changed")
    output = {"created_utc": datetime.now(timezone.utc).isoformat(), "cohort_size": 40,
        "references_opened": False, "inference_implemented": False, "parameters": PARAMETERS,
        "implementation": record(__file__), "identities": record(args.identities),
        "source_provenance": record(args.provenance), "stems": record(args.stems),
        "primary_sources": record(args.sources), "numpy_version": np.__version__,
        "soundfile_version": sf.__version__, "selftest": selftest(), "entries": entries,
        "future_asr": {"status": "not implemented or executed by this command", "pilot": PILOT,
            "arms": ["mix-native", "mix-rms", "vocals-native", "vocals-rms"],
            "same_vocal_cuts_for_both_audio_sources": True, "expected_pilot_transcriptions": 16,
            "clock": "original absolute time, no fitted shift or stretched clock",
            "text": "preserve all raw words and repetitions; no string deduplication",
            "boundary_policy": "concatenate ordered nonoverlapping inputs; keep and flag crossing timestamps rather than silently discarding words",
            "decoding": "existing Turbo CPU int8, three CPU threads, batch one, beam five, word timestamps, fixed language, VAD disabled and previous-text conditioning disabled"}}
    save(args.output / "plan.json", output)
    print(json.dumps({"planned": len(entries), "plan_sha256": digest(args.output / "plan.json"),
                      "source_bytes": sum(Path(e["stem"]["path"]).stat().st_size for e in entries)}))


def cuts(args):
    settings = load(args.output / "plan.json")
    check(settings["implementation"])
    if settings["parameters"] != PARAMETERS:
        raise ValueError("Parameters changed after plan")
    if (args.output / "frozen.json").exists():
        raise ValueError("Cuts are already frozen")
    started = time.monotonic()
    rows = []
    for entry in settings["entries"]:
        before = time.monotonic()
        source = check(entry["stem"])
        with sf.SoundFile(source) as stream:
            if (len(stream), stream.samplerate, stream.channels) != (entry["samples"], entry["sample_rate"], entry["channels"]):
                raise ValueError("Source geometry changed")
            blocks = stream.blocks(blocksize=4 * stream.samplerate, dtype="float32", always_2d=True)
            rms = rms_blocks(blocks, len(stream), entry["window_samples"], entry["hop_samples"])
        result = segmentation(rms, entry["samples"], entry["sample_rate"])
        folder = args.output / entry["id"]
        folder.mkdir()
        with (folder / "rms.npy").open("xb") as output:
            np.save(output, rms, allow_pickle=False)
        save(folder / "cuts.json", {"id": entry["id"], "stem_sha256": entry["stem"]["sha256"],
            "audio_sha256": entry["audio"]["sha256"], "samples": entry["samples"],
            "sample_rate": entry["sample_rate"], "hop_samples": entry["hop_samples"],
            "window_samples": entry["window_samples"], "rms_sha256": digest(folder / "rms.npy"), **result})
        rows.append({"id": entry["id"], "language": entry["language"], "samples": entry["samples"],
            "sample_rate": entry["sample_rate"], "rms_frames": len(rms), "segments": len(result["segments"]),
            "forced_cuts": len(result["forced_cuts"]),
            "forced_active_cuts": sum(c["score_is_active"] for c in result["forced_cuts"]),
            "protected_silences": len(result["protected_silences"]),
            "included_samples": result["included_samples"], "excluded_samples": result["excluded_samples"],
            "zero_energy": result["zero_energy"], "cuts_sha256": digest(folder / "cuts.json"),
            "rms_sha256": digest(folder / "rms.npy"), "seconds": time.monotonic() - before})
    assert "torch" not in sys.modules and "faster_whisper" not in sys.modules
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    save(args.output / "frozen.json", {"frozen_utc": datetime.now(timezone.utc).isoformat(),
        "plan_sha256": digest(args.output / "plan.json"), "cohort_size": 40, "present": len(rows),
        "missing": 40 - len(rows), "references_opened": False, "asr_executed": False,
        "wall_seconds": time.monotonic() - started,
        "max_resident_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "memory_source": "resource.getrusage(RUSAGE_SELF).ru_maxrss; macOS bytes, Linux KiB converted",
        "rows": rows})
    print(json.dumps({"songs": len(rows), "segments": sum(r["segments"] for r in rows),
        "wall_seconds": time.monotonic() - started,
        "max_resident_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "freeze_sha256": digest(args.output / "frozen.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("selftest", "plan", "cuts"))
    for name, default in {
        "output": "build/generation-next/rms-vad/v1",
        "identities": "docs/validation/generacion-muestra.json",
        "stems": "build/generation-v3/shared/stems.json",
        "provenance": "build/generation-next/consensus-releases/v2/plan.json",
        "sources": "build/generation-next/rms-vad/sources/sources.json",
    }.items():
        parser.add_argument("--" + name, type=Path, default=Path(default))
    args = parser.parse_args()
    if args.command == "selftest":
        print(json.dumps(selftest(), indent=2))
    else:
        {"plan": plan, "cuts": cuts}[args.command](args)
