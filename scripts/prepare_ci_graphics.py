#!/usr/bin/env python3
"""Prepare a disposable software-rendered test copy; never alter the release ZIP."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from package_windows import bundle_tools, audit_pe


def main():
    if sys.platform != 'win32' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('This helper is restricted to disposable Windows CI runners.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--tools', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    copy = output / 'Karaoke'
    shutil.copytree(args.package, copy)
    drivers = output / 'graphics-driver'
    roots = [args.tools / name for name in ('opengl32.dll', 'libgallium_wgl.dll')]
    manifest = bundle_tools(drivers, args.tools, initial_files=roots)
    for dll in drivers.iterdir():
        target = copy / 'engine' / dll.name
        if target.exists() and target.read_bytes() != dll.read_bytes():
            raise RuntimeError('CI graphics driver would replace a product DLL: ' + dll.name)
        shutil.copy2(dll, target)
    result = {'scope': 'MSYS2 Mesa llvmpipe graphics driver added only to a disposable CI copy. SDL dummy audio. Driver DLLs are absent from the release ZIP; no physical audio or GPU test.', 'dependencies': manifest, 'architecture': audit_pe(drivers)}
    path = output / 'graphics-manifest.json'
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8') as env:
        for key, value in {'KARAOKE_CI_LAUNCHER': copy / 'karaoke.exe', 'KARAOKE_CI_GRAPHICS_MANIFEST': path, 'SDL_OPENGL_LIBRARY': copy / 'engine/opengl32.dll', 'SDL_AUDIODRIVER': 'dummy', 'GALLIUM_DRIVER': 'llvmpipe'}.items():
            env.write(f'{key}={value}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
