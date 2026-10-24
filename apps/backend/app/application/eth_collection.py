"""Real ETH observations with frozen block bounds and resumable request caches."""
import asyncio
from copy import deepcopy
import hashlib
import json
from itertools import groupby
from pathlib import Path

from packages.collection_recent import RecentHistoryCollector
from packages.data import normalize_records
from packages.io import atomic_bytes
from packages.transactions import address, integer

from ..adapters.analysis_store import utc
from ..errors import ServiceError
from .eth_presentation import basic_information


class EthCollection:
    DISPLAY_MAX_NODES = 64
    DISPLAY_FIRST_HOP_WITH_ROOT = 48
    DISPLAY_SECOND_HOP_MAX_NODES = 16
    DISPLAY_SECOND_HOP_PER_PARENT = 4
    DISPLAY_MAX_EDGES = 4096
    def __init__(self, store, lease, settings, etherscan, rpc):
        self.store, self.lease, self.settings = store, lease, settings
        self.etherscan, self.rpc = etherscan, rpc
        self.directory = Path(settings.analysis_artifact_path) / lease['id']
        self.directory.mkdir(parents=True, exist_ok=True)
        self.completed = self.records = 0

    def stage(self, name, message):
        self.completed = self.records = 0
        self.store.save(self.lease, {'status': 'running', 'stage': name, 'message': message,
            'progress': {'state': 'running', 'unit': 'requests', 'completed': 0,
                         'total': None, 'total_final': False, 'records_collected': 0}})

    async def fetch(self, module, action, **params):
        query = {'chainid': 1, 'module': module, 'action': action, **params}
        key = hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
        path = self.directory / 'requests' / f'{key}.json'
        if path.exists():
            cached = json.loads(path.read_text())
            digest = hashlib.sha256(json.dumps(cached['result'], sort_keys=True).encode()).hexdigest()
            if cached['query'] != query or cached['sha256'] != digest:
                raise ServiceError('data_incomplete')
            result = cached['result']
        else:
            result = await self.etherscan.request(module, action, **params)
            cached = {'query': query, 'result': result, 'retrieved_at': utc(),
                      'sha256': hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()}
            await asyncio.to_thread(atomic_bytes, path, json.dumps(cached).encode(), immutable=True)
        self.completed += 1
        self.records += len(result) if isinstance(result, list) and action in ('txlist', 'txlistinternal', 'tokentx') else 0
        self.store.save(self.lease, {'progress': {'state': 'running', 'unit': 'requests',
            'completed': self.completed, 'total': None, 'total_final': False, 'records_collected': self.records}})
        if action in ('txlist', 'txlistinternal', 'tokentx'):
            return [{**row, 'source_kind': {'txlist': 'normal', 'txlistinternal': 'internal', 'tokentx': 'token_transfer'}[action],
                     'request_id': key, 'source_row': index, 'raw_path': str(path),
                     'retrieved_at': cached['retrieved_at'], '_history_address': params['address'],
                     '_history_page': params.get('page', 1)} for index, row in enumerate(result)]
        return result

    async def freeze(self, request):
        context = self.store.artifact(self.lease['id'], 'context')
        if context and context.get('resolution_complete', True):
            return context
        if context is None:
            if await self.rpc.call('eth_chainId', []) != '0x1':
                raise ServiceError('unsupported_chain')
            head = await self.rpc.call('eth_getBlockByNumber', ['latest', False])
            head_number, head_time = integer(head['number']), integer(head['timestamp'])
            if request.cutoff:
                cutoff = int(request.cutoff.timestamp())
                if cutoff > head_time:
                    raise ServiceError('cutoff_in_future')
                number = integer(await self.fetch('block', 'getblocknobytime', timestamp=cutoff, closest='before'))
            else:
                number = max(0, head_number - 12)
            header = await self.rpc.call('eth_getBlockByNumber', [hex(number), False])
            if not isinstance(header, dict) or integer(header.get('number')) != number or not header.get('hash'):
                raise ServiceError('provider_response_invalid')
            cutoff = integer(header['timestamp'])
            entity = await self.rpc.classify_address(request.target, number)
            balance = await self.rpc.call('eth_getBalance', [request.target, hex(number)])
            if integer(balance) is None:
                raise ServiceError('provider_response_invalid')
            context = {'target': request.target, 'entity_type': entity.entity_type, 'cutoff': cutoff,
                       'cutoff_block': number, 'cutoff_hash': header['hash'], 'window_start': cutoff - 30 * 86400,
                       'balance_wei': str(integer(balance))}
            # Identity is frozen before optional enrichment or history requests.
            context['snapshot_id'] = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
            context.update(start_block=None, metadata={}, creation={}, resolution_complete=False,
                           metadata_complete=entity.entity_type != 'contract')
            self.publish_context(context)
        if context['start_block'] is None:
            start_block = integer(await self.fetch('block', 'getblocknobytime', timestamp=max(0, context['window_start']), closest='before'))
            if start_block is None or start_block > context['cutoff_block']:
                raise ServiceError('provider_response_invalid')
            context['start_block'] = start_block
            self.publish_context(context)
        if context['entity_type'] == 'contract' and not context['metadata_complete']:
            try:
                source = await self.fetch('contract', 'getsourcecode', address=request.target)
                if isinstance(source, list) and source:
                    context['metadata'] = {k: source[0].get(k) for k in ('ContractName', 'CompilerVersion', 'ABI')}
                    self.publish_context(context)
                created = await self.fetch('contract', 'getcontractcreation', contractaddresses=request.target)
                if isinstance(created, list) and created:
                    context['creation'] = {k: created[0].get(k) for k in ('contractCreator', 'txHash')}
            except ServiceError as error:
                if error.code in ('quota_exhausted', 'quota_store_unavailable'):
                    raise
                # Explorer verification/creation metadata is optional enrichment.
                context['metadata']['reason'] = error.code
        context.update(resolution_complete=True, metadata_complete=True)
        self.publish_context(context)
        return context

    def publish_context(self, context):
        self.store.save(self.lease, {'cutoff': utc(context['cutoff']), 'cutoff_block': context['cutoff_block'],
            'cutoff_block_hash': context['cutoff_hash'], 'window_start': utc(context['window_start']),
            'snapshot_id': context['snapshot_id'], 'basic_information': basic_information(context)},
            artifacts={('context', ''): context})

    @staticmethod
    def validate_rows(rows, entity, low, high, cutoff, descending=True):
        previous = high
        for row in rows:
            block, stamp = integer(row.get('blockNumber')), integer(row.get('timeStamp'))
            if block is None or not low <= block <= high or stamp is None or stamp > cutoff:
                raise ServiceError('data_incomplete')
            if entity not in {address(row.get('from')), address(row.get('to')), address(row.get('contractAddress'))}:
                raise ServiceError('data_incomplete')
            if descending and block > previous:
                raise ServiceError('data_incomplete')
            previous = block

    async def window(self, context, action):
        async def interval(low, high):
            collected = []
            for page in range(1, 11):
                rows = await self.fetch('account', action, address=context['target'], startblock=low,
                    endblock=high, sort='desc', page=page, offset=1000)
                self.validate_rows(rows, context['target'], low, high, context['cutoff'])
                collected.extend(rows)
                if len(collected) > 100000:
                    raise ServiceError('data_incomplete')
                if len(rows) < 1000:
                    return collected
            if low == high:
                raise ServiceError('data_incomplete')
            middle = (low + high) // 2
            newer = await interval(middle + 1, high)
            older = await interval(low, middle)
            if len(newer) + len(older) > 100000:
                raise ServiceError('data_incomplete')
            return newer + older
        rows = await interval(context['start_block'], context['cutoff_block'])
        if len(rows) > 100000:
            raise ServiceError('data_incomplete')
        return [r for r in rows if (context['window_start'] <= integer(r['timeStamp']) if context.get('boundary_inclusive')
                else context['window_start'] < integer(r['timeStamp'])) and integer(r['timeStamp']) <= context['cutoff']]

    async def blocks(self, context, action):
        """Yield complete blocks newest first without downloading older history.

        Withhold a full page's last block, then restart the range at that block
        so a provider's 10,000-result range ceiling cannot hide older pages.
        """
        low, high = context['start_block'], context['cutoff_block']
        while high >= low:
            rows = await self.fetch('account', action, address=context['target'], startblock=low,
                                    endblock=high, sort='desc', page=1, offset=1000)
            if len(rows) > 1000:
                raise ServiceError('data_incomplete')
            self.validate_rows(rows, context['target'], low, high, context['cutoff'])
            groups = [(block, list(batch)) for block, batch in groupby(rows, key=lambda r: integer(r['blockNumber']))]
            if len(rows) < 1000:
                for block, batch in groups:
                    yield block, batch
                return
            if len(groups) > 1:
                for block, batch in groups[:-1]:
                    yield block, batch
                high = groups[-1][0]
                continue
            # A single block itself needs paging. Keep its transactions atomic.
            block = groups[0][0]
            complete = list(rows)
            for page in range(2, 11):
                batch = await self.fetch('account', action, address=context['target'], startblock=block,
                                         endblock=block, sort='desc', page=page, offset=1000)
                self.validate_rows(batch, context['target'], block, block, context['cutoff'])
                complete.extend(batch)
                if len(batch) < 1000:
                    break
            else:
                raise ServiceError('data_incomplete')
            yield block, complete
            high = block - 1

    async def transaction_groups(self, context):
        """Merge both source streams before yielding newest observed transactions."""
        streams = [self.blocks(context, action) for action in ('txlist', 'txlistinternal')]
        current = [None, None]
        try:
            for index, stream in enumerate(streams):
                current[index] = await anext(stream, None)
            while any(item is not None for item in current):
                block = max(item[0] for item in current if item is not None)
                batch, consumed = [], []
                for index, item in enumerate(current):
                    if item is not None and item[0] == block:
                        batch.extend(r for r in item[1] if context['window_start'] < integer(r['timeStamp']) <= context['cutoff'])
                        consumed.append(index)
                if batch:
                    events, _, _ = await self.normalize(batch)
                    by_tx, by_event = {}, {}
                    for row in batch:
                        by_tx.setdefault(row['hash'].lower(), []).append(row)
                    for event in events:
                        by_event.setdefault(event['tx_hash'], []).append(event)
                    ordered = sorted(by_tx, key=lambda tx: (max(integer(r.get('transactionIndex')) or 0 for r in by_tx[tx]), tx), reverse=True)
                    for tx in ordered:
                        yield by_tx[tx], by_event.get(tx, [])
                for index in consumed:
                    current[index] = await anext(streams[index], None)
        finally:
            for stream in streams:
                await stream.aclose()

    @staticmethod
    def display_keys(events):
        return ({n for e in events for n in (e['src'], e['dst'])},
                {(e['src'], e['dst'], e['relation'], str(e.get('asset') or 'unknown')) for e in events})

    async def display_history(self, context):
        """Keep 47 direct neighbors, then up to 16 genuine second-hop nodes."""
        root = context['target']
        selected, nodes, edges = [], {root}, set()
        limited = False
        groups = self.transaction_groups(context)
        try:
            async for rows, events in groups:
                tx_nodes, tx_edges = self.display_keys(events)
                if (len(nodes | tx_nodes) > self.DISPLAY_FIRST_HOP_WITH_ROOT
                        or len(edges | tx_edges) > self.DISPLAY_MAX_EDGES):
                    limited = True
                    break
                selected.extend(rows); nodes |= tx_nodes; edges |= tx_edges
                if len(selected) > 100000:
                    raise ServiceError('data_incomplete')
                if len(nodes) == self.DISPLAY_FIRST_HOP_WITH_ROOT or len(edges) == self.DISPLAY_MAX_EDGES:
                    limited = True
                    break
        finally:
            await groups.aclose()
        if limited and not selected:
            raise ServiceError('data_incomplete')
        first_hop = nodes - {root}
        root_transactions = {r['hash'].lower() for r in selected}
        root_events, _, _ = await self.normalize(selected)
        recency = {n: max((e['timestamp'] for e in root_events if n in (e['src'], e['dst'])), default=0) for n in first_hop}
        second_hop = set()
        # A soft per-parent share spreads the leaves across branches. A larger
        # indivisible transaction may use more of the remaining global budget.
        for parent in sorted(first_hop, key=lambda n: (-recency[n], n)):
            if len(second_hop) == self.DISPLAY_SECOND_HOP_MAX_NODES or len(edges) == self.DISPLAY_MAX_EDGES:
                break
            added_for_parent = 0
            groups = self.transaction_groups({**context, 'target': parent})
            try:
                async for rows, events in groups:
                    tx_nodes, tx_edges = self.display_keys(events)
                    # Do not reintroduce older root activity or additional direct
                    # neighbors through another address's query results.
                    if root in tx_nodes and rows[0]['hash'].lower() not in root_transactions:
                        continue
                    if any(root in (e['src'], e['dst']) and
                           ({e['src'], e['dst']} - {root}) - first_hop for e in events):
                        continue
                    fresh = tx_nodes - nodes
                    if not fresh and not (tx_nodes & second_hop):
                        continue
                    if (len(second_hop | fresh) > self.DISPLAY_SECOND_HOP_MAX_NODES
                            or len(nodes | tx_nodes) > self.DISPLAY_MAX_NODES
                            or len(edges | tx_edges) > self.DISPLAY_MAX_EDGES):
                        limited = True
                        break
                    selected.extend(rows); nodes |= tx_nodes; edges |= tx_edges
                    second_hop |= fresh; added_for_parent += len(fresh)
                    if len(selected) > 100000:
                        raise ServiceError('data_incomplete')
                    if (added_for_parent >= self.DISPLAY_SECOND_HOP_PER_PARENT
                            or len(second_hop) == self.DISPLAY_SECOND_HOP_MAX_NODES
                            or len(edges) == self.DISPLAY_MAX_EDGES):
                        limited = True
                        break
            finally:
                await groups.aclose()
        display_context = {**context, 'display_limited': limited, 'display_max_nodes': self.DISPLAY_MAX_NODES,
            'display_max_edges': self.DISPLAY_MAX_EDGES, 'display_policy': 'eth-two-hop-display-3',
            'display_first_hop_with_root': self.DISPLAY_FIRST_HOP_WITH_ROOT,
            'display_second_hop_max_nodes': self.DISPLAY_SECOND_HOP_MAX_NODES,
            'display_node_hops': {root: 0, **{n: 1 for n in sorted(first_hop)}, **{n: 2 for n in sorted(second_hop)}}}
        if limited:
            display_context.update(window_start=min((integer(r['timeStamp']) for r in selected), default=context['cutoff']),
                start_block=min((integer(r['blockNumber']) for r in selected), default=context['cutoff_block']),
                boundary_inclusive=True, boundary_transaction_limited=True)
        identities = sorted((r['source_kind'], r['hash'].lower(), str(r.get('traceId') or ''), r['_history_address']) for r in selected)
        display_context['display_selection_hash'] = hashlib.sha256(json.dumps(identities).encode()).hexdigest()
        return display_context, selected

    async def recent(self, entity, context):
        rows = []
        for action in ('txlist', 'txlistinternal'):
            batch = await self.fetch('account', action, address=entity, startblock=0,
                endblock=context['cutoff_block'], sort='desc', page=1, offset=100)
            if len(batch) > 100:
                raise ServiceError('data_incomplete')
            self.validate_rows(batch, entity, 0, context['cutoff_block'], context['cutoff'])
            rows.extend(batch)
        return rows

    async def normalize(self, raw):
        rows = deepcopy(raw)
        traces = {}
        RecentHistoryCollector._scope_internal_records(rows, traces)
        events, audit = await asyncio.to_thread(normalize_records, rows)
        for invalid in audit['invalid_records']:
            if invalid['reason'] != 'conflicting_transaction_success_flags':
                continue
            row = rows[invalid['row']]
            if row['source_kind'] != 'normal':
                continue
            receipt = await self.rpc.call('eth_getTransactionReceipt', [row['hash']])
            if (not isinstance(receipt, dict) or integer(receipt.get('status')) not in (0, 1)
                or receipt.get('transactionHash', '').lower() != row['hash'].lower()
                or integer(receipt.get('blockNumber')) != integer(row['blockNumber'])
                or address(receipt.get('from')) != address(row.get('from'))
                or address(receipt.get('to')) != address(row.get('to'))):
                raise ServiceError('data_incomplete')
            row['success'] = integer(receipt['status']) == 1
        if audit['invalid_records']:
            events, audit = await asyncio.to_thread(normalize_records, rows)
        if not audit['complete']:
            raise ServiceError('data_incomplete')
        for event in events:
            event.pop('input', None)
        audit['trace_identity_resolutions'] = list(traces.values())
        return events, audit, rows
