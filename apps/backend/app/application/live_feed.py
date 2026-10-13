"""Real chain feed, independent of the analysis/demo adapters."""
import asyncio
from collections import deque
from datetime import datetime
import json
import re
import time
from fastapi.responses import StreamingResponse
from ..adapters.feed_store import FeedStore, utc
from ..api.schemas import FeedTransaction
from ..adapters.feed_rpc import FeedRpc, RpcUnavailable


class LiveFeedService:
    enabled = True

    def __init__(self, store: FeedStore):
        self.store = store

    async def recent(self, limit: int):
        return self.store.snapshot(limit)

    async def events(self, last_event_id: str | None):
        async def stream():
            try:
                last = int(last_event_id) if last_event_id is not None else -1
            except ValueError:
                last = -1
            if last < 0:
                snapshot = self.store.snapshot()
                last = snapshot['sequence']
                yield self.encode(last, 'snapshot', snapshot)
            heartbeat = time.monotonic()
            while True:
                for seq, kind, data in self.store.replay(last):
                    yield self.encode(seq, kind, data)
                    last = seq
                if time.monotonic() - heartbeat >= 5:
                    # No event ID: status heartbeats cannot advance replay past a transaction.
                    meta = self.store.snapshot()
                    meta.pop('transactions')
                    yield 'event: status\ndata: ' + json.dumps(meta, separators=(',', ':')) + '\n\n'
                    heartbeat = time.monotonic()
                await asyncio.sleep(.5)
        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    @staticmethod
    def encode(sequence, kind, data):
        return f'id: {sequence}\nevent: {kind}\ndata: {json.dumps(data, separators=(",", ":"))}\n\n'


class LiveFeedCollector:
    """Poll headers every 4s; bound catch-up to 4 blocks, history to 32 headers."""
    def __init__(self, rpc: FeedRpc, store: FeedStore, clock=time.monotonic):
        self.rpc, self.store = rpc, store
        self.candidates = deque()
        self.next_publish = 0.0
        self.clock = clock
        self.chain_verified = False
        self.receipts = {}
        self.receipt_slots = asyncio.Semaphore(4)

    def discard_candidates(self):
        self.candidates.clear()
        for task in self.receipts.values():
            task.cancel()
        self.receipts.clear()

    async def close(self):
        tasks = list(self.receipts.values())
        self.discard_candidates()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def fetch_receipt(self, tx_hash):
        async with self.receipt_slots:
            try:
                return await asyncio.wait_for(self.rpc.receipt(tx_hash), timeout=2)
            except (TimeoutError, RpcUnavailable):
                return None

    async def poll_block(self):
        if not self.chain_verified:
            await self.rpc.verify_chain()
            self.chain_verified = True
        head = await self.rpc.block('latest', False)
        number = int(head['number'], 16)
        state = self.store.state()
        previous = state.get('head_block')
        if previous == number and head['hash'] == state.get('head_hash'):
            self.store.update(checked_at=utc(), source_status='live', message=None)
            return
        if previous is not None:
            # A temporarily lagging provider must not rewind an otherwise canonical view.
            if number < previous:
                raise RpcUnavailable('Ethereum RPC is behind the collected head')
            same = await self.rpc.block(previous, False)
            if same['hash'] != state['head_hash']:
                self.discard_candidates()
                ancestor = None
                for height, known_hash in sorted(self.store.blocks().items(), reverse=True):
                    if height == previous:
                        continue
                    if (await self.rpc.block(height, False))['hash'] == known_hash:
                        ancestor = height
                        break
                self.store.rollback(ancestor, 'Chain reorganization: refreshed the affected transactions')
                previous = ancestor
            if previous is not None and number - previous > 4:
                self.store.rollback(None, 'Collector caught up to the latest block; intervening samples were skipped')
                previous = None
        start = number if previous is None else previous + 1
        blocks = []
        parent = self.store.state().get('head_hash') if previous is not None else None
        for height in range(start, number + 1):
            block = await self.rpc.block(height)
            if int(block['number'], 16) != height or (parent and block['parentHash'] != parent):
                raise RpcUnavailable('Chain changed during collection; retrying the canonical head')
            blocks.append(block)
            parent = block['hash']
        if not blocks:
            return
        if blocks[-1]['hash'] != head['hash']:
            raise RpcUnavailable('Chain changed during collection; retrying the canonical head')
        # Only sample the current head. Recovered blocks establish continuity, not a playback backlog.
        latest = blocks[-1]
        transactions = [tx for tx in latest['transactions'] if int(quantity(tx['value'])) > 0]
        selected = min(24, len(transactions))
        rows = [normalize(transactions[len(transactions) - 1 - index * len(transactions) // selected], latest)
                for index in range(selected)]
        self.store.accept(blocks)
        self.discard_candidates()
        self.candidates = deque(rows)
        # Bounded prefetch removes receipt round-trip time from steady-state publication.
        self.receipts = {row['hash']: asyncio.create_task(self.fetch_receipt(row['hash'])) for row in rows}

    async def publish_sample(self):
        if self.clock() < self.next_publish:
            return
        while self.candidates:
            row = self.candidates.popleft()
            task = self.receipts.pop(row['hash'], None)
            age = time.time() - datetime.fromisoformat(row['block_time']).timestamp()
            if age > 45 or age < -30 or int(row['value_wei']) <= 0:
                if task:
                    task.cancel()
                continue
            receipt = await task if task else await self.fetch_receipt(row['hash'])
            if receipt is not None:
                if (receipt.get('transactionHash') != row['hash'] or receipt.get('blockHash') != row['block_hash']
                        or int(receipt['blockNumber'], 16) != row['block_number']):
                    self.discard_candidates()
                    raise RpcUnavailable('Receipt inclusion changed; refreshing the chain')
                gas_used = quantity(receipt['gasUsed'])
                price = quantity(receipt['effectiveGasPrice']) if receipt.get('effectiveGasPrice') else None
                row.update(gas_used=gas_used, effective_gas_price_wei=price,
                           execution_fee_wei=str(int(gas_used) * int(price)) if price is not None else None,
                           status={'0x1': 'success', '0x0': 'failed'}.get(receipt.get('status')))
            result = FeedTransaction.model_validate(row).model_dump(mode='json')
            self.next_publish = self.clock() + .5
            if self.store.publish(result):
                return


def quantity(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]+', value):
        raise RpcUnavailable('Malformed RPC quantity')
    return str(int(value, 16))


def normalize(tx: dict, block: dict) -> dict:
    for key, digits in [('hash', 64), ('from', 40), ('to', 40)]:
        if key == 'to' and tx.get(key) is None:
            continue
        if not re.fullmatch(r'0x[0-9a-fA-F]{' + str(digits) + '}', tx.get(key, '')):
            raise RpcUnavailable('Malformed Ethereum transaction identity')
    if tx.get('blockHash') != block['hash'] or tx.get('blockNumber') != block['number']:
        raise RpcUnavailable('Transaction belongs to a different block')
    return FeedTransaction(
        hash=tx['hash'], from_address=tx['from'], to_address=tx['to'], block_hash=block['hash'],
        transaction_index=int(quantity(tx['transactionIndex'])), block_number=int(quantity(block['number'])),
        block_time=utc(int(quantity(block['timestamp']))), value_wei=quantity(tx['value']), gas_limit=quantity(tx['gas']),
    ).model_dump(mode='json')
