#!/usr/bin/env python3
"""Bounded real desktop startup probe; synthetic demo, never physical audio QA."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    data = output / ('session-' + uuid.uuid4().hex)
    data.mkdir()
    report = {'scope': 'Real packaged launcher and native engine startup in explicit synthetic demo mode. No physical microphone, latency or visual verification.', 'platform': platform.platform(), 'launcher': str(args.launcher.resolve()), 'data_directory': str(data), 'passed': False}
    environment = dict(os.environ)
    if sys.platform == 'win32':
        environment['PATH'] = os.pathsep.join([str(args.launcher.resolve().parent / 'bin'), str(Path(os.environ['WINDIR']) / 'System32'), os.environ['WINDIR']])
    report['path_environment'] = environment.get('PATH', '')
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
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)
        (output / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
