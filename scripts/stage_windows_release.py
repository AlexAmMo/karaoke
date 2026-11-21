#!/usr/bin/env python3
"""Verify an exact CI artifact and stage its Windows assets on an existing draft."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import zipfile

from package_macos import VERSION

REPO = 'AlexAmMo/karaoke'
TAG = 'v' + VERSION
BLOCK = 8 * 1024 * 1024
PART_SIZE = 1024 ** 3


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(BLOCK), b''):
            result.update(block)
    return result.hexdigest()


def gh_json(*args):
    return json.loads(subprocess.check_output(['gh', *args], text=True))


def require_draft():
    release = gh_json('release', 'view', TAG, '--repo', REPO, '--json', 'isDraft,tagName')
    if release['isDraft'] is not True or release['tagName'] != TAG:
        raise RuntimeError('Refusing to stage assets: the existing release must still be a draft')


def check_sidecar(path):
    expected, name = Path(str(path) + '.sha256').read_text().strip().split()
    if name != path.name or not re.fullmatch('[a-fA-F0-9]{64}', expected):
        raise RuntimeError('Invalid checksum sidecar for ' + path.name)
    actual = digest(path)
    if actual != expected.lower():
        raise RuntimeError('SHA256 mismatch: ' + path.name)
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--expected-zip-sha', required=True)
    args = parser.parse_args()
    if not args.run_id.isdecimal() or not re.fullmatch('[a-fA-F0-9]{64}', args.expected_zip_sha):
        raise RuntimeError('An exact run and expected package SHA256 are required')
    require_draft()
    run = gh_json('api', f'repos/{REPO}/actions/runs/{args.run_id}')
    if run['conclusion'] != 'success':
        raise RuntimeError('Source build run did not succeed')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    package = args.input / f'Karaoke-{VERSION}-windows-x86_64.zip'
    source = args.input / f'Karaoke-{VERSION}-dependency-source-windows-x86_64.tar.gz'
    package_hash = check_sidecar(package)
    if package_hash != args.expected_zip_sha.lower():
        raise RuntimeError('Package differs from the explicitly requested build')
    source_hash = check_sidecar(source)
    smoke = json.loads((args.input / 'smoke/result.json').read_text(encoding='utf-8'))
    if smoke.get('passed') is not True or smoke.get('package_sha256') != package_hash or smoke.get('frozen_provider_stdin') is not True:
        raise RuntimeError('Missing matching successful frozen-worker/desktop evidence')
    with zipfile.ZipFile(package) as archive:
        audit = json.loads(archive.read('Karaoke/package-audit.json'))
        provenance = json.loads(archive.read('Karaoke/licenses/SOURCE.json'))
        if provenance['application_commit'] != run['head_sha']:
            raise RuntimeError('Packaged provenance does not match source run')
        pe_files = audit['pe_architecture']
        if not pe_files or any(item['machine'] != '0x8664' for item in pe_files):
            raise RuntimeError('Package architecture audit is not uniformly AMD64')
        if 'Karaoke/engine/opengl32.dll' in archive.namelist():
            raise RuntimeError('CI-only graphics driver leaked into the product ZIP')
        audio_dlls = {item['file']: item['sha256'] for item in audit['engine_audio_dependencies']}
        if not {'sdl2.dll', 'sdl3.dll'}.issubset(name.lower() for name in audio_dlls):
            raise RuntimeError('Native SDL compatibility or streaming runtime is absent')
        for name, expected in audio_dlls.items():
            if hashlib.sha256(archive.read('Karaoke/engine/' + name)).hexdigest() != expected:
                raise RuntimeError('Native audio dependency differs from its build audit: ' + name)
        launcher_hash = hashlib.sha256(archive.read('Karaoke/karaoke.exe')).hexdigest()
        if launcher_hash != smoke['launcher_sha256']:
            raise RuntimeError('Desktop probe did not use this frozen launcher')
        engine_hash = hashlib.sha256(archive.read('Karaoke/engine/ultrastardx.exe')).hexdigest()
        installed_size = sum(item.file_size for item in archive.infolist() if not item.is_dir())
    with tarfile.open(source, 'r:gz') as archive:
        members = {member.name for member in archive.getmembers()}
        manifest = json.load(archive.extractfile('corresponding-sources/source-manifest.json'))
        source_packages = {item['name'] for item in manifest['items'] if item['group'] == 'msys2-complete'}
        for package_name in ('sdl2-compat', 'sdl3'):
            if 'mingw-w64-ucrt-x86_64-' + package_name + '-allsource' not in source_packages:
                raise RuntimeError('Corresponding sources missing for ' + package_name)
        if manifest['unresolved']:
            raise RuntimeError('Dependency sources have unresolved entries: ' + str(manifest['unresolved']))
        for item in manifest['items']:
            if item['status'] != 'collected' or f"corresponding-sources/{item['group']}/{item['filename']}" not in members:
                raise RuntimeError('Manifest source file absent: ' + item['name'])
    parts = []
    with source.open('rb') as reader:
        part_number = 0
        while True:
            block = reader.read(BLOCK)
            if not block:
                break
            part_number += 1
            part = output / f'{source.name}.part{part_number:02d}'
            hasher = hashlib.sha256()
            written = 0
            with part.open('wb') as writer:
                while block:
                    writer.write(block)
                    hasher.update(block)
                    written += len(block)
                    if written == PART_SIZE:
                        break
                    block = reader.read(min(BLOCK, PART_SIZE - written))
            parts.append({'name': part.name, 'bytes': written, 'sha256': hasher.hexdigest()})
    parts_checksum = output / f'Karaoke-{VERSION}-dependency-source-windows-x86_64.parts.sha256'
    parts_checksum.write_text(''.join(f"{part['sha256']}  {part['name']}\n" for part in parts), encoding='ascii')
    source_checksum = output / (source.name + '.sha256')
    shutil.copy2(Path(str(source) + '.sha256'), source_checksum)
    readme = output / f'Karaoke-{VERSION}-windows-source-reassembly.md'
    ps_parts = ', '.join("'" + item['name'] + "'" for item in parts)
    readme.write_text(f'''# Windows dependency sources for Karaoke {VERSION}

These files contain build sources, not songs or application installation files. The Windows application installs from its separate ZIP. The dependency source archive is split into 1 GiB parts because GitHub limits individual release assets. Download every numbered part, the parts checksum file and the complete archive checksum.

Original archive: `{source.name}` ({source.stat().st_size:,} bytes).
SHA256: `{source_hash}`.
Verified source manifest: {len(manifest['items'])} collected entries; no unresolved entries.
Build: https://github.com/{REPO}/actions/runs/{args.run_id}

macOS/Linux, from the download directory:

```sh
shasum -a 256 -c {parts_checksum.name}
cat {source.name}.part[0-9][0-9] > {source.name}
shasum -a 256 -c {source_checksum.name}
tar -xzf {source.name}
```

Windows PowerShell, from the download directory:

```powershell
Get-Content '{parts_checksum.name}' | ForEach-Object {{
  $Expected, $Name = $_ -split '\\s+', 2
  if ((Get-FileHash $Name -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected) {{ throw "Part checksum mismatch: $Name" }}
}}
$Parts = @({ps_parts})
$Output = [IO.File]::Create((Join-Path $PWD '{source.name}'))
try {{
  foreach ($Part in $Parts) {{
    $InputFile = [IO.File]::OpenRead((Join-Path $PWD $Part))
    try {{ $InputFile.CopyTo($Output) }} finally {{ $InputFile.Dispose() }}
  }}
}} finally {{ $Output.Dispose() }}
if ((Get-FileHash '{source.name}' -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{source_hash}') {{ throw 'Complete archive checksum mismatch' }}
tar -xzf '{source.name}'
```

The extracted `corresponding-sources/BUILDING.md`, manifests and source packages document rebuilding. Source hashes remain unchanged by splitting/reassembly. CI Mesa software graphics and dummy audio were used only for startup validation; the application ZIP contains neither that added graphics driver nor physical-audio test results.
''', encoding='utf-8')
    assets = [package, Path(str(package) + '.sha256'), *(output / item['name'] for item in parts), parts_checksum, source_checksum, readme]
    expected_assets = {asset.name: {'bytes': asset.stat().st_size, 'sha256': digest(asset)} for asset in assets}
    require_draft()
    subprocess.run(['gh', 'release', 'upload', TAG, '--repo', REPO, '--clobber', *(str(asset) for asset in assets)], check=True)
    remote = gh_json('release', 'view', TAG, '--repo', REPO, '--json', 'isDraft,assets')
    if remote['isDraft'] is not True:
        raise RuntimeError('Release changed state while staging')
    by_name = {asset['name']: asset for asset in remote['assets']}
    for name, expected in expected_assets.items():
        asset = by_name.get(name, {})
        if asset.get('state') != 'uploaded' or asset.get('size') != expected['bytes'] or asset.get('digest') != 'sha256:' + expected['sha256']:
            raise RuntimeError('Remote asset verification failed: ' + name)
    report = {'ci_run': f'https://github.com/{REPO}/actions/runs/{args.run_id}', 'application_commit': provenance['application_commit'], 'archive': package.name, 'archive_bytes': package.stat().st_size, 'archive_sha256': package_hash, 'installed_uncompressed_bytes': installed_size, 'launcher_sha256': launcher_hash, 'native_executable_sha256': engine_hash, 'engine_audio_dependencies': audio_dlls, 'pe_files_amd64': len(pe_files), 'media_dependency_files': len(audit['media_dependencies']), 'media_smoke_path': audit['media_smoke_path'], 'dependency_source_archive': source.name, 'dependency_source_bytes': source.stat().st_size, 'dependency_source_sha256': source_hash, 'dependency_source_entries': len(manifest['items']), 'dependency_source_groups': dict(Counter(item['group'] for item in manifest['items'])), 'dependency_source_unresolved': [], 'source_parts': parts, 'source_parts_checksums': parts_checksum.name, 'source_full_checksum': source_checksum.name, 'source_reassembly_instructions': readme.name, 'desktop_smoke': {key: smoke[key] for key in ('passed', 'frozen_provider_stdin', 'platform', 'engine_state', 'graphics_audio_log', 'ci_audio_driver', 'elapsed_seconds')}, 'validation_scope': 'Windows software startup and clean quit, frozen provider stdin, AMD64 dependency audit and isolated media startup. Native desktop tested in a disposable copy with CI-only Mesa llvmpipe graphics and SDL dummy audio. No physical microphone, monitoring latency, hardware GPU or Windows singing session validated.', 'draft_assets_verified': expected_assets, 'release_is_draft': True}
    (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
