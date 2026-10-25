"""Check a running model service against the pinned Release and real fixtures.

Standard library only. Exits non-zero on the first failed check:
health, all five pinned model versions loaded, API-key enforcement (when a key
is given), and real held-out Forecast fixtures reproducing their recorded
research scores and outcomes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent


def call(url: str, method: str = 'GET', body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b'{}')


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f'FAIL: {message}')
    print(f'ok   {message}', flush=True)


def wait_live(base: str, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            if call(base + '/health/live')[0] == 200:
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f'FAIL: {base}/health/live did not answer within {seconds:.0f}s')
        time.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='e.g. http://127.0.0.1:7860 or https://OWNER-SPACE.hf.space')
    parser.add_argument('--release', type=Path, default=HERE / 'release.json')
    parser.add_argument('--fixtures', type=Path, default=HERE / 'fixtures')
    parser.add_argument('--wait', type=float, default=300, help='seconds to wait for startup')
    parser.add_argument('--tolerance', type=float, default=1e-5)
    args = parser.parse_args()
    base = args.url.rstrip('/')
    key = os.getenv('INFERENCE_API_KEY')
    headers = {'X-Inference-Key': key} if key else {}
    if os.getenv('HF_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['HF_TOKEN']

    wait_live(base, args.wait)
    check(True, 'service is live')
    expected = {task: entry['model_version'] for task, entry in json.loads(args.release.read_text())['bundles'].items()}
    status, models = call(base + '/models', headers=headers)
    check(status == 200, f'/models answered (HTTP {status})')
    served = {row.get('task_id'): row for row in models.get('tasks', [])}
    for task, version in expected.items():
        row = served.get(task, {})
        check(row.get('model_version') == version, f'{task} serves {version}')
    if key:
        # Keep a private Space's HF token, drop only the inference key.
        without_key = {name: value for name, value in headers.items() if name != 'X-Inference-Key'}
        status, _ = call(base + '/predict', 'POST', {}, without_key)
        check(status == 401, f'/predict without the API key is rejected (HTTP {status})')

    fixtures = sorted(args.fixtures.glob('*.json'))
    check(bool(fixtures), f'{len(fixtures)} real fixtures found')
    for path in fixtures:
        fixture = json.loads(path.read_text())
        want, packet = fixture['expected'], fixture['packet']
        started = time.perf_counter()
        status, result = call(base + '/predict', 'POST', packet, headers)
        elapsed = 1000 * (time.perf_counter() - started)
        check(status == 200 and result.get('status') == 'ok' and result.get('result_origin') == 'model',
              f'{path.name}: model prediction returned (HTTP {status}, {elapsed:.0f} ms)')
        check(result.get('task_id') == want['task_id'] and result.get('model_version') == want['model_version'],
              f"{path.name}: identity {result.get('task_id')} / {result.get('model_version')}")
        difference = abs(result['score'] - want['score'])
        check(difference <= args.tolerance, f"{path.name}: score {result['score']:.6f} matches research {want['score']:.6f} (diff {difference:.1e})")
        check(result.get('decision') == want['decision'], f"{path.name}: decision {result.get('decision')} (true outcome {want.get('true_outcome')})")
    print('PASS: all checks succeeded')


if __name__ == '__main__':
    main()
