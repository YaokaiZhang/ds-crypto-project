"""Authenticated model-service transport. Remote failures never produce fixtures."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx

from packages.graph import graph_is_usable
from packages.io import atomic_bytes
from scripts.build_wallet_graph import validate_graph
from .model_response import read_model_response
from ..errors import ServiceError
from ..settings import BACKEND_ROOT


def forecast_input_contract():
    return json.loads((BACKEND_ROOT / 'config/forecast_input.json').read_text())


def outcome_cache_kind(task, registry=None):
    manifest = forecast_input_contract() if task == 'continued_activity' else registry.entries[task][0]
    return 'remote_outcome_v1:' + manifest['model_version']


class RemotePredictor:
    def __init__(self, settings, registry=None, *, transport=None):
        self.settings, self.registry = settings, registry
        self.url = (settings.inference_url or '').rstrip('/')
        self.client = httpx.AsyncClient(transport=transport, timeout=settings.inference_timeout,
                                        trust_env=False, follow_redirects=False)

    async def close(self):
        await self.client.aclose()

    async def predict(self, sample, directory):
        if not graph_is_usable(sample):
            raise ValueError('Input is not eligible for model prediction')
        payload = await asyncio.to_thread(self.registry.payload, sample)
        return await self.send(payload, directory)

    async def send(self, payload, directory):
        if not self.url or not self.settings.inference_api_key:
            raise ServiceError('model_unavailable')
        body = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        digest = hashlib.sha256(body).hexdigest()
        path = Path(directory) / 'model_inputs' / f"{payload['task_id']}-{digest}.json"
        await asyncio.to_thread(atomic_bytes, path, body, immutable=True)
        try:
            # Busy responses may come from another job sharing the one container.
            for attempt in range(4):
                response = await self.client.post(self.url + '/predict', content=body,
                    headers={'Content-Type': 'application/json', 'X-Inference-Key': self.settings.inference_api_key})
                if response.status_code != 429 or attempt == 3:
                    break
                await asyncio.sleep(2 ** attempt)
        except httpx.HTTPError:
            raise ServiceError('model_error') from None
        if response.status_code in (401, 403, 404):
            raise ServiceError('model_unavailable')
        if response.status_code == 422:
            raise ServiceError('model_input_mismatch')
        if response.status_code != 200:
            raise ServiceError('model_error')
        try:
            data = response.json()
            outcome = read_model_response(payload, data)
            if outcome.get('score') is not None and data.get('scaler_sha256') != payload['scaler_sha256']:
                raise ValueError('Response scaler identity mismatch')
        except (ValueError, KeyError, TypeError):
            raise ServiceError('model_input_mismatch') from None
        return outcome, {'input_sha256': digest, 'input_path': str(path), 'target': self.url,
                         'delivery': 'model_responded', 'result_origin': 'model', 'response': data}


class ForecastRemotePredictor(RemotePredictor):
    async def predict(self, payload, directory):
        validate_graph(payload['graph_sample'])
        if not payload['quality']['observation_complete'] or not payload['quality']['model_ready']:
            raise ValueError('Forecast input is incomplete')
        contract = forecast_input_contract()
        if any(payload.get(key) != contract[key] for key in ('model_version', 'scaler_sha256')):
            raise ValueError('Forecast input identity mismatch')
        return await self.send(payload, directory)
