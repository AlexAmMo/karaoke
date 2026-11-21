"""Check the public source without login; retain only outcomes and numeric effects."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare_generation_validation import pcm_sha, sha
from karaoke.allkaraoke import download_recording
from yt_dlp.utils import DownloadError

root = Path(os.environ["RUNNER_TEMP"])
reports = root / "reports"
reports.mkdir(exist_ok=True)
cases = [r for r in json.loads(Path("docs/validation/generacion-muestra.json").read_text()) if r["language"] == "es"]
statuses = []
selected = []
for case in cases[int(os.environ["SHARD"])::4]:
    d = root / case["tag"]
    d.mkdir()
    entry = {"id": case["tag"], "expected_sha": case["audio_sha"]}
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            audio = download_recording(case, d, lambda _: None)
        actual = sha(audio)
        entry["actual_sha"] = actual
        entry["matches_pcm"] = pcm_sha(audio) == case["pcm_sha256"]
        matched = actual == case["audio_sha"] or entry["matches_pcm"]
        entry["outcome"] = "verified" if matched else "different_master"
        if matched:
            selected.append(dict(tag=case["tag"], audio_sha=actual, audio=str(audio.resolve())))
    except DownloadError as exc:
        message = str(exc).lower()
        entry["outcome"] = "login_required" if ("sign in" in message or "bot" in message) else "provider_unavailable"
    statuses.append(entry)
    print(entry["id"], entry["outcome"], flush=True)
(reports / "availability.json").write_text(json.dumps(statuses))
(root / "verified.json").write_text(json.dumps(selected))
with open(os.environ["GITHUB_ENV"], "a") as f:
    print("HAS_MATCH=" + ("yes" if selected else "no"), file=f)
