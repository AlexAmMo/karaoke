"""Align a verified CC vocal and return numeric offsets without posting any words."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import zlib
from timing_neural import ForcedAligner, MODEL_SHA, Word, word_offsets

def digest(p):
    with p.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()

tmp = Path(os.environ["RUNNER_TEMP"])
provenance = json.loads((tmp/"export/provenance.json").read_text())
tag = provenance["tag"]
voice = tmp/"export/vocals.wav"
suite = json.loads(zlib.decompress(base64.b85decode(os.environ.pop("PRIVATE_CUES"))))
request = suite[tag]
if (digest(voice),provenance["audio_sha256"]) != (request["stem"], request["audio"]):
    raise ValueError("Incompatible master or numeric vocal signature")
out = {}
model = ForcedAligner(Path(sys.argv[1]), tmp/"qwen.gguf", 4, "cpu")
try:
    for key,entry in request["cases"].items():
        words = [Word(text,owner,start/60,end/60) for text,owner,start,end in entry["w"]]
        shifts, points = word_offsets(model,words,entry["n"],voice)
        out[key] = {"baseline_sha256":entry["base"],"rows":entry["n"],"anchors":points,"offsets":{name:vector.tolist() for name,vector in shifts.items()}}
finally:
    model.close()
(tmp/"numeric-output.json").write_text(json.dumps(dict(id=tag, model_sha256=MODEL_SHA,
    stem_sha256=request["stem"],audio_sha256=request["audio"], native="Linux x86_64 0.8.54 Q4 CPU",cases=out)))
print("Completed",tag,"variants",len(out))
