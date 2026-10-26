"""The backend consumes service labels and runs without a deploy directory."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from apps.backend.app.adapters.model_response import read_model_response
from checks.backend.model_fixtures import model_response
from apps.backend.app.settings import PROJECT_ROOT


def packet(task='phishing'):
    return {'task_id': task, 'sample_id': 'sample-1', 'target': '0x'+'11'*20,
            'cutoff': 1792796000, 'model_version': 'bundle-identity'}


class ModelResponseChecks(unittest.TestCase):
    def test_server_response_has_a_score_and_label_for_each_task(self):
        for task in ('phishing','ponzi','honeypot','rug_pull','continued_activity'):
            with self.subTest(task=task):
                request = packet(task)
                result = read_model_response(request, model_response(request))
                self.assertEqual(result['score'], .73)
                self.assertEqual(result['label'], 'Continued activity' if task=='continued_activity' else 'High Risk')
                self.assertEqual(result['result_origin'], 'model')
                if task=='continued_activity':
                    self.assertNotIn('risk_band', result)
                    self.assertEqual(result['forecast']['outcome'], result['decision'])
                else:
                    self.assertEqual(result['risk_band'], 'high')

    def test_real_response_passes_labels_through_without_rethresholding(self):
        request = packet()
        response = model_response(request)
        response.update(score=.01, result_origin='model', model_version=request['model_version'])
        result = read_model_response(request,response)
        self.assertEqual(result['score'], .01)
        self.assertEqual(result['label'], 'High Risk')
        self.assertEqual(result['risk_band'], 'high')

    def test_response_identity_and_labels_must_be_complete(self):
        request = packet()
        for changes in ({'score': float('nan')}, {'sample_id': 'wrong'}, {'target':'wrong'},
                        {'cutoff':0}, {'model_version':'wrong'}, {'task_id':'ponzi'},
                        {'result_origin':'simulated'}, {'label': None}, {'label':'Low Risk'},
                        {'score':None}, {'risk_band_policy_version':None}, {'decision':'invented'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                read_model_response(request,{**model_response(request),**changes})

    def test_forecast_label_requires_matching_semantics(self):
        request = packet('continued_activity')
        response = model_response(request)
        response['forecast']['outcome']='low_volume_dead'
        with self.assertRaises(ValueError):
            read_model_response(request,response)

    def test_forecast_rejects_scam_bands_and_wrong_outcome_windows(self):
        request=packet('continued_activity')
        for changes in ({'risk_band':'high','risk_band_policy_version':'scam-policy'},
                        {'forecast':{**model_response(request)['forecast'],'horizon_days':30}},
                        {'forecast':{**model_response(request)['forecast'],'observation_days':30}},
                        {'forecast':{**model_response(request)['forecast'],'swap_volume_threshold_usd':'100'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                read_model_response(request,{**model_response(request),**changes})

    def test_unavailable_response_stays_unscored(self):
        request = packet()
        response = {**request,'status':'model_unavailable','score':None,'label':None,'result_origin':'model'}
        result = read_model_response(request,response)
        self.assertIsNone(result.get('score'))
        self.assertIsNone(result.get('label'))
        self.assertNotIn('risk_band',result)

    def test_backend_runtime_is_independent_of_deploy_files(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            shutil.copytree(PROJECT_ROOT/'apps/backend',folder/'apps/backend',
                ignore=shutil.ignore_patterns('checks','__pycache__','local_secrets.py','.env'))
            shutil.copytree(PROJECT_ROOT/'packages',folder/'packages',
                ignore=shutil.ignore_patterns('__pycache__'))
            (folder/'scripts').mkdir()
            for name in ('__init__.py','build_wallet_graph.py','participant_fields.py'):
                shutil.copy2(PROJECT_ROOT/'scripts'/name,folder/'scripts'/name)
            code = '''
import asyncio, sys
sys.path.insert(0, sys.argv[1])
from apps.backend.app.settings import Settings
from apps.backend.app.adapters.model_inputs import EthInputRegistry, TokenInputRegistry
from apps.backend.app.adapters.remote_predictor import ForecastRemotePredictor
from apps.backend.app.adapters.model_response import read_model_response
settings=Settings()
assert set(EthInputRegistry(settings).entries)=={'phishing','ponzi'}
assert set(TokenInputRegistry(settings).entries)=={'honeypot','rug_pull'}
async def check():
    predictor=ForecastRemotePredictor(settings)
    await predictor.close()
asyncio.run(check())
assert not hasattr(settings,'risk_policy_path')
assert not hasattr(settings,'forecast_policy_path')
assert not any(name=='deploy' or name.startswith('deploy.') for name in sys.modules)
print('independent backend config loaded')
'''
            result=subprocess.run([sys.executable,'-I','-c',code,str(folder)],cwd=folder,
                capture_output=True,text=True,check=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            self.assertIn('independent backend config loaded',result.stdout)

    def test_request_preparation_needs_no_tensor_or_training_libraries(self):
        code = '''
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
class NoTrainingLibraries:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch','numpy','pyarrow','sklearn'}:
            raise AssertionError('Backend request preparation imported a training library')
sys.meta_path.insert(0,NoTrainingLibraries())
from apps.backend.app.settings import Settings
from apps.backend.app.main import create_app
from apps.backend.app.adapters.model_inputs import EthInputRegistry,TokenInputRegistry
settings=Settings()
create_app(settings)
for registry in (EthInputRegistry(settings),TokenInputRegistry(settings)):
    for task in registry.tasks:
        fixture=Path(sys.argv[1])/'checks/fixtures/model_api'/('scam-'+task+'.json')
        sample=json.loads(fixture.read_text())['packet']['graph_sample']
        packet=registry.payload(sample)
        assert packet['graph_sample']==sample and 'inputs' not in packet
assert not any(name in sys.modules for name in ('torch','numpy','pyarrow','sklearn'))
print('lightweight backend packets passed')
'''
        result=subprocess.run([sys.executable,'-I','-c',code,str(PROJECT_ROOT)],cwd=PROJECT_ROOT,
            capture_output=True,text=True,check=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        self.assertIn('lightweight backend packets passed',result.stdout)
