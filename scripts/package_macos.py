#!/usr/bin/env python3
"""Build a self-contained, ad-hoc signed macOS application from a compiled engine.

Run with `uv run python scripts/package_macos.py`. This does not publish a release.
Developer ID signing/notarization is deliberately not claimed by an ad-hoc build.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.3.1'
USDX_COMMIT = '8b9d9e08eca997d2e3fe789084fbac136988f276'
SYNCER_COMMIT = '1690c6d7505701047b245a3470867c0b3ddae01d'


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def output(*args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()


def copy_file(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source.resolve(), target)
    target.chmod(target.stat().st_mode | 0o200)


def collect_licenses(destination: Path):
    """Keep package license texts plus exact installed versions; do not infer licenses."""
    destination.mkdir(parents=True, exist_ok=True)
    packages = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get('Name', 'unknown')
        entry = {'name': name, 'version': distribution.version, 'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License'), 'home': distribution.metadata.get('Home-page'), 'project_urls': distribution.metadata.get_all('Project-URL') or []}
        packages.append(entry)
        for member in distribution.files or []:
            filename = str(member).lower()
            if any(part in Path(filename).name for part in ('license', 'copying', 'notice')) and not filename.endswith(('.py', '.pyc', '.so', '.dll')):
                source = Path(distribution.locate_file(member))
                if source.is_file():
                    # Preserve metadata subdirectories to avoid duplicate LICENSE names.
                    safe = Path(*[p for p in Path(str(member)).parts if p not in ('..', '.')])
                    copy_file(source, destination / 'python' / name / safe)
    (destination / 'python-packages.json').write_text(json.dumps(sorted(packages, key=lambda p: p['name'].lower()), indent=2), encoding='utf-8')
    for name in ('LICENSE', 'COPYRIGHT.txt'):
        source = ROOT / 'build/engine' / name
        if source.exists():
            copy_file(source, destination / 'UltraStar-Deluxe' / name)
    for name in ('LICENSE', 'NOTICE.md', 'THIRD_PARTY.md'):
        source = ROOT / name
        if source.exists():
            copy_file(source, destination / name)
    copy_file(ROOT / 'assets/fonts/OFL.txt', destination / 'Instrument-Sans/OFL.txt')
    for name in ('ffmpeg', 'ffprobe', 'ffplay'):
        result = subprocess.run([name, '-L'], text=True, capture_output=True)
        (destination / f'{name}-license.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    (destination / 'SOURCE.json').write_text(json.dumps({'application': 'https://github.com/AlexAmMo/karaoke', 'application_commit': output('git', '-C', ROOT, 'rev-parse', 'HEAD') if subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--verify', 'HEAD'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0 else 'uncommitted-development-build', 'engine': {'repository': 'https://github.com/UltraStar-Deluxe/USDX', 'commit': USDX_COMMIT, 'modifications': 'patches/deluxe-integration.patch, native/UKaraoke*.pas and scripts/prepare_engine_theme.py in application source'}, 'syncer': {'repository': 'https://github.com/bohning/usdb_syncer', 'commit': SYNCER_COMMIT}, 'python_dependencies': 'uv.lock in application source', 'distribution_note': 'A release must accompany binaries with corresponding-source assets and native dependency provenance. This file alone is not a source offer.'}, indent=2), encoding='utf-8')


def pyinstaller(destination: Path, work: Path, name='karaoke'):
    import uv
    worker_assets = []
    for member in sorted((ROOT / 'src/karaoke/generation_assets').iterdir()):
        if member.is_file() and member.suffix in ('.py', '.in', '.txt'):
            worker_assets.extend(['--add-data', str(member) + ':karaoke/generation_assets'])
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', name,
        *(['--windowed', '--osx-bundle-identifier', 'org.alexammo.karaoke'] if sys.platform == 'darwin' else ['--hide-console', 'hide-early'] if sys.platform == 'win32' else []),
        '--distpath', destination, '--workpath', work, '--specpath', ROOT / 'build',
        '--additional-hooks-dir', ROOT / 'scripts/pyinstaller-hooks', '--paths', ROOT / 'src', '--hidden-import', 'karaoke.provider', '--hidden-import', 'karaoke.picker',
        '--hidden-import', 'usdb_syncer.song_loader', '--collect-data', 'usdb_syncer',
        '--copy-metadata', 'usdb-syncer', '--copy-metadata', 'yt-dlp',
        '--add-binary', str(uv.find_uv_bin()) + ':tools',
        '--add-data', str(ROOT / 'src/karaoke/generation_worker.py') + ':karaoke',
        *worker_assets,
        '--add-data', str(ROOT / 'src/karaoke/review_web') + ':karaoke/review_web',
        '--add-data', str(ROOT / 'src/karaoke/remote_web') + ':karaoke/remote_web',
        '--collect-data', 'yt_dlp_ejs', '--hidden-import', 'keyring.backends.macOS' if sys.platform == 'darwin' else 'keyring.backends.Windows',
        ROOT / 'scripts/launcher.py')


def find_deno() -> Path:
    # Pip's Windows console shim is also a PE executable; never bundle it.
    from deno._find_deno import find_deno_bin
    return Path(find_deno_bin()).resolve()


def dependencies(binary: Path):
    return [line.strip().split(' (', 1)[0] for line in output('otool', '-L', binary).splitlines()[1:] if 'compatibility version' in line]


def rpaths(binary: Path):
    text = output('otool', '-l', binary)
    return re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset', text)


def system_library(value: str):
    return value.startswith(('/usr/lib/', '/System/Library/'))


def macho(path: Path):
    if not path.is_file() or path.is_symlink():
        return False
    with path.open('rb') as f:
        return f.read(4) in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca')


def bundle_media(resources: Path, frameworks: Path):
    """Resolve and copy the actual native dependency graph of FFmpeg and Deno."""
    binaries = [Path(shutil.which(name) or '') for name in ('ffmpeg', 'ffprobe', 'ffplay')]
    if any(not binary.is_file() for binary in binaries):
        raise RuntimeError('ffmpeg, ffprobe and ffplay must be installed before packaging')
    binaries.append(find_deno())
    pending = []
    copied = {}
    for source in binaries:
        target = resources / 'bin' / source.name
        copy_file(source, target)
        pending.append((source.resolve(), target))
    # SDL2-compat loads SDL3 dynamically; otool cannot discover this edge.
    sdl3 = Path(output('brew', '--prefix')) / 'lib/libSDL3.dylib'
    if sdl3.is_file():
        sdl3_target = frameworks / 'libSDL3.dylib'
        copy_file(sdl3, sdl3_target)
        pending.append((sdl3.resolve(), sdl3_target))
    manifest = []
    while pending:
        source, target = pending.pop()
        # install_name_tool edits invalidate the old signature; re-sign after all edits.
        # Removing signatures first can corrupt __LINKEDIT with older Intel tools.
        source_rpaths = rpaths(source)
        for dependency in dependencies(source):
            if system_library(dependency):
                continue
            if dependency.startswith('@loader_path/'):
                resolved = source.parent / dependency.removeprefix('@loader_path/')
            elif dependency.startswith('@executable_path/'):
                resolved = source.parent / dependency.removeprefix('@executable_path/')
            elif dependency.startswith('@rpath/'):
                tail = dependency.removeprefix('@rpath/')
                candidates = [Path(r.replace('@loader_path', str(source.parent)).replace('@executable_path', str(source.parent))) / tail for r in source_rpaths]
                candidates += [source.parent / tail, Path('/opt/homebrew/lib') / tail, Path('/usr/local/lib') / tail]
                resolved = next((p for p in candidates if p.is_file()), None)
                if resolved is None:
                    raise RuntimeError(f'Unresolved {dependency} in {source}')
            else:
                resolved = Path(dependency)
            resolved = resolved.resolve()
            if not resolved.is_file():
                raise RuntimeError(f'Missing library {dependency} for {source}')
            dest = frameworks / resolved.name
            if resolved not in copied:
                if dest.exists() and hashlib.sha256(dest.read_bytes()).digest() != hashlib.sha256(resolved.read_bytes()).digest():
                    raise RuntimeError(f'Conflicting library basename: {resolved.name}')
                copy_file(resolved, dest)
                copied[resolved] = dest
                pending.append((resolved, dest))
            replacement = '@loader_path/' + os.path.relpath(dest, target.parent)
            run('install_name_tool', '-change', dependency, replacement, target)
        if target.suffix == '.dylib':
            run('install_name_tool', '-id', '@rpath/' + target.name, target)
        manifest.append({'source': str(source), 'path': str(target.relative_to(resources.parent)), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    (resources / 'licenses/native-media-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # Homebrew receipt and formula record the actual source URL, version and patches.
    formulas = set()
    for entry in manifest:
        path = Path(entry['source'])
        if '/Cellar/' in str(path):
            parts = path.parts
            position = parts.index('Cellar')
            formulas.add(Path(*parts[:position+3]))
    for formula in formulas:
        dest = resources / 'licenses/homebrew' / formula.parent.name
        for file in (formula / '.brew').glob('*.rb'):
            copy_file(file, dest / file.name)
        receipt = formula / 'INSTALL_RECEIPT.json'
        if receipt.exists():
            copy_file(receipt, dest / receipt.name)
        for file in formula.glob('**/*'):
            if file.is_file() and file.name.lower() in ('license', 'license.txt', 'license.md', 'copying', 'copying.lgplv2.1', 'copying.gplv2', 'copyright', 'notice'):
                copy_file(file, dest / file.relative_to(formula))


def audit_macos(app: Path):
    """Audit dependency closure and both processes' Retina bundle declarations."""
    high_resolution = {}
    for label, relative in [('launcher', 'Contents/Info.plist'), ('engine', 'Contents/Resources/Engine.app/Contents/Info.plist')]:
        info = plistlib.loads((app / relative).read_bytes())
        high_resolution[label] = info.get('NSHighResolutionCapable') is True
        if not high_resolution[label]:
            raise RuntimeError('Missing NSHighResolutionCapable=true in ' + relative)
    binaries = [p for p in app.rglob('*') if macho(p)]
    failures = []
    minimums = []
    for binary in binaries:
        for dep in dependencies(binary):
            if dep.startswith('/') and not system_library(dep):
                failures.append(f'{binary.relative_to(app)} -> {dep}')
            if dep.startswith('@loader_path/') and not (binary.parent / dep.removeprefix('@loader_path/')).exists():
                failures.append(f'{binary.relative_to(app)} -> missing {dep}')
        load = output('otool', '-l', binary)
        for value in re.findall(r'\bminos ([0-9.]+)', load):
            minimums.append(value)
        for value in re.findall(r'cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version ([0-9.]+)', load):
            minimums.append(value)
    if failures:
        raise RuntimeError('External/missing dylib references:\n' + '\n'.join(failures))
    minimum = max(minimums, key=lambda x: tuple(int(p) for p in x.split('.'))) if minimums else None
    return {'high_resolution_capable': high_resolution, 'mach_o_files': len(binaries), 'external_absolute_references': failures, 'minimum_macos_from_binaries': minimum, 'arch': platform.machine(), 'physical_audio_validated': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-python', action='store_true', help='Reuse build/python-dist after a previous PyInstaller build')
    parser.add_argument('--engine', type=Path, default=ROOT / 'build/engine/UltraStar Deluxe.app')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('Run this packager on macOS.')
    engine = args.engine.resolve()
    if not engine.exists():
        raise SystemExit('Build the engine first: scripts/build_macos.sh')
    python_dist = ROOT / 'build/python-dist'
    if not args.skip_python:
        pyinstaller(python_dist, ROOT / 'build/pyinstaller-macos')
    args.output.mkdir(parents=True, exist_ok=True)
    app = args.output.resolve() / 'Karaoke.app'
    if app.exists():
        shutil.rmtree(app)
    macos = app / 'Contents/MacOS'
    resources = app / 'Contents/Resources'
    shutil.copytree(python_dist / 'karaoke.app', app, symlinks=True)
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copytree(engine, resources / 'Engine.app', symlinks=True)
    # The renderer runs in the nested bundle; the launcher's flag does not cover it.
    engine_plist = resources / 'Engine.app/Contents/Info.plist'
    engine_info = plistlib.loads(engine_plist.read_bytes())
    engine_info['NSHighResolutionCapable'] = True
    engine_plist.write_bytes(plistlib.dumps(engine_info))
    collect_licenses(resources / 'licenses')
    bundle_media(resources, app / 'Contents/Frameworks/Media')
    plist = {'CFBundleName': 'Karaoke', 'CFBundleDisplayName': 'Karaoke', 'CFBundleIdentifier': 'org.alexammo.karaoke', 'CFBundleExecutable': 'karaoke', 'CFBundleVersion': VERSION, 'CFBundleShortVersionString': VERSION, 'CFBundlePackageType': 'APPL', 'NSHighResolutionCapable': True, 'LSUIElement': True, 'NSMicrophoneUsageDescription': 'Karaoke usa el micrófono para mostrar tu afinación, puntuar y reproducir tu voz si activas el retorno.'}
    plist['NSLocalNetworkUsageDescription'] = 'Karaoke conecta los móviles de tu red para elegir canciones y controlar la sesión.'
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
    audit = audit_macos(app)
    if audit['minimum_macos_from_binaries']:
        plist['LSMinimumSystemVersion'] = audit['minimum_macos_from_binaries']
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(plist))
    (resources / 'package-audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    # Sign leaves first, then nested bundles and outer application. Ad hoc is explicit.
    for binary in (p for p in app.rglob('*') if macho(p) and p.name not in ('karaoke', 'ultrastardx')):
        run('codesign', '--force', '--sign', '-', binary, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # The engine lives in Resources, which the outer signature can seal as ordinary data.
    # Sign its final binary and plist as a bundle before sealing the launcher.
    engine_bundle = resources / 'Engine.app'
    run('codesign', '--force', '--deep', '--sign', '-', engine_bundle)
    run('codesign', '--verify', '--deep', '--strict', engine_bundle)
    run('codesign', '--force', '--deep', '--sign', '-', app)
    run('codesign', '--verify', '--deep', '--strict', '--verbose=2', app)
    env = dict(os.environ, PATH=str(resources / 'bin') + ':/usr/bin:/bin')
    for name in ('ffmpeg', 'ffprobe', 'ffplay'):
        run(resources / 'bin' / name, '-version', env=env, stdout=subprocess.DEVNULL, timeout=30)
    run(resources / 'bin/deno', '--version', env=env, stdout=subprocess.DEVNULL, timeout=30)
    archive = args.output.resolve() / f'Karaoke-{VERSION}-macos-{platform.machine()}.zip'
    run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n')
    print(json.dumps({'app': str(app), 'archive': str(archive), 'bytes': archive.stat().st_size, 'audit': audit}, indent=2))


if __name__ == '__main__':
    main()
