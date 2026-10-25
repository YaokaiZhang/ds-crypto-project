"""Real inputs and an explicit fixed, service-shaped mock response."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx

from packages.bundle import _bundle_digest, _validate_manifest
from packages.graph import batch_graph_samples, graph_recipe, graph_is_usable, validate_graph_sample
from packages.io import atomic_bytes

from .model_response import fixed_mock_response, read_model_response
from ..settings import BACKEND_ROOT


class EthInputRegistry:
    tasks = ('phishing', 'ponzi')
    filename = 'eth_models.json'
    path_setting = 'model_registry_path'

    def __init__(self, settings):
        configured = getattr(settings, self.path_setting)
        registry = Path(configured).resolve() if configured else BACKEND_ROOT / 'config' / self.filename
        content = json.loads(registry.read_text())
        self.entries = {}
        for task in self.tasks:
            directory = Path(content['tasks'][task])
            if not directory.is_absolute():
                directory = registry.parent / directory
            manifest = json.loads((directory / 'manifest.json').read_text())
            _validate_manifest(manifest, task)
            digest = _bundle_digest(manifest)
            if digest != manifest['bundle_sha256'] or manifest['model_version'] != f'{task}-{digest[:16]}':
                raise ValueError('Input manifest identity mismatch')
            scaler_bytes = (directory / 'scaler.json').read_bytes()
            if hashlib.sha256(scaler_bytes).hexdigest() != manifest['scaler_sha256']:
                raise ValueError('Input scaler checksum mismatch')
            scaler = json.loads(scaler_bytes)
            if scaler['graph_recipe'] != manifest['graph_recipe']:
                raise ValueError('Input scaler recipe mismatch')
            self.entries[task] = (manifest, scaler)

    def payload(self, sample):
        validate_graph_sample(sample)
        manifest, scaler = self.entries[sample['task_id']]
        if graph_recipe(sample) != manifest['graph_recipe']:
            raise ValueError('Input sampling recipe mismatch')
        batch = batch_graph_samples([sample], scaler, add_reverse=manifest['add_reverse'])
        mapping = {'node_features': batch.x.tolist(), 'edge_index': batch.edge_index.tolist(),
                   'root_index': int(batch.root_indices[0]), 'edge_attributes': batch.edge_attr.tolist(),
                   'relation_ids': batch.relation_ids.tolist()}
        return {'protocol_version': 'token-graph-inference-1' if sample['task_id'] in ('honeypot', 'rug_pull') else 'eth-graph-inference-1', 'task_id': sample['task_id'],
                'sample_id': sample['sample_id'], 'target': sample['target'], 'cutoff': sample['cutoff'],
                'model_version': manifest['model_version'], 'scaler_sha256': manifest['scaler_sha256'],
                'graph_recipe': manifest['graph_recipe'], 'feature_names': manifest['feature_names'],
                'inputs': {k: mapping[k] for k in manifest['consumed_inputs']}, 'graph_sample': sample}


class TokenInputRegistry(EthInputRegistry):
    tasks = ('honeypot', 'rug_pull')
    filename = 'token_models.json'
    path_setting = 'token_model_registry_path'


class MockPredictor:
    def __init__(self, settings, registry, *, transport=None):
        self.url, self.registry = settings.mock_predictor_url, registry
        self.client = httpx.AsyncClient(transport=transport, timeout=.8, trust_env=False)

    async def close(self):
        await self.client.aclose()

    async def predict(self, sample, directory):
        if not graph_is_usable(sample):
            raise ValueError('Input is not eligible for mock prediction')
        payload = await asyncio.to_thread(self.registry.payload, sample)
        body = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        digest = hashlib.sha256(body).hexdigest()
        path = Path(directory) / 'model_inputs' / f"{sample['task_id']}-{digest}.json"
        await asyncio.to_thread(atomic_bytes, path, body, immutable=True)
        delivery = 'target_unavailable'
        try:
            response = await self.client.post(self.url, content=body, headers={'Content-Type': 'application/json'})
            delivery = 'target_responded_ignored'
            # This mode always generates a simulated result, even if someone
            # unexpectedly starts a service on the reserved temporary port.
            del response
        except httpx.HTTPError:
            pass
        response = fixed_mock_response(payload)
        outcome = read_model_response(payload, response, origin='simulated')
        return outcome, {'input_sha256': digest, 'input_path': str(path), 'delivery': delivery,
                         'target': self.url, 'result_origin': 'simulated', 'response': response}
