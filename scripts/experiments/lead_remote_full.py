"""Compute paired models on the original public recording inside the worker; export only numeric events."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import types

import soundfile as sf

from lead_mdx import open_model, separate
from lead_separation import separate_center, digest
from melody_transcribe import MODEL_SHA, some_predictor, infer
from lead_fcpe import contours, MODEL_SHA as FCPE_SHA
import numpy as np
import onnxruntime as ort

root = Path(os.environ["RUNNER_TEMP"])
out = root/"export"
meta=json.loads((out/"provenance.json").read_text())
wave=out/"vocals.wav"
assert digest(wave) == meta["stem_sha256"]
with sf.SoundFile(wave) as f:
    h=hashlib.sha256()
    for chunk in f.blocks(blocksize=32768,dtype="float32",always_2d=True):
        h.update(chunk.astype("<f4",copy=False).tobytes())
    meta["stem_pcm_sha256"]=h.hexdigest()
for name,prep in (("center",lambda dest:separate_center(wave,dest)),("mdx",lambda dest:separate(wave,dest,open_model(root/"uvr.onnx",3)))):
    start=time.monotonic()
    prep(root/(name+".wav"))
    meta[name+"_seconds"]=round(time.monotonic()-start,3)
some=next((root/"someweights").rglob("model_ckpt_steps_100000_simplified.ckpt"))
assert digest(some)==MODEL_SHA["some"]
predict=some_predictor(types.SimpleNamespace(source=root/"SOME",model=some,threads=3,device="cpu"))
for name,src in (("all_vocals",wave),("center",root/"center.wav"),("mdx",root/"mdx.wav")):
    start=time.monotonic();events=infer(src,predict,18,2)
    payload={"settings":{"some_sha256":MODEL_SHA["some"],"stem_sha256":meta["stem_sha256"],"model":name,"device":"cpu"},
             "events":events,"seconds":round(time.monotonic()-start,3),"separation_s":meta.get(name+"_seconds",0)}
    (out/(name+".json")).write_text(json.dumps(payload))
assert digest(root/"fcpe.onnx")==FCPE_SHA
opts=ort.SessionOptions();opts.intra_op_num_threads=3;opts.inter_op_num_threads=1
model=ort.InferenceSession(str(root/"fcpe.onnx"),sess_options=opts,providers=["CPUExecutionProvider"])
start=time.monotonic()
a,b=contours(wave,model)
np.savez_compressed(out/"observations.npz",raw=a,center=b,source_sha=meta["stem_sha256"],model_sha=FCPE_SHA,
                    seconds=round(time.monotonic()-start,3))
(out/"provenance.json").write_text(json.dumps(meta))
