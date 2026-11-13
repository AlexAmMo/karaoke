#!/usr/bin/env python3
"""Collect source archives for the Windows native build and MSYS2 media runtime.

Run on the same Windows builder as package_windows.py. Pacman ownership and
cached .PKGINFO determine exact package base/version; unknown ownership fails.
"""
from __future__ import annotations
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
import requests
from package_macos import ROOT, VERSION
from collect_sources import OUT, python_sources, source_download


def sections(file):
    text = file.read_text(encoding='utf-8')
    return {match[0]: match[1].strip().splitlines() for match in re.findall(r'%([^%]+)%\n(.*?)(?=\n%|\Z)', text, re.S)}


def qt_sources():
    from importlib.metadata import version
    v = version('PySide6')
    branch = '.'.join(v.split('.')[:2])
    urls = [f'https://download.qt.io/official_releases/qt/{branch}/{v}/submodules/{m}-everywhere-src-{v}.tar.xz' for m in ('qtbase', 'qtsvg', 'qtimageformats')]
    urls.append(f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{v}-src/pyside-setup-everywhere-src-{v}.tar.xz')
    entries = []
    for url in urls:
        response = requests.get(url+'.sha256', timeout=30); response.raise_for_status()
        checksum = response.text.split()[0]
        if not re.fullmatch('[a-f0-9]{64}', checksum): raise ValueError('Invalid Qt checksum')
        entries.append(source_download({'name': Path(url).name, 'group': 'qt', 'filename': Path(url).name, 'url': url, 'sha256': checksum}))
    return entries


def main():
    if sys.platform != 'win32': raise SystemExit('Run on the Windows package builder.')
    msys = Path('C:/msys64')
    local = msys / 'var/lib/pacman/local'
    cache = msys / 'var/cache/pacman/pkg'
    target = ROOT / 'dist/Karaoke'
    manifest = json.loads((target / 'package-audit.json').read_text())
    required = {str(Path(m['source']).relative_to(msys)).replace('\\', '/').lower() for m in manifest['media_dependencies'] if Path(m['source']).is_relative_to(msys)}
    owners = {}
    for folder in local.iterdir():
        if not (folder / 'files').exists(): continue
        files = set(x.lower() for x in sections(folder / 'files').get('FILES', []))
        found = required.intersection(files)
        if found:
            description = sections(folder / 'desc')
            for file in found: owners[file] = (folder, description)
    if required - owners.keys(): raise RuntimeError('Unknown native package ownership: ' + str(required-owners.keys()))
    results = []
    done = set()
    for folder, description in owners.values():
        name = description['NAME'][0]; version = description['VERSION'][0]
        file_version = version.split(':', 1)[-1]
        if name in done: continue
        done.add(name)
        # Binary .PKGINFO records package base for split packages as well.
        archives = list(cache.glob(name+'-'+file_version+'-*.pkg.tar.*'))
        archives = [p for p in archives if not p.name.endswith('.sig')]
        if not archives: raise RuntimeError('Pacman package cache missing: '+name)
        info = subprocess.check_output([str(msys / 'usr/bin/tar.exe'), '-xOf', str(archives[0]), '.PKGINFO'], text=True)
        base_match = re.search(r'^pkgbase = (.+)$', info, re.M)
        if not base_match: raise RuntimeError('No pkgbase in '+str(archives[0]))
        base = base_match.group(1)
        package_source = base+'-'+file_version+'.src.tar.zst'
        url = 'https://repo.msys2.org/mingw/sources/'+package_source
        item = {'name': name, 'version': version, 'group': 'msys2', 'filename': package_source, 'url': url, 'package_base': base}
        result = source_download(item)
        if result['status'] == 'failed':
            item['url'] = url.replace('.tar.zst', '.tar.gz'); item['filename'] = package_source.replace('.tar.zst', '.tar.gz')
            result = source_download(item)
        results.append(result)
        metadata = OUT / 'build-recipes/msys2' / name
        metadata.mkdir(parents=True, exist_ok=True)
        (metadata / 'PKGINFO').write_text(info, encoding='utf-8')
        shutil.copy2(folder / 'desc', metadata / 'installed-desc')
        if result['status'] == 'collected':
            # Source packages may contain recipes + source archives or source URLs.
            archive = OUT / result['group'] / result['filename']
            listing = subprocess.check_output([str(msys / 'usr/bin/tar.exe'), '-tf', str(archive)], text=True)
            (metadata / 'source-archive-files.txt').write_text(listing, encoding='utf-8')
            # Generate an all-source package, fetching and verifying any upstream
            # archives omitted from the repository's recipe-only source package.
            extracted = ROOT / 'build/msys-source-packages' / name
            extracted.mkdir(parents=True, exist_ok=True)
            subprocess.run([str(msys / 'usr/bin/tar.exe'), '-xf', str(archive), '-C', str(extracted)], check=True)
            recipes = list(extracted.rglob('PKGBUILD'))
            if len(recipes) != 1: raise RuntimeError('Expected one PKGBUILD in '+package_source)
            environment = dict(os.environ, MSYSTEM='UCRT64', CHERE_INVOKING='1')
            subprocess.run([str(msys / 'usr/bin/bash.exe'), '-lc',
                'cd -- "$(cygpath -u "$1")" && makepkg-mingw --allsource --force --nodeps --noconfirm',
                'collect-sources', str(recipes[0].parent)], env=environment, check=True, timeout=1800)
            complete = list(recipes[0].parent.glob('*.src.tar.*'))
            if not complete: raise RuntimeError('makepkg produced no complete source package for '+name)
            full = OUT / 'msys2-complete'
            full.mkdir(exist_ok=True)
            for file in complete:
                if file.name.endswith('.sig'): continue
                shutil.copy2(file, full / file.name)
                results.append({'name': name+'-allsource', 'group': 'msys2-complete', 'filename': file.name,
                    'status': 'collected', 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                    'source_checks': 'makepkg-mingw --allsource with normal integrity checks'})
    # Upstream Deluxe recipe already downloaded and verified its dependency tarballs.
    deps = ROOT / 'build/engine/dists/windows/deps/dl'
    native = OUT / 'deluxe-native'
    native.mkdir(parents=True, exist_ok=True)
    for file in deps.iterdir():
        if file.is_file() and any(file.name.endswith(ext) for ext in ('.zip', '.tar.gz', '.tar.xz', '.tar.bz2', '.tgz')):
            if 'bass' in file.name.lower(): continue
            shutil.copy2(file, native / file.name)
            results.append({'name': file.name, 'group': 'deluxe-native', 'filename': file.name, 'status': 'collected', 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(), 'upstream_hash_checked': True})
    recipe = OUT / 'build-recipes/deluxe-windows'
    shutil.copytree(ROOT / 'build/engine/dists/windows', recipe, ignore=shutil.ignore_patterns('deps', 'prefix'), dirs_exist_ok=True)
    for item in python_sources():
        results.append(item if 'status' in item else source_download(item))
    results.extend(qt_sources())
    py_version = platform.python_version()
    results.append(source_download({'name': 'CPython', 'version': py_version, 'group': 'python', 'url': f'https://www.python.org/ftp/python/{py_version}/Python-{py_version}.tar.xz', 'filename': f'Python-{py_version}.tar.xz'}))
    if not any(item['group'] == 'deluxe-native' for item in results):
        raise RuntimeError('No verified Deluxe dependency source archives collected')
    (OUT / 'BUILDING.md').write_text('''# Windows corresponding sources

Use the companion application source archive, its uv.lock and .github/workflows/build.yml to build the same application. The Deluxe source tree and its patched dists/windows build recipes are included. deluxe-native contains the upstream dependency archives whose checksums were verified by those recipes.

The build-recipes/msys2 directories record installed package metadata and source recipes. msys2-complete contains all-source packages generated with makepkg-mingw --allsource and normal integrity verification, including fetched upstream sources. Build these using the included PKGBUILD in MSYS2 UCRT64. QtBase, QtSvg and QtImageFormats cover the bundled Qt libraries and plugins; pyside-setup contains PySide6 and Shiboken. These modules are unmodified and use the versions locked in uv.lock. Their archives contain license texts and build instructions. See https://doc.qt.io/qtforpython-6/building_from_source/index.html for the upstream PySide build guide.

The bundled DLLs are dynamically linked and can be replaced with compatible builds. Python package source archives include their build metadata and upstream instructions. CPython is included separately. Consult source-manifest.json for exact versions, source URLs, hashes and any unresolved entries; never interpret a failed or missing source download as collected.
''', encoding='utf-8')
    report = {'items': results, 'unresolved': [r for r in results if r['status'] in ('failed', 'no-sdist')]}
    (OUT / 'source-manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    archive = ROOT / 'dist' / f'Karaoke-{VERSION}-dependency-source-windows-x86_64.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar: tar.add(OUT, arcname='corresponding-sources', filter=lambda info: None if info.name.endswith('.part') else info)
    archive.with_suffix('.gz.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    print(json.dumps({'archive': str(archive), 'unresolved': report['unresolved']}, indent=2))
    if any(r['status'] == 'failed' for r in results): raise SystemExit(1)


if __name__ == '__main__': main()
