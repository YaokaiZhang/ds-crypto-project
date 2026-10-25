"""Check an existing service and optionally replay a saved model-input packet."""
import argparse
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='https://OWNER-SPACE.hf.space or http://127.0.0.1:7860')
    parser.add_argument('--payload', type=Path)
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    headers = {}
    if os.getenv('HF_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['HF_TOKEN']
    if os.getenv('INFERENCE_API_KEY'):
        headers['X-Inference-Key'] = os.environ['INFERENCE_API_KEY']
    with httpx.Client(base_url=args.url.rstrip('/') + '/', headers=headers, timeout=args.timeout) as client:
        for endpoint in ('health/live', 'health/ready', 'models'):
            response = client.get(endpoint)
            response.raise_for_status()
            print(json.dumps({'endpoint': endpoint, 'response': response.json()}, indent=2))
        if args.payload:
            payload = json.loads(args.payload.read_text())
            response = client.post('predict', json=payload)
            response.raise_for_status()
            result = response.json()
            if (result.get('status') != 'ok' or result.get('result_origin') != 'model'
                    or result.get('sample_id') != payload['graph_sample']['sample_id']
                    or result.get('task_id') != payload['task_id'] or result.get('score') is None):
                raise RuntimeError('Service did not return a successful bound model prediction')
            print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
