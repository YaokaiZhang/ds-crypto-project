"""Real transport authentication, identity binding and explicit failure behavior."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from apps.backend.app.adapters.analysis_store import AnalysisStore
from apps.backend.app.adapters.model_inputs import EthInputRegistry, TokenInputRegistry
from checks.backend.model_fixtures import model_response
from apps.backend.app.adapters.remote_predictor import (RemotePredictor, ForecastRemotePredictor,
    forecast_input_contract, outcome_cache_kind)
from apps.backend.app.application.live_analysis import LiveAnalysisService
from apps.backend.app.application.live_pipeline import LivePipeline
from apps.backend.app.settings import Settings
from apps.backend.app.errors import ServiceError
from apps.backend.app.container import build_container
from apps.backend.app.api.schemas import AnalysisRequest, AnalysisResult
from apps.backend.app.adapters.analysis_rpc import AnalysisRpc
from apps.backend.app.adapters.etherscan_client import BackendEtherscan
from apps.backend.app.workers.analysis import AnalysisWorker
from checks.backend.test_live_eth import Chain, ROOT
from checks.backend.test_live_token import TokenChain
from checks.backend.test_live_forecast import ForecastChain
from checks.backend.test_model_response import packet


class RemoteChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.settings = Settings(analysis_mode='eth_live', inference_url='https://model.example',
            inference_api_key='private-test-key', ethereum_rpc_url='https://rpc.example',
            etherscan_api_key='provider-test-key')
        self.payload = {**packet(), 'scaler_sha256': 'expected-scaler'}
        self.response = {**model_response(self.payload), 'result_origin': 'model',
            'model_version': self.payload['model_version'], 'score': .0123,
            'scaler_sha256': self.payload['scaler_sha256']}

    async def send(self, handler, payload=None):
        predictor = RemotePredictor(self.settings, transport=httpx.MockTransport(handler))
        try:
            return await predictor.send(payload or self.payload, self.directory)
        finally:
            await predictor.close()

    async def test_authentication_label_passthrough_and_credential_free_artifacts(self):
        def handler(request):
            self.assertEqual(str(request.url), 'https://model.example/predict')
            self.assertEqual(request.headers['X-Inference-Key'], 'private-test-key')
            self.assertEqual(json.loads(request.content), self.payload)
            return httpx.Response(200, json=self.response)
        result, delivery = await self.send(handler)
        self.assertEqual(result['label'], 'High Risk')
        self.assertEqual(result['score'], .0123)
        self.assertEqual(result['result_origin'], 'model')
        self.assertNotIn('private-test-key', json.dumps(delivery))
        self.assertNotIn('private-test-key', Path(delivery['input_path']).read_text())

    async def test_remote_failures_never_fall_back_to_mock(self):
        for status, code in ((401,'model_unavailable'), (403,'model_unavailable'), (404,'model_unavailable'),
                             (422,'model_input_mismatch'), (500,'model_error'), (503,'model_error')):
            with self.subTest(status=status), self.assertRaises(ServiceError) as raised:
                await self.send(lambda _: httpx.Response(status, text='upstream-private-secret'))
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn('upstream-private-secret', str(raised.exception))
        def timeout(request):
            raise httpx.ReadTimeout('private-upstream', request=request)
        with self.assertRaises(ServiceError) as raised:
            await self.send(timeout)
        self.assertEqual(raised.exception.code, 'model_error')

    async def test_busy_response_retries_then_decodes_real_response(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(429 if len(calls) < 3 else 200, json=self.response)
        with patch('apps.backend.app.adapters.remote_predictor.asyncio.sleep', new_callable=AsyncMock):
            result, _ = await self.send(handler)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result['result_origin'], 'model')

    async def test_rejects_malformed_or_wrong_model_response(self):
        for changes in ({'sample_id':'wrong'}, {'model_version':'wrong'}, {'score':float('nan')},
                        {'label':None}, {'scaler_sha256':'wrong'}, {'result_origin':'simulated'}):
            # httpx deliberately refuses to encode NaN in its JSON helper.
            body=json.dumps({**self.response, **changes})
            with self.subTest(changes=changes), self.assertRaises(ServiceError) as raised:
                await self.send(lambda _:httpx.Response(200, text=body))
            self.assertEqual(raised.exception.code, 'model_input_mismatch')

    async def test_unavailable_model_stays_unscored(self):
        response={**self.payload, 'result_origin':'model', 'status':'model_unavailable', 'score':None}
        result, _ = await self.send(lambda _:httpx.Response(200,json=response))
        self.assertIsNone(result.get('score'))
        self.assertIsNone(result.get('label'))

    async def test_forecast_transports_and_validates_its_pinned_input_identity(self):
        payload={**packet('continued_activity'),**forecast_input_contract(),
            'quality':{'observation_complete':True,'model_ready':True},'graph_sample':{}}
        received=[]
        def handler(request):
            data=json.loads(request.content); received.append(data)
            return httpx.Response(200,json={**model_response(data), 'result_origin':'model',
                'model_version':data['model_version'], 'scaler_sha256':data['scaler_sha256'], 'score':.72})
        predictor=ForecastRemotePredictor(self.settings,transport=httpx.MockTransport(handler))
        try:
            with patch('apps.backend.app.adapters.remote_predictor.validate_graph'):
                result,_=await predictor.predict(payload,self.directory)
        finally:
            await predictor.close()
        self.assertEqual(result['label'],'Continued activity')
        self.assertEqual(received[0]['model_version'],forecast_input_contract()['model_version'])
        self.assertEqual(payload['model_version'],forecast_input_contract()['model_version'])
        payload['model_version']='wrong'
        predictor=ForecastRemotePredictor(self.settings)
        try:
            with patch('apps.backend.app.adapters.remote_predictor.validate_graph'), self.assertRaises(ValueError):
                await predictor.predict(payload,self.directory)
        finally:
            await predictor.close()
        self.assertNotIn('risk_band',result)

    async def test_live_composition_and_model_bound_cache_identity(self):
        store=AnalysisStore(self.directory/'jobs.sqlite')
        pipeline=LivePipeline(self.settings,store,None)
        try:
            for family, item in pipeline.pipelines.items():
                self.assertIsInstance(item.predictor,RemotePredictor)
            for registry in (EthInputRegistry(self.settings),TokenInputRegistry(self.settings)):
                for task in registry.tasks:
                    self.assertEqual(outcome_cache_kind(task,registry),'remote_outcome_v1:'+registry.entries[task][0]['model_version'])
            job=store.create({'target':'0x'+'11'*20,'family':'eth_scam','tasks':['phishing']},None)
            with store.db() as db:
                result=store.get(job['analysis_id']);result['result_origin']='synthetic'
                db.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps(result),job['analysis_id']))
            lease=store.claim('test')
            with self.assertRaises(ServiceError):
                await pipeline.execute(lease)
        finally:
            await pipeline.close()

    async def test_real_worker_persists_server_results_for_all_three_families(self):
        for family, chain, tasks in (('eth_scam',Chain(contract=True),['phishing','ponzi']),
                ('token_scam',TokenChain(),['honeypot','rug_pull']),
                ('forecast',ForecastChain(),['continued_activity'])):
            with self.subTest(family=family):
                settings=replace(self.settings,analysis_database_path=str(self.directory/(family+'.sqlite')),
                    analysis_artifact_path=str(self.directory/family),etherscan_quota_path=str(self.directory/(family+'-quota.sqlite')))
                services=build_container(settings)
                services.real.budget.acquire=AsyncMock()
                dispatcher=LivePipeline(settings,services.real.store,services.real.budget)
                pipeline=dispatcher.pipelines[family]
                await pipeline.rpc.close(); await pipeline.etherscan.close(); await pipeline.predictor.close()
                pipeline.rpc=AnalysisRpc(settings,transport=httpx.MockTransport(chain.rpc))
                pipeline.etherscan=BackendEtherscan(settings,services.real.budget,
                    transport=httpx.MockTransport(chain.etherscan),sleep=AsyncMock(),retries=0)
                def handler(request):
                    payload=json.loads(request.content)
                    return httpx.Response(200,json={**model_response(payload), 'result_origin':'model',
                        'score':.73,'model_version':payload['model_version'],'scaler_sha256':payload['scaler_sha256']})
                pipeline.predictor=(ForecastRemotePredictor(settings,transport=httpx.MockTransport(handler)) if family=='forecast'
                    else RemotePredictor(settings,pipeline.registry,transport=httpx.MockTransport(handler)))
                try:
                    job=await services.real.create(AnalysisRequest(target=ROOT,family=family).to_command())
                    await AnalysisWorker(services,'test',pipeline=dispatcher).run_once()
                    result=services.real.store.get(job['analysis_id']);AnalysisResult.model_validate(result)
                    self.assertEqual(result['status'],'completed',result.get('message'))
                    self.assertEqual(result['result_origin'],'chain_data_model_scores')
                    self.assertEqual([item['task_id'] for item in result['tasks']],tasks)
                    for item in result['tasks']:
                        self.assertEqual(item['result_origin'],'model');self.assertEqual(item['score'],.73)
                        self.assertFalse(item['model_version'].startswith('simulated:'))
                        delivery=services.real.store.artifact(job['analysis_id'],'model_delivery',item['task_id'])
                        self.assertEqual(delivery['delivery'],'model_responded')
                finally:
                    await dispatcher.close();services.close()

    async def test_capabilities_only_advertise_verified_matching_models(self):
        store=AnalysisStore(self.directory/'jobs.sqlite');store.worker_tick('test')
        service=LiveAnalysisService(store,None,self.settings)
        self.assertFalse(service.capabilities()['analysis_enabled'])
        entries=[]
        for registry in (EthInputRegistry(self.settings),TokenInputRegistry(self.settings)):
            entries += [{'task_id':task,'model_available':True,**{key:manifest[key]
                for key in ('model_version','scaler_sha256')}} for task,(manifest,_) in registry.entries.items()]
        entries.append({'task_id':'continued_activity','model_available':True,**forecast_input_contract()})
        async def get(*args,**kwargs):
            return httpx.Response(200,json={'status':'ready','tasks':entries},request=httpx.Request('GET','https://model.example/models'))
        with patch('httpx.AsyncClient.get',new=get):
            await service.refresh_models()
            self.assertTrue(service.capabilities()['analysis_enabled'])
            entries[0]['model_version']='wrong';service.models_checked_at=float('-inf')
            await service.refresh_models()
        self.assertFalse(service.capabilities()['analysis_enabled'])
        self.assertEqual(service.capabilities()['score_mode'],'model')

    def test_retired_simulation_modes_are_rejected(self):
        for mode in ('eth_live_mock','demo'):
            with self.assertRaises(ValueError):
                replace(self.settings,analysis_mode=mode)

    def test_endpoint_configuration_requires_https_and_key_repr_is_private(self):
        self.assertNotIn('private-test-key',repr(self.settings))
        for url in ('http://example.com','https://user:pass@example.com','https://example.com?key=bad'):
            with self.assertRaises(ValueError):
                replace(self.settings,inference_url=url)
