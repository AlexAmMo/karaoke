#!/usr/bin/env python3
"""Archive project, modified engine and exact Syncer source for a candidate release.

Native transitive source distributions must be reviewed separately before release;
this artifact does not pretend to contain Qt/FFmpeg/codec corresponding sources.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path
from package_macos import ROOT, VERSION, USDX_COMMIT, SYNCER_COMMIT


def git_files(directory):
    data = subprocess.check_output(['git', '-C', str(directory), 'ls-files', '-z'])
    for name in data.decode().split('\0'):
        if name and (directory / name).is_file():
            yield Path(name)


def main():
    destination = ROOT / 'dist'
    destination.mkdir(exist_ok=True)
    syncer = ROOT / 'build/sources/usdb-syncer'
    if not (syncer / '.git').exists():
        syncer.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', 'https://github.com/bohning/usdb_syncer.git', str(syncer)], check=True)
        subprocess.run(['git', '-C', str(syncer), 'checkout', '--detach', SYNCER_COMMIT], check=True)
    if subprocess.check_output(['git', '-C', str(syncer), 'rev-parse', 'HEAD'], text=True).strip() != SYNCER_COMMIT:
        raise RuntimeError('Unexpected Syncer source revision')
    archive = destination / f'Karaoke-{VERSION}-source.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tracked = set(git_files(ROOT))
        # Include the same explicit development sources before the first commit.
        for folder in ('src', 'native', 'scripts', 'tests', 'docs', '.github'):
            tracked.update(p.relative_to(ROOT) for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
        tracked.update(Path(p) for p in ('pyproject.toml', 'uv.lock', 'README.md', 'LICENSE', 'NOTICE.md', 'THIRD_PARTY.md', 'PLAN-DEL-KARAOKE.md') if (ROOT / p).exists())
        for file in sorted(tracked):
            if file.parts[0] in ('build', 'dist', '.venv') or file.suffix == '.pyc':
                continue
            tar.add(ROOT / file, arcname=str(Path('karaoke') / file), recursive=False)
        engine = ROOT / 'build/engine'
        if subprocess.check_output(['git', '-C', str(engine), 'rev-parse', 'HEAD'], text=True).strip() != USDX_COMMIT:
            raise RuntimeError('Unexpected Deluxe source revision')
        for file in git_files(engine):
            tar.add(engine / file, arcname=str(Path('upstream/USDX') / file), recursive=False)
        shell = engine / 'src/base/UKaraokeShell.pas'
        tar.add(shell, arcname='upstream/USDX/src/base/UKaraokeShell.pas', recursive=False)
        for file in git_files(syncer):
            tar.add(syncer / file, arcname=str(Path('upstream/usdb-syncer') / file), recursive=False)
    archive.with_suffix('.gz.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
    print(archive)


if __name__ == '__main__':
    main()
