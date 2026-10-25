"""Serving integration checks against the existing frozen local bundles.

No fitting, provider calls or source-artifact modifications. Real saved packets
are optional; the API contract checks also run with a small synthetic graph.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

from deploy.inference_service.app import create_app
from deploy.inference_service.prepare import prepare
from deploy.inference_service.runtime import InferenceRuntime, read_config
from deploy.inference_service.policies import RiskPolicy, ForecastPolicy
from packages.bundle import predict_bundle
from packages.graph import build_graph_sample

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT.parent
CONFIG = ROOT / 'inference_service/models.json'
POLICY = ROOT / 'registry/risk_policies.json'


class ServingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = InferenceRuntime(CONFIG, risk_policy_path=POLICY)
        cls.app = create_app(cls.runtime, api_key='local-test-key')
        cls.client = TestClient(cls.app)
        cls.headers = {'X-Inference-Key': 'local-test-key'}
        bundle = cls.runtime.bundles['phishing']
        sampling = bundle.manifest['graph_recipe']['sampling']
        cutoff = 2_000_000_000
        address = lambda n: '0x' + f'{n:040x}'
        coverage = {'complete': True, 'scope': sampling['sampling_mode'],
                    'cutoff': cutoff, 'sources': [{'complete': True}],
                    'sampled_history_complete': True, 'full_history_complete': False,
                    'neighborhood_history_complete': False,
                    **{key: sampling[key] for key in ('hops', 'fanouts', 'seed', 'max_nodes',
                                                     'rows_per_action', 'pages_per_action')}}
        graph = build_graph_sample({'target': address(1), 'task_id': 'phishing',
            'sample_id': 'deploy-synthetic-check', 'cutoff': cutoff, 'chain_id': 1,
            'coverage': coverage}, [{'event_id': 'deploy-event', 'chain_id': 1,
            'timestamp': cutoff - 100, 'block_number': 1, 'src': address(2), 'dst': address(1),
            'relation': 'external_eth', 'asset': 'ETH', 'raw_amount': str(10**18),
            'decimals': 18, 'success': True}], **sampling)
        cls.payload = {'task_id': 'phishing', 'graph_sample': graph}

    def post(self, payload):
        return self.client.post('/predict', json=payload, headers=self.headers)

    def test_all_four_models_loaded_forecast_unavailable(self):
        metadata = self.runtime.models()
        self.assertEqual(sum(t['model_available'] for t in metadata['tasks']), 4)
        response = self.post({'task_id': 'continued_activity', 'sample_id': 'forecast-check'})
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(response.json()['score'])

    def test_health_and_authentication(self):
        self.assertEqual(self.client.get('/health/live').status_code, 200)
        self.assertEqual(self.client.get('/models').status_code, 401)
        self.assertEqual(self.client.post('/predict', json=self.payload).status_code, 401)
        self.assertEqual(self.client.post('/gradio_api/call/predict', json={'data': [self.payload]}).status_code, 401)
        response = self.client.get('/health/ready', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['loaded_tasks']), 4)

    def test_rest_matches_shared_predictor_and_ignores_pre_scaled_tensors(self):
        packet = copy.deepcopy(self.payload)
        packet['inputs'] = {'node_features': [[999999]], 'edge_index': [[], []]}
        result = self.post(packet)
        self.assertEqual(result.status_code, 200)
        data = result.json()
        expected = predict_bundle(self.runtime.bundles['phishing'], [packet['graph_sample']])[0]
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['score'], expected['score'])
        self.assertEqual(data['result_origin'], 'model')
        self.assertEqual(data['sample_id'], packet['graph_sample']['sample_id'])
        self.assertIn(data['risk_band'], ('low', 'medium', 'high'))
        self.assertEqual(data['label'], {'low':'Low Risk','medium':'Medium Risk','high':'High Risk'}[data['risk_band']])

    def test_service_thresholds_use_raw_scores(self):
        for task, entry in self.runtime.policy.models.items():
            version = entry['model_version']
            self.assertEqual(self.runtime.policy.classify(task,version,entry['L']-0.00001),'low')
            self.assertEqual(self.runtime.policy.classify(task,version,entry['L']),'medium')
            self.assertEqual(self.runtime.policy.classify(task,version,entry['H']),'high')
            self.assertIsNone(self.runtime.policy.classify(task,'different-weights',entry['H']))
        policy=self.runtime.forecast_policy
        version=policy.data['model_version']
        self.assertEqual(policy.result(.499999,version)['label'],'Low volume')
        self.assertEqual(policy.result(.5,version)['label'],'Continued activity')
        self.assertEqual(policy.result(.999,version)['forecast']['outcome'],'continued_activity')
        with self.assertRaises(ValueError):
            policy.result(.999,'different-weights')
        with self.assertRaises(ValueError):
            policy.outcome(float('nan'))

    def test_service_response_matches_backend_consumption_contract(self):
        from apps.backend.app.adapters.model_response import read_model_response
        sample=self.payload['graph_sample']
        request={**self.payload, **{k:sample[k] for k in ('task_id','sample_id','target','cutoff')},
                 'model_version':self.runtime.bundles['phishing'].manifest['model_version']}
        response=self.runtime.predict(request)
        consumed=read_model_response(request,response)
        self.assertEqual(consumed['score'],response['score'])
        self.assertEqual(consumed['label'],response['label'])

    def test_identity_mismatches_are_unscored(self):
        for field, value in [('model_version', 'wrong'), ('scaler_sha256', 'wrong'),
                             ('sample_id', 'wrong'), ('protocol_version', 'wrong'),
                             ('cutoff', 0), ('feature_names', [])]:
            with self.subTest(field=field):
                response = self.post({**self.payload, field: value})
                self.assertEqual(response.status_code, 422)
                self.assertIsNone(response.json()['score'])

    def test_tensor_only_and_wrong_task_rejected(self):
        for packet in ({'task_id': 'phishing', 'inputs': {}},
                       {**self.payload, 'task_id': 'ponzi'},
                       {**self.payload, 'task_id': 'unknown'}):
            self.assertEqual(self.post(packet).status_code, 422)

    def test_invalid_edges_and_nonfinite_features_rejected(self):
        packet = copy.deepcopy(self.payload)
        packet['graph_sample']['edge_index'][0][0] = 9999999
        self.assertEqual(self.post(packet).status_code, 422)
        packet = copy.deepcopy(self.payload)
        packet['graph_sample']['node_features'][0][0] = float('nan')
        # Exercise runtime directly: HTTP JSON does not admit NaN at all.
        with self.assertRaises(ValueError):
            self.runtime.predict(packet)

    def test_shared_lock_prevents_rest_from_bypassing_concurrency(self):
        with self.runtime.lock:
            response = self.post(self.payload)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['retry-after'], '2')
        self.assertIsNone(response.json()['score'])

    def test_body_limit_including_chunked_requests(self):
        response = self.client.post('/predict', content=iter([b' ' * (9*1024*1024)] * 2),
                                    headers=self.headers)
        self.assertEqual(response.status_code, 413)

    def test_unusable_graph_never_gets_score(self):
        packet = copy.deepcopy(self.payload)
        packet['graph_sample']['quality']['status'] = 'data_incomplete'
        packet['graph_sample']['quality']['model_ready'] = False
        result = self.post(packet)
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()['score'])

    def test_invalid_config_and_corrupt_bundle_fail_startup(self):
        destination = ROOT / '.test-output'
        destination.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination) as temporary:
            temporary = Path(temporary)
            config = temporary / 'models.json'
            config.write_text('{"tasks": {}}')
            with self.assertRaises(ValueError):
                InferenceRuntime(config)
            shutil.copytree(read_config(CONFIG)['phishing'], temporary / 'bundle')
            (temporary / 'bundle/model.pt').write_bytes(b'broken')
            config.write_text('{"tasks": {"phishing": "bundle"}}')
            with self.assertRaises(ValueError):
                InferenceRuntime(config)

    def test_prepared_subset_is_self_contained_and_does_not_overwrite(self):
        destination = ROOT / '.test-output'
        destination.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination) as temporary:
            output = Path(temporary) / 'space'
            prepare(output, CONFIG, ['phishing'])
            packaged = InferenceRuntime(output / 'models.json', risk_policy_path=output / 'risk_policies.json')
            self.assertEqual(packaged.predict(self.payload)['score'], self.runtime.predict(self.payload)['score'])
            self.assertTrue((output / 'packages/transactions.py').is_file())
            self.assertTrue((output / 'DEPLOYMENT.md').is_file())
            self.assertFalse((output / 'apps').exists())
            self.assertFalse((output / 'bundles/ponzi').exists())
            # Import only the packaged code, independently of this checkout.
            code = '''
import json, sys
sys.path.insert(0,sys.argv[1])
from app import create_app
from fastapi.testclient import TestClient
request=json.loads(sys.stdin.read())
with TestClient(create_app(api_key='')) as client:
    response=client.post('/predict',json=request)
    assert response.status_code==200, response.text
    assert response.json()['label'] in ('Low Risk','Medium Risk','High Risk')
assert not any(name=='apps' or name.startswith('apps.') for name in sys.modules)
print('standalone model server passed')
'''
            completed=subprocess.run([sys.executable,'-I','-c',code,str(output)],cwd=output,
                input=json.dumps(self.payload),capture_output=True,text=True,check=True)
            self.assertIn('standalone model server passed',completed.stdout)
            with self.assertRaises(FileExistsError):
                prepare(output, CONFIG)

    def test_subset_does_not_require_unselected_bundles(self):
        destination = ROOT / '.test-output'
        destination.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination) as temporary:
            config = Path(temporary) / 'models.json'
            paths = read_config(CONFIG)
            config.write_text(json.dumps({'tasks': {'phishing': str(paths['phishing']),
                                                    'ponzi': 'not-present'}}))
            output = Path(temporary) / 'space'
            prepare(output, config, ['phishing'])
            self.assertEqual(list(read_config(output / 'models.json')), ['phishing'])

    def test_real_saved_packets_for_each_task_match_local_prediction(self):
        for task, bundle in self.runtime.bundles.items():
            packets = list((PROJECT / '.runtime/eth-artifacts').glob(f'*/model_inputs/{task}-*.json'))
            if not packets:
                self.skipTest(f'No optional saved real packet for {task}')
            with self.subTest(task=task):
                packet = json.loads(packets[0].read_text())
                response = self.post(packet)
                self.assertEqual(response.status_code, 200)
                result = response.json()
                expected = predict_bundle(bundle, [packet['graph_sample']])[0]
                self.assertEqual(result['status'], 'ok')
                self.assertEqual(result['score'], expected['score'])


if __name__ == '__main__':
    unittest.main()
