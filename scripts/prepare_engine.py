#!/usr/bin/env python3
"""Prepare the pinned Deluxe source and our reviewed integration patch.

The generated checkout is disposable. Source changes live in native/ and patches/,
not in an untracked build tree. Existing, unexpected changes are never discarded.
"""
import subprocess
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
print(target)
