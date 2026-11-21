"""Compute the secondary (lead) output of UVR-MDX-NET Karaoke 2 on a verified CC voice."""
import hashlib, json, os, time
from pathlib import Path
from lead_mdx import open_model, separate
def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
root=Path(os.environ["RUNNER_TEMP"])
folder=root/"export"
record=json.loads((folder/"provenance.json").read_text())
wav=folder/"vocals.wav"
assert digest(wav)==record["stem_sha256"]
model=open_model(root/"uvr.onnx",3)
start=time.monotonic()
out=folder/"lead.wav"
separate(wav,out,model)
record.update(separation_s=round(time.monotonic()-start,3),lead_sha256=digest(out), separator="MDX-KARA2")
(folder/"lead.json").write_text(json.dumps(record))
