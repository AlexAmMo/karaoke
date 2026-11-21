#!/usr/bin/env python3
"""Prepare the pinned Deluxe source and our reviewed integration patch.

The generated checkout is disposable. Source changes live in native/ and patches/,
not in an untracked build tree. Existing, unexpected changes are never discarded.
"""
import subprocess
import hashlib
import shutil
import os
import tempfile
from pathlib import Path
from prepare_engine_theme import prepare_theme

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


def apply_integration():
    git = ["git", "-C", str(target)]
    current = patch.read_bytes()

    def applies(data, *options):
        return subprocess.run(
            [*git, "apply", "--check", *options, "-"], input=data, capture_output=True
        ).returncode == 0

    if applies(current, "--reverse"):
        return
    delta = current
    if not applies(current):
        # Compare two published integrations against the same upstream commit using a
        # private index. Apply only their delta so local, unrelated build files survive.
        relative = patch.relative_to(ROOT).as_posix()
        history = subprocess.run(
            ["git", "-C", str(ROOT), "log", "--format=%H", "--", relative],
            capture_output=True, text=True,
        )
        earlier = None
        for revision in history.stdout.splitlines():
            candidate = subprocess.check_output(["git", "-C", str(ROOT), "show", revision + ":" + relative])
            if candidate != current and applies(candidate, "--reverse"):
                earlier = candidate
                break
        if earlier is None:
            raise SystemExit("The Deluxe checkout has unrecognised edits. Keep it and build in a fresh checkout.")

        with tempfile.TemporaryDirectory(prefix="karaoke-patch-") as scratch:
            env = dict(os.environ, GIT_INDEX_FILE=str(Path(scratch, "index")))
            trees = []
            for data in (earlier, current):
                subprocess.run([*git, "read-tree", COMMIT], env=env, check=True)
                subprocess.run([*git, "apply", "--cached", "-"], input=data, env=env, check=True)
                trees.append(subprocess.check_output([*git, "write-tree"], env=env, text=True).strip())
            delta = subprocess.check_output([*git, "diff", "--binary", *trees])
    subprocess.run([*git, "apply", "-"], input=delta, check=True)


apply_integration()
for unit in (ROOT / 'native').glob('UKaraoke*.pas'):
    (target / 'src/base' / unit.name).write_bytes(unit.read_bytes())
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
prepare_theme(target)
print(target)
