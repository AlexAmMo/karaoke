"""Cache beat locations on the exact full mixture without consulting a chart.

Run with Beat This! installed and its final0 checkpoint downloaded locally.
The original recordings and intermediate files stay in a private directory.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import torch
from beat_this.inference import Audio2Beats


def decode(media):
    pcm = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(media),
            "-map",
            "0:a:0",
            "-vn",
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            "22050",
            "-",
        ]
    )
    return np.frombuffer(pcm, dtype="<f4").copy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--device", choices=["cpu", "mps", "cuda"], default="cpu")
    parser.add_argument(
        "--cohort",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "docs/validation/generacion-muestra.json",
    )
    args = parser.parse_args()
    tracks = json.loads(args.corpus.read_text())
    tracks = (
        [r for values in tracks.values() for r in values] if isinstance(tracks, dict) else tracks
    )
    selected = {row["tag"]: row["audio_sha"] for row in json.loads(args.cohort.read_text())}
    tracks = [r for r in tracks if r["tag"] in selected]
    if {r["tag"]: r["audio_sha"] for r in tracks} != selected:
        raise ValueError("Missing or changed frozen recordings")
    model_hash = hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()
    torch.set_num_threads(2)
    model = Audio2Beats(str(args.checkpoint), device=args.device, dbn=False)
    args.output.mkdir(exist_ok=True, parents=True)
    for song in tracks:
        target = args.output / (song["tag"] + ".json")
        audio = Path(song["audio"])
        audio_hash = hashlib.sha256(audio.read_bytes()).hexdigest()
        if song["audio_sha"] != audio_hash:
            raise ValueError(f"Different recording for {song['tag']}")
        if target.exists():
            existing = json.loads(target.read_text())
            if (existing["audio_sha256"], existing["model_sha256"]) == (audio_hash, model_hash):
                continue
        with torch.inference_mode():
            beats, downbeats = model(decode(audio), 22050)
        value = dict(
            id=song["tag"],
            audio_sha256=audio_hash,
            model_sha256=model_hash,
            beats=np.asarray(beats).tolist(),
            downbeats=np.asarray(downbeats).tolist(),
        )
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(value))
        tmp.replace(target)
        print(song["tag"], len(beats), flush=True)


if __name__ == "__main__":
    main()
