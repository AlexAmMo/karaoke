"""Freeze text-only changes on a set of predictions without opening evaluation references."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_assets.spelling import restore_spelling  # noqa: E402
from karaoke.songs import read_chart  # noqa: E402


def run(args):
    corpus = {r["tag"]: r for group in json.loads(args.corpus.read_text()).values() for r in group}
    bases = json.loads(args.charts.read_text())
    folders = json.loads(args.baselines.read_text())
    out, counts = {}, {}
    args.output.mkdir(parents=True, exist_ok=True)
    for tag, pred in bases.items():
        row, path = corpus[tag], Path(pred)
        caption_output = args.captions / tag / "draft.txt" if args.captions else None
        if caption_output and caption_output.is_file():
            path = caption_output
        corrections = 0
        if row["language"] == "en":
            stage = Path(folders[tag]).parent
            source = json.loads((stage / "metrics.json").read_text())["lyrics_source"]["kind"]
            if source == "lrclib":
                words = json.loads((stage / "acoustics.json").read_text())["words"]
                text, corrections = restore_spelling(read_chart(path)[0], words, row["title"], "en")
                if corrections:
                    path = args.output / (tag + ".txt")
                    path.write_text(text, encoding="utf-8")
        out[tag] = str(path.resolve())
        counts[tag] = {
            "corrections": corrections,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (args.output / "charts.json").write_text(json.dumps(out))
    (args.output / "corrections.json").write_text(json.dumps(counts, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("corpus", "charts", "baselines", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--captions", type=Path)
    run(p.parse_args())
