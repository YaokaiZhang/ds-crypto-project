"""Exact native amounts and graph views derived from actual observations."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib

from packages.transactions import address, integer

from ..adapters.analysis_store import utc
from ..api.schemas import LedgerRow


def eth_amount(raw):
    value = int(raw)
    digits = str(abs(value)).zfill(19)
    whole, fraction = digits[:-18], digits[-18:].rstrip('0')
    return ('-' if value < 0 else '') + whole + ('.' + fraction if fraction else '')


def enrich_token_amounts(ledger, transfers, root):
    """Join explorer ERC-20 observations to existing external transaction rows.

    Group by contract and root-relative direction, never merely token symbol.
    These display amounts do not enter native totals, graphs or model inputs.
    """
    external = {row['hash']: row for row in ledger if row['category'] == 'external'}
    groups = {}
    for transfer in transfers:
        row = external.get(str(transfer.get('hash', '')).lower())
        if row is None or row['status'] != 'success':
            continue
        src, dst = address(transfer.get('from')), address(transfer.get('to'))
        contract = address(transfer.get('contractAddress'))
        raw, decimals = integer(transfer.get('value')), integer(transfer.get('tokenDecimal'))
        # Invalid or missing units remain unknown; do not invent token precision.
        if not contract or raw is None or raw < 0 or decimals is None or not 0 <= decimals <= 36 or root not in (src, dst):
            continue
        if integer(transfer.get('blockNumber')) != row['block_number']:
            raise ValueError('Token and transaction block identities disagree')
        direction = 'self' if src == dst == root else 'outgoing' if src == root else 'incoming'
        key = row['hash'], contract, decimals, direction
        symbol = str(transfer.get('tokenSymbol') or '').strip()[:80] or contract
        if key not in groups:
            groups[key] = {'asset': symbol, 'raw': '0', 'decimals': decimals,
                           'contract_address': contract, 'direction': direction}
        elif groups[key]['asset'] != symbol:
            # Conflicting metadata cannot identify the asset by symbol.
            groups[key]['asset'] = contract
        groups[key]['raw'] = str(int(groups[key]['raw']) + raw)
    for (tx, _, _, _), amount in groups.items():
        external[tx]['amounts'].append(amount)
    return ledger


def graph_view(task, sample_id, root, events, cutoff, *, refs=None, lineage=None, scope='display_recent', model=None, kind='contract', display_context=None):
    groups = defaultdict(list)
    for event in events:
        if refs is not None and (event['src'] not in refs or event['dst'] not in refs):
            continue
        if lineage is not None and event['event_id'] not in lineage:
            continue
        groups[(event['src'], event['dst'], event['relation'], str(event.get('asset') or 'unknown'))].append(event)
    nodes = {root}
    edges = []
    for (src, dst, relation, asset), rows in sorted(groups.items()):
        nodes.update((src, dst))
        amounts = [int(r['raw_amount']) for r in rows if r.get('success') is True and r.get('raw_amount') is not None]
        structural = relation in ('deployed', 'contains', 'participates', 'pair_created')
        edges.append({'id': hashlib.sha256(f'{src}:{dst}:{relation}:{asset}'.encode()).hexdigest(),
            'source': src, 'target': dst, 'relation': relation, 'kind': 'structural' if structural else 'observed',
            'direction': 'original', 'event_count': len(rows),
            'amount': eth_amount(sum(amounts)) if amounts and asset == 'ETH' else None,
            'asset': 'ETH' if amounts and asset == 'ETH' else None,
            'first_seen': utc(min(r['timestamp'] for r in rows)), 'last_seen': utc(max(r['timestamp'] for r in rows))})
    if refs is not None:
        nodes.update(refs)
    if display_context and (len(nodes) > display_context['display_max_nodes'] or len(edges) > display_context['display_max_edges']):
        raise ValueError('Display graph exceeds its declared limits')
    return {'task_id': task, 'sample_id': sample_id,
        'nodes': [{'id': n, 'ref': n, 'hop': (display_context or {}).get('display_node_hops', {}).get(n),
                   'role': ('wallet' if kind == 'eoa' else 'contract') if n == root else 'unknown',
                   'is_root': n == root, 'individually_assessed': n == root} for n in sorted(nodes)], 'edges': edges,
        'context': {'sample_id': sample_id, 'task_id': task,
            'model_nodes': len(model['node_refs']) if model else None,
            'model_edges': len(model['edge_index'][0]) if model else None,
            'model_sample_id': model['sample_id'] if model else None, 'view_scope': scope,
            'window': f"{utc(display_context['window_start'])} → {utc(cutoff)}" if display_context else 'Frozen bounded model recipe',
            'cutoff': utc(cutoff), 'version': 'eth-display-3' if display_context else model['graph_view_version'],
            'sampling': ('Two hops; root and first hop at most 48 nodes, second hop at most 16; '
                         '4096 directed relations')
                        if display_context else str(model['lineage']['sampling'])}}


def basic_information(context, rows=None, inflow=None, outflow=None, metrics=None):
    """Publish confirmed state before the history-dependent facts are complete."""
    root = context['target']
    meta, created = context['metadata'], context['creation']
    pending = rows is None and metrics is None
    metrics = metrics or {}
    def field(key, label, value, hint='Complete declared root-address window; excludes gas from native flow totals.'):
        return {'key': key, 'label': label, 'value': str(value), 'hint': hint}
    counterparties = {a for r in rows or [] for a in (r['from_address'], r['to_address']) if a and a != root}
    waiting = 'Awaiting 30-day address activity.'
    def activity_field(key, label, value):
        return field(key, label, '—' if pending else value, waiting if pending else
                     '30-day root-address activity collected so far; native flow totals exclude gas.')
    return {'entity_type': context['entity_type'], 'name': meta.get('ContractName') or ('Ethereum wallet' if context['entity_type'] == 'eoa' else 'Ethereum contract'),
        'balance_wei': context['balance_wei'], 'state_time': utc(context['cutoff']), 'state_block': context['cutoff_block'],
        'source_verification': (None if not context.get('metadata_complete', True) else
            'verified' if meta.get('ABI') and meta['ABI'] != 'Contract source code not verified' else 'unverified_or_not_applicable'),
        'compiler': meta.get('CompilerVersion'), 'deployment_transaction': created.get('txHash'),
        'deployer': address(created.get('contractCreator')), 'pools': [],
        'fields': [field('type', 'Account type', context['entity_type']),
            field('balance', 'ETH balance', eth_amount(context['balance_wei']), 'Balance at the frozen cutoff block.'),
            field('window', 'Observation window', f"{utc(context['window_start'])} → {utc(context['cutoff'])}", 'Fixed 30-day root-address observation window.'),
            activity_field('inflow', 'Native inflow · ETH', eth_amount(metrics.get('inflow', inflow or 0))),
            activity_field('outflow', 'Native outflow · ETH', eth_amount(metrics.get('outflow', outflow or 0))),
            activity_field('net', 'Net flow · ETH', eth_amount(metrics.get('inflow', inflow or 0) - metrics.get('outflow', outflow or 0))),
            activity_field('external', 'External transactions', metrics.get('external', sum(r['category'] == 'external' for r in rows or []))),
            activity_field('internal', 'Internal transfers', metrics.get('internal', sum(r['category'] == 'internal' for r in rows or []))),
            activity_field('counterparties', 'Native counterparties', metrics.get('counterparties', len(counterparties))),
            activity_field('first', 'First activity', metrics.get('first') or min((r['block_time'] for r in rows or []), default='No activity in this window')),
            activity_field('last', 'Last activity', metrics.get('last') or max((r['block_time'] for r in rows or []), default='No activity in this window')),
            field('metadata', 'Contract metadata', meta.get('ContractName') or ('—' if not context.get('metadata_complete', True) else 'Not available'),
                  'Explorer metadata is optional enrichment, not a model feature.')]}


def ledger_rows(context, raw):
    root = context['target']
    ledger = {}
    # Raw transaction identities, rather than expanded normalized relations, keep
    # calls and value transfers in one ledger row each.
    for row in raw:
        category = 'external' if row['source_kind'] == 'normal' else 'internal'
        tx = row['hash'].lower(); trace = str(row.get('traceId')) if category == 'internal' else None
        identity = f'{tx}:{category}:{trace or ""}'
        src, dst = address(row.get('from')), address(row.get('to')) or address(row.get('contractAddress'))
        status = 'success' if row.get('success') is True else 'failed' if row.get('success') is False else (
            'success' if str(row.get('isError')) == '0' else 'failed' if str(row.get('isError')) == '1' else 'unknown')
        item = LedgerRow(id=identity, category=category, hash=tx, block_number=integer(row['blockNumber']),
            block_time=utc(integer(row['timeStamp'])), from_address=src, to_address=dst,
            direction='self' if src == dst == root else 'outgoing' if src == root else 'incoming' if dst == root else 'neighbor',
            value_raw=str(integer(row['value'])), decimals=18, asset='ETH', status=status,
            method=row.get('functionName') or row.get('methodId') or row.get('type'), trace_id=trace,
            gas_used=str(integer(row['gasUsed'])) if integer(row.get('gasUsed')) is not None else None,
            gas_price_wei=str(integer(row['gasPrice'])) if integer(row.get('gasPrice')) is not None else None,
            transaction_index=integer(row.get('transactionIndex'))).model_dump(mode='json')
        if identity in ledger and ledger[identity] != item:
            # Different retrieval metadata is not in the public row.
            raise ValueError('Conflicting ledger identity')
        ledger[identity] = item
    rows = sorted(ledger.values(), key=lambda r: (r['block_number'], r['transaction_index'] or 0, r['id']), reverse=True)
    return rows


def display(context, raw, events, tasks):
    root = context['target']
    rows = ledger_rows(context, raw)
    buckets = defaultdict(lambda: {'inflow_wei': 0, 'outflow_wei': 0, 'external_count': 0})
    start_day = context['window_start'] // 86400
    for day in range(start_day, context['cutoff'] // 86400 + 1):
        buckets[day]
    for row in rows:
        day = int(datetime.fromisoformat(row['block_time'].replace('Z', '+00:00')).timestamp()) // 86400
        buckets[day]['external_count'] += row['category'] == 'external'
    inflow = outflow = 0
    for event in events:
        if event['relation'] not in ('external_eth', 'internal_eth') or event.get('success') is not True:
            continue
        amount = int(event['raw_amount']); day = event['timestamp'] // 86400
        if event['dst'] == root:
            buckets[day]['inflow_wei'] += amount; inflow += amount
        if event['src'] == root:
            buckets[day]['outflow_wei'] += amount; outflow += amount
    points = [{'date': datetime.fromtimestamp(day * 86400, timezone.utc).date().isoformat(), 'covered': True,
               'inflow_wei': str(value['inflow_wei']), 'outflow_wei': str(value['outflow_wei']),
               'external_count': value['external_count']} for day, value in sorted(buckets.items())]
    facts = basic_information(context, rows, inflow, outflow)
    activity = {'scope': {'chain_id': 1, 'target': root, 'window_start': utc(context['window_start']), 'cutoff': utc(context['cutoff']),
                           'complete': not context.get('display_limited', False), 'selection_complete': True,
                           'display_limited': context.get('display_limited', False), 'source': 'Etherscan',
                           'boundary_buckets': 'Partial UTC days; limit boundary may retain only the newest transactions within a block'}, 'points': points}
    graphs = {task: graph_view(task, hashlib.sha256(f"{context['snapshot_id']}:{task}:display-3:{context['display_selection_hash']}".encode()).hexdigest(),
                  root, events, context['cutoff'], kind=context['entity_type'], display_context=context) for task in tasks}
    return facts, activity, graphs, rows
