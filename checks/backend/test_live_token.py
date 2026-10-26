"""Live ERC-20 contracts with controlled providers, never production fixtures."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from apps.backend.app.adapters.analysis_rpc import AnalysisRpc
from apps.backend.app.adapters.etherscan_client import BackendEtherscan
from apps.backend.app.adapters.remote_predictor import RemotePredictor
from checks.backend.model_fixtures import model_response
from apps.backend.app.adapters.model_inputs import TokenInputRegistry
from apps.backend.app.application.token_pipeline import TokenPipeline
from apps.backend.app.application.token_collection import TokenCollection, uint_word, abi_text, QUOTES
from apps.backend.app.api.schemas import AnalysisResult
from apps.backend.app.main import create_app
from apps.backend.app.settings import Settings
from apps.backend.app.errors import QuotaExhausted
from apps.backend.app.workers.analysis import AnalysisWorker
from packages.graph import graph_recipe
from packages.token import UNISWAP_V2_FACTORY
from packages.transactions import TRANSFER_TOPIC, V2_TOPICS

ROOT = '0x' + '11'*20
POOL = '0x' + '22'*20
WALLET = '0x' + '33'*20
QUOTE = QUOTES[0][0]
STAMP = 1792796000


def word(number):
    return f'{number:064x}'


def topic(entity):
    return '0x' + entity[2:].rjust(64, '0')


def log(number, emitter, relation, src=WALLET, dst=POOL, amount=10, block=99):
    first = TRANSFER_TOPIC if relation == 'erc20_transfer' else next(k for k,v in V2_TOPICS.items() if v == relation)
    topics = [first]
    if relation == 'erc20_transfer':
        topics += [topic(src), topic(dst)]; values = [amount]
    elif relation == 'pair_created':
        topics += [topic(ROOT), topic(QUOTE)]; values = [int(POOL,16), 1]
    elif relation == 'swap':
        topics += [topic(src), topic(dst)]; values = [0, 30, amount, 0]
    elif relation == 'mint':
        topics += [topic(src)]; values = [amount, 30]
    elif relation == 'burn':
        topics += [topic(src), topic(dst)]; values = [amount, 30]
    else:
        values = [amount, 3000]
    return {'address': emitter, 'topics': topics, 'data': '0x'+''.join(word(v) for v in values),
        'transactionHash': '0x'+word(number+1), 'blockNumber': hex(block), 'timeStamp': hex(STAMP-(100-block)*12),
        'logIndex': hex(number), 'transactionIndex': hex(number//4), 'blockHash': '0x'+word(block)}


class TokenChain:
    def __init__(self, count=70, pool=True, quote=QUOTE):
        self.pool = pool
        self.quote = quote
        self.calls, self.deliveries = [], []
        self.logs = [log(i, ROOT, 'erc20_transfer', dst='0x'+f'{0x1000+i:040x}') for i in range(count)]
        self.logs += [log(10000+i, POOL, relation, dst=WALLET) for i,relation in enumerate(('swap','mint','burn','sync'))] if pool else []
        self.logs += [log(11000, POOL, 'erc20_transfer', dst=WALLET)] if pool else []
        self.observer = None
        self.invalid_decimals = False
        self.non_token = False
        self.fail_once = False
        self.factory_mismatch = False

    def rpc(self, request):
        body = json.loads(request.content); method, params = body['method'], body['params']
        if method == 'eth_chainId': result='0x1'
        elif method == 'eth_getBlockByNumber':
            number = 112 if params[0]=='latest' else int(params[0],16)
            result={'number':hex(number), 'timestamp':hex(STAMP+(number-100)*12), 'hash':'0x'+word(number)}
        elif method == 'eth_getBalance': result='0x0'
        elif method == 'eth_getCode': result='0x' if self.non_token else '0x60016000'
        elif method == 'eth_call':
            to, data = params[0]['to'], params[0]['data']
            assert isinstance(params[1],dict) and params[1]['requireCanonical']
            if data == '0x313ce567': result = '0x' if self.invalid_decimals else '0x'+word(6 if to==ROOT else 18)
            elif data == '0x18160ddd': result='0x'+word(10**18+123)
            elif data.startswith('0x70a08231'): result='0x'+word(0)
            elif data in ('0x95d89b41','0x06fdde03'):
                result='0x'+('REAL' if data=='0x95d89b41' else 'Real Token').encode().hex().ljust(64,'0')
            elif data == '0x0dfe1681': result=topic(min(ROOT,self.quote))
            elif data == '0xd21220a7': result=topic(max(ROOT,self.quote))
            elif data == '0xc45a0155': result=topic(WALLET if self.factory_mismatch else UNISWAP_V2_FACTORY)
            elif data.startswith('0xe6a43905'): result=topic(POOL)
            else: raise AssertionError(data)
        else: raise AssertionError(method)
        return httpx.Response(200,json={'id':body['id'],'jsonrpc':'2.0','result':result})

    def etherscan(self, request):
        params=dict(request.url.params); self.calls.append(params)
        if self.observer:
            self.observer(params)
        action=params['action']
        if action=='getblocknobytime': result='1'
        elif action=='getsourcecode': result=[{'ContractName':'Verified Token','CompilerVersion':'v0.8','ABI':'[]'}]
        elif action=='getcontractcreation': result=[]
        elif action=='getLogs':
            if params['address']==UNISWAP_V2_FACTORY:
                slot = 'topic1' if 'topic1' in params else 'topic2'
                matching_slot='topic1' if ROOT < self.quote else 'topic2'
                result=[log(12000, UNISWAP_V2_FACTORY, 'pair_created', block=10)] if self.pool and slot==matching_slot else []
                if result:
                    result[0]['topics'][1:]=[topic(min(ROOT,self.quote)),topic(max(ROOT,self.quote))]
            else:
                result=[deepcopy(r) for r in self.logs if r['address']==params['address']
                    and int(params['fromBlock']) <= int(r['blockNumber'],16) <= int(params['toBlock'])]
                # Deliberately ascending: the adapter must not assume descending logs.
                result.sort(key=lambda r:(int(r['blockNumber'],16),int(r['logIndex'] or '0x0',16)))
                limit, page=int(params['offset']),int(params['page'])
                result=result[(page-1)*limit:page*limit]
                if self.fail_once and page==2:
                    self.fail_once=False
                    raise httpx.ReadTimeout('private-test-value',request=request)
        elif action in ('txlist','txlistinternal'): result=[]
        else: raise AssertionError(action)
        return httpx.Response(200,json={'status':'1','message':'OK','result':result})

    def predict(self, request):
        payload=json.loads(request.content);self.deliveries.append(payload)
        return httpx.Response(200,json=model_response(payload))


class LiveTokenChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.settings=Settings(analysis_mode='eth_live',inference_url='https://model.example',inference_api_key='private-inference-key', ethereum_rpc_url='https://rpc.example/private', etherscan_api_key='private-key',
            analysis_database_path=str(root/'jobs.sqlite'), analysis_artifact_path=str(root/'artifacts'), etherscan_quota_path=str(root/'quota.sqlite'))
        self.app=create_app(self.settings)
        self.lifespan=self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.real=self.app.state.container.real
        self.real.store.worker_tick('test')
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test')
        self.pipelines=[]
        self.real.budget.acquire=self.sleep

    async def sleep(self,*_): pass

    async def asyncTearDown(self):
        await self.client.aclose()
        for pipeline in self.pipelines: await pipeline.close()
        await self.lifespan.__aexit__(None,None,None)

    def worker(self,chain):
        predictor=RemotePredictor(self.settings,TokenInputRegistry(self.settings),transport=httpx.MockTransport(chain.predict))
        pipeline=TokenPipeline(self.settings,self.real.store,self.real.budget,
            rpc=AnalysisRpc(self.settings,transport=httpx.MockTransport(chain.rpc)),
            etherscan=BackendEtherscan(self.settings,self.real.budget,transport=httpx.MockTransport(chain.etherscan),sleep=self.sleep,retries=0),predictor=predictor)
        self.pipelines.append(pipeline)
        return AnalysisWorker(self.app.state.container,'token-test',pipeline=pipeline)

    async def submit(self, **scope):
        response=await self.client.post('/api/v1/analyses',json={'target':ROOT,'family':'token_scam',**scope})
        self.assertEqual(response.status_code,202,response.text)
        return response.json()['analysis_id']

    async def test_complete_token_history_separate_graph_and_exact_frozen_model_inputs(self):
        chain=TokenChain(); worker=self.worker(chain); identity=await self.submit()
        await worker.run_once()
        result=self.real.store.get(identity)
        AnalysisResult.model_validate(result)
        self.assertEqual(result['status'],'completed',result['message'])
        self.assertEqual(result['family'],'token_scam')
        self.assertEqual(result['transactions']['total'],70)
        self.assertEqual(sum(p['transfer_count'] for p in result['activity']['points']),70)
        self.assertEqual(sum(p['swap_count'] for p in result['activity']['points']),1)
        self.assertTrue(result['activity']['scope']['complete'])
        facts=result['basic_information']
        self.assertEqual(facts['decimals'],6)
        self.assertEqual(facts['total_supply_raw'],str(10**18+123))
        self.assertEqual(facts['pools'][0]['address'],POOL)
        graph=result['graphs']['honeypot']
        self.assertLessEqual(len(graph['nodes']),64)
        self.assertLessEqual(sum(n['hop'] in (0,1) for n in graph['nodes']),48)
        self.assertLessEqual(sum(n['hop']==2 for n in graph['nodes']),16)
        self.assertEqual(len(chain.deliveries),2)
        self.assertTrue(any(edge['amount'] is not None and edge['asset']=='REAL' for edge in graph['edges']))
        for payload in chain.deliveries:
            manifest=worker.pipeline.registry.entries[payload['task_id']][0]
            self.assertEqual(graph_recipe(payload['graph_sample']),manifest['graph_recipe'])
            self.assertNotIn('inputs',payload)
            self.assertEqual(len(payload['graph_sample']['node_features'][0]),35)
            self.assertEqual(len(payload['graph_sample']['edge_attributes'][0]),17)
            self.assertNotIn('private-key',json.dumps(payload))
            self.assertEqual(payload['graph_sample']['quality']['status'],'ok')
        rows=(await self.client.get(f'/api/v1/analyses/{identity}/transactions?category=pool_event')).json()
        self.assertEqual(rows['total'],5)
        self.assertEqual({r['event'] for r in rows['items']},{'Swap','Mint','Burn','Sync','LP Transfer'})
        swap=next(r for r in rows['items'] if r['event']=='Swap')
        self.assertEqual(swap['amounts'][0]['decimals'],6)
        self.assertEqual(swap['amounts'][0]['raw'],'10')
        self.assertEqual(len(swap['amounts']),2)
        self.assertEqual((await self.client.get(f'/api/v1/analyses/{identity}/transactions?category=external')).status_code,422)
        # Retries reuse all observations and persisted fixed scores.
        sample_before=self.real.store.artifact(identity,'graph_sample','honeypot')
        with self.real.store.db() as db:
            replay=deepcopy(result); replay['status']='running'
            db.execute('UPDATE jobs SET result=?,lease_until=0 WHERE id=?',(json.dumps(replay),identity))
        network=len(chain.calls)
        await worker.run_once()
        self.assertEqual(len(chain.calls),network)
        self.assertEqual(len(chain.deliveries),2)
        self.assertEqual(self.real.store.get(identity)['tasks'],result['tasks'])
        self.assertEqual(self.real.store.artifact(identity,'graph_sample','honeypot'),sample_before)

    async def test_non_weth_quote_discovery_checks_second_indexed_token_position(self):
        quote='0x'+'01'*20
        chain=TokenChain(quote=quote)
        identity=await self.submit(); await self.worker(chain).run_once()
        result=self.real.store.get(identity)
        self.assertEqual(result['status'],'completed',result['message'])
        selected=result['basic_information']['pools'][0]
        self.assertEqual(selected['paired_asset'],quote)
        self.assertEqual(selected['token1'],ROOT)

    async def test_no_supported_pool_keeps_token_activity_with_unavailable_reasons(self):
        chain=TokenChain(pool=False); identity=await self.submit(); await self.worker(chain).run_once()
        result=self.real.store.get(identity)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['transactions']['total'],70)
        self.assertEqual(result['basic_information']['pools'],[])
        self.assertTrue(all(t['status']=='not_applicable' and t['score'] is None and t['reason'] for t in result['tasks']))
        self.assertFalse(chain.deliveries)

    async def test_wallet_and_non_erc20_calls_never_receive_scores(self):
        for case in ('non_token','invalid_decimals'):
            chain=TokenChain(); setattr(chain,case,True)
            identity=await self.submit(); await self.worker(chain).run_once()
            result=self.real.store.get(identity)
            self.assertTrue(all(t['status']=='invalid_token' and t['score'] is None and t['reason'] for t in result['tasks']))
            self.assertFalse(chain.deliveries)

    async def test_supplied_pool_requires_factory_membership(self):
        chain=TokenChain(); chain.factory_mismatch=True
        identity=await self.submit(pools=[POOL]); await self.worker(chain).run_once()
        self.assertTrue(all(t['status']=='invalid_pool' and t['score'] is None for t in self.real.store.get(identity)['tasks']))
        self.assertFalse(chain.deliveries)

    async def test_progressive_full_window_precedes_graph_and_single_block_overflow_is_paged(self):
        chain=TokenChain(count=1200); identity=await self.submit(); snapshots=[]
        def observe(params):
            if params['action']=='getLogs' and params['address'] in (ROOT,POOL):
                snapshots.append(deepcopy(self.real.store.get(identity)))
        chain.observer=observe
        await self.worker(chain).run_once()
        result=self.real.store.get(identity)
        self.assertEqual(result['status'],'completed',result['message'])
        self.assertEqual(result['transactions']['total'],1200)
        self.assertTrue(any(s.get('transactions',{}).get('total',0)==1200 and not s['graphs'] for s in snapshots))
        self.assertTrue(any(s.get('basic_information',{}).get('decimals')==6 and not s.get('transactions') for s in snapshots))
        self.assertTrue(any(p.get('page')=='2' and p['fromBlock']==p['toBlock'] for p in chain.calls if p['action']=='getLogs'))
        self.assertEqual(len({r['id'] for r in self.real.store.transactions(identity,'token_transfer',1300,0)[0]}),1200)
        self.assertLessEqual(len(result['graphs']['honeypot']['nodes']),64)

    async def test_empty_model_history_is_unscored(self):
        chain=TokenChain(count=0); chain.logs=[]
        identity=await self.submit(); await self.worker(chain).run_once()
        result=self.real.store.get(identity)
        self.assertEqual(result['status'],'partial',result['message'])
        self.assertTrue(all(t['score'] is None and t['reason'] and t['status'] in ('no_activity','insufficient_history') for t in result['tasks']))
        self.assertFalse(chain.deliveries)

    async def test_quota_pause_preserves_partial_data_and_recovers_without_duplicate_rows(self):
        chain=TokenChain(count=1200)
        for index,row in enumerate(chain.logs[:1200]):
            block=99 if index < 1000 else 50
            row.update(blockNumber=hex(block),timeStamp=hex(STAMP-(100-block)*12))
        identity=await self.submit(); worker=self.worker(chain)
        pause=[True]; visible=[]
        def observe(params):
            if params['action']!='getLogs' or params['address']!=ROOT: return
            current=self.real.store.get(identity)
            total=(current.get('transactions') or {}).get('total',0)
            if total:
                visible.append(total)
            if pause[0] and total>=1000 and int(params['toBlock'])<=50:
                pause[0]=False
                raise QuotaExhausted(9999999999)
        chain.observer=observe
        await worker.run_once()
        paused=self.real.store.get(identity)
        self.assertEqual(paused['status'],'waiting_quota')
        self.assertEqual(paused['transactions']['total'],1000)
        self.assertFalse(paused['graphs'])
        with self.real.store.db() as db:
            db.execute('UPDATE jobs SET retry_at=0 WHERE id=?',(identity,))
        await worker.run_once()
        result=self.real.store.get(identity)
        self.assertEqual(result['status'],'completed',result['message'])
        self.assertEqual(result['transactions']['total'],1200)
        self.assertEqual(self.real.store.transactions(identity,'token_transfer',0,0)[1],1200)
        self.assertEqual(sorted(visible),visible)
        self.assertEqual(sum(p['transfer_count'] for p in result['activity']['points']),1200)

    async def test_malformed_and_duplicate_logs_fail_without_scores(self):
        for duplicate in (False,True):
            chain=TokenChain(count=1)
            if duplicate: chain.logs.append(deepcopy(chain.logs[0]))
            else: chain.logs[0]['logIndex']=None
            identity=await self.submit(); await self.worker(chain).run_once()
            self.assertTrue(all(t['status']=='data_incomplete' and t['score'] is None for t in self.real.store.get(identity)['tasks']))
            self.assertFalse(chain.deliveries)

    def test_abi_precision_and_text_are_validated(self):
        self.assertEqual(uint_word('0x'+word(255)),255)
        self.assertEqual(abi_text('0x'+'USDC'.encode().hex().ljust(64,'0')),'USDC')
        with self.assertRaises(ValueError): uint_word('0x')
        with self.assertRaises(ValueError): abi_text('0x'+word(64)+word(5))
