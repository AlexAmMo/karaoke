#!/usr/bin/env python3
"""Prepare the pinned Deluxe source and our reviewed integration patch.

The generated checkout is disposable. Source changes live in native/ and patches/,
not in an untracked build tree. Existing, unexpected changes are never discarded.
"""
import subprocess
import hashlib
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '8b9d9e08eca997d2e3fe789084fbac136988f276'
target = ROOT / 'build/engine'
patch = ROOT / 'patches/deluxe-integration.patch'
if not (target / '.git').exists():
    target.parent.mkdir(exist_ok=True)
    local = ROOT / 'technical-spike/USDX'
    subprocess.run(['git', 'clone', '--no-hardlinks', str(local) if local.exists() else 'https://github.com/UltraStar-Deluxe/USDX.git', str(target)], check=True)
    subprocess.run(['git', '-C', str(target), 'checkout', '--detach', COMMIT], check=True)
actual = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
if actual != COMMIT:
    raise SystemExit('Unexpected Deluxe checkout. Preserve it and prepare a fresh build/engine.')
reverse = subprocess.run(['git', '-C', str(target), 'apply', '--reverse', '--check', str(patch)], capture_output=True)
if reverse.returncode:
    subprocess.run(['git', '-C', str(target), 'apply', '--check', str(patch)], check=True)
    subprocess.run(['git', '-C', str(target), 'apply', str(patch)], check=True)
(target / 'src/base/UKaraokeShell.pas').write_bytes((ROOT / 'native/UKaraokeShell.pas').read_bytes())
# Preserve the exact upstream source when its download host is intermittent.
lua_source = ROOT / 'third_party/sources/lua-5.5.1.tar.gz'
lua_hash = '1c4b4068d67061f2a2231ad2b5422e77acea1487ea9890f6320af614f4373dce'
if lua_source.exists():
    if hashlib.sha256(lua_source.read_bytes()).hexdigest() != lua_hash:
        raise SystemExit('Vendored Lua source checksum mismatch.')
    source_cache = target / 'dists/windows/deps/dl'
    source_cache.mkdir(parents=True, exist_ok=True)
    shutil.copy2(lua_source, source_cache / lua_source.name)
# With no local archive, the native recipe uses its verified network downloader.
print(target)
