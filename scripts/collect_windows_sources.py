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



def prepare_pgp_keys(msys: Path, recipe: Path, environment: dict, metadata: Path):
    """Import only recipe-declared full fingerprints before normal makepkg checks."""
    def command(arguments, check=True, timeout=120):
        return subprocess.run([str(msys / 'usr/bin/bash.exe'), '-lc',
            'cd -- "$(cygpath -u "$1")" && shift && "$@"',
            'source-keys', str(recipe.parent), *arguments], env=environment,
            check=check, capture_output=True, text=True, errors='replace', timeout=timeout)

    info = command(['makepkg-mingw', '--printsrcinfo']).stdout
    (metadata / 'SRCINFO').write_text(info, encoding='utf-8')
    fingerprints = sorted(set(re.findall(r'^\s*validpgpkeys\s*=\s*(\S+)\s*$', info, re.M)))
    for fingerprint in fingerprints:
        if not re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}', fingerprint):
            raise RuntimeError('Recipe declares a non-full PGP fingerprint: ' + fingerprint)
        fingerprint = fingerprint.upper()
        def present():
            listing = command(['gpg', '--batch', '--with-colons', '--fingerprint', fingerprint], check=False)
            return any(line.startswith('fpr:') and line.split(':')[9].upper() == fingerprint for line in listing.stdout.splitlines())
        if present():
            continue
        bundled = recipe.parent / 'keys/pgp' / (fingerprint + '.asc')
        if bundled.is_file():
            command(['gpg', '--batch', '--import', bundled.as_posix()])
        else:
            for server in ('hkps://keyserver.ubuntu.com', 'hkps://keys.openpgp.org'):
                try:
                    command(['gpg', '--batch', '--keyserver-options', 'timeout=30', '--keyserver', server, '--recv-keys', fingerprint], check=False, timeout=90)
                except subprocess.TimeoutExpired:
                    continue
                if present():
                    break
        if not present():
            raise RuntimeError('Could not import the exact source-signing key: ' + fingerprint)
    (metadata / 'verified-key-fingerprints.json').write_text(json.dumps(fingerprints, indent=2), encoding='utf-8')


def main():
    if sys.platform != 'win32': raise SystemExit('Run on the Windows package builder.')
    msys = Path(os.environ.get('MSYS2_ROOT', 'C:/msys64')).resolve()
    tar_environment = dict(os.environ, PATH=os.pathsep.join([str(msys / 'usr/bin'), str(msys / 'ucrt64/bin'), os.environ.get('PATH', '')]))
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
    completed_sources = set()
    for folder, description in owners.values():
        name = description['NAME'][0]; version = description['VERSION'][0]
        file_version = version.split(':', 1)[-1]
        if name in done: continue
        done.add(name)
        # Binary .PKGINFO records package base for split packages as well.
        archives = list(cache.glob(name+'-'+file_version+'-*.pkg.tar.*'))
        archives = [p for p in archives if not p.name.endswith('.sig')]
        if not archives: raise RuntimeError('Pacman package cache missing: '+name)
        info = subprocess.check_output([str(msys / 'usr/bin/tar.exe'), '--force-local', '-xOf', archives[0].as_posix(), '.PKGINFO'], text=True, env=tar_environment)
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
        if (base, file_version) in completed_sources:
            continue
        if result['status'] == 'collected':
            # Source packages may contain recipes + source archives or source URLs.
            archive = OUT / result['group'] / result['filename']
            listing = subprocess.check_output([str(msys / 'usr/bin/tar.exe'), '--force-local', '-tf', archive.as_posix()], text=True, env=tar_environment)
            (metadata / 'source-archive-files.txt').write_text(listing, encoding='utf-8')
            # Generate an all-source package, fetching and verifying any upstream
            # archives omitted from the repository's recipe-only source package.
            extracted = ROOT / 'build/msys-source-packages' / name
            extracted.mkdir(parents=True, exist_ok=True)
            subprocess.run([str(msys / 'usr/bin/tar.exe'), '--force-local', '-xf', archive.as_posix(), '-C', extracted.as_posix()], check=True, env=tar_environment)
            recipes = list(extracted.rglob('PKGBUILD'))
            if len(recipes) != 1: raise RuntimeError('Expected one PKGBUILD in '+package_source)
            environment = dict(os.environ, MSYSTEM='UCRT64', CHERE_INVOKING='1')
            prepare_pgp_keys(msys, recipes[0], environment, metadata)
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
            completed_sources.add((base, file_version))
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
