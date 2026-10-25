"""End-to-end live-adapter contracts with controlled chain providers."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

import httpx

from apps.backend.app.adapters.analysis_rpc import AnalysisRpc
from apps.backend.app.adapters.analysis_store import LeaseLost, utc
from apps.backend.app.adapters.etherscan_budget import EtherscanBudget
from apps.backend.app.adapters.etherscan_client import BackendEtherscan
from apps.backend.app.adapters.mock_predictor import EthInputRegistry, MockPredictor
from apps.backend.app.application.eth_pipeline import EthPipeline
from apps.backend.app.application.eth_presentation import eth_amount
from apps.backend.app.api.schemas import AnalysisResult
from apps.backend.app.main import create_app
from apps.backend.app.settings import Settings
from apps.backend.app.workers.analysis import AnalysisWorker

ROOT = '0x' + '11' * 20
OTHER = '0x' + '22' * 20
THIRD = '0x' + '33' * 20
STAMP = 1792796000


def tx(number, source, destination, value, internal=False):
    row = {'hash': '0x' + f'{number:064x}', 'from': source, 'to': destination,
           'blockNumber': '99', 'timeStamp': str(STAMP - 100), 'value': str(value),
           'isError': '0', 'gasUsed': '21000', 'input': '0x', 'gasPrice': '1000000000',
           'blockHash': '0x' + 'aa' * 32, 'transactionIndex': str(number)}
    if internal:
        row.update(traceId='0_1', type='call')
    return row


class Chain:
    def __init__(self, contract=False, empty=False):
        self.contract, self.empty = contract, empty
        self.calls, self.deliveries = [], []
        self.rpc_down = False
        self.external = [tx(2, OTHER, ROOT, 50), tx(1, OTHER if contract else ROOT, ROOT if contract else OTHER, 100)]
        self.internal = [tx(3, ROOT, THIRD, 20, True)] if contract else []
        self.tokens = []

    def rpc(self, request):
        if self.rpc_down:
            raise httpx.ReadTimeout('private-provider-token', request=request)
        body = json.loads(request.content); method, params = body['method'], body['params']
        if method == 'eth_chainId': result = '0x1'
        elif method == 'eth_getBlockByNumber':
            number = 112 if params[0] == 'latest' else int(params[0], 16)
            result = {'number': hex(number), 'hash': '0x' + f'{number:064x}', 'timestamp': hex(STAMP + (number - 100) * 12)}
        elif method == 'eth_getCode': result = '0x60016000' if self.contract else '0x'
        elif method == 'eth_getBalance': result = hex(10**18 + 1)
        else: raise AssertionError(method)
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})

    def etherscan(self, request):
        params = dict(request.url.params); self.calls.append(params)
        action = params['action']
        if action == 'getblocknobytime': result = '1'
        elif action == 'getsourcecode': result = [{'ContractName': 'Real-chain test vault', 'ABI': '[]', 'CompilerVersion': 'v0.8'}]
        elif action == 'getcontractcreation': result = [{'contractCreator': OTHER, 'txHash': '0x' + 'cc' * 32}]
        elif action in ('txlist', 'txlistinternal', 'tokentx'):
            rows = [] if self.empty else {'txlist': self.external, 'txlistinternal': self.internal, 'tokentx': self.tokens}[action]
            result = [deepcopy(r) for r in rows if params['address'] in (r['from'], r['to'])
                      and int(params.get('startblock', 0)) <= int(r['blockNumber']) <= int(params.get('endblock', 100))]
            offset, page = int(params.get('offset', 1000)), int(params.get('page', 1))
            result = result[(page - 1) * offset:page * offset]
        else: raise AssertionError(action)
        return httpx.Response(200, json={'status': '1', 'message': 'OK', 'result': result})

    def nonexistent(self, request):
        self.deliveries.append(json.loads(request.content))
        raise httpx.ConnectError('Expected temporary target unavailable', request=request)


class LiveEthChecks(unittest.IsolatedAsyncioTestCase):
    def test_native_amounts_preserve_all_digits_and_signed_net_flow(self):
        self.assertEqual(eth_amount(123456789012345678901234567890123456), '123456789012345678.901234567890123456')
        self.assertEqual(eth_amount(-1), '-0.000000000000000001')
        self.assertEqual(eth_amount(10**18), '1')

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.settings = Settings(analysis_mode='eth_live_mock', etherscan_api_key='private-test-key',
            ethereum_rpc_url='https://rpc.example/private-provider-token', analysis_database_path=str(root / 'jobs.sqlite3'),
            analysis_artifact_path=str(root / 'artifacts'), etherscan_quota_path=str(root / 'quota.sqlite3'))
        self.app = create_app(self.settings)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')
        self.real = self.app.state.container.real
        self.now = time.time()
        async def sleep(delay): self.now += delay
        self.sleep = sleep
        self.real.budget = EtherscanBudget(self.settings.etherscan_quota_path, clock=lambda: self.now, sleep=sleep)
        self.pipelines = []

    async def asyncTearDown(self):
        for pipeline in self.pipelines: await pipeline.close()
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    def worker(self, chain):
        registry = EthInputRegistry(self.settings)
        predictor = MockPredictor(self.settings, registry, transport=httpx.MockTransport(chain.nonexistent))
        pipeline = EthPipeline(self.settings, self.real.store, self.real.budget,
            rpc=AnalysisRpc(self.settings, transport=httpx.MockTransport(chain.rpc)),
            etherscan=BackendEtherscan(self.settings, self.real.budget, transport=httpx.MockTransport(chain.etherscan), sleep=self.sleep),
            predictor=predictor)
        self.pipelines.append(pipeline)
        return AnalysisWorker(self.app.state.container, 'test-worker', pipeline=pipeline)

    async def submit(self, idem='job'):
        response = await self.client.post('/api/v1/analyses', json={'target': ROOT, 'family': 'eth_scam'},
                                          headers={'Idempotency-Key': idem})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()['analysis_id']

    async def test_wallet_real_data_null_ponzi_and_persisted_model_payload(self):
        chain = Chain(); worker = self.worker(chain); identity = await self.submit()
        await worker.run_once()
        response = await self.client.get('/api/v1/analyses/' + identity)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['status'], 'completed', result['message'])
        tasks = {r['task_id']: r for r in result['tasks']}
        self.assertEqual(tasks['ponzi']['status'], 'not_applicable')
        self.assertIsNone(tasks['ponzi']['score'])
        self.assertEqual(tasks['phishing']['score'], .999)
        self.assertEqual(tasks['phishing']['label'], 'High Risk')
        self.assertEqual(tasks['phishing']['risk_band'], 'high')
        self.assertEqual(tasks['phishing']['result_origin'], 'simulated')
        self.assertTrue(tasks['phishing']['model_version'].startswith('simulated:'))
        self.assertEqual(result['basic_information']['balance_wei'], str(10**18 + 1))
        self.assertEqual(result['transactions']['total'], 2)
        self.assertEqual(sum(int(p['inflow_wei']) for p in result['activity']['points']), 50)
        self.assertEqual(sum(int(p['outflow_wei']) for p in result['activity']['points']), 100)
        self.assertEqual(len(chain.deliveries), 1)
        payload = chain.deliveries[0]
        self.assertEqual(payload['sample_id'], tasks['phishing']['sample_id'])
        self.assertEqual(set(payload['inputs']), {'node_features', 'edge_index', 'root_index'})
        self.assertTrue(all(len(row) == 20 for row in payload['inputs']['node_features']))
        self.assertLessEqual(len(payload['graph_sample']['node_refs']), 512)
        self.assertNotIn('observed_target', json.dumps(payload))
        self.assertNotIn('private-test-key', json.dumps(payload))
        self.assertEqual(result['graphs']['phishing']['context']['view_scope'], 'display_recent')
        # Restart recovery reuses captured data and the stored fixed outcome.
        with self.real.store.db() as db:
            recovered = deepcopy(result); recovered['status'] = 'running'
            db.execute('UPDATE jobs SET result=?,lease_until=0 WHERE id=?', (json.dumps(recovered), identity))
        network = len(chain.calls)
        await worker.run_once()
        self.assertEqual(len(chain.calls), network)
        self.assertEqual(len(chain.deliveries), 1)
        self.assertEqual((await self.client.get('/api/v1/analyses/' + identity)).json()['tasks'], result['tasks'])

    async def test_recovery_does_not_reuse_an_obsolete_random_mock_artifact(self):
        chain = Chain(); worker = self.worker(chain); identity = await self.submit()
        await worker.run_once()
        result = self.real.store.get(identity)
        with self.real.store.db() as db:
            row = db.execute("SELECT payload FROM artifacts WHERE job=? AND kind='mock_outcome_fixed_0999_v1' AND task='phishing'",(identity,)).fetchone()
            old = json.loads(row['payload']); old.update(score=.12, label='Low Risk', risk_band='low')
            db.execute("UPDATE artifacts SET kind='mock_outcome',payload=? WHERE job=? AND kind='mock_outcome_fixed_0999_v1'",(json.dumps(old),identity))
            result['status']='running'
            db.execute('UPDATE jobs SET result=?,lease_until=0 WHERE id=?',(json.dumps(result),identity))
        await worker.run_once()
        task = self.real.store.get(identity)['tasks'][0]
        self.assertEqual(task['score'],.999)
        self.assertEqual(task['label'],'High Risk')
        self.assertEqual(len(chain.deliveries),2)

    async def test_confirmed_facts_precede_history_without_fabricated_zero_counts(self):
        chain = Chain(contract=True)
        observed = []
        original = chain.etherscan
        identity = await self.submit()
        def inspect(request):
            if request.url.params['action'] in ('getblocknobytime', 'txlist'):
                result = self.real.store.get(identity)
                AnalysisResult.model_validate(result)
                observed.append(result)
            return original(request)
        chain.etherscan = inspect
        await self.worker(chain).run_once()
        self.assertGreaterEqual(len(observed), 2)
        for result in observed[:2]:
            facts = result['basic_information']
            self.assertEqual(facts['entity_type'], 'contract')
            self.assertEqual(facts['balance_wei'], str(10**18 + 1))
            fields = {f['key']: f['value'] for f in facts['fields']}
            self.assertEqual(fields['balance'], '1.000000000000000001')
            for key in ('inflow', 'outflow', 'net', 'external', 'internal', 'counterparties', 'first', 'last'):
                self.assertEqual(fields[key], '—')
            self.assertEqual(result.get('window_start'), utc(STAMP - 30 * 86400))
            self.assertIsNone(result.get('activity'))
        final = self.real.store.get(identity)
        fields = {f['key']: f['value'] for f in final['basic_information']['fields']}
        self.assertEqual(fields['external'], '2')
        self.assertEqual(fields['internal'], '1')
        self.assertEqual(final['snapshot_id'], observed[0]['snapshot_id'])

    async def test_quota_during_context_enrichment_retains_facts_and_frozen_cutoff(self):
        self.real.budget = EtherscanBudget(self.settings.etherscan_quota_path, limit=1, clock=lambda: self.now, sleep=self.sleep)
        chain = Chain(contract=True); worker = self.worker(chain); identity = await self.submit()
        await worker.run_once()
        paused = self.real.store.get(identity)
        self.assertEqual(paused['status'], 'waiting_quota')
        self.assertEqual(paused['basic_information']['balance_wei'], str(10**18 + 1))
        self.assertIsNone(paused['basic_information']['source_verification'])
        self.assertFalse(self.real.store.artifact(identity, 'context')['resolution_complete'])
        self.now = self.real.budget.snapshot().resets_at
        self.real.budget = EtherscanBudget(self.settings.etherscan_quota_path, clock=lambda: self.now, sleep=self.sleep)
        worker.pipeline.etherscan.budget = self.real.budget
        with self.real.store.db() as db: db.execute('UPDATE jobs SET retry_at=0 WHERE id=?', (identity,))
        await worker.run_once()
        final = self.real.store.get(identity)
        self.assertEqual(final['status'], 'completed')
        for key in ('snapshot_id', 'cutoff', 'cutoff_block', 'cutoff_block_hash'):
            self.assertEqual(final[key], paused[key])
        self.assertEqual(paused.get('window_start'), utc(STAMP - 30 * 86400))
        self.assertEqual(final['window_start'], utc(self.real.store.artifact(identity, 'context')['window_start']))
        self.assertEqual(sum(p['action'] == 'getblocknobytime' for p in chain.calls), 1)

    async def test_contract_both_tasks_and_ledger_scope_pagination_events(self):
        chain = Chain(contract=True); worker = self.worker(chain); identity = await self.submit()
        await worker.run_once()
        result = (await self.client.get('/api/v1/analyses/' + identity)).json()
        self.assertEqual(result['status'], 'completed', result['message'])
        self.assertEqual([r['status'] for r in result['tasks']], ['ok', 'ok'])
        self.assertEqual(len(chain.deliveries), 2)
        internal = await self.client.get(f'/api/v1/analyses/{identity}/transactions?category=internal&limit=1')
        self.assertEqual(internal.json()['total'], 1)
        external = (await self.client.get(f'/api/v1/analyses/{identity}/transactions?category=external&limit=1')).json()
        self.assertIsNotNone(external['next_cursor'])
        wrong = await self.client.get(f'/api/v1/analyses/{identity}/transactions', params={'category':'internal','cursor':external['next_cursor']})
        self.assertEqual(wrong.status_code, 400)
        stream = await self.client.get(f'/api/v1/analyses/{identity}/events')
        self.assertIn('event: progress', stream.text)
        self.assertIn('"stage": "collecting"', stream.text)
        self.assertIn('"stage": "completed"', stream.text)
        self.assertEqual(sum(int(p['outflow_wei']) for p in result['activity']['points']), 20)

    async def test_external_token_amounts_use_exact_units_contract_and_direction(self):
        chain = Chain()
        chain.external[-1]['value'] = '0'
        chain.external[-1]['input'] = '0xa9059cbb'
        failed = tx(3, ROOT, THIRD, 0); failed['isError'] = '1'
        chain.external.insert(0, failed)
        def token(number, contract, raw, src=ROOT, dst=OTHER, decimals='6'):
            return {**tx(number, src, dst, raw), 'contractAddress': contract,
                    'tokenDecimal': decimals, 'tokenSymbol': 'USDT'}
        chain.tokens = [token(1, THIRD, 1000001), token(1, THIRD, 2000000),
                        token(1, OTHER, 500, OTHER, ROOT), token(1, THIRD, 123, decimals=''),
                        token(3, THIRD, 9000000)]
        identity = await self.submit(); await self.worker(chain).run_once()
        result = self.real.store.get(identity)
        self.assertEqual(result['status'], 'completed')
        rows = {int(r['hash'], 16): r for r in result['transactions']['items']}
        self.assertEqual(rows[1]['value_raw'], '0')
        self.assertEqual(rows[1]['amounts'], [
            {'asset':'USDT', 'raw':'3000001', 'decimals':6, 'contract_address':THIRD, 'direction':'outgoing'},
            {'asset':'USDT', 'raw':'500', 'decimals':6, 'contract_address':OTHER, 'direction':'incoming'}])
        self.assertEqual(rows[3]['amounts'], [])
        self.assertEqual(sum(int(p['inflow_wei']) for p in result['activity']['points']), 50)
        self.assertEqual(sum(int(p['outflow_wei']) for p in result['activity']['points']), 0)
        self.assertEqual(self.real.store.artifact(identity, 'token_ledger')['records'], 5)

    async def test_token_api_unavailable_preserves_native_data_and_scores(self):
        chain = Chain(); original = chain.etherscan
        def transport(request):
            if request.url.params['action'] == 'tokentx':
                return httpx.Response(200, json={'status':'0', 'message':'NOTOK', 'result':'Unable to retrieve records'})
            return original(request)
        chain.etherscan = transport
        identity = await self.submit(); await self.worker(chain).run_once()
        result = self.real.store.get(identity)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['transactions']['total'], 2)
        self.assertEqual(result['tasks'][0]['status'], 'ok')
        self.assertEqual(self.real.store.artifact(identity, 'token_ledger')['status'], 'unavailable')

    async def test_complete_30_day_ledger_is_independent_of_bounded_graph(self):
        chain = Chain()
        chain.external = [tx(i + 100, '0x' + f'{i + 5000:040x}', ROOT, 1) for i in range(1001)]
        worker = self.worker(chain); identity = await self.submit()
        await worker.run_once()
        result = self.real.store.get(identity)
        self.assertEqual(result['status'], 'completed', result['message'])
        self.assertEqual(result['transactions']['total'], 1001)
        self.assertEqual(len(result['graphs']['phishing']['nodes']), 48)
        self.assertLessEqual(len(chain.deliveries[0]['graph_sample']['node_refs']), 512)
        self.assertTrue(any(r.get('offset') == '1000' and r.get('page') == '2' for r in chain.calls))
        self.assertEqual(sum(int(p['inflow_wei']) for p in result['activity']['points']), 1001)
        self.assertTrue(result['activity']['scope']['complete'])
        self.assertEqual(result['window_start'], utc(STAMP - 30 * 86400))

    async def test_display_stops_paging_early_and_merges_external_internal_by_recency(self):
        chain = Chain()
        chain.external = []
        for i in range(3000):
            row = tx(10000 - i, '0x' + f'{5000 + i:040x}', ROOT, 1)
            block = 99 - i // 40
            row.update(blockNumber=str(block), timeStamp=str(STAMP - (100 - block) * 12))
            chain.external.append(row)
        recent = tx(30000, THIRD, ROOT, 7, True)
        recent.update(blockNumber='100', timeStamp=str(STAMP))
        chain.internal = [recent]
        identity = await self.submit(); await self.worker(chain).run_once()
        result = self.real.store.get(identity)
        self.assertEqual(result['status'], 'completed', result['message'])
        self.assertEqual(len(result['graphs']['phishing']['nodes']), 48)
        fields = {f['key']: f['value'] for f in result['basic_information']['fields']}
        self.assertEqual(fields['external'], '3000')
        self.assertEqual(fields['internal'], '1')
        self.assertEqual(result['window_start'], utc(STAMP - 30 * 86400))
        native_calls = [p for p in chain.calls if p['action'] == 'txlist' and p.get('offset') == '1000' and p['address'] == ROOT]
        self.assertGreaterEqual(len(native_calls), 3)
        self.assertEqual(len(native_calls), len({json.dumps(p, sort_keys=True) for p in native_calls}))
        internal = await self.client.get(f'/api/v1/analyses/{identity}/transactions?category=internal')
        self.assertEqual(internal.json()['items'][0]['value_raw'], '7')
        self.assertEqual(sum(int(p['inflow_wei']) for p in result['activity']['points']), 3007)

    async def test_two_hop_display_reserves_16_leaves_and_uses_all_retained_times(self):
        chain = Chain()
        parents = ['0x' + f'{3000 + i:040x}' for i in range(70)]
        leaves = ['0x' + f'{9000 + i:040x}' for i in range(20)]
        chain.external = [tx(10000 - i, ROOT, parent, 1) for i, parent in enumerate(parents)]
        for i in range(4):
            for j in range(5):
                child = tx(20000 + i * 5 + j, parents[i], leaves[i * 5 + j], 1)
                child.update(blockNumber='90', timeStamp=str(STAMP - 1000))
                chain.external.append(child)
        chain.tokens = [{**tx(10000, ROOT, parents[0], 1000000), 'contractAddress': OTHER,
                         'tokenDecimal': '6', 'tokenSymbol': 'USDT'}]
        identity = await self.submit(); await self.worker(chain).run_once()
        result = self.real.store.get(identity)
        self.assertEqual(result['status'], 'completed', result['message'])
        graph = result['graphs']['phishing']
        self.assertEqual(len(graph['nodes']), 64)
        hops = {n['id']: n['hop'] for n in graph['nodes']}
        self.assertEqual(sum(h == 0 for h in hops.values()), 1)
        self.assertEqual(sum(h == 1 for h in hops.values()), 47)
        self.assertEqual(sum(h == 2 for h in hops.values()), 16)
        self.assertNotIn(parents[47], hops)
        self.assertEqual(result['window_start'], utc(STAMP - 30 * 86400))
        self.assertEqual(result['cutoff'], utc(STAMP))
        self.assertEqual(result['transactions']['total'], 70)
        ledger, total = self.real.store.transactions(identity, 'external', 100, 0)
        self.assertEqual(total, 70)
        self.assertEqual(sum(r['direction'] == 'neighbor' for r in ledger), 0)
        self.assertTrue(all(ROOT in (r['from_address'], r['to_address']) for r in ledger))
        self.assertEqual(sum(int(p['outflow_wei']) for p in result['activity']['points']), 70)
        self.assertEqual(sum(p['external_count'] for p in result['activity']['points']), 70)
        token_row = next(r for r in ledger if int(r['hash'], 16) == 10000)
        self.assertEqual(len(token_row['amounts']), 1)
        self.assertEqual(token_row['amounts'][0]['raw'], '1000000')
        for leaf in (n for n, h in hops.items() if h == 2):
            self.assertTrue(any(e['source'] in parents[:47] and e['target'] == leaf for e in graph['edges']))
            self.assertFalse(any({e['source'], e['target']} == {ROOT, leaf} for e in graph['edges']))
        self.assertFalse(any(p.get('address') in leaves for p in chain.calls))

    async def test_empty_address_returns_real_empty_ledger_and_no_random_score(self):
        chain = Chain(empty=True); worker = self.worker(chain); identity = await self.submit()
        await worker.run_once()
        result = (await self.client.get('/api/v1/analyses/' + identity)).json()
        self.assertEqual(result['status'], 'partial', result['message'])
        self.assertEqual(result['transactions']['items'], [])
        self.assertEqual(result['tasks'][0]['status'], 'insufficient_history')
        self.assertTrue(all(t['score'] is None for t in result['tasks']))
        self.assertEqual(chain.deliveries, [])

    async def test_full_window_updates_in_batches_and_graph_waits_for_ledger(self):
        chain = Chain(); chain.external = []
        for i in range(3000):
            row = tx(10000 - i, '0x' + f'{5000 + i:040x}', ROOT, 1)
            block = 99 - i // 40
            row.update(blockNumber=str(block), timeStamp=str(STAMP - (100 - block) * 12))
            chain.external.append(row)
        original = chain.etherscan; snapshots = []; root_calls = 0
        identity = await self.submit()
        def inspect(request):
            nonlocal root_calls
            params = dict(request.url.params)
            if params['action'] == 'txlist' and params.get('address') == ROOT and params.get('offset') == '1000':
                root_calls += 1
                if root_calls == 3:
                    snapshots.append(self.real.store.get(identity))
            if params['action'] == 'tokentx' and params.get('address') == ROOT:
                value = self.real.store.get(identity)
                self.assertTrue(value['activity']['scope']['complete'])
                self.assertEqual(value['graphs'], {})
                self.assertEqual(value['transactions']['total'], 3000)
            return original(request)
        chain.etherscan = inspect
        await self.worker(chain).run_once()
        self.assertEqual(len(snapshots), 1)
        partial = snapshots[0]
        self.assertEqual(partial['graphs'], {})
        self.assertFalse(partial['activity']['scope']['complete'])
        self.assertGreater(partial['transactions']['total'], 0)
        self.assertLess(partial['transactions']['total'], 3000)
        self.assertEqual(sum(int(p['inflow_wei']) for p in partial['activity']['points']), partial['transactions']['total'])
        final = self.real.store.get(identity)
        self.assertEqual(final['status'], 'completed')
        self.assertEqual(final['transactions']['total'], 3000)
        self.assertGreater(final['transactions']['revision'], partial['transactions']['revision'])

    async def test_incremental_root_internal_traces_do_not_double_native_flow(self):
        chain = Chain(contract=True)
        duplicate = tx(1, OTHER, ROOT, 100, True); duplicate['traceId'] = '0'
        chain.internal.append(duplicate)
        identity = await self.submit(); await self.worker(chain).run_once()
        result = self.real.store.get(identity)
        self.assertEqual(result['status'], 'completed', result['message'])
        self.assertEqual(sum(int(p['inflow_wei']) for p in result['activity']['points']), 150)
        self.assertEqual(sum(int(p['outflow_wei']) for p in result['activity']['points']), 20)
        internal = await self.client.get(f'/api/v1/analyses/{identity}/transactions?category=internal')
        self.assertEqual(internal.json()['total'], 2)

    async def test_partial_window_retry_does_not_erase_or_reduce_published_ledger(self):
        chain = Chain(); chain.external = []
        for i in range(3000):
            row = tx(10000 - i, '0x' + f'{5000 + i:040x}', ROOT, 1)
            block = 99 - i // 40
            row.update(blockNumber=str(block), timeStamp=str(STAMP - (100 - block) * 12))
            chain.external.append(row)
        original = chain.etherscan; failing = True
        def transport(request):
            params = dict(request.url.params)
            if (failing and params['action'] == 'txlist' and params.get('address') == ROOT
                    and params.get('offset') == '1000' and int(params['endblock']) <= 27):
                raise httpx.ReadTimeout('temporary provider unavailable', request=request)
            return original(request)
        chain.etherscan = transport
        worker = self.worker(chain); identity = await self.submit()
        await worker.run_once()
        paused = self.real.store.get(identity)
        self.assertEqual(paused['progress']['state'], 'retrying')
        published = paused['transactions']['total']
        self.assertGreater(published, 1000)
        failing = False
        original_save = self.real.store.save
        def checked_save(lease, patch, **kwargs):
            if patch.get('transactions') is not None:
                self.assertGreaterEqual(patch['transactions']['total'], published)
            return original_save(lease, patch, **kwargs)
        self.real.store.save = checked_save
        with self.real.store.db() as db: db.execute('UPDATE jobs SET retry_at=0 WHERE id=?', (identity,))
        await worker.run_once()
        result = self.real.store.get(identity)
        self.assertEqual(result['status'], 'completed', result['message'])
        self.assertEqual(result['transactions']['total'], 3000)
        self.assertEqual(sum(int(p['inflow_wei']) for p in result['activity']['points']), 3000)

    async def test_quota_pause_rejects_new_work_then_recovers_without_refetching(self):
        self.real.budget = EtherscanBudget(self.settings.etherscan_quota_path, limit=2, clock=lambda: self.now, sleep=self.sleep)
        chain = Chain(); worker = self.worker(chain); identity = await self.submit()
        await worker.run_once()
        result = (await self.client.get('/api/v1/analyses/' + identity)).json()
        self.assertEqual(result['status'], 'waiting_quota')
        self.assertEqual(result['progress']['state'], 'waiting_quota')
        blocked = await self.client.post('/api/v1/analyses', json={'target': ROOT, 'family': 'eth_scam'})
        self.assertEqual(blocked.status_code, 429)
        self.assertIn('retry_at', blocked.json())
        retry = await self.client.post('/api/v1/analyses', json={'target': ROOT, 'family': 'eth_scam'}, headers={'Idempotency-Key':'job'})
        self.assertEqual(retry.json()['analysis_id'], identity)
        context = self.real.store.artifact(identity, 'context')
        self.now = self.real.budget.snapshot().resets_at
        self.real.budget = EtherscanBudget(self.settings.etherscan_quota_path, clock=lambda: self.now, sleep=self.sleep)
        worker.pipeline.etherscan.budget = self.real.budget
        with self.real.store.db() as db: db.execute('UPDATE jobs SET retry_at=0 WHERE id=?', (identity,))
        await worker.run_once()
        self.assertEqual(self.real.store.get(identity)['status'], 'completed')
        self.assertEqual(self.real.store.artifact(identity, 'context'), context)
        first_page = [r for r in chain.calls if r['action']=='txlist' and r.get('offset')=='1000' and r['address'] == ROOT]
        self.assertEqual(len(first_page), 1)

    async def test_expired_lease_is_fenced_and_queue_has_global_concurrency_limit(self):
        identity = await self.submit('first')
        await self.submit('second'); await self.submit('third')
        store = self.real.store
        first = store.claim('a', concurrency=2)
        second = store.claim('b', concurrency=2)
        self.assertIsNotNone(second)
        self.assertIsNone(store.claim('c', concurrency=2))
        with store.db() as db: db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (first['id'],))
        recovered = store.claim('c', concurrency=2)
        self.assertNotEqual(recovered['token'], first['token'])
        with self.assertRaises(LeaseLost): store.save(first, {'message':'stale worker'})
        store.save(recovered, {'message':'current owner'})
        self.assertEqual(store.get(identity)['message'], 'current owner')

    async def test_rpc_failure_is_durable_and_retries_without_secret_leak(self):
        chain = Chain(); chain.rpc_down = True; worker = self.worker(chain); identity = await self.submit()
        await worker.run_once()
        result = self.real.store.get(identity)
        self.assertEqual(result['progress']['state'], 'retrying')
        self.assertNotIn('private-provider-token', json.dumps(result))
        self.assertTrue(all(t.get('score') is None for t in result['tasks']))
        chain.rpc_down = False
        with self.real.store.db() as db: db.execute('UPDATE jobs SET retry_at=0 WHERE id=?', (identity,))
        await worker.run_once()
        self.assertEqual(self.real.store.get(identity)['status'], 'completed')


if __name__ == '__main__': unittest.main()
