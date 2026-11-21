"""Exercise the actual admission path on exactly identified videos and duration-matched negatives."""

import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from karaoke.generation_verification import verify_generated  # noqa: E402
from karaoke.songs import duration, read_chart  # noqa: E402


def run(args):
    rows = {r["tag"]: r for group in json.loads(args.corpus.read_text()).values() for r in group}
    ids = json.loads(args.manifest.read_text())
    charts = json.loads(args.charts.read_text())
    tested = []
    with tempfile.TemporaryDirectory(prefix="karaoke-verification-test-") as tmp:
        temp = Path(tmp)

        def verify(tag, case, chart, media, video):
            result = verify_generated(chart, media, duration(media), video, args.cache)
            tested.append(
                dict(
                    id=tag,
                    case=case,
                    video_id=video,
                    accepted=bool(result),
                    reference_sha256=result["reference_sha256"] if result else "",
                )
            )
            return result

        for item in ids:
            tag, video = item["tag"], item.get("video_id")
            if not video:
                continue
            audio, predicted = Path(rows[tag]["audio"]), Path(charts[tag])
            if not verify(tag, "exact", predicted, audio, video):
                continue
            text = read_chart(predicted)[0]
            for case, content in (
                ("chart_late_350ms", re.sub(r"(?m)^#GAP:.*$", "#GAP:350", text)),
                (
                    "target_up_two_semitones",
                    re.sub(
                        r"(?m)^([:*] -?\d+ \d+ )(-?\d+)", lambda m: m[1] + str(int(m[2]) + 2), text
                    ),
                ),
            ):
                chart = temp / (case + ".txt")
                chart.write_text(content, encoding="utf-8")
                verify(tag, case, chart, audio, video)
            others = [r for r in ids if r.get("video_id") and r["tag"] != tag]
            other = min(
                others, key=lambda i: abs(rows[i["tag"]]["duration"] - rows[tag]["duration"])
            )
            verify(tag, "other_video", predicted, audio, other["video_id"])
            for case, source, filters in (
                ("same_recording_late_400ms", audio, "adelay=400:all=1,apad"),
                ("different_vocals_same_duration", Path(rows[other["tag"]]["audio"]), "apad"),
            ):
                substitute = temp / (case + ".wav")
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-v",
                        "error",
                        "-i",
                        str(source),
                        "-af",
                        filters,
                        "-t",
                        str(duration(audio)),
                        "-c:a",
                        "pcm_s16le",
                        str(substitute),
                    ],
                    check=True,
                )
                verify(tag, case, predicted, substitute, video)
            verify(tag, "unknown_video", predicted, audio, "abcdefghijk")
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(tested[0]))
        writer.writeheader()
        writer.writerows(tested)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, default=Path("docs/validation/generacion-muestra.json"))
    for name in ("charts", "corpus", "cache", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    run(p.parse_args())
