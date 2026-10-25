"""One frozen bundle per task. No collection, fitting or random fallback."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading

# Work both in this checkout and in the standalone Space prepared by prepare.py.
HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / 'packages').is_dir() else HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.bundle import load_model_bundle, predict_bundle
from packages.forecast import load_forecast_bundle, predict_forecast, validate_forecast_graph
from packages.graph import graph_recipe, validate_graph_sample
try:
    from .policies import RiskPolicy, ForecastPolicy
except ImportError:
    from policies import RiskPolicy, ForecastPolicy

TASKS = ('phishing', 'ponzi', 'honeypot', 'rug_pull', 'continued_activity')
SCAM_TASKS = TASKS[:-1]
FORECAST = 'continued_activity'
FORECAST_PROTOCOL = 'forecast-wallet-observations-1'
# Backend packets built before a real Forecast bundle existed carry this marker.
PENDING_FORECAST_VERSION = 'forecast-wallet-graph-mock-v1'


class BusyError(Exception):
    pass


def read_config(path):
    path = Path(path).resolve()
    content = json.loads(path.read_text(encoding='utf-8'))
    tasks = content.get('tasks')
    if not isinstance(tasks, dict) or not tasks or set(tasks) - set(TASKS):
        raise ValueError('Configure at least one supported task')
    if any(not isinstance(value, str) or not value for value in tasks.values()):
        raise ValueError('Each task must name one bundle directory')
    return {task: (path.parent / value).resolve() for task, value in tasks.items()}


class InferenceRuntime:
    def __init__(self, config_path, *, device='cpu', risk_policy_path=None, forecast_policy_path=None, tasks=None):
        if device not in ('cpu', 'cuda'):
            raise ValueError('INFERENCE_DEVICE must be cpu or cuda')
        self.device = device
        # A missing or corrupt configured bundle must fail startup visibly.
        paths = read_config(config_path)
        selected = list(tasks) if tasks is not None else list(paths)
        if not selected or len(selected) != len(set(selected)) or set(selected) - paths.keys():
            raise ValueError('Select unique tasks present in the model config')
        self.bundles = {task: load_forecast_bundle(paths[task], device=device) if task == FORECAST
                        else load_model_bundle(paths[task], device=device, expected_task=task)
                        for task in selected}
        self.lock = threading.Lock()
        policy_root = HERE if (HERE / 'risk_policies.json').is_file() else HERE.parent / 'registry'
        self.policy = RiskPolicy.load(risk_policy_path or policy_root / 'risk_policies.json')
        self.forecast_policy = ForecastPolicy(forecast_policy_path or policy_root / 'forecast_policy.json')
        for task, bundle in self.bundles.items():
            if task == FORECAST:
                if (self.forecast_policy.data['model_version'] != bundle.manifest['model_version']
                        or self.forecast_policy.data['threshold'] != bundle.manifest['threshold']):
                    raise ValueError('Forecast policy does not match bundle')
            elif self.policy.models[task]['model_version'] != bundle.manifest['model_version']:
                raise ValueError(f'Risk policy does not match bundle: {task}')

    def models(self):
        tasks = []
        for task in TASKS:
            bundle = self.bundles.get(task)
            manifest = bundle.manifest if bundle else {}
            tasks.append({'task_id': task, 'model_available': bundle is not None,
                          'model_version': manifest.get('model_version'),
                          'scaler_sha256': manifest.get('scaler_sha256'),
                          'graph_recipe': manifest.get('graph_recipe'),
                          'feature_names': manifest.get('feature_names', manifest.get('node_feature_names')),
                          'threshold': manifest.get('threshold'),
                          'calibration_status': manifest.get('calibration_status'),
                          'reason': None if bundle else ('Forecast deployment bundle/scaler is not available.'
                              if task == 'continued_activity' else 'Task is not loaded in this deployment.')})
        return {'status': 'ready', 'device': self.device, 'tasks': tasks,
                'forecast_policy': self.forecast_policy.data}

    def predict(self, payload):
        if not isinstance(payload, dict) or payload.get('task_id') not in TASKS:
            raise ValueError('A supported task_id is required')
        task = payload['task_id']
        bundle = self.bundles.get(task)
        if bundle is None:
            return {'task_id': task, 'sample_id': payload.get('sample_id'), 'status': 'model_unavailable',
                    'target': payload.get('target'), 'cutoff': payload.get('cutoff'),
                    'score': None, 'label': None, 'model_version': None, 'result_origin': 'model',
                    'reason': 'No deployment bundle is loaded for this task.'}
        if task == FORECAST:
            return self._forecast(bundle, payload)
        sample = payload.get('graph_sample')
        if not isinstance(sample, dict):
            raise ValueError('graph_sample must contain the unscaled canonical model graph')
        validate_graph_sample(sample)
        manifest = bundle.manifest
        if sample['task_id'] != task or graph_recipe(sample) != manifest['graph_recipe']:
            raise ValueError('Graph task or recipe does not match the loaded model')
        # Current backend packets include identity metadata and already-scaled
        # tensors. Check metadata, then use ONLY the canonical unscaled graph.
        # predict_bundle applies the frozen training scaler exactly once.
        protocol = 'token-graph-inference-1' if task in ('honeypot', 'rug_pull') else 'eth-graph-inference-1'
        expected = {'protocol_version': protocol, 'model_version': manifest['model_version'],
                    'scaler_sha256': manifest['scaler_sha256'], 'graph_recipe': manifest['graph_recipe'],
                    'feature_names': manifest['feature_names'], 'sample_id': sample['sample_id'],
                    'target': sample['target'], 'cutoff': sample['cutoff']}
        for key, value in expected.items():
            if key in payload and payload[key] != value:
                raise ValueError(f'Input identity mismatch: {key}')
        limits = manifest['graph_recipe']['sampling']
        if (len(sample['node_features']) > limits['max_nodes']
                or len(sample['edge_index'][0]) > limits['max_edges']):
            raise ValueError('Graph exceeds the frozen model input budget')
        if not self.lock.acquire(blocking=False):
            raise BusyError('Inference is busy; retry later')
        try:
            result = predict_bundle(bundle, [sample], device=self.device, batch_size=1)[0]
        finally:
            self.lock.release()
        result['decision'] = result['predicted_label']
        result['calibration'] = result['calibration_status']
        result['threshold'] = manifest['threshold']
        result['scaler_sha256'] = manifest['scaler_sha256']
        result['label'] = None
        if result['score'] is not None:
            result['risk_band'] = self.policy.classify(task, manifest['model_version'], result['score'])
            result['risk_band_policy_version'] = self.policy.version
            result['label'] = {'low': 'Low Risk', 'medium': 'Medium Risk', 'high': 'High Risk'}[result['risk_band']]
        return result

    def _forecast(self, bundle, payload):
        graph = payload.get('graph_sample')
        if not isinstance(graph, dict):
            raise ValueError('graph_sample must contain the unscaled first-week wallet graph')
        validate_forecast_graph(graph)
        manifest = bundle.manifest
        # Identity metadata is optional, but anything supplied must match.
        if payload.get('protocol_version', FORECAST_PROTOCOL) != FORECAST_PROTOCOL:
            raise ValueError('Input identity mismatch: protocol_version')
        if payload.get('model_version', manifest['model_version']) not in (manifest['model_version'], PENDING_FORECAST_VERSION):
            raise ValueError('Input identity mismatch: model_version')
        for key, field in (('target', 'token_address'), ('cutoff', 'cutoff')):
            if key in payload and payload[key] != graph.get(field):
                raise ValueError(f'Input identity mismatch: {key}')
        result = {'task_id': FORECAST, 'sample_id': payload.get('sample_id'),
                  'target': payload.get('target', graph.get('token_address')),
                  'cutoff': payload.get('cutoff', graph.get('cutoff')), 'status': 'ok', 'score': None,
                  'label': None, 'decision': None, 'model_version': manifest['model_version'],
                  'result_origin': 'model', 'score_meaning': manifest['score_meaning'],
                  'calibration': manifest['calibration_status'], 'threshold': manifest['threshold'],
                  'scaler_sha256': manifest['scaler_sha256'], 'ensemble_members': len(manifest['members'])}
        # Swap-free graphs were part of Task A training and evaluation, so they
        # are scored; the backend decides which tokens are eligible to send.
        if not self.lock.acquire(blocking=False):
            raise BusyError('Inference is busy; retry later')
        try:
            score = predict_forecast(bundle, [graph], device=self.device)[0]
        finally:
            self.lock.release()
        result['score'] = score
        result.update(self.forecast_policy.result(score, manifest['model_version']))
        return result
