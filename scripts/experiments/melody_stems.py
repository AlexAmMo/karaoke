"""Prepare stems from the exact benchmark masters; keep private media and path indexes local."""

import argparse
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import soundfile as sf
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke import generation_worker as worker  # noqa: E402


def write_index(path, values):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("baseline_scores", type=Path)
    parser.add_argument("separator", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--previous", type=Path, help="Private scratch root from benchmark 0.3")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument(
        "--delegated", type=Path, help="Private list of IDs being separated on a runner"
    )
    parser.add_argument(
        "--incoming", type=Path, help="Directory of authenticated per-ID stem manifests"
    )
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    if worker.digest(args.separator) != worker.SEPARATOR_SHA:
        raise ValueError("Unexpected separator weights")
    selected = {
        r["id"]
        for r in csv.DictReader(args.baseline_scores.open())
        if r["revision"] == "produccion" and r["muestra"] in ("completa-ES", "completa-EN")
    }
    entries = sum(json.loads(args.corpus.read_text()).values(), [])
    rows = {r["tag"]: r for r in entries if r["tag"] in selected}
    if len(selected) != 40 or selected != rows.keys():
        raise ValueError("Corpus IDs differ from the 40 release masters")
    args.output.mkdir(parents=True, exist_ok=True)
    dest = args.output / "stems.json"
    idx = {}
    delegated = set(json.loads(args.delegated.read_text())) if args.delegated else set()
    if not delegated <= selected or delegated and not args.incoming:
        parser.error(
            "Delegated IDs must belong to the release corpus and have an incoming directory"
        )

    # Retain stems only when their earlier benchmark checkpoint identifies the exact audio.
    def eligible(row, voice, checkpoint=None):
        if not voice.is_file() or abs(sf.info(voice).duration - row["duration"]) > 0.12:
            return False
        if checkpoint is not None:
            if not checkpoint.is_file():
                return False
            sig = json.loads(checkpoint.read_text())["signature"]
            if (sig[0], sig[1]) != (row["audio_sha"], 0):
                return False
        return True

    for tag, row in rows.items():
        if worker.digest(Path(row["audio"])) != row["audio_sha"]:
            raise ValueError(f"Changed master: {tag}")
        known = args.output / f"{tag}-{row['audio_sha'][:12]}.wav"
        if eligible(row, known):
            idx[tag] = str(known.resolve())
        if args.previous and tag not in idx:
            for folder in ("full-es-captions", "full-es-extra", "full-es", "reused"):
                base = args.previous / folder / tag
                for name in ("vocals.wav", "voice.wav"):
                    if eligible(row, base / name, base / "acoustics.json"):
                        idx[tag] = str((base / name).resolve())
        # Exact full-song stem previously used for the EN second-listen benchmark.
        if args.previous and tag == "jonathan-coulton-mr-fancy-pants":
            voice = args.previous / "rescue/vocals.wav"
            checkpoint = args.previous / "fullbench" / tag / "acoustics.json"
            if eligible(row, voice, checkpoint):
                idx[tag] = str(voice.resolve())

    def collect_remote():
        for tag in delegated - idx.keys():
            manifest = args.incoming / f"{tag}.json"
            if not manifest.is_file():
                continue
            packet = json.loads(manifest.read_text())
            voice = Path(packet["path"])
            if (
                packet["audio_sha256"] != rows[tag]["audio_sha"]
                or packet["separator_sha256"] != worker.SEPARATOR_SHA
                or worker.digest(voice) != packet["stem_sha256"]
                or not eligible(rows[tag], voice)
            ):
                raise ValueError(f"Failed recording or stem identity check: {tag}")
            idx[tag] = str(voice.resolve())
            print("verified runner", len(idx), tag, flush=True)

    collect_remote()
    write_index(dest, idx)
    print("verified previous stems", len(idx), flush=True)
    pending = {
        lang: sorted(
            (
                t
                for t, r in rows.items()
                if r["language"] == lang and t not in idx and t not in delegated
            ),
            key=lambda t: rows[t]["duration"],
        )
        for lang in ("es", "en")
    }
    while any(pending.values()):
        for group in pending.values():
            if not group:
                continue
            tag = group.pop(0)
            row = rows[tag]
            with tempfile.TemporaryDirectory(dir=args.output) as tmp:
                voice, _ = worker.split_vocals(Path(row["audio"]), Path(tmp), args.separator)
                if not eligible(row, voice):
                    raise ValueError(f"Stem duration changed: {tag}")
                final = args.output / f"{tag}-{row['audio_sha'][:12]}.wav"
                os.replace(voice, final)
            idx[tag] = str(final.resolve())
            collect_remote()
            write_index(dest, idx)
            print("ready", len(idx), tag, flush=True)

    while selected != idx.keys():
        time.sleep(10)
        collect_remote()
        write_index(dest, idx)


if __name__ == "__main__":
    main()
