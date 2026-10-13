"""Exercise job timing, replay, persistence and data consistency through HTTP."""
import asyncio
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from httpx import ASGITransport, AsyncClient
from apps.backend.app.main import create_app
from apps.backend.app.settings import Settings
from apps.backend.app.demo.datasets import ETH_TARGET, TOKEN_TARGET, POOL, CUTOFF, FIXTURE_DIRECTORY, build_dataset
from apps.backend.app.api.schemas import AnalysisRequest


class DemoChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(analysis_mode='demo', demo_database_path=str(Path(self.temp.name) / 'jobs.sqlite3'), demo_delay_scale=.02)
        await self.open()

    async def open(self):
        self.app = create_app(self.settings)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url='http://local')

    async def close(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    async def asyncTearDown(self):
        await self.close()
        self.temp.cleanup()

    async def create(self, family='eth_scam', key=None):
        response = await self.client.post('/api/v1/analyses', json={
            'target': ETH_TARGET if family == 'eth_scam' else TOKEN_TARGET,
            'family': family, 'pools': [POOL] if family == 'token_scam' else [],
        }, headers={'Idempotency-Key': key} if key else {})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    async def wait(self, identity, stage='completed'):
        for _ in range(300):
            result = (await self.client.get(f'/api/v1/analyses/{identity}')).json()
            self.assertNotEqual(result['status'], 'failed', result)
            if result['stage'] == stage:
                return result
            await asyncio.sleep(.003)
        self.fail(f'Job did not reach {stage}')

    async def test_delays_graph_before_scores_and_replay(self):
        accepted = await self.create()
        identity = accepted['analysis_id']
        self.assertEqual(accepted['status'], 'queued')
        self.assertFalse(accepted['graphs'])
        self.assertTrue(all(task['score'] is None for task in accepted['tasks']))
        early = await self.wait(identity, 'predicting')
        self.assertTrue(early['graphs'])
        self.assertTrue(early['activity']['points'])
        self.assertIsNotNone(early['transactions']['next_cursor'])
        self.assertTrue(all(task['score'] is None for task in early['tasks']))
        complete = await self.wait(identity)
        self.assertEqual([task['risk_band'] for task in complete['tasks']], ['medium', 'low'])
        for task in complete['tasks']:
            self.assertEqual(task['sample_id'], complete['graphs'][task['task_id']]['sample_id'])
        events = await self.client.get(f'/api/v1/analyses/{identity}/events')
        self.assertIn('text/event-stream', events.headers['content-type'])
        records = [json.loads(line[6:]) for line in events.text.splitlines() if line.startswith('data: ')]
        self.assertEqual([row['stage'] for row in records], ['queued', 'resolving', 'collecting', 'normalizing', 'building_graph', 'predicting', 'completed'])
        replay = await self.client.get(f'/api/v1/analyses/{identity}/events', headers={'Last-Event-ID': '5'})
        self.assertNotIn('id: 5\n', replay.text)
        self.assertIn('id: 6\n', replay.text)
        self.assertEqual((await self.client.get(f'/api/v1/analyses/{identity}/events', headers={'Last-Event-ID': '999'})).status_code, 400)

    async def test_token_categories_pagination_and_identity(self):
        identity = (await self.create('token_scam'))['analysis_id']
        result = await self.wait(identity)
        self.assertEqual([task['risk_band'] for task in result['tasks']], ['high', 'medium'])
        self.assertEqual(result['basic_information']['entity_type'], 'token')
        query = f'/api/v1/analyses/{identity}/transactions'
        seen = set()
        cursor = None
        while True:
            params = {'category': 'pool_event', 'limit': 17}
            if cursor:
                params['cursor'] = cursor
            page = (await self.client.get(query, params=params)).json()
            self.assertTrue(all(row['category'] == 'pool_event' for row in page['items']))
            self.assertTrue(all(row['log_index'] is not None and row['pool'] == POOL for row in page['items']))
            ids = {row['id'] for row in page['items']}
            self.assertFalse(seen & ids)
            seen |= ids
            cursor = page['next_cursor']
            if not cursor:
                self.assertEqual(len(seen), page['total'])
                break
        transfer_cursor = result['transactions']['next_cursor']
        self.assertEqual((await self.client.get(query, params={'category': 'pool_event', 'cursor': transfer_cursor})).status_code, 400)
        self.assertEqual((await self.client.get(query, params={'category': 'external'})).status_code, 422)

    async def test_idempotency_persistence_and_scope(self):
        first = await self.create(key='same-operation')
        repeated = await self.create(key='same-operation')
        self.assertEqual(first['analysis_id'], repeated['analysis_id'])
        conflict = await self.client.post('/api/v1/analyses', headers={'Idempotency-Key': 'same-operation'},
                                          json={'target': TOKEN_TARGET, 'family': 'token_scam'})
        self.assertEqual(conflict.status_code, 409)
        complete = await self.wait(first['analysis_id'])
        await self.close()
        await self.open()
        saved = (await self.client.get('/api/v1/analyses/' + first['analysis_id'])).json()
        self.assertEqual(saved, complete)
        arbitrary = await self.client.post('/api/v1/analyses', json={'target': '0x' + '11' * 20, 'family': 'eth_scam'})
        self.assertEqual(arbitrary.status_code, 202)
        resolved = await self.wait(arbitrary.json()['analysis_id'])
        self.assertEqual(resolved['target'], '0x' + '11' * 20)
        self.assertEqual([task['score'] for task in resolved['tasks']], [task['score'] for task in complete['tasks']])
        missing = await self.client.get('/api/v1/analyses/00000000-0000-0000-0000-000000000000')
        self.assertEqual(missing.status_code, 404)

    async def test_capabilities_do_not_claim_real_models_or_feed(self):
        value = (await self.client.get('/api/v1/capabilities')).json()
        self.assertTrue(value['analysis_enabled'])
        self.assertTrue(value['events_enabled'])
        self.assertEqual(value['result_origin'], 'synthetic')
        self.assertFalse(value['feed_enabled'])
        self.assertFalse(any(task['model_available'] for task in value['tasks']))
        self.assertEqual((await self.client.get('/api/v1/feed/recent')).status_code, 501)

    async def test_any_valid_address_uses_the_frozen_family_scenario(self):
        for family in ('eth_scam', 'token_scam'):
            address = '0x' + ('AB' if family == 'eth_scam' else 'CD') * 20
            response = await self.client.post('/api/v1/analyses', json={
                'target': address, 'family': family, 'cutoff': '2020-01-01T00:00:00Z',
            })
            self.assertEqual(response.status_code, 202)
            self.assertEqual(datetime.fromisoformat(response.json()['cutoff']), CUTOFF)
            result = await self.wait(response.json()['analysis_id'])
            self.assertEqual(result['target'], address.lower())
            self.assertEqual(result['family'], family)
            self.assertEqual([item['risk_band'] for item in result['tasks']], ['medium', 'low'] if family == 'eth_scam' else ['high', 'medium'])
            for graph in result['graphs'].values():
                roots = [node for node in graph['nodes'] if node['is_root']]
                self.assertEqual([node['ref'] for node in roots], [address.lower()])
            if family == 'token_scam':
                pool = result['basic_information']['pools'][0]
                self.assertLess(pool['token0'], pool['token1'])
                self.assertIn(address.lower(), (pool['token0'], pool['token1']))
        malformed = await self.client.post('/api/v1/analyses', json={'target': '0x123', 'family': 'eth_scam'})
        self.assertEqual(malformed.status_code, 422)

    def test_frozen_values_reuse_and_address_collision(self):
        for family, canonical in [('eth_scam', ETH_TARGET), ('token_scam', TOKEN_TARGET)]:
            baseline = build_dataset(AnalysisRequest(target=canonical, family=family), 'first')
            changed = build_dataset(AnalysisRequest(target='0x' + 'ff' * 20, family=family), 'second')
            self.assertEqual(baseline['result']['activity']['points'], changed['result']['activity']['points'])
            self.assertEqual(baseline['result']['basic_information']['fields'], changed['result']['basic_information']['fields'])
            for before, after in zip(baseline['ledger'], changed['ledger'], strict=True):
                for field in ('hash', 'value_raw', 'block_time', 'block_number', 'amounts', 'status'):
                    self.assertEqual(before[field], after[field])
            graph = next(iter(baseline['result']['graphs'].values()))
            collision = next(node['ref'] for node in graph['nodes'] if not node['is_root'])
            aliased = build_dataset(AnalysisRequest(target=collision, family=family), 'collision')
            for graph in aliased['result']['graphs'].values():
                ids = [node['id'] for node in graph['nodes']]
                self.assertEqual(len(ids), len(set(ids)))
                self.assertEqual([node['ref'] for node in graph['nodes'] if node['is_root']], [collision])
                self.assertTrue(all(edge['source'] in ids and edge['target'] in ids for edge in graph['edges']))
            self.assertEqual(build_dataset(AnalysisRequest(target=canonical, family=family), 'first'), baseline)

    def test_ledger_chart_graph_reconciliation_and_exact_units(self):
        for family, target in [('eth_scam', ETH_TARGET), ('token_scam', TOKEN_TARGET)]:
            dataset = build_dataset(AnalysisRequest(target=target, family=family), 'sample-analysis')
            result, ledger = dataset['result'], dataset['ledger']
            self.assertEqual(len(result['activity']['points']), 30)
            cutoff = datetime.fromisoformat(result['cutoff'])
            self.assertTrue(all(datetime.fromisoformat(row['block_time']) <= cutoff for row in ledger))
            self.assertEqual(len({row['id'] for row in ledger}), len(ledger))
            rows_by_date = defaultdict(list)
            for row in ledger:
                rows_by_date[row['block_time'][:10]].append(row)
            for point in result['activity']['points']:
                rows = rows_by_date[point['date']]
                if family == 'eth_scam':
                    self.assertEqual(int(point['inflow_wei']), sum(int(row['value_raw']) for row in rows if row['direction'] == 'inflow' and row['status'] == 'success'))
                    self.assertEqual(point['external_count'], sum(row['category'] == 'external' for row in rows))
                else:
                    self.assertEqual(point['transfer_count'], sum(row['category'] == 'token_transfer' for row in rows))
                    self.assertEqual(point['burn_count'], sum(row['event'] == 'Burn' for row in rows))
            for graph in result['graphs'].values():
                ids = {node['id'] for node in graph['nodes']}
                self.assertEqual(sum(node['is_root'] for node in graph['nodes']), 1)
                self.assertEqual(graph['context']['sample_id'], graph['sample_id'])
                self.assertTrue(any(edge['kind'] == 'observed' and target not in (edge['source'], edge['target']) for edge in graph['edges']))
                self.assertGreater(len(graph['nodes']), 35)
                for edge in graph['edges']:
                    self.assertIn(edge['source'], ids)
                    self.assertIn(edge['target'], ids)
                    if edge['kind'] == 'structural':
                        self.assertIsNone(edge['amount'])
                    else:
                        rows = [row for row in dataset['graph_events'] if row['from_address'] == edge['source'] and row['to_address'] == edge['target'] and row['status'] == 'success' and row['category'] != 'pool_event']
                        self.assertEqual(edge['event_count'], len(rows))
                        self.assertEqual(Decimal(edge['amount']) * 10**18, sum(int(row['value_raw']) for row in rows))

    def test_contract_calls_traces_and_balance_are_chain_consistent(self):
        fixture = json.loads((FIXTURE_DIRECTORY / 'eth_scam.json').read_text())
        target = fixture['result']['target']
        roles = {node['ref']: node['role'] for node in next(iter(fixture['result']['graphs'].values()))['nodes']}
        balance = int(fixture['metadata']['opening_balance_wei'])
        for row in sorted(fixture['ledger'], key=lambda row: (row['block_number'], row['transaction_index'], row['trace_id'] or '')):
            if row['category'] == 'external':
                self.assertNotEqual(row['from_address'], target, 'A plain smart contract does not sign transactions')
                self.assertEqual(row['to_address'], target)
            else:
                self.assertIsNotNone(row['trace_id'])
                self.assertEqual(roles[row['from_address']], 'contract')
            if row['status'] == 'success':
                balance += int(row['value_raw']) * (1 if row['direction'] == 'inflow' else -1)
                self.assertGreaterEqual(balance, 0)
        self.assertEqual(balance, int(fixture['result']['basic_information']['balance_wei']))
        self.assertEqual(balance, int(fixture['metadata']['closing_balance_wei']))

    def test_token_logs_pool_reserves_and_holdings_reconcile(self):
        fixture = json.loads((FIXTURE_DIRECTORY / 'token_scam.json').read_text())
        rows = fixture['ledger']
        pair = fixture['result']['basic_information']['pools'][0]
        arc_index = 0 if pair['token0'] == TOKEN_TARGET else 1
        self.assertLess(pair['token0'], pair['token1'])
        grouped = defaultdict(list)
        for row in rows:
            grouped[row['hash']].append(row)
        r0, r1 = (int(fixture['metadata']['initial_pool_reserves'][key]) for key in ('reserve0', 'reserve1'))
        operations = sorted((row for row in rows if row['category'] == 'pool_event' and row['event'] != 'Sync'),
                            key=lambda row: (row['block_number'], row['transaction_index']))
        for row in operations:
            siblings = grouped[row['hash']]
            self.assertEqual(len({(event['block_number'], event['block_time'], event['transaction_index']) for event in siblings}), 1)
            self.assertEqual(len({event['log_index'] for event in siblings}), len(siblings))
            sync = next(event for event in siblings if event['event'] == 'Sync')
            transfer = next(event for event in siblings if event['event'] == 'Transfer')
            self.assertLess(sync['log_index'], row['log_index'])
            self.assertEqual(transfer['emitter'], TOKEN_TARGET)
            self.assertEqual(row['emitter'], POOL)
            fields = row['event_data']
            if row['event'] == 'Swap':
                in0, in1, out0, out1 = (int(fields[key]) for key in ('amount0In', 'amount1In', 'amount0Out', 'amount1Out'))
                next0, next1 = r0 + in0 - out0, r1 + in1 - out1
                self.assertGreaterEqual((next0 * 1000 - in0 * 3) * (next1 * 1000 - in1 * 3), r0 * r1 * 1000**2)
                self.assertEqual(int(transfer['value_raw']), in0 + out0 if arc_index == 0 else in1 + out1)
                r0, r1 = next0, next1
            else:
                amount0, amount1 = int(fields['amount0']), int(fields['amount1'])
                sign = 1 if row['event'] == 'Mint' else -1
                self.assertEqual(int(transfer['value_raw']), amount0 if arc_index == 0 else amount1)
                r0, r1 = r0 + sign * amount0, r1 + sign * amount1
            self.assertGreater(r0, 0)
            self.assertGreater(r1, 0)
            self.assertEqual((r0, r1), (int(sync['event_data']['reserve0']), int(sync['event_data']['reserve1'])))
        self.assertEqual((r0, r1), tuple(int(fixture['metadata']['final_pool_reserves'][key]) for key in ('reserve0', 'reserve1')))
        holdings = {owner: int(value) for owner, value in fixture['metadata']['opening_token_balances'].items()}
        supply = int(fixture['result']['basic_information']['total_supply_raw'])
        self.assertEqual(sum(holdings.values()), supply)
        for row in sorted((row for row in rows if row['category'] == 'token_transfer'), key=lambda row: (row['block_number'], row['transaction_index'], row['log_index'])):
            quantity = int(row['value_raw'])
            holdings[row['from_address']] -= quantity
            holdings[row['to_address']] = holdings.get(row['to_address'], 0) + quantity
            self.assertGreaterEqual(holdings[row['from_address']], 0)
        self.assertEqual(sum(holdings.values()), supply)
        self.assertEqual(holdings[POOL], r0 if arc_index == 0 else r1)


if __name__ == '__main__':
    unittest.main()
