#!/usr/bin/env python3
"""Create the Windows portable package on Windows after compiling Deluxe."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from package_macos import ROOT, VERSION, collect_licenses, copy_file, find_deno, pyinstaller


def bundle_tools(destination: Path, tool_directory: Path):
    """Follow PE imports, copying non-system DLLs alongside the media tools."""
    objdump = shutil.which('objdump') or str(tool_directory / 'objdump.exe')
    if not Path(objdump).is_file():
        raise RuntimeError('objdump.exe from MSYS2 UCRT64 is required for dependency auditing')
    system = Path(os.environ['WINDIR']) / 'System32'
    search = [tool_directory, ROOT / 'build/engine/game', ROOT / 'build/engine/dists/windows/prefix/x86_64/bin']
    pending = []
    for name in ('ffmpeg.exe', 'ffprobe.exe', 'ffplay.exe'):
        source = tool_directory / name
        if not source.exists():
            raise RuntimeError(f'Missing media tool: {source}')
        pending.append(source)
    pending.append(find_deno())
    copied = set()
    manifest = []
    while pending:
        source = pending.pop().resolve()
        if source in copied:
            continue
        copied.add(source)
        target = destination / source.name
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise RuntimeError(f'Conflicting DLL: {source.name}')
        copy_file(source, target)
        details = subprocess.check_output([objdump, '-p', str(source)], text=True, errors='replace')
        for line in details.splitlines():
            if 'DLL Name:' not in line:
                continue
            name = line.split('DLL Name:', 1)[1].strip()
            if name.lower().startswith(('api-ms-win-', 'ext-ms-win-')) or (system / name).is_file():
                continue
            dependency = next((directory / name for directory in [source.parent, *search] if (directory / name).is_file()), None)
            if dependency is None:
                raise RuntimeError(f'Unresolved DLL {name} required by {source}')
            pending.append(dependency)
        manifest.append({'source': str(source), 'file': source.name, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tools', type=Path, default=Path('C:/msys64/ucrt64/bin'))
    parser.add_argument('--skip-python', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Run this packager on Windows.')
    engine = ROOT / 'build/engine/game'
    if not (engine / 'ultrastardx.exe').is_file():
        raise SystemExit('Build the Windows engine first; see .github/workflows/build.yml.')
    python_dist = ROOT / 'build/python-dist'
    if not args.skip_python:
        pyinstaller(python_dist, ROOT / 'build/pyinstaller-windows')
    target = ROOT / 'dist/Karaoke'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(python_dist / 'karaoke', target)
    shutil.copytree(engine, target / 'engine', ignore=shutil.ignore_patterns('*.debug', '*.o', '*.ppu', '*.a', '*.log', '*.ini', '*.db', 'bass.dll'))
    # No personal config, songs, or captured audio are part of a distribution.
    for filename in ('config.ini', 'Ultrastar.db'):
        (target / 'engine' / filename).unlink(missing_ok=True)
    collect_licenses(target / 'licenses')
    for source in (ROOT / 'build/engine/dists/windows/deps').glob('**/*'):
        if source.is_file() and source.name.lower() in ('license', 'license.txt', 'license.md', 'copying', 'copying.lgplv2.1', 'copyright', 'notice', 'bass.txt'):
            copy_file(source, target / 'licenses/native' / source.relative_to(ROOT / 'build/engine/dists/windows/deps'))
    manifest = bundle_tools(target / 'bin', args.tools)
    audit = {'platform': 'windows-x86_64', 'media_dependencies': manifest, 'physical_audio_validated': False, 'audio_backend': 'SDL capture/playback; BASS is disabled and excluded by the fork.'}
    (target / 'package-audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    for name in ('ffmpeg', 'ffprobe', 'ffplay'):
        subprocess.run([str(target / 'bin' / (name + '.exe')), '-version'], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(target / 'bin/deno.exe'), '--version'], check=True, stdout=subprocess.DEVNULL)
    archive = Path(shutil.make_archive(str(ROOT / 'dist' / f'Karaoke-{VERSION}-windows-x86_64'), 'zip', target.parent, target.name))
    archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps({'package': str(target), 'archive': str(archive), 'bytes': archive.stat().st_size}, indent=2))


if __name__ == '__main__':
    main()
