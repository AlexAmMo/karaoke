"""Verify one platform from an immutable release build on a GitHub runner."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess
import tarfile
import zipfile

REPO = 'AlexAmMo/karaoke'
VERSION = '0.3.1'
TAG = f'v{VERSION}'
LABELS = {'arm64': 'macos-latest', 'x86_64': 'macos-15-intel'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def api(endpoint, text=False):
    value = gh('api', f'repos/{REPO}/{endpoint}', '--allow-escape-sequences')
    return value if text else json.loads(value)


def json_file(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(stream):
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def file_sha(path):
    with path.open('rb') as stream:
        return digest(stream)


def pair(path):
    checksum = path.with_name(path.name + '.sha256')
    expected, name = checksum.read_text(encoding='ascii').strip().split()
    require(name == path.name and expected == file_sha(path), f'Checksum mismatch for {path.name}')
    return {path: expected, checksum: file_sha(checksum)}


def draft(commit):
    meta = json.loads(gh('release', 'view', TAG, '--repo', REPO, '--json', 'isDraft,isPrerelease,targetCommitish,tagName,assets'))
    require(meta['isDraft'] and meta['isPrerelease'] and meta['targetCommitish'] == commit and meta['tagName'] == TAG, 'Expected exact candidate draft prerelease')
    return {x['name']: x for x in meta['assets']}


def same_asset(item, path, expected):
    return item['size'] == path.stat().st_size and item['state'] == 'uploaded' and item['digest'] == 'sha256:' + expected


def stage(assets, commit):
    for path, expected in assets.items():
        existing = draft(commit).get(path.name)
        if existing:
            require(same_asset(existing, path, expected), f'Different existing draft asset: {path.name}')
        else:
            subprocess.run(['gh', 'release', 'upload', TAG, '--repo', REPO, str(path)], check=True)
    remote = draft(commit)
    for path, expected in assets.items():
        require(path.name in remote and same_asset(remote[path.name], path, expected), f'Remote digest/size mismatch: {path.name}')


def source_job(args):
    require(args.run.isdecimal() and re.fullmatch('[0-9a-f]{40}', args.commit), 'Full source run ID and commit required')
    run = api(f'actions/runs/{args.run}')
    require(run['head_sha'] == args.commit and run['repository']['full_name'] == run['head_repository']['full_name'] == REPO and run['path'] == '.github/workflows/build.yml', 'Unexpected originating workflow/commit')
    require(run['conclusion'] == 'success' and run['status'] == 'completed', 'Source build is incomplete or failed')
    job_name = 'Windows x64 development package' if args.arch == 'windows' else f'macOS {LABELS[args.arch]} development package'
    # Failed-only reruns may omit the already successful platform builders
    # from the latest attempt. Use their actual job, logs and immutable artifact.
    jobs = api(f'actions/runs/{args.run}/jobs?filter=all&per_page=100')['jobs']
    matches = [job for job in jobs if job['name'] == job_name]
    require(matches, 'No source platform job matched ' + job_name)
    job = max(matches, key=lambda job: (job['run_attempt'], job['id']))
    require(job['conclusion'] == 'success', 'Platform build and installation tests must pass: ' + job_name)
    require(subprocess.check_output(['git', '-C', str(args.candidate), 'rev-parse', 'HEAD'], text=True).strip() == args.commit, 'Wrong reference source checkout')
    if args.stage:
        draft(args.commit)
    return job


def verify_deps(path, candidate):
    members = {}
    manifest = None
    with tarfile.open(path, 'r|gz') as archive:
        for member in archive:
            if not member.isfile():
                continue
            with archive.extractfile(member) as file:
                if member.name == 'corresponding-sources/source-manifest.json':
                    manifest = json.load(file)
                else:
                    members[member.name] = digest(file)
    require(manifest and manifest['application_version'] == VERSION and manifest['items'] and not manifest['unresolved'], 'Incomplete dependency source manifest')
    expected_media = json_file(candidate / 'third_party/wheel-media-sources.json')['sources']
    for item in manifest['items']:
        name = f"corresponding-sources/{item['group']}/{item['filename']}"
        require(item['status'] == 'collected' and members.get(name) == item['sha256'], 'Unverified source entry: ' + name)
    for item in expected_media:
        if not item.get('windows_only'):
            name = f"corresponding-sources/{item['group']}/{item['filename']}"
            require(members.get(name) == item['sha256'], 'Missing pinned media source: ' + name)
    return len(manifest['items'])


def verify_common(path, candidate):
    selected = ['.github/workflows/build.yml', 'scripts/install.sh', 'scripts/install.ps1', 'scripts/package_macos.py', 'scripts/package_windows.py', 'scripts/prepare_engine.py', 'scripts/test_audio_score_clock.py', 'patches/deluxe-integration.patch', 'src/karaoke/generation_lab.py', 'src/karaoke/generation_verification.py', 'src/karaoke/songs.py', 'uv.lock', 'pyproject.toml']
    selected.extend(str(p.relative_to(candidate)) for p in sorted((candidate / 'native').glob('UKaraoke*.pas')))
    expected = {'karaoke/' + p: file_sha(candidate / p) for p in selected}
    for key in list(expected):
        if key.startswith('karaoke/native/'):
            expected['upstream/USDX/src/base/' + Path(key).name] = expected[key]
    collected = {}
    with tarfile.open(path, 'r|gz') as archive:
        for member in archive:
            if member.name in expected and member.isfile():
                with archive.extractfile(member) as file:
                    collected[member.name] = digest(file)
    require(expected == collected, 'Packaged application/native sources do not match the source build')


def one(root, name):
    path, = root.rglob(name)
    return path


def verify_mac(args, job):
    root = args.input
    prefix = 'Karaoke-' + VERSION
    package = one(root, f'{prefix}-macos-{args.arch}.zip')
    deps = one(root, f'{prefix}-dependency-source-macos-{args.arch}.tar.gz')
    common = one(root, f'{prefix}-source.tar.gz')
    assets = {**pair(package), **pair(deps)}
    common_pair = pair(common)
    if args.arch == 'arm64':
        assets.update(common_pair)
    session = json_file(one(root, 'macos-install-session.json'))
    durations = []
    for attempt in range(1, 4):
        result = json_file(one(root, f'macos-session-runs/attempt-{attempt}.json'))
        require(result['passed'] and result['panel_checks'] and len(result['checks']) >= 21 and all(c['passed'] for c in result['checks']), 'Desktop trial failed')
        require(all(result[k] == session[k] for k in ('launcher_sha256', 'engine_sha256')), 'Different binary across the three sessions')
        exits = [c['evidence']['exit_code'] for c in result['checks'] if c['name'] in ('Closing native game shuts down the main app', 'Final close succeeds')]
        require(exits == [0, 0], 'Desktop exit was not clean')
        durations.append(result['elapsed_seconds'])
    require(session == result, 'Summary does not match final session')
    with zipfile.ZipFile(package) as archive:
        base = 'Karaoke.app/Contents/'
        info = plistlib.loads(archive.read(base + 'Info.plist'))
        provenance = json.loads(archive.read(base + 'Resources/licenses/SOURCE.json'))
        audit = json.loads(archive.read(base + 'Resources/package-audit.json'))
        require(info['CFBundleIdentifier'] == 'org.alexammo.karaoke' and info['CFBundleVersion'] == info['CFBundleShortVersionString'] == VERSION, 'Wrong application version')
        require(provenance['application_commit'] == args.commit and audit['arch'] == args.arch and audit['mach_o_files'] > 0 and not audit['external_absolute_references'], 'Package has wrong platform, provenance or dylib references')
        for name, key in [('MacOS/karaoke', 'launcher_sha256'), ('Resources/Engine.app/Contents/MacOS/ultrastardx', 'engine_sha256')]:
            with archive.open(base + name) as file:
                require(digest(file) == session[key], f'Untested binary in package: {name}')
    logs = api(f'actions/jobs/{job["id"]}/logs', text=True)
    markers = ['PASS 65536 exact mono samples', "PASS: the installed host decoded the phone's Opus stream", 'PASS: two controllers, separate searches', 'PASS contention']
    for marker in markers:
        require(any(line.partition('Z ')[2].startswith(marker) for line in logs.splitlines()), 'Missing test evidence: ' + marker)
    deps_count = verify_deps(deps, args.candidate)
    verify_common(common, args.candidate)
    if args.stage:
        stage(assets, args.commit)
    report = {'run_id': args.run, 'commit': args.commit, 'job': job['html_url'], 'arch': args.arch, 'stage': args.stage, 'version': VERSION, 'minimum_macos': info['LSMinimumSystemVersion'], 'builder_attempt': job['run_attempt'], 'session_checks': len(session['checks']), 'sessions_elapsed_seconds': durations, 'launcher_sha256': session['launcher_sha256'], 'engine_sha256': session['engine_sha256'], 'dependency_source_entries_verified': deps_count, 'assets': {p.name: {'sha256': h, 'bytes': p.stat().st_size} for p, h in assets.items()}}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arch', required=True, choices=(*LABELS, 'windows'))
    p.add_argument('--run', required=True)
    p.add_argument('--commit', required=True)
    p.add_argument('--candidate', required=True, type=Path)
    p.add_argument('--input', type=Path)
    p.add_argument('--report', type=Path)
    p.add_argument('--stage', action='store_true')
    p.add_argument('--preflight', action='store_true')
    args = p.parse_args()
    job = source_job(args)
    if not args.preflight:
        require(args.arch != 'windows' and args.input and args.report, 'Mac archive, report and architecture required')
        verify_mac(args, job)
