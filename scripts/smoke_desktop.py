#!/usr/bin/env python3
"""Bounded real desktop startup probe; synthetic demo, never physical audio QA."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import uuid



def windows_diagnostics(launcher: Path, output: Path, capture=False):
    copy_errors = []
    for label, directory in [('engine', launcher.parent / 'engine'), ('user', Path(os.environ.get('APPDATA', '')) / 'ultrastardx')]:
        for log in directory.glob('*.log'):
            try:
                shutil.copy2(log, output / (label + '-' + log.name))
            except OSError as exc:
                copy_errors.append({'path': str(log), 'error': str(exc)})
    (output / 'log-copy-errors.json').write_text(json.dumps(copy_errors, indent=2), encoding='utf-8')
    # Desktop capture is restricted to disposable GitHub Actions runners.
    if not capture or os.environ.get('GITHUB_ACTIONS') != 'true':
        return
    script = output / 'capture-desktop.ps1'
    script.write_text(r'''param([string]$OutputDir)
$ErrorActionPreference = 'Stop'
Get-Process | Where-Object { $_.ProcessName -in @('karaoke', 'ultrastardx') } | Select-Object ProcessName,Id,MainWindowTitle,Responding | ConvertTo-Json | Set-Content (Join-Path $OutputDir 'windows-processes.json') -Encoding utf8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$Bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$Bitmap = New-Object System.Drawing.Bitmap $Bounds.Width,$Bounds.Height
$Graphics = [System.Drawing.Graphics]::FromImage($Bitmap)
try {
    $Graphics.CopyFromScreen($Bounds.Location,[System.Drawing.Point]::Empty,$Bounds.Size)
    $Bitmap.Save((Join-Path $OutputDir 'desktop.png'),[System.Drawing.Imaging.ImageFormat]::Png)
} finally { $Graphics.Dispose(); $Bitmap.Dispose() }
''', encoding='utf-8')
    capture = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-File', str(script), '-OutputDir', str(output)], capture_output=True, timeout=20)
    (output / 'desktop-capture.log').write_bytes(capture.stdout + capture.stderr)


def check_singing_cursor(data, process):
    from test_session import ROOT, Session, read_json

    subprocess.run([sys.executable, str(ROOT / 'technical-spike/scripts/generate_fixtures.py')],
                   check=True, capture_output=True, timeout=30)
    session = Session(data, [], {})
    session.process = process
    chart = ROOT / 'technical-spike/fixtures/initial/A/song.txt'
    session.event('import:open')
    view = data / 'ipc/view.json'
    session.wait(lambda _: read_json(view).get('page') == 'Importar paquete')
    session.event('field:import', str(chart))
    session.wait(lambda _: any(row.get('action') == 'field:import' and row.get('value') == str(chart)
                               for row in read_json(view).get('rows', [])))
    session.event('import')
    session.wait(lambda _: bool(session.rows("SELECT id FROM songs WHERE title='Probe A'")), timeout=45)
    song = session.rows("SELECT id FROM songs WHERE title='Probe A'")[0]
    def visible_row(page, predicate):
        selected = {}
        def find(_):
            current = read_json(view)
            if current.get('page') != page:
                return False
            for row in current.get('rows', []):
                if predicate(row):
                    selected.update(row)
                    return True
            return False
        session.wait(find)
        return selected

    # Search merges local songs synchronously. External catalogues are unreachable in
    # this smoke test, and all actions below come from controls advertised by the UI.
    session.event('page:Buscar')
    field = visible_row('Buscar', lambda r: r.get('action') == 'field:query')
    session.event(field['action'], 'Probe A')
    hit = visible_row('Buscar', lambda r: r.get('label') == 'Probe A' and r.get('add_action'))
    session.event(hit['add_action'])
    session.wait(lambda _: any(turn['song_id'] == song['id'] for turn in session.queue()))
    turn = next(item['id'] for item in session.queue() if item['song_id'] == song['id'])
    session.event('page:Cola')
    play = visible_row('Cola', lambda r: r.get('action') == 'start:' + turn)
    session.event(play['action'])
    start = session.wait(lambda s: s.get('state') == 'singing' and s.get('position', 0) > 1.5)
    samples = [start]
    for collapsed in (True, False):
        session.native('panel', collapsed=collapsed)
        previous = samples[-1]['position']
        samples.append(session.wait(lambda s: s.get('panel_collapsed') is collapsed
                                    and s.get('position', 0) > previous + 0.2))
    if not all(s.get('cursor_visible') and s.get('token') == turn for s in samples):
        raise AssertionError('System cursor or active turn lost during panel transition')
    return [{k: s.get(k) for k in ('state', 'position', 'cursor_visible', 'panel_collapsed', 'scores')}
            for s in samples]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--package-archive', type=Path)
    parser.add_argument('--source-run')
    parser.add_argument('--check-cursor', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    data = output / ('session-' + uuid.uuid4().hex)
    data.mkdir()
    report = {'scope': 'Real packaged launcher and native engine startup in explicit synthetic demo mode. No physical microphone, latency or visual verification.', 'platform': platform.platform(), 'launcher': str(args.launcher.resolve()), 'data_directory': str(data), 'passed': False}
    report['launcher_sha256'] = hashlib.sha256(args.launcher.read_bytes()).hexdigest()
    if args.package_archive:
        report['package_archive'] = str(args.package_archive.resolve())
        report['package_sha256'] = hashlib.sha256(args.package_archive.read_bytes()).hexdigest()
    if args.source_run:
        report['source_run'] = args.source_run
    environment = dict(os.environ)
    if sys.platform == 'win32':
        environment['PATH'] = os.pathsep.join([str(args.launcher.resolve().parent / 'bin'), str(Path(os.environ['WINDIR']) / 'System32'), os.environ['WINDIR']])
    if args.check_cursor:
        # Exercise immediate local search even on a runner that normally has Internet.
        for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
            environment[name] = environment[name.lower()] = 'http://127.0.0.1:1'
        environment['NO_PROXY'] = environment['no_proxy'] = ''
    report['path_environment'] = environment.get('PATH', '')
    report['ci_audio_driver'] = environment.get('SDL_AUDIODRIVER')
    report['ci_opengl_library'] = environment.get('SDL_OPENGL_LIBRARY')
    if environment.get('GITHUB_ACTIONS') == 'true' and environment.get('KARAOKE_CI_GRAPHICS_MANIFEST'):
        report['ci_graphics'] = json.loads(Path(environment['KARAOKE_CI_GRAPHICS_MANIFEST']).read_text(encoding='utf-8'))
    process = None
    started = time.monotonic()
    try:
        worker_response = output / 'worker-response.json'
        worker = subprocess.run([str(args.launcher.resolve()), '--worker', 'karaoke.provider'],
            input=json.dumps({'operation': 'smoke-unknown-operation', 'root': str(output / 'worker'), 'response': str(worker_response)}).encode('utf-8'),
            capture_output=True, env=environment, timeout=45)
        (output / 'worker.log').write_bytes(worker.stdout + worker.stderr)
        if worker.returncode != 0 or not worker_response.is_file():
            raise RuntimeError(f'Frozen provider stdin probe failed: exit {worker.returncode}')
        response = json.loads(worker_response.read_text(encoding='utf-8'))
        if response.get('error') != 'Operación de catálogo desconocida.':
            raise RuntimeError('Frozen provider did not reach operation dispatch: ' + str(response))
        report['frozen_provider_stdin'] = True
        # Use a new response path even if this evidence directory is reused. The
        # frozen worker must start Chromium and load the native BitTorrent binding.
        picker_response = data / 'picker-probe.json'
        with (output / 'picker-probe.log').open('wb') as picker_log:
            picker = subprocess.run([str(args.launcher.resolve()), '--worker', 'karaoke.spanish_picker'],
                input=json.dumps({'probe': True, 'response': str(picker_response)}).encode('utf-8'),
                stdout=picker_log, stderr=subprocess.STDOUT, env=environment, timeout=45)
        if picker.returncode != 0 or not picker_response.is_file():
            raise RuntimeError(f'Frozen download picker probe failed: exit {picker.returncode}; inspect picker-probe.log')
        capabilities = json.loads(picker_response.read_text(encoding='utf-8'))
        if capabilities.get('browser') is not True or capabilities.get('torrent') is not True:
            raise RuntimeError(f'Frozen download picker did not load its dependencies: {capabilities}')
        report['frozen_download_picker'] = capabilities
        with (output / 'launcher.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([str(args.launcher.resolve()), '--data-dir', str(data), '--demo'], stdout=log, stderr=log, env=environment)
            deadline = time.monotonic() + 45
            state = {}
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f'Launcher exited before engine startup: {process.returncode}')
                try:
                    state = json.loads((data / 'ipc/engine.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    pass
                if state.get('synthetic') is True and state.get('state') == 'idle':
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError('No idle synthetic engine state within 45 seconds; inspect engine.log and engine.json')
            report['engine_state'] = state
            if args.check_cursor:
                report['singing_cursor'] = check_singing_cursor(data, process)
                report['local_search_journey'] = {
                    'query': 'Probe A', 'catalogue_http_unreachable': True,
                    'controls': ['Buscar', 'Campo de búsqueda', 'Añadir a la cola', 'Cola', 'Empezar a cantar'],
                    'passed': True,
                }
            commands = data / 'ipc/commands'
            command = commands / ('smoke-' + uuid.uuid4().hex + '.json')
            temporary = command.with_suffix('.tmp')
            temporary.write_text(json.dumps({'op': 'quit'}), encoding='utf-8')
            os.replace(temporary, command)
            process.wait(timeout=20)
            if process.returncode != 0:
                raise RuntimeError(f'Launcher failed during graceful close: {process.returncode}')
            report['passed'] = True
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        if sys.platform == 'win32':
            try:
                windows_diagnostics(args.launcher.resolve(), output, capture=not report['passed'])
            except Exception as exc:
                report['diagnostic_error'] = str(exc)
        if process is not None and process.poll() is None:
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=False, capture_output=True, timeout=15)
            else:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        native_log = output / 'engine-Error.log'
        if native_log.exists():
            report['graphics_audio_log'] = [line for line in native_log.read_text(encoding='utf-8', errors='replace').splitlines() if any(term in line for term in ('OpenGL vendor', 'OpenGL renderer', 'OpenGL version', 'driver [SDL]', '#Input-Devices'))]
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
