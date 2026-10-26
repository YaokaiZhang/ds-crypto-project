"""Backend-owned frozen input manifests, scalers and request construction."""
import hashlib
import json
from pathlib import Path

from packages.bundle import _bundle_digest, _validate_manifest
from packages.graph import graph_recipe, validate_graph_sample

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
        manifest, _ = self.entries[sample['task_id']]
        if graph_recipe(sample) != manifest['graph_recipe']:
            raise ValueError('Input sampling recipe mismatch')
        return {'protocol_version': 'token-graph-inference-1' if sample['task_id'] in ('honeypot', 'rug_pull') else 'eth-graph-inference-1', 'task_id': sample['task_id'],
                'sample_id': sample['sample_id'], 'target': sample['target'], 'cutoff': sample['cutoff'],
                'model_version': manifest['model_version'], 'scaler_sha256': manifest['scaler_sha256'],
                'graph_recipe': manifest['graph_recipe'], 'feature_names': manifest['feature_names'],
                'graph_sample': sample}


class TokenInputRegistry(EthInputRegistry):
    tasks = ('honeypot', 'rug_pull')
    filename = 'token_models.json'
    path_setting = 'token_model_registry_path'
