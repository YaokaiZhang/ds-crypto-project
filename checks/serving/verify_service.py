"""Verify a deployed model API, its pinned models and real regression packets.

Standard library only. This is the single live-service validation entrypoint;
it also accepts --payload and --timeout from the retired smoke command.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

PROJECT = Path(__file__).resolve().parents[2]


def call(url, method='GET', body=None, headers=None, *, timeout=180):
    data = None if body is None else json.dumps(body, allow_nan=False).encode()
    request = urllib.request.Request(url, data=data, method=method,
        headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b'{}')


def check(condition, message):
    if not condition:
        raise SystemExit(f'FAIL: {message}')
    print(f'ok   {message}', flush=True)


def request_headers(base):
    headers = {}
    if os.getenv('INFERENCE_API_KEY'):
        headers['X-Inference-Key'] = os.environ['INFERENCE_API_KEY']
    host = (urlsplit(base).hostname or '').lower()
    if os.getenv('HF_TOKEN') and (host == 'huggingface.co' or host.endswith('.hf.space')):
        headers['Authorization'] = 'Bearer ' + os.environ['HF_TOKEN']
    return headers


def wait_live(base, seconds, timeout):
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit('FAIL: service did not become live before the startup deadline')
        try:
            status, result = call(base + '/health/live', timeout=min(timeout, remaining))
            if status == 200 and result.get('status') == 'ok':
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError):
            pass
        time.sleep(min(2, max(0, deadline - time.monotonic())))


def validate_prediction(packet, result, model_version):
    check(isinstance(result, dict) and result.get('status') == 'ok'
          and result.get('result_origin') == 'model', 'response is a real scored model result')
    graph = packet.get('graph_sample', {})
    for key in ('task_id', 'sample_id', 'target', 'cutoff'):
        expected = packet.get(key, graph.get('token_address' if key == 'target' else key))
        check(expected is not None and result.get(key) == expected, f'response binds {key}')
    check(result.get('model_version') == model_version, 'response binds the pinned model')
    if packet.get('scaler_sha256'):
        check(result.get('scaler_sha256') == packet['scaler_sha256'], 'response binds the scaler')
    score = result.get('score')
    check(not isinstance(score, bool) and isinstance(score, (int, float)) and math.isfinite(score)
          and 0 <= score <= 1, 'score is finite and in [0,1]')
    if packet['task_id'] == 'continued_activity':
        label = {'continued_activity':'Continued activity', 'low_volume_dead':'Low volume'}.get(result.get('decision'))
    else:
        check(result.get('decision') in ('screen_positive', 'screen_negative'), 'Scam decision is categorical')
        label = {'low':'Low Risk', 'medium':'Medium Risk', 'high':'High Risk'}.get(result.get('risk_band'))
    check(label is not None and result.get('label') == label, 'server supplied a consistent display label')


def verify(base, *, release, fixtures, headers, wait=300, timeout=180, tolerance=1e-5, payload=None):
    base = base.rstrip('/')
    wait_live(base, wait, timeout)
    check(True, 'service is live')
    expected = {task: entry['model_version'] for task, entry in json.loads(Path(release).read_text())['bundles'].items()}
    status, ready = call(base + '/health/ready', headers=headers, timeout=timeout)
    check(status == 200 and ready.get('status') == 'ready'
          and set(expected) <= set(ready.get('loaded_tasks', [])), 'all pinned tasks are ready')
    status, models = call(base + '/models', headers=headers, timeout=timeout)
    check(status == 200 and models.get('status') == 'ready', 'model catalog is ready')
    served = {row.get('task_id'): row for row in models.get('tasks', [])}
    for task, version in expected.items():
        row = served.get(task, {})
        check(row.get('model_available') is True and row.get('model_version') == version, f'{task} serves {version}')
    if 'X-Inference-Key' in headers:
        without_key = {name:value for name,value in headers.items() if name != 'X-Inference-Key'}
        status, _ = call(base + '/predict', 'POST', {}, without_key, timeout=timeout)
        check(status == 401, 'prediction without the API key is rejected')
    paths = sorted(Path(fixtures).glob('*.json'))
    check(bool(paths), f'{len(paths)} real regression fixtures found')
    packets = [(path.name, json.loads(path.read_text())) for path in paths]
    if payload:
        packets.append((Path(payload).name, {'packet':json.loads(Path(payload).read_text())}))
    for name, fixture in packets:
        packet, want = fixture['packet'], fixture.get('expected')
        start = time.perf_counter()
        status, result = call(base + '/predict', 'POST', packet, headers, timeout=timeout)
        check(status == 200, f'{name}: prediction answered in {1000*(time.perf_counter()-start):.0f} ms')
        version = expected[packet['task_id']]
        validate_prediction(packet, result, version)
        if want:
            check(want['model_version'] == version and want['task_id'] == packet['task_id'], 'fixture binds the pinned model')
            check(abs(result['score'] - want['score']) <= tolerance, f'{name}: score matches the recorded regression value')
            check(result.get('decision') == want['decision'], f'{name}: decision matches the recorded regression value')
            for field in ('label', 'risk_band', 'risk_band_policy_version'):
                if field in want:
                    check(result.get(field) == want[field], f'{name}: {field} matches the recorded policy result')
    print('PASS: all checks succeeded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='Local HTTP URL or deployed HTTPS base URL')
    parser.add_argument('--release', type=Path, default=PROJECT / 'deploy/release.json')
    parser.add_argument('--fixtures', type=Path, default=PROJECT / 'checks/fixtures/model_api')
    parser.add_argument('--payload', type=Path, help='Also replay one saved model-input packet')
    parser.add_argument('--wait', type=float, default=300)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--tolerance', type=float, default=1e-5)
    args = parser.parse_args()
    if any(not math.isfinite(value) or value <= 0 for value in (args.wait, args.timeout, args.tolerance)):
        parser.error('--wait, --timeout and --tolerance must be finite positive values')
    try:
        verify(args.url, release=args.release, fixtures=args.fixtures, headers=request_headers(args.url),
               wait=args.wait, timeout=args.timeout, tolerance=args.tolerance, payload=args.payload)
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, KeyError, TypeError):
        raise SystemExit('FAIL: service response or regression packet was unavailable or invalid') from None


if __name__ == '__main__':
    main()
