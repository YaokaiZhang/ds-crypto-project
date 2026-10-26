"""Forecast live window, native wallet graph and remote decision contracts."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from checks.backend.test_live_token import TokenChain, ROOT, POOL, WALLET, STAMP, word, log
from apps.backend.app.adapters.analysis_rpc import AnalysisRpc
from apps.backend.app.adapters.etherscan_client import BackendEtherscan
from apps.backend.app.adapters.remote_predictor import ForecastRemotePredictor
from apps.backend.app.application.forecast_pipeline import ForecastPipeline
from apps.backend.app.api.schemas import AnalysisResult
from apps.backend.app.errors import QuotaExhausted
from apps.backend.app.main import create_app
from apps.backend.app.settings import Settings
from apps.backend.app.workers.analysis import AnalysisWorker
from packages.token import UNISWAP_V2_FACTORY

T0 = STAMP-20*86400
END = T0+7*86400


class ForecastChain(TokenChain):
    def __init__(self,count=70,pool=True,immature=False):
        super().__init__(count,pool)
        self.immature = immature
        self.rpc_calls=[]
        for row in self.logs:
            block=30 if row['address']==ROOT else 40
            row.update(blockNumber=hex(block),timeStamp=hex(T0+(block-10)*10080))
        for number,block,stamp in ((20000,10,T0),(20001,70,END),(20002,80,END+1),(20003,9,T0-1)):
            row=log(number,ROOT,'erc20_transfer',dst=WALLET,block=block)
            row['timeStamp']=hex(stamp)
            self.logs.append(row)

    def etherscan(self,request):
        response=super().etherscan(request)
        params=dict(request.url.params)
        if params['action']=='getblocknobytime':
            stamp=int(params['timestamp'])
            result='70' if stamp==END else '100' if stamp>=STAMP else '10' if stamp>=T0 else '1'
            return httpx.Response(200,json={'status':'1','message':'OK','result':result})
        if params['action']=='getLogs' and params['address']==UNISWAP_V2_FACTORY:
            data=response.json()
            for row in data['result']:
                row['timeStamp']=hex(STAMP-86400 if self.immature else T0)
            return httpx.Response(200,json=data)
        return response

    def rpc(self,request):
        body=json.loads(request.content); method,params=body['method'],body['params']
        self.rpc_calls.append(body)
        if method=='eth_getBlockByNumber':
            number=112 if params[0]=='latest' else int(params[0],16)
            stamp=STAMP+(number-100)*12 if number>=100 else T0+(number-10)*10080
            return httpx.Response(200,json={'id':body['id'],'result':{'number':hex(number),'timestamp':hex(stamp),'hash':'0x'+word(number)}})
        return super().rpc(request)


class ForecastChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.settings=Settings(analysis_mode='eth_live',inference_url='https://model.example',inference_api_key='private-inference-key',ethereum_rpc_url='https://rpc.example/private',etherscan_api_key='private-key',
            analysis_database_path=str(root/'jobs.sqlite'),analysis_artifact_path=str(root/'artifacts'),etherscan_quota_path=str(root/'quota.sqlite'))
        self.app=create_app(self.settings); self.lifespan=self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.real=self.app.state.container.real
        self.real.store.worker_tick('test')
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test')
        self.real.budget.acquire=self.sleep
        self.pipelines=[]

    async def sleep(self,*_): pass

    async def asyncTearDown(self):
        await self.client.aclose()
        for pipeline in self.pipelines: await pipeline.close()
        await self.lifespan.__aexit__(None,None,None)

    def worker(self,chain):
        predictor=ForecastRemotePredictor(self.settings,transport=httpx.MockTransport(chain.predict))
        pipeline=ForecastPipeline(self.settings,self.real.store,self.real.budget,
            rpc=AnalysisRpc(self.settings,transport=httpx.MockTransport(chain.rpc)),
            etherscan=BackendEtherscan(self.settings,self.real.budget,transport=httpx.MockTransport(chain.etherscan),sleep=self.sleep,retries=0),predictor=predictor)
        self.pipelines.append(pipeline)
        return AnalysisWorker(self.app.state.container,'forecast-test',pipeline=pipeline)

    async def submit(self):
        response=await self.client.post('/api/v1/analyses',json={'target':ROOT,'family':'forecast'})
        self.assertEqual(response.status_code,202,response.text)
        return response.json()['analysis_id']

    async def test_http_lifecycle_idempotency_pagination_and_sse_replay(self):
        # Restored from the retired demo checks, now using the real worker and
        # controlled provider/model HTTP responses instead of demo datasets.
        body={'target':ROOT,'family':'forecast','pools':[POOL]}
        headers={'Idempotency-Key':'forecast-http-regression'}
        accepted=await self.client.post('/api/v1/analyses',json=body,headers=headers)
        self.assertEqual(accepted.status_code,202,accepted.text)
        initial=accepted.json();identity=initial['analysis_id'];url='/api/v1/analyses/'+identity
        self.assertIsNone(initial['tasks'][0]['score'])
        repeated=await self.client.post('/api/v1/analyses',json=body,headers=headers)
        self.assertEqual(repeated.json()['analysis_id'],identity)
        conflict=await self.client.post('/api/v1/analyses',json={**body,'target':'0x'+'ab'*20},headers=headers)
        self.assertEqual(conflict.status_code,409)
        self.assertEqual((await self.client.get(url+'/graphs/continued_activity')).status_code,409)
        await self.worker(ForecastChain()).run_once()
        result=(await self.client.get(url)).json()
        self.assertEqual(result['status'],'completed',result.get('message'))
        self.assertEqual(result['result_origin'],'chain_data_model_scores')
        self.assertEqual(result['graphs']['continued_activity']['context']['model_sample_id'],result['tasks'][0]['sample_id'])
        self.assertEqual((await self.client.get(url+'/graphs/honeypot')).status_code,404)
        first=(await self.client.get(url+'/transactions',params={'category':'token_transfer','limit':10})).json()
        self.assertEqual(len(first['items']),10);self.assertTrue(first['next_cursor'])
        second=(await self.client.get(url+'/transactions',params={
            'category':'token_transfer','limit':10,'cursor':first['next_cursor']})).json()
        self.assertFalse({row['id'] for row in first['items']} & {row['id'] for row in second['items']})
        bad=await self.client.get(url+'/transactions',params={'category':'pool_event','cursor':first['next_cursor']})
        self.assertEqual(bad.status_code,400)
        stream=await self.client.get(url+'/events',headers={'Last-Event-ID':'4'})
        self.assertIn('id: 5',stream.text);self.assertNotIn('id: 4\n',stream.text)
        self.assertIn('completed',stream.text)
        for changes in ({'tasks':['honeypot']},{'tasks':['continued_activity','continued_activity']},
                        {'target':'bad'},{'chain_id':137},{'pools':['not-an-address']}):
            with self.subTest(changes=changes):
                response=await self.client.post('/api/v1/analyses',json={**body,**changes})
                self.assertEqual(response.status_code,422)

    async def test_first_week_only_wallet_model_input_and_unscored_future_labels(self):
        chain=ForecastChain(); worker=self.worker(chain); identity=await self.submit()
        swap_topic='0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822'
        for row in chain.logs:
            if row['topics'][0]==swap_topic:
                row['topics'][2]='0x'+'0'*24+'44'*20
        await worker.run_once(); result=self.real.store.get(identity)
        AnalysisResult.model_validate(result)
        self.assertEqual(result['status'],'completed',result.get('message'))
        context=self.real.store.artifact(identity,'context')
        self.assertEqual(context['t0'],T0); self.assertEqual(context['cutoff'],END)
        self.assertEqual(context['cutoff_block'],70)
        self.assertEqual(result['transactions']['total'],72)
        self.assertEqual(sum(p['transfer_count'] for p in result['activity']['points']),72)
        self.assertTrue(result['activity']['scope']['complete'])
        self.assertEqual(result['activity']['scope']['family'],'forecast')
        self.assertEqual(result['basic_information']['state_block'],70)
        self.assertTrue(any(b['method']=='eth_call' and b['params'][1]['blockHash']=='0x'+word(70) for b in chain.rpc_calls))
        self.assertEqual(len(chain.deliveries),1)
        payload=chain.deliveries[0]
        self.assertEqual(len(payload['inputs']['node_features'][0]),18)
        self.assertEqual(payload['inputs']['root_index'],0)
        self.assertEqual(payload['historical_usd'],'unavailable; no current-price substitution')
        self.assertNotIn('label',payload['graph_sample'])
        self.assertEqual(payload['graph_sample']['partition'],'inference')
        graph=payload['graph_sample']
        wallets=[r['id'] for r in graph['node_refs'] if r['kind']=='wallet']
        self.assertEqual(wallets,[WALLET])
        self.assertTrue(all(r['relation'] in ('contains_token','swap_activity') for r in graph['edge_refs']))
        task=result['tasks'][0]
        self.assertEqual(task['score'],.73)
        self.assertEqual(task['label'],'Continued activity')
        self.assertEqual(task['decision'],'continued_activity')
        self.assertNotIn('risk_band',task)
        self.assertEqual(task['forecast']['decision_policy_version'],'test-forecast-policy')
        self.assertEqual(task['result_origin'],'model')
        self.assertEqual(task['forecast']['observation_days'],7)
        # Checkpoint replay reuses the original exact payload and fixed outcome.
        with self.real.store.db() as db:
            replay=deepcopy(result); replay['status']='running'
            db.execute('UPDATE jobs SET result=?,lease_until=0 WHERE id=?',(json.dumps(replay),identity))
        await worker.run_once()
        self.assertEqual(len(chain.deliveries),1)
        self.assertEqual(self.real.store.get(identity)['tasks'],result['tasks'])

    async def test_display_keeps_only_16_second_hop_senders_without_limiting_model_or_ledger(self):
        chain=ForecastChain(count=1200)
        for i in range(80):
            row=log(30000+i,POOL,'swap',src='0x'+f'{0x5000+i:040x}',dst=WALLET,block=40)
            row['timeStamp']=hex(T0+3*86400); chain.logs.append(row)
        identity=await self.submit(); await self.worker(chain).run_once()
        result=self.real.store.get(identity)
        self.assertEqual(result['status'],'completed',result['message'])
        graph=result['graphs']['continued_activity']
        self.assertEqual(sum(n['hop']==2 for n in graph['nodes']),16)
        self.assertEqual(len(graph['nodes']),18)
        self.assertEqual(graph['context']['model_nodes'],83)
        self.assertEqual(result['transactions']['total'],1202)
        self.assertEqual(result['tasks'][0]['decision'],'continued_activity')
        self.assertEqual(sum(p['swap_count'] for p in result['activity']['points']),81)

    async def test_incomplete_first_week_or_empty_swaps_never_sends_predictor_input(self):
        for immature in (False,True):
            chain=ForecastChain(immature=immature)
            if not immature:
                chain.logs=[r for r in chain.logs if r['address']==ROOT]
            identity=await self.submit(); await self.worker(chain).run_once()
            result=self.real.store.get(identity)
            self.assertEqual(result['status'],'partial',result.get('message'))
            task=result['tasks'][0]
            self.assertEqual(task['status'],'insufficient_history' if immature else 'no_activity')
            self.assertIsNone(task['score']); self.assertTrue(task['reason'])
            self.assertFalse(chain.deliveries)

    async def test_no_pool_is_unavailable_with_reason(self):
        chain=ForecastChain(pool=False)
        identity=await self.submit(); await self.worker(chain).run_once()
        result=self.real.store.get(identity)
        self.assertEqual(result['tasks'][0]['status'],'not_applicable')
        self.assertIsNone(result['tasks'][0]['score'])
        self.assertTrue(result['tasks'][0]['reason'])
        self.assertFalse(chain.deliveries)

    async def test_progressive_history_is_visible_before_graph_and_quota_resume_preserves_it(self):
        chain=ForecastChain(count=1200)
        for i,row in enumerate(chain.logs[:1200]):
            block=35 if i<1000 else 20
            row.update(blockNumber=hex(block),timeStamp=hex(T0+(block-10)*10080))
        identity=await self.submit(); worker=self.worker(chain)
        paused=[False]; counts=[]
        def observe(params):
            if params['action']!='getLogs' or params['address']!=ROOT: return
            state=self.real.store.get(identity)
            count=(state.get('transactions') or {}).get('total',0)
            if count:
                counts.append(count)
            if count>=1000 and not paused[0] and int(params['toBlock'])<35:
                self.assertFalse(state['graphs'])
                paused[0]=True
                raise QuotaExhausted(9999999999)
        chain.observer=observe
        await worker.run_once()
        self.assertEqual(self.real.store.get(identity)['status'],'waiting_quota')
        with self.real.store.db() as db: db.execute('UPDATE jobs SET retry_at=0 WHERE id=?',(identity,))
        await worker.run_once()
        result=self.real.store.get(identity)
        self.assertEqual(result['status'],'completed',result.get('message'))
        self.assertEqual(result['transactions']['total'],1202)
        self.assertEqual(counts,sorted(counts))
