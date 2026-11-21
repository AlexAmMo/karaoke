"""Fetch the exact public corpus recordings into private scratch space for one validation shard."""

import argparse
import hashlib
import json
import shutil
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from karaoke.official_packs import download_starter  # noqa: E402
from karaoke.songs import validate  # noqa: E402


class Progress:
    def __init__(self, directory):
        self.directory = directory

    def check_space(self):
        if shutil.disk_usage(self.directory).free < 1_000_000_000:
            raise ValueError("Insufficient scratch disk space")

    def write(self, *args):
        pass


def sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def pcm_sha(path):
    # MP3 metadata can vary by FFmpeg build; compare every decoded stereo sample
    # at 44.1 kHz/16-bit before accepting any differently encoded input.
    digest = hashlib.sha256()
    command = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-f",
        "s16le",
        "-c:a",
        "pcm_s16le",
        "-",
    ]
    with subprocess.Popen(command, stdout=subprocess.PIPE) as decoder:
        for block in iter(lambda: decoder.stdout.read(1048576), b""):
            digest.update(block)
        if decoder.wait():
            raise ValueError("Could not verify the decoded recording")
    return digest.hexdigest()


def build(args):
    args.scratch.mkdir(exist_ok=True, parents=True)
    items = [r for r in json.loads(args.corpus.read_text()) if r["language"] == args.language]
    if args.shards < 1 or not 0 <= args.shard < args.shards:
        raise ValueError("Invalid shard")
    result = []
    for case in items[args.shard :: args.shards]:
        key = case["tag"]
        if Path(key).name != key:
            raise ValueError("Invalid recording ID")
        if case["source"] == "deluxe":
            chart = download_starter(key, args.scratch, Progress(args.scratch))
            audio = Path(validate(chart)["audio"])
        else:
            from karaoke import acoustic, allkaraoke

            folder = args.scratch / key
            folder.mkdir(exist_ok=True)
            chart, audio = allkaraoke.prepare_review(
                {**case, "source": "allkaraoke:" + key, "tracks": 1}, folder, lambda _: None
            )
            acoustic.require_alignment(chart, audio)
        actual_audio = sha(audio)
        if sha(chart) != case["chart_sha"]:
            raise ValueError(f"The frozen chart has changed for {key}")
        if actual_audio != case["audio_sha"] and (
            not case.get("pcm_sha256") or pcm_sha(audio) != case["pcm_sha256"]
        ):
            raise ValueError(f"The frozen recording has changed for {key}")
        case = dict(case, audio_sha=actual_audio)
        result.append({**case, "audio": str(audio.resolve()), "reference": str(chart.resolve())})
    (args.scratch / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("--language", choices=("en", "es"), required=True)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    build(parser.parse_args())
