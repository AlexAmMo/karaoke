"""Exercise a fresh optional inference environment and the production chart worker."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace

from prepare_generation_validation import Progress

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from karaoke.generation_lab import GenerationLab, WORKER  # noqa: E402
from karaoke.official_packs import download_starter  # noqa: E402
from karaoke.songs import validate  # noqa: E402
from karaoke.store import Store  # noqa: E402


def run(base):
    store = Store(base / "songs.sqlite3")
    lab = GenerationLab(SimpleNamespace(root=base, store=store))
    log = base / "generation.log"
    try:
        uid = lab.enqueue("abcdefghijk", "Mr. Fancy Pants", "Jonathan Coulton", "en", "quality")
        job = lab.row(uid)
        started = time.monotonic()
        lab.bootstrap(job, log)
        if not (lab.root / "env-ready").is_file():
            raise RuntimeError("This test needs to create a new generation environment.")
        setup_seconds = time.monotonic() - started

        original = download_starter(
            "jonathan-coulton-mr-fancy-pants", base / "source", Progress(base)
        )
        mix = base / "mixture.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-ss",
                "22",
                "-t",
                "8",
                "-i",
                str(validate(original)["audio"]),
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=220:duration=8:sample_rate=44100",
                "-filter_complex",
                "[1:a]volume=0.06[backing];[0:a][backing]amix=inputs=2:duration=first:normalize=0",
                "-ar",
                "44100",
                str(mix),
            ],
            check=True,
        )
        command = [lab.python, WORKER, "--cache", lab.models, "--profile", "quality"]
        lab.run([*command, "--prepare"], job, log)
        started = time.monotonic()
        draft = base / "draft"
        lab.run(
            [
                *command,
                "--audio",
                mix,
                "--output",
                draft,
                "--artist",
                "Jonathan Coulton",
                "--title",
                "Mr. Fancy Pants (test excerpt)",
                "--language",
                "en",
            ],
            job,
            log,
        )
        elapsed = time.monotonic() - started
        validate(draft / "song.txt")
        details = json.loads((draft / "generation.json").read_text(encoding="utf-8"))
        if (
            details["notes"] <= 0
            or hashlib.sha256(mix.read_bytes()).hexdigest() != details["input_sha256"]
        ):
            raise RuntimeError("The worker did not produce a chart for the supplied recording.")
        return {
            "system": platform.platform(),
            "machine": platform.machine(),
            "input_seconds": 8,
            "bootstrap_seconds": round(setup_seconds, 1),
            "processing_seconds": round(elapsed, 1),
            "notes": details["notes"],
        }
    except Exception:
        if log.is_file():
            print(log.read_text(encoding="utf-8", errors="replace")[-8000:], file=sys.stderr)
        raise
    finally:
        lab.close()
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Also write metrics to this JSON file")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="karaoke-generation-first-run-") as tmp:
        metrics = json.dumps(run(Path(tmp)), indent=2)
        print(metrics)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(metrics + "\n", encoding="utf-8")
