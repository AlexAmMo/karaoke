#!/usr/bin/env python3
"""Collect actual corresponding-source archives and build provenance for a macOS package.

Downloads are cached, expected upstream SHA-256 values are checked when supplied,
and failed/missing source artifacts remain explicit in source-manifest.json.
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.parse import urlparse
import requests
from package_macos import ROOT, VERSION

OUT = ROOT / 'build/corresponding-sources'


def source_download(item):
    target = OUT / item['group'] / item['filename']
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = item.get('sha256')
    vendored = ROOT / 'third_party/sources' / Path(urlparse(item['url']).path).name
    if not target.exists() and expected and vendored.is_file() and hashlib.sha256(vendored.read_bytes()).hexdigest() == expected:
        shutil.copy2(vendored, target)
    try:
        if not target.exists() or (expected and hashlib.sha256(target.read_bytes()).hexdigest() != expected):
            temp = target.with_suffix(target.suffix + '.part')
            url = item['url']
            if item.get('name') == 'lua' and '5.4.8' in url:
                # Exact upstream tarball mirrored by MacPorts; authoritative hash still applies.
                url = 'https://distfiles.macports.org/lua/' + Path(urlparse(url).path).name
            with requests.get(url, stream=True, timeout=(20, 90)) as response:
                response.raise_for_status()
                with temp.open('wb') as f:
                    for block in response.iter_content(1024 * 1024):
                        f.write(block)
            digest = hashlib.sha256(temp.read_bytes()).hexdigest()
            if expected and digest != expected:
                temp.unlink()
                raise ValueError(f'SHA-256 mismatch for {item["filename"]}')
            temp.replace(target)
        return {**item, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'upstream_hash_checked': bool(expected), 'bytes': target.stat().st_size, 'status': 'collected'}
    except Exception as exc:
        return {**item, 'status': 'failed', 'error': str(exc)}


def installed_formulae(app):
    paths = set()
    manifest = app / 'Contents/Resources/licenses/native-media-manifest.json'
    if manifest.exists():
        paths.update(Path(entry['source']) for entry in json.loads(manifest.read_text()))
    prefix = Path(subprocess.check_output(['brew', '--prefix'], text=True).strip())
    for lib in (app / 'Contents/Resources/Engine.app').rglob('*.dylib'):
        candidate = prefix / 'lib' / lib.name
        if candidate.exists():
            paths.add(candidate.resolve())
        else:
            # Keg-only libraries and aliases may not be linked into prefix/lib.
            matches = list((prefix / 'Cellar').glob('*/*/lib/' + lib.name))
            if len(matches) == 1:
                paths.add(matches[0].resolve())
            elif matches:
                # The engine is linked from current opt; use its installed selected keg.
                for match in matches:
                    opt = prefix / 'opt' / match.relative_to(prefix / 'Cellar').parts[0]
                    if opt.resolve() == match.parents[1]: paths.add(match.resolve())
            else:
                raise RuntimeError(f'Cannot identify installed formula for engine library {lib.name}')
    formulae = set()
    for path in paths:
        if 'Cellar' in path.parts:
            index = path.parts.index('Cellar')
            formulae.add(Path(*path.parts[:index+3]))
    return sorted(formulae)


def formula_sources(formula):
    formulas = list((formula / '.brew').glob('*.rb'))
    if not formulas:
        raise RuntimeError('No installed build formula for ' + str(formula))
    file = formulas[0]
    name = formula.parent.name
    text = file.read_text()
    folder = OUT / 'build-recipes/homebrew' / name
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(file, folder / file.name)
    shutil.copy2(formula / 'INSTALL_RECEIPT.json', folder / 'INSTALL_RECEIPT.json')
    # Record current brew metadata too, but installed formula is authoritative for URL/hash.
    metadata = subprocess.run(['brew', 'info', '--json=v2', name], text=True, capture_output=True)
    if metadata.returncode == 0: (folder / 'current-info.json').write_text(metadata.stdout)
    items = []
    initial = re.search(r'^  url "([^"]+)"([^\n]*(?:\n      [^\n]+)*)', text, re.M)
    if not initial:
        raise RuntimeError('No source URL in ' + str(file))
    url = initial.group(1)
    revision = re.search(r'revision: "([a-f0-9]{40})"', initial.group(2))
    if url.endswith('.git') and revision:
        commit = revision.group(1)
        target = OUT / 'native' / f'{name}-{commit}.tar.gz'
        if not target.exists():
            checkout = ROOT / 'build/source-checkouts' / name
            checkout.mkdir(parents=True, exist_ok=True)
            if not (checkout / '.git').exists(): subprocess.run(['git', 'init', str(checkout)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(checkout), 'fetch', '--depth=1', url, commit], check=True, capture_output=True)
            actual = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'FETCH_HEAD'], text=True).strip()
            if actual != commit: raise RuntimeError('Git source revision differs: ' + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('wb') as f: subprocess.run(['git', '-C', str(checkout), 'archive', '--format=tar.gz', '--prefix='+name+'/', commit], stdout=f, check=True)
        items.append({'name': name, 'group': 'native', 'filename': target.name, 'url': url, 'revision': commit, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'git_object_checked': True, 'status': 'collected', 'bytes': target.stat().st_size})
    else:
        following = text[initial.end():]
        checksum = re.search(r'^  sha256 "([a-f0-9]{64})"', following, re.M)
        if not checksum: raise RuntimeError('No source checksum in ' + str(file))
        filename = name + '-' + Path(urlparse(url).path).name
        items.append({'name': name, 'group': 'native', 'url': url, 'filename': filename, 'sha256': checksum.group(1)})
    # Include externally applied patches/resources named by this precise installed formula.
    for index, block in enumerate(re.findall(r'(?:patch|resource [^\n]+) do\n(.*?)\n  end', text, re.S)):
        link = re.search(r'url "([^"]+)"', block)
        digest = re.search(r'sha256 "([a-f0-9]{64})"', block)
        if link and digest:
            patch_url = link.group(1).replace('#{version}', formula.name.split('_')[0])
            if '#{' in patch_url: raise RuntimeError('Unresolved formula resource: ' + patch_url)
            items.append({'name': name+'-resource-'+str(index), 'group': 'native', 'url': patch_url, 'filename': name+'-resource-'+str(index)+'-'+Path(urlparse(patch_url).path).name, 'sha256': digest.group(1)})
    return items


def wheel_media_sources():
    """PyAV and pylibsrtp wheels carry native libraries independent of system FFmpeg."""
    manifest = json.loads((ROOT / 'third_party/wheel-media-sources.json').read_text())
    for name in ('av', 'pylibsrtp'):
        if importlib.metadata.version(name) != manifest[name]:
            raise RuntimeError(f'Review wheel source recipes for the new {name} version')
    return [item for item in manifest['sources'] if not item.get('windows_only') or sys.platform == 'win32']


def python_sources():
    items = wheel_media_sources()
    for d in importlib.metadata.distributions():
        name = d.metadata.get('Name', '')
        if name.lower().replace('_', '-') in ('karaoke-local', 'usdb-syncer', 'pyside6', 'pyside6-essentials', 'pyside6-addons', 'shiboken6'): continue
        if name.lower() == 'libtorrent' and d.version == '2.1.1':
            items.append({'name': name, 'version': d.version, 'group': 'python',
                          'filename': 'libtorrent-2.1.1.tar.gz',
                          'url': 'https://codeload.github.com/arvidn/libtorrent/tar.gz/56ae8caba38bf154ffc210403cb23f91d0ecaa49',
                          'sha256': '29127305cca0def7f5327f826957dd58c17ef0965e9d5cd899ad37bd9859320b'})
            continue
        try:
            response = requests.get(f'https://pypi.org/pypi/{name}/{d.version}/json', timeout=20)
            response.raise_for_status()
            releases = response.json()['urls']
            sdists = [r for r in releases if r['packagetype'] == 'sdist']
            if sdists:
                s = sdists[0]
                items.append({'name': name, 'version': d.version, 'group': 'python', 'filename': s['filename'], 'url': s['url'], 'sha256': s['digests']['sha256']})
            else:
                items.append({'name': name, 'version': d.version, 'status': 'no-sdist', 'license': d.metadata.get('License-Expression') or d.metadata.get('License'), 'project_urls': d.metadata.get_all('Project-URL') or []})
        except Exception as exc:
            items.append({'name': name, 'version': d.version, 'status': 'failed', 'error': str(exc)})
    return items


def qt_sources(app):
    version = importlib.metadata.version('PySide6')
    parts = version.split('.')
    qt_base = f'https://download.qt.io/official_releases/qt/{parts[0]}.{parts[1]}/{version}/submodules/'
    # Match both macOS framework and Windows DLL layouts to their Qt source modules.
    modules = {p.name.removesuffix('.framework') for p in app.rglob('Qt*.framework')}
    modules.update('Qt'+p.stem[3:] for p in app.rglob('Qt6*.dll'))
    modules.update({'QtCore', 'QtSvg'})
    sources = {'qtbase', 'qtimageformats'}
    base = {'Core', 'Concurrent', 'DBus', 'Gui', 'Network', 'OpenGL', 'OpenGLWidgets',
            'PrintSupport', 'Sql', 'Test', 'Widgets', 'Xml'}
    for module in sorted(modules):
        name = module.removeprefix('Qt')
        if name in base:
            continue
        # Qt ships its declarative runtime as several narrowly named libraries.
        if name.startswith('Quick3D'):
            sources.add('qtquick3d')
        elif name.startswith(('Qml', 'Quick')):
            sources.add('qtdeclarative')
        elif name.startswith('WebEngine'):
            sources.add('qtwebengine')
        elif name.startswith('WebChannel'):
            sources.add('qtwebchannel')
        elif name.startswith('Positioning'):
            sources.add('qtpositioning')
        elif name == 'SerialPort':
            sources.add('qtserialport')
        elif name.startswith('Svg'):
            sources.add('qtsvg')
        else:
            raise RuntimeError('Add source module for additional bundled Qt library: ' + module)
    urls = [qt_base + f'{source}-everywhere-src-{version}.tar.xz' for source in sorted(sources)]
    urls.append(f'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{version}-src/pyside-setup-everywhere-src-{version}.tar.xz')
    items = []
    for url in urls:
        response = requests.get(url+'.sha256', timeout=20); response.raise_for_status()
        checksum = response.text.split()[0]
        if not re.fullmatch('[a-f0-9]{64}', checksum): raise ValueError('Invalid upstream Qt checksum')
        items.append({'name': Path(url).name, 'group': 'qt', 'filename': Path(url).name, 'url': url, 'sha256': checksum})
    return items


def main():
    app = ROOT / 'dist/Karaoke.app'
    if sys.platform != 'darwin' or not app.is_dir():
        raise SystemExit('Build the macOS package first.')
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    for formula in installed_formulae(app):
        try: items.extend(formula_sources(formula))
        except Exception as exc: items.append({'name': formula.parent.name, 'status': 'failed', 'error': str(exc)})
    items.extend(qt_sources(app))
    items.extend(python_sources())
    py_version = platform.python_version()
    items.append({'name': 'CPython', 'version': py_version, 'group': 'python', 'url': f'https://www.python.org/ftp/python/{py_version}/Python-{py_version}.tar.xz', 'filename': f'Python-{py_version}.tar.xz'})
    pending = [i for i in items if 'status' not in i]
    results = [i for i in items if 'status' in i]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(source_download, pending):
            results.append(result)
            print(result['name'] + ': ' + result['status'], flush=True)
    manifest = {'application_version': VERSION, 'python': platform.python_version(), 'platform': platform.platform(), 'items': results, 'unresolved': [r for r in results if r['status'] in ('failed', 'no-sdist')]}
    (OUT / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (OUT / 'BUILDING.md').write_text('''# Corresponding sources for the packaged dependencies

`source-manifest.json` records the exact versions, source URLs, archive hashes and verification results. `build-recipes/homebrew` contains the installed formulas and receipts, including configure flags, patches, resource declarations and dependency versions. The installed formula is authoritative; `current-info.json` is only supplementary and may describe a newer release.

Build the application with the scripts included in its companion source archive and `uv.lock`. Build native Homebrew libraries from the included archive and installed formula. The formula `install` method records the actual configure/build invocation; apply any included patch/resource archives before that invocation. Libraries are dynamically linked and may be replaced with compatible builds; do not treat an ad-hoc signature as a restriction on replacement. Re-sign the local application ad hoc after modification (`codesign --force --deep --sign - Karaoke.app`).

QtCore, QtNetwork, QtGui, QtWidgets, QtDBus and QtOpenGL belong to the included qtbase module. The source manifest includes the modules used by the publisher window, including Qt WebEngine with Chromium, Qt Declarative, Qt WebChannel and Qt Positioning, plus qtsvg and qtimageformats. PySide6 and Shiboken are in the included pyside-setup source. Their source archives contain the upstream license texts and build instructions. The application uses the Qt for Python wheels locked in uv.lock and does not modify Qt. Qt's upstream build guide is https://doc.qt.io/qtforpython-6/building_from_source/index.html .

Python package archives include their upstream build instructions, license files and build metadata. CPython is included separately. Developer tools present in the build environment may also be listed; inclusion in this source archive does not imply they are shipped in the application.

The manifest's unresolved list must be reviewed before publication. A failed download is never silently described as a collected source. A permissively licensed wheel without an sdist is recorded as such rather than claiming its binary wheel is source.
''', encoding='utf-8')
    archive = ROOT / 'dist' / f'Karaoke-{VERSION}-dependency-source-macos-{platform.machine()}.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(OUT, arcname='corresponding-sources', filter=lambda info: None if info.name.endswith('.part') else info)
    archive.with_suffix('.gz.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'unresolved': manifest['unresolved']}, indent=2))
    if any(r['status'] == 'failed' for r in results): raise SystemExit(1)


if __name__ == '__main__':
    main()
