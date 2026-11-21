"""Combine independently frozen musical pitches and word timings, without opening a human chart."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from timing_predict import parse, serialize


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def combine(base, pitches, timing):
    headers, original = parse(base)
    _, tuned = parse(pitches)
    _, aligned = parse(timing)
    result = []
    for seed, pitch, clock in zip(original, tuned, aligned, strict=True):
        if (seed.kind, seed.lyric, seed.line) != (pitch.kind, pitch.lyric, pitch.line):
            raise ValueError("Pitch model changed lexical content or note type")
        if (seed.start, seed.end) != (pitch.start, pitch.end):
            raise ValueError("Pitch model also changed an attack or a duration")
        if (seed.kind, seed.lyric, seed.line, seed.pitch) != (
            clock.kind,
            clock.lyric,
            clock.line,
            clock.pitch,
        ):
            raise ValueError("Time model changed the melody or lexical content")
        result.append(replace(clock, pitch=pitch.pitch))
    return serialize(headers, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("charts", type=Path)
    parser.add_argument("consensus", type=Path)
    parser.add_argument("qwen", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for tag, filename in json.loads(args.charts.read_text()).items():
        base = Path(filename)
        pitches = args.consensus / tag / "consensus.txt"
        timing = args.qwen / tag / "qwen-consenso.txt"
        certificate = args.consensus / tag / "frozen.json"
        if not (certificate.is_file() and (args.qwen / tag / "hashes.json").is_file()):
            continue
        frozen = json.loads(certificate.read_text())
        if (
            digest(base) != frozen["baseline_sha256"]
            or digest(pitches) != frozen["charts"]["consensus"]
        ):
            raise ValueError(f"Pitch verifier rejected {tag}")
        if (
            digest(timing)
            != json.loads((timing.parent / "hashes.json").read_text())["qwen-consenso"]
        ):
            raise ValueError(f"Timing verifier rejected {tag}")
        folder = args.output / tag
        folder.mkdir(exist_ok=True, parents=True)
        target = folder / "consenso-completo.txt"
        target.write_text(combine(base, pitches, timing), encoding="utf-8")
        (folder / "hashes.json").write_text(json.dumps({"consenso-completo": digest(target)}))
        print(tag, flush=True)


if __name__ == "__main__":
    main()
