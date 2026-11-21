"""Isolate the exact public CC master using the frozen CPU separation engine."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import soundfile as sf
import torch
from huggingface_hub import hf_hub_download

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from karaoke import generation_worker as w

root = Path(os.environ['RUNNER_TEMP'])
row, = json.loads((root/'songs/manifest.json').read_text())
pinned = next(r for r in json.loads(Path('docs/validation/generacion-muestra.json').read_text()) if r['tag']==row['tag'])
if row['source']!='deluxe' or row['audio_sha']!=pinned['audio_sha']:
    raise ValueError('Different audio or source')
weights=Path(hf_hub_download(repo_id='adefossez/HTDemucs', filename='955717e8.safetensors', revision=w.SEPARATOR_REV))
if w.digest(weights)!=w.SEPARATOR_SHA: raise ValueError('Changed weights')
torch.set_num_threads(4)
stage=root/'export'
stage.mkdir()
stem,_=w.split_vocals(Path(row['audio']),stage,weights)
final=stage/'vocals.wav'
if stem!=final: shutil.move(stem,final)
info=sf.info(final)
assert info.samplerate==44100 and info.channels==2 and info.subtype=='FLOAT'
manifest=dict(tag=row['tag'], audio_sha256=row['audio_sha'], stem_sha256=w.digest(final), duration=info.duration, frames=info.frames, separator_sha256=w.SEPARATOR_SHA, torch=torch.__version__, source='official-pack')
(stage/'provenance.json').write_text(json.dumps(manifest))
(root/'stems.json').write_text(json.dumps({row['tag']:str(final)}))
