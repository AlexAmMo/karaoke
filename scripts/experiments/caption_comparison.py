"""Compare the authored caption resolver with the frozen full-song baseline; export only metrics."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_assets.captions import matching_lyrics  # noqa: E402
from karaoke.generation_metrics import passes, score  # noqa: E402


def audit(args):
    rows = sum(json.loads(args.corpus.read_text()).values(), [])
    identities = {r["tag"]: r for r in json.loads(args.manifest.read_text())}
    rows = [r for r in rows if r["tag"] in identities]
    charts = json.loads(args.charts.read_text())
    if (
        len(charts) != 40
        or set(charts) != set(identities)
        or set(charts) != {r["tag"] for r in rows}
    ):
        raise ValueError("Expected the same 40 songs in every input.")
    captions, words = {}, {}
    for row in rows:
        tag = row["tag"]
        if row["language"] == "es":
            data = json.loads((args.captions / f"{tag}.json").read_text())
            if "error" in data:
                raise ValueError(f"Missing caption lookup for {tag}")
            tracks = [t for t in data["tracks"] if t["video_id"] == identities[tag]["video_id"]]
            if tracks:
                captions[tag] = tracks
            words[tag] = json.loads((args.transcripts / tag / "acoustics.json").read_text())[
                "words"
            ]
    controls = []
    for tag, tracks in captions.items():
        for other, transcript in words.items():
            if other != tag:
                matched = matching_lyrics(tracks, transcript, "es") is not None
                controls.append(dict(source=tag, test=other, accepted=matched))
        for delay in (-6, 6):
            shifted = [
                {**t, "cues": [[s + delay, e + delay, w] for s, e, w in t["cues"]]} for t in tracks
            ]
            controls.append(
                dict(
                    source=tag,
                    test=f"shift_{delay}s",
                    accepted=matching_lyrics(shifted, words[tag], "es") is not None,
                )
            )
    outcomes = []
    for row in sorted(rows, key=lambda r: r["tag"]):
        tag = row["tag"]
        before = Path(charts[tag])
        chosen = matching_lyrics(captions[tag], words[tag], "es") if tag in captions else None
        revised = bool(chosen and "variant_agreement" in chosen[1])
        after = args.regenerated / tag / "draft.txt" if revised else before
        if not after.is_file():
            raise ValueError(f"Missing new prediction for {tag}")
        reference = Path(row["reference"])
        if hashlib.sha256(reference.read_bytes()).hexdigest() != identities[tag]["chart_sha"]:
            raise ValueError(f"Reference mismatch for {tag}")
        for name, pred in (("base", before), ("subtitulos", after)):
            metrics = score(reference, pred, 0, row["duration"], False)
            outcomes.append(
                dict(
                    id=tag,
                    language=row["language"],
                    method=name,
                    prediction_sha256=hashlib.sha256(pred.read_bytes()).hexdigest(),
                    recording_sha256=identities[tag]["audio_sha"],
                    authored_caption=bool(chosen),
                    relaxed_spelling=revised,
                    wer=metrics["wer"],
                    word_p90_s=metrics["word_mae_p50_p90_s"][1],
                    pitch=metrics["correct_class_all"],
                    attacks=metrics["onset_pitch_f1_100ms"],
                    passes=passes(metrics),
                )
            )
    for path, data in ((args.out, outcomes), (args.controls, controls)):
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("docs/validation/generacion-muestra.json")
    )
    for name in ("corpus", "charts", "captions", "transcripts", "regenerated", "out", "controls"):
        parser.add_argument("--" + name, type=Path, required=True)
    audit(parser.parse_args())
