"""Bootstrap the optional chart worker as a new desktop installation and run its full CLI."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from karaoke.generation_lab import GenerationLab
from karaoke.official_packs import download_starter
from karaoke.songs import validate
from karaoke.store import Store


class Progress:
    def check_space(self): pass
    def write(self, phase, message): print(phase, message, flush=True)


def main():
    with tempfile.TemporaryDirectory(prefix='generation-first-run-') as temp:
        base = Path(temp)
        host = SimpleNamespace(root=base, store=Store(base / 'songs.sqlite3'))
        lab = GenerationLab(host)
        uid = lab.enqueue('abcdefghijk', 'Mr. Fancy Pants', 'Jonathan Coulton', 'en', 'quality')
        job = lab.row(uid)
        report = dict(system=platform.platform(),machine=platform.machine(),seconds=8)
        try:
            started = time.monotonic()
            lab.bootstrap(job,base/'bootstrap.log')
            assert (lab.root/'env-ready').is_file()
            report['bootstrap_seconds'] = round(time.monotonic()-started,1)
            subprocess.run([lab.python,'-c','import torch, torchaudio, demucs, librosa, faster_whisper, ctranslate2, onnxruntime, numpy, scipy, soundfile, safetensors, pyphen, uroman; print(torch.__version__, ctranslate2.__version__)'],check=True)
            source = download_starter('jonathan-coulton-mr-fancy-pants',base/'source',Progress())
            audio=validate(source)['audio']
            mixed=base/'mixture.wav'
            subprocess.run(['ffmpeg','-nostdin','-v','error','-ss','22','-t','8','-i',audio,'-f','lavfi','-i','sine=frequency=220:duration=8:sample_rate=44100','-filter_complex','[1:a]volume=0.06[backing];[0:a][backing]amix=inputs=2:duration=first:normalize=0','-ar','44100',mixed],check=True)
            out=base/'draft';env=dict(os.environ,PYTHONNOUSERSITE='1',HF_HOME=str(base/'models/huggingface'),TORCH_HOME=str(base/'models/torch'))
            worker=[lab.python,ROOT/'src/karaoke/generation_worker.py','--cache',base/'models','--profile','quality']
            subprocess.run([*worker,'--prepare'],env=env,check=True)
            started=time.monotonic()
            subprocess.run([*worker,'--audio',mixed,'--output',out,'--artist','Jonathan Coulton','--title','Mr. Fancy Pants (test excerpt)','--language','en'],env=env,check=True)
            validate(out/'song.txt'); report['processing_seconds']=round(time.monotonic()-started,1)
            report['notes']=sum(line.startswith((': ', 'F ','* ')) for line in (out/'song.txt').read_text().splitlines());assert report['notes']>0,report
            report['requirements_sha256']=hashlib.sha256((ROOT/'src/karaoke/generation_assets/requirements.txt').read_bytes()).hexdigest()
            (ROOT/'generation-compatibility.json').write_text(json.dumps(report,indent=2));print(report)
        except Exception:
            if (base/'bootstrap.log').is_file():print((base/'bootstrap.log').read_text(errors='replace')[-8000:])
            raise
        finally:lab.close();host.store.close()


if __name__ == '__main__': main()
