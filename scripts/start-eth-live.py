#!/usr/bin/env python3
"""Start local API, durable ETH worker and Vite. All model scores are simulated."""
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
RUNTIME.mkdir(exist_ok=True)
RECORD = RUNTIME / 'eth-live-services.json'
PYTHON = ROOT / '.venv/bin/python'
ENV = {**os.environ, 'ANALYSIS_MODE': 'eth_live_mock', 'PYTHONUNBUFFERED': '1'}
SERVICES = {
    'api': [str(PYTHON), '-m', 'uvicorn', 'app.main:app', '--app-dir', 'apps/backend', '--host', '127.0.0.1', '--port', '8000'],
    'worker': [str(PYTHON), '-m', 'apps.backend.app.workers.analysis'],
    'frontend': ['npm', '--prefix', 'apps/frontend', 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173', '--strictPort'],
}


def alive(pid):
    try: os.kill(pid, 0); return True
    except ProcessLookupError: return False


def main():
    if not PYTHON.exists():
        raise SystemExit('Install the root serving environment before starting services.')
    previous = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    restarting = set(SERVICES) if '--restart' in sys.argv else {'api', 'worker'} if '--restart-backend' in sys.argv else set()
    if restarting:
        for name, old in previous.items():
            if name not in restarting:
                continue
            if name not in SERVICES or old.get('command') != SERVICES[name] or not old.get('pid'):
                continue
            if alive(old['pid']):
                actual = subprocess.run(['ps', '-p', str(old['pid']), '-o', 'command='], capture_output=True, text=True).stdout
                cwd = subprocess.run(['lsof', '-a', '-p', str(old['pid']), '-d', 'cwd', '-Fn'],
                                     capture_output=True, text=True).stdout
                belongs_here = any(line == f'n{ROOT}' or line == f'n{ROOT / "apps/frontend"}' for line in cwd.splitlines())
                if belongs_here and (str(ROOT) in actual or name == 'frontend' and 'npm' in actual):
                    try:
                        os.killpg(old['pid'], signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    raise SystemExit(f'Cannot verify the recorded {name} process belongs to this project; it was left running.')
        previous = {name: old for name, old in previous.items() if name not in restarting}
        time.sleep(1)
    current = {}
    for name, command in SERVICES.items():
        old = previous.get(name, {})
        if old.get('command') == command and old.get('pid') and alive(old['pid']):
            current[name] = old
            continue
        with (RUNTIME / f'eth-live-{name}.log').open('ab') as log:
            process = subprocess.Popen(command, cwd=ROOT, env=ENV, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        current[name] = {'pid': process.pid, 'command': command, 'log': str(RUNTIME / f'eth-live-{name}.log')}
    RECORD.write_text(json.dumps(current, indent=2) + '\n')
    for _ in range(100):
        try:
            with urlopen('http://127.0.0.1:8000/api/v1/capabilities', timeout=1) as response:
                capability = json.load(response)
            with urlopen('http://127.0.0.1:5173/eth-scam', timeout=1) as response:
                frontend_ok = response.status == 200
            if capability.get('mode') == 'eth_live_mock' and capability.get('analysis_enabled') and frontend_ok:
                print(json.dumps({'frontend': 'http://127.0.0.1:5173/eth-scam', 'api': 'http://127.0.0.1:8000/docs',
                                  'mode': capability['mode'], 'score_mode': capability['score_mode'],
                                  'pids': {name: row['pid'] for name, row in current.items()}}, indent=2))
                return
        except Exception:
            pass
        time.sleep(.2)
    raise SystemExit('Services did not become ready; inspect .runtime/eth-live-*.log. No other processes were stopped.')


if __name__ == '__main__': main()
