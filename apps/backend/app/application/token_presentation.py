"""Real token facts, exact-unit event ledger and independent bounded graph."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json

from packages.transactions import address
from .token_collection import QUOTES, ZERO
from ..adapters.analysis_store import utc
from ..api.schemas import LedgerRow

EVENT_NAMES = {'swap': 'Swap', 'mint': 'Mint', 'burn': 'Burn', 'sync': 'Sync', 'lp_transfer': 'LP Transfer'}


def units(raw, decimals):
    if decimals is None or raw is None:
        return 'Unknown'
    value = int(raw)
    if not decimals:
        return str(value)
    digits = str(abs(value)).zfill(decimals+1)
    fraction = digits[-decimals:].rstrip('0')
    return ('-' if value < 0 else '') + digits[:-decimals] + ('.'+fraction if fraction else '')


def pools(context):
    root = context['target']
    quotes = dict(QUOTES)
    return [{'address': p['pool'], 'token0': p['token0'], 'token1': p['token1'],
             'protocol': 'Uniswap v2', 'paired_asset': quotes.get(p['token1'] if p['token0'] == root else p['token0'],
                 p['token1'] if p['token0'] == root else p['token0'])} for p in context.get('pool_metadata', [])]


def basic_information(context, metrics=None):
    meta, created = context.get('metadata', {}), context.get('creation', {})
    decimals = context.get('token_metadata', {}).get('decimals')
    symbol = context.get('symbol') or context['target']
    selected = pools(context)
    def field(key, label, value, hint):
        return {'key': key, 'label': label, 'value': str(value), 'hint': hint}
    def count(key, label):
        return field(key, label, '—' if metrics is None or metrics.get(key) is None else metrics[key],
                     'Collected events in the fixed 30-day window.')
    return {'entity_type': 'token' if decimals is not None else context['entity_type'],
        'name': context.get('name') or meta.get('ContractName') or 'ERC-20 token',
        'symbol': context.get('symbol'), 'decimals': decimals, 'total_supply_raw': context.get('total_supply_raw'),
        'state_time': utc(context['cutoff']), 'state_block': context['cutoff_block'],
        'source_verification': None if not context.get('metadata_complete') else
            'verified' if meta.get('ABI') and meta['ABI'] != 'Contract source code not verified' else 'unverified',
        'compiler': meta.get('CompilerVersion'), 'deployment_transaction': created.get('txHash'),
        'deployer': address(created.get('contractCreator')), 'pools': selected,
        'fields': [field('identity', 'Token identity', f'{symbol} · {decimals} decimals' if decimals is not None else '—', 'ERC-20'),
            field('supply', 'Total supply', f"{units(context.get('total_supply_raw'), decimals)} {symbol}" if decimals is not None else '—', 'At the frozen cutoff block.'),
            field('window', 'Observation window', f"{utc(context['window_start'])} → {utc(context['cutoff'])}", 'Fixed 30-day observation window.'),
            field('pools', 'Selected pools', len(selected) if context.get('token_resolution_complete') else '—',
                  'Verified Ethereum Uniswap v2 pools; selected independently of risk labels.'),
            count('transfers', 'Transfer events'), count('participants', 'Transfer participants'),
            count('swap', 'Swap events'), count('mint', 'Mint events'), count('burn', 'Burn events'),
            field('first', 'First activity', (metrics or {}).get('first') or ('—' if metrics is None else 'No activity in this window'), 'Within the observation window.'),
            field('last', 'Last activity', (metrics or {}).get('last') or ('—' if metrics is None else 'No activity in this window'), 'Within the observation window.'),
            field('verification', 'Contract metadata', 'Verified' if meta.get('ABI') and meta['ABI'] != 'Contract source code not verified' else 'Not available',
                  'Explorer verification is optional metadata, not a risk result.')]}


def ledger_row(context, event):
    root = context['target']
    relation = event['relation']
    token = relation == 'erc20_transfer' and event.get('asset') == root
    if not token and relation not in EVENT_NAMES:
        return None
    data = {}
    if context.get('family') == 'forecast' and relation == 'swap':
        if event.get('event_sender'):
            data['swap_sender'] = event['event_sender']
        data['swap_recipient'] = event['dst']
    amounts = []
    symbol = context.get('symbol') or root
    if token:
        data['value'] = str(event['raw_amount'])
    elif relation == 'lp_transfer':
        data['value'] = str(event['raw_amount'])
        amounts = [{'asset': 'UNI-V2', 'contract_address': event['asset'], 'raw': str(event['raw_amount']), 'decimals': 18}]
    else:
        mapping = {'swap': [('amount0_in', 'amount0In'), ('amount1_in', 'amount1In'), ('amount0_out', 'amount0Out'), ('amount1_out', 'amount1Out')],
                   'mint': [('amount0', 'amount0'), ('amount1', 'amount1')], 'burn': [('amount0', 'amount0'), ('amount1', 'amount1')],
                   'sync': [('reserve0', 'reserve0'), ('reserve1', 'reserve1')]}
        for key, label in mapping[relation]:
            if event.get(key) is not None:
                data[label] = str(event[key])
        for side in (0, 1):
            asset = event.get(f'token{side}')
            metadata = ({'decimals': context['token_metadata']['decimals'], 'symbol': symbol} if asset == root
                        else context.get('quote_metadata', {}).get(asset, {}))
            keys = [f'amount{side}_in', f'amount{side}_out'] if relation == 'swap' else [f'amount{side}'] if relation in ('mint', 'burn') else [f'reserve{side}']
            for key in keys:
                raw = event.get(key)
                if raw is None or metadata.get('decimals') is None or relation == 'swap' and int(raw) == 0:
                    continue
                amounts.append({'asset': metadata.get('symbol') or asset, 'contract_address': asset,
                    'raw': str(raw), 'decimals': metadata['decimals'],
                    'direction': 'incoming' if key.endswith('_in') or relation == 'mint' else 'outgoing' if key.endswith('_out') or relation == 'burn' else None})
    return LedgerRow(id=event['event_id'], category='token_transfer' if token else 'pool_event',
        hash=event['tx_hash'], block_number=event['block_number'], block_time=utc(event['timestamp']),
        from_address=event['src'], to_address=event['dst'], value_raw=str(event['raw_amount']) if token else None,
        decimals=context['token_metadata']['decimals'] if token else None, asset=symbol if token else None,
        status='success', log_index=event['log_index'], pool=None if token else event.get('pool') or event.get('asset'),
        event='Transfer' if token else EVENT_NAMES[relation], amounts=amounts, emitter=event.get('address'),
        transaction_index=event.get('transaction_index'), event_data=data).model_dump(mode='json')


class DisplayGraph:
    """Bounded streaming display selection, unrelated to frozen model fanouts."""
    def __init__(self, context):
        self.context = context
        self.root = context['target']
        self.first = {self.root, *context.get('pools', [])}
        self.second = set()
        self.groups = {}
        self.locked = False
        for pool in context.get('pools', []):
            self.add(self.root, pool, 'contains', self.root, context['cutoff'], structural=True)

    def add(self, src, dst, relation, asset, stamp, structural=False, raw_amount=None, decimals=None, symbol=None):
        if src not in self.first | self.second or dst not in self.first | self.second:
            return
        key = src, dst, relation, asset or 'unknown'
        if key not in self.groups:
            if len(self.groups) >= 4096:
                return
            self.groups[key] = {'source': src, 'target': dst, 'relation': relation,
                'asset': None, 'amount': None, 'direction': 'original',
                'kind': 'structural' if structural else 'observed', 'event_count': 0,
                'first_seen': utc(stamp), 'last_seen': utc(stamp)}
        item = self.groups[key]
        item['event_count'] += 1
        item['first_seen'] = min(item['first_seen'], utc(stamp))
        item['last_seen'] = max(item['last_seen'], utc(stamp))
        if not structural and raw_amount is not None and decimals is not None:
            item['_raw_amount'] = str(int(item.get('_raw_amount', '0')) + int(raw_amount))
            item['_decimals'] = decimals
            item['asset'] = symbol or asset

    def observe(self, events):
        for event in sorted(events, key=lambda e: (e['timestamp'], e['block_number'], e.get('log_index', -1)), reverse=True):
            relation, stamp = event['relation'], event['timestamp']
            src, dst = event['src'], event['dst']
            participants = {src, dst} - {ZERO, self.root}
            if relation == 'erc20_transfer':
                if not self.locked:
                    for participant in sorted(participants):
                        if participant not in self.first | self.second and len(self.first) < 48:
                            self.first.add(participant)
                        if participant in self.first:
                            self.add(self.root, participant, 'participates', self.root, stamp, True)
                # Actual token transfer links give leaves their second-hop edges.
                if participants & self.first:
                    for participant in sorted(participants - self.first - self.second):
                        if len(self.second) < 16:
                            self.second.add(participant)
            elif event.get('pool') in self.first:
                pool = event['pool']
                for participant in sorted(participants - self.first - self.second):
                    if len(self.second) < 16:
                        self.second.add(participant)
                for participant in participants - {pool}:
                    self.add(pool, participant, 'participates', self.root, stamp, True)
            decimals = self.context['token_metadata']['decimals'] if relation == 'erc20_transfer' else 18 if relation == 'lp_transfer' else None
            symbol = (self.context.get('symbol') or self.root) if relation == 'erc20_transfer' else 'UNI-V2' if relation == 'lp_transfer' else None
            self.add(src, dst, relation, event.get('asset'), stamp, raw_amount=event.get('raw_amount'), decimals=decimals, symbol=symbol)

    def payload(self):
        return {'first': sorted(self.first), 'second': sorted(self.second), 'groups': list(self.groups.values())}

    @classmethod
    def restore(cls, context, data):
        graph = cls(context)
        graph.first, graph.second = set(data['first']), set(data['second'])
        graph.groups = {(str(i), '', '', ''): row for i, row in enumerate(data['groups'])}
        return graph

    def views(self, tasks):
        context, root = self.context, self.root
        selected_pools = set(context.get('pools', []))
        nodes = [{'id': a, 'ref': a, 'hop': 0 if a == root else 1 if a in self.first else 2,
                  'role': 'token' if a == root else 'pool' if a in selected_pools else 'wallet',
                  'label': context.get('name') if a == root else None,
                  'is_root': a == root, 'individually_assessed': a == root} for a in sorted(self.first | self.second)]
        edges = [{**{k: v for k, v in row.items() if not k.startswith('_')},
            'amount': units(row['_raw_amount'], row['_decimals']) if '_raw_amount' in row else None,
            'id': hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()} for row in self.groups.values()]
        result = {}
        for task in tasks:
            sample = hashlib.sha256(f"{context['snapshot_id']}:{task}:token-display-1".encode()).hexdigest()
            result[task] = {'task_id': task, 'sample_id': sample, 'nodes': nodes, 'edges': edges,
                'context': {'task_id': task, 'sample_id': sample, 'model_nodes': None, 'model_edges': None,
                    'window': f"{utc(context['window_start'])} → {utc(context['cutoff'])}", 'cutoff': utc(context['cutoff']),
                    'version': 'token-display-1', 'sampling': 'Two hops; root and first hop at most 48 nodes, second hop at most 16; 4096 directed relations',
                    'view_scope': 'display_recent'}}
        return result
