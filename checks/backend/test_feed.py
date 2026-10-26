"""Feed invariants with a deterministic RPC double; no network in unit checks."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
import httpx

from apps.backend.app.adapters.feed_store import FeedStore, utc
from apps.backend.app.adapters.feed_rpc import FeedRpc, RpcUnavailable
from apps.backend.app.adapters.feed_price import EthUsdPrice
from apps.backend.app.application.live_feed import LiveFeedCollector, LiveFeedService, normalize
from apps.backend.app.api.schemas import FeedSnapshot
from apps.backend.app.main import create_app
from apps.backend.app.settings import Settings


def identity(number):
    return '0x' + f'{number:064x}'


def block(number, parent, branch=0, count=24):
    result = {'number': hex(number), 'hash': identity(number + branch * 10000), 'parentHash': parent,
              'timestamp': hex(int(time.time())), 'transactions': []}
    result['transactions'] = [dict(hash=identity(number * 1000 + branch * 100000 + i),
        blockHash=result['hash'], blockNumber=hex(number), transactionIndex=hex(i),
        **{'from': '0x' + '11' * 20, 'to': None if i == 0 else '0x' + '22' * 20},
        value=hex(10**20 + 123), gas='0x15f90') for i in range(count)]
    return result


class RpcDouble:
    def __init__(self):
        self.chain = {10: block(10, identity(9))}; self.head = 10; self.calls = []
        self.receipt_missing = False; self.receipt_bad_block = False

    async def verify_chain(self):
        self.calls.append('chain')

    async def block(self, height, full=True):
        self.calls.append((height, full))
        return deepcopy(self.chain[self.head if height == 'latest' else height])

    async def receipt(self, tx_hash):
        if self.receipt_missing:
            return None
        for entry in self.chain.values():
            if any(tx['hash'] == tx_hash for tx in entry['transactions']):
                return {'transactionHash': tx_hash, 'blockHash': identity(999) if self.receipt_bad_block else entry['hash'],
                        'blockNumber': entry['number'], 'gasUsed': '0x5208', 'effectiveGasPrice': hex(1234567891), 'status': '0x0'}
        return None

    def append(self, branch=0):
        self.chain[self.head+1] = block(self.head+1, self.chain[self.head]['hash'], branch)
        self.head += 1


class FeedChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FeedStore(os.path.join(self.temp.name, 'feed.sqlite3'))
        self.rpc = RpcDouble()
        self.collector = LiveFeedCollector(self.rpc, self.store)

    async def asyncTearDown(self):
        await self.collector.close()
        self.store.close(); self.temp.cleanup()

    async def test_sample_bounds_precision_receipts_and_rate(self):
        await self.collector.poll_block()
        self.assertEqual(len(self.collector.candidates), 24)
        await self.collector.publish_sample()
        row = self.store.snapshot()['transactions'][0]
        self.assertEqual(row['value_wei'], str(10**20 + 123))
        self.assertEqual(row['gas_limit'], '90000')
        self.assertEqual(row['gas_used'], '21000')
        self.assertEqual(row['execution_fee_wei'], str(21000 * 1234567891))
        self.assertEqual(row['status'], 'failed')
        await self.collector.publish_sample()
        self.assertEqual(len(self.store.snapshot()['transactions']), 1)
        self.assertFalse(self.store.publish(row))
        FeedSnapshot.model_validate(self.store.snapshot())

    async def test_positive_value_filter_and_half_second_publication(self):
        for tx in self.rpc.chain[10]['transactions'][::2]: tx['value'] = '0x0'
        await self.collector.poll_block()
        self.assertEqual(len(self.collector.candidates), 12)
        self.assertTrue(all(int(row['value_wei']) > 0 for row in self.collector.candidates))
        self.assertEqual(len(self.collector.receipts), 12)
        with patch.object(self.collector, 'clock', return_value=100):
            await self.collector.publish_sample()
        with patch.object(self.collector, 'clock', return_value=100.49):
            await self.collector.publish_sample()
        self.assertEqual(len(self.store.snapshot()['transactions']), 1)
        with patch.object(self.collector, 'clock', return_value=100.5):
            await self.collector.publish_sample()
        self.assertEqual(len(self.store.snapshot()['transactions']), 2)
        self.assertFalse(self.store.publish({**self.store.snapshot()['transactions'][0], 'hash': identity(9000), 'value_wei': '0'}))

    async def test_price_cache_expiry_and_zero_value_policy_migration(self):
        row = normalize(self.rpc.chain[10]['transactions'][0], self.rpc.chain[10])
        self.store.publish(row)
        with self.store.db:
            seq = self.store._event('transaction', {})
            self.store.db.execute('INSERT INTO feed_rows VALUES (?,?,?,?)',
                (identity(99999), 10, json.dumps({**row, 'hash': identity(99999), 'value_wei': '0'}), seq))
        self.store.apply_positive_filter()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM feed_rows').fetchone()[0], 1)
        self.assertEqual(self.store.replay(seq)[0][1], 'snapshot')
        sequence = self.store.snapshot()['sequence']
        self.store.apply_positive_filter()
        self.assertEqual(self.store.snapshot()['sequence'], sequence)
        self.store.update(usd_quote={'price': '2493.055', 'fetched_at': utc(), 'source': 'Coinbase spot'})
        self.assertEqual(self.store.snapshot()['usd_quote']['price'], '2493.055')
        self.store.update(usd_quote={'price': '2493.055', 'fetched_at': utc(time.time()-301), 'source': 'Coinbase spot'})
        self.assertIsNone(self.store.snapshot()['usd_quote'])

    async def test_public_price_currency_and_response_validation(self):
        def respond(request):
            self.assertNotIn('authorization', request.headers)
            return httpx.Response(200, json={'data': {'base': 'ETH', 'currency': 'USD', 'amount': '2493.055'}})
        price = EthUsdPrice(httpx.MockTransport(respond))
        self.assertEqual((await price.fetch())['price'], '2493.055')
        await price.close()
        for data in [{'base': 'BTC', 'currency': 'USD', 'amount': '2000'},
                     {'base': 'ETH', 'currency': 'USD', 'amount': 'NaN'},
                     {'base': 'ETH', 'currency': 'USD', 'amount': '0'}]:
            price = EthUsdPrice(httpx.MockTransport(lambda request: httpx.Response(200, json={'data': data})))
            with self.assertRaises(ValueError): await price.fetch()
            await price.close()

    async def test_empty_block_missing_receipt_and_creation(self):
        self.rpc.chain[10]['transactions'] = self.rpc.chain[10]['transactions'][:1]
        self.rpc.receipt_missing = True
        await self.collector.poll_block(); await self.collector.publish_sample()
        row = self.store.snapshot()['transactions'][0]
        self.assertIsNone(row['to_address']); self.assertIsNone(row['gas_used'])
        self.assertIsNone(row['status']); self.assertIsNone(row['execution_fee_wei'])
        self.rpc.append(); self.rpc.chain[11]['transactions'] = []
        await self.collector.poll_block()
        self.assertEqual(len(self.collector.candidates), 0)

    async def test_new_head_replaces_queue_and_same_head_avoids_full_refetch(self):
        await self.collector.poll_block()
        full_before = len([call for call in self.rpc.calls if isinstance(call, tuple) and call[1]])
        await self.collector.poll_block()
        self.assertEqual(full_before, len([call for call in self.rpc.calls if isinstance(call, tuple) and call[1]]))
        self.rpc.append(); await self.collector.poll_block()
        self.assertTrue(all(row['block_number'] == 11 for row in self.collector.candidates))
        self.assertEqual(self.rpc.calls.count('chain'), 1)

    async def test_reorganization_removes_orphans_and_resets_clients(self):
        await self.collector.poll_block(); await self.collector.publish_sample()
        self.rpc.append(); await self.collector.poll_block()
        self.collector.next_publish = 0; await self.collector.publish_sample()
        seq = self.store.snapshot()['sequence']
        self.rpc.chain[11] = block(11, self.rpc.chain[10]['hash'], branch=1)
        await self.collector.poll_block()
        rows = self.store.snapshot()['transactions']
        self.assertEqual([row['block_number'] for row in rows], [10])
        events = self.store.replay(seq)
        self.assertEqual(events[0][1], 'snapshot')
        self.assertEqual(events[0][2]['transactions'][0]['block_number'], 10)
        self.assertTrue(all(row['block_hash'] == self.rpc.chain[11]['hash'] for row in self.collector.candidates))
        self.assertIsNotNone(self.store.snapshot()['last_gap_at'])

    async def test_gap_recovery_is_bounded_and_lagging_rpc_does_not_rewind(self):
        await self.collector.poll_block(); await self.collector.publish_sample()
        for _ in range(8): self.rpc.append()
        self.rpc.calls.clear(); await self.collector.poll_block()
        self.assertEqual(len([c for c in self.rpc.calls if isinstance(c, tuple) and c[1]]), 1)
        self.assertEqual(self.store.snapshot()['head_block'], 18)
        self.assertIsNotNone(self.store.snapshot()['last_gap_at'])
        self.rpc.head = 17
        with self.assertRaises(RpcUnavailable): await self.collector.poll_block()
        self.assertEqual(self.store.snapshot()['head_block'], 18)

    async def test_wrong_receipt_cannot_publish_and_expired_queue_is_dropped(self):
        await self.collector.poll_block(); self.rpc.receipt_bad_block = True
        with self.assertRaises(RpcUnavailable): await self.collector.publish_sample()
        self.assertEqual(self.store.snapshot()['transactions'], [])
        self.rpc.append(); self.rpc.chain[11]['timestamp'] = hex(int(time.time()) - 50)
        await self.collector.poll_block(); await self.collector.publish_sample()
        self.assertEqual(self.store.snapshot()['transactions'], [])

    async def test_sequence_replay_retention_snapshot_and_store_reopen(self):
        row = normalize(self.rpc.chain[10]['transactions'][0], self.rpc.chain[10])
        for index in range(305):
            self.store.publish({**row, 'hash': identity(50000+index)})
        snapshot = self.store.snapshot()
        self.assertEqual(len(snapshot['transactions']), 30)
        self.assertEqual(len(self.store.snapshot(100)['transactions']), 100)
        self.assertEqual(len(self.store.replay(snapshot['sequence']-2)), 2)
        reset = self.store.replay(1)[0]
        self.assertEqual(reset[1], 'snapshot')
        self.assertEqual(reset[2]['sequence'], snapshot['sequence'])
        self.assertEqual(self.store.replay(snapshot['sequence']), [])
        other = FeedStore(self.store.path)
        self.assertEqual(other.snapshot(), snapshot); other.close()

    async def test_single_owner_lock_and_freshness(self):
        self.store.acquire()
        other = FeedStore(self.store.path)
        with self.assertRaises(RuntimeError): other.acquire()
        other.close()
        await self.collector.poll_block()
        self.assertEqual(self.store.snapshot()['status'], 'live')
        self.store.update(checked_at=utc(time.time()-30))
        self.assertEqual(self.store.snapshot()['status'], 'stale')

    async def test_sse_initial_snapshot_and_replay(self):
        await self.collector.poll_block(); await self.collector.publish_sample()
        service = LiveFeedService(self.store)
        response = await service.events(None)
        event = await anext(response.body_iterator)
        self.assertIn('event: snapshot', event); self.assertIn('id: 1', event)
        await response.body_iterator.aclose()
        response = await service.events('0')
        event = await anext(response.body_iterator)
        self.assertIn('event: transaction', event)
        await response.body_iterator.aclose()

    async def test_api_capabilities_independent_of_analysis_mode(self):
        app = create_app(Settings(feed_enabled=True, feed_database_path=self.store.path))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
                caps = (await client.get('/api/v1/capabilities')).json()
                self.assertTrue(caps['feed_enabled']); self.assertFalse(caps['analysis_enabled'])
                recent = await client.get('/api/v1/feed/recent')
                self.assertEqual(recent.status_code, 200)
                self.assertEqual(recent.json()['transactions'], [])
                self.assertEqual((await client.get('/api/v1/feed/recent?limit=101')).status_code, 422)

    async def test_rpc_chain_validation_and_error_redaction(self):
        def respond(request):
            return httpx.Response(200, json={'id': json.loads(request.content)['id'], 'result': '0x89'})
        rpc = FeedRpc('https://provider.test/secret', httpx.MockTransport(respond))
        with self.assertRaisesRegex(RpcUnavailable, 'mainnet'): await rpc.verify_chain()
        await rpc.close()
        def fail(request):
            return httpx.Response(429, json={'error': 'secret'})
        rpc = FeedRpc('https://provider.test/secret', httpx.MockTransport(fail))
        with self.assertRaises(RpcUnavailable) as error: await rpc.block('latest')
        self.assertNotIn('secret', str(error.exception)); await rpc.close()


if __name__ == '__main__': unittest.main()
