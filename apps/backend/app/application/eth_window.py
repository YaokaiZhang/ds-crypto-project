"""Incremental complete 30-day root ledger, independent of graph display budgets."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import time

from packages.transactions import integer
from ..adapters.analysis_store import utc
from ..errors import ServiceError
from .eth_presentation import basic_information, ledger_rows
from .live_analysis import LiveAnalysisService


class RootWindow:
    def __init__(self, collector):
        self.collector = collector
        self.store, self.lease = collector.store, collector.lease
        self.normal = {}
        self.identities, self.counterparties, self.seen_sources = {}, set(), set()
        self.flows = {}
        self.buckets = defaultdict(lambda: {'inflow': 0, 'outflow': 0, 'external': 0})
        self.metrics = {'inflow': 0, 'outflow': 0, 'external': 0, 'internal': 0, 'first': None, 'last': None}
        self.revision = 0
        self.resume_counts = {'external': 0, 'internal': 0}

    async def add(self, context, incoming):
        root = context['target']
        by_tx = defaultdict(list)
        for row in incoming:
            tx = row['hash'].lower()
            by_tx[tx].append(row)
            if row['source_kind'] == 'normal':
                self.normal[tx] = row
        for tx, rows in by_tx.items():
            if tx in self.normal and not any(r['source_kind'] == 'normal' for r in rows):
                rows.append(self.normal[tx])
        events, _, normalized = await self.collector.normalize([r for rows in by_tx.values() for r in rows])
        updates = ledger_rows(context, normalized)
        for row in updates:
            identity = row['id']
            fingerprint = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            if identity in self.identities:
                if fingerprint != self.identities[identity]:
                    raise ServiceError('data_incomplete')
                continue
            self.identities[identity] = fingerprint
            self.seen_sources.add(row['category'])
            self.metrics[row['category']] += 1
            self.counterparties.update(a for a in (row['from_address'], row['to_address']) if a and a != root)
            stamp = row['block_time']
            self.metrics['first'] = min(self.metrics['first'] or stamp, stamp)
            self.metrics['last'] = max(self.metrics['last'] or stamp, stamp)
            if row['category'] == 'external':
                day = int(datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()) // 86400
                self.buckets[day]['external'] += 1
        # Each incoming block contains complete observed traces for a hash.
        # Reconcile its original external row too, suppressing duplicate root traces.
        fresh = {tx: {} for tx in by_tx}
        for event in events:
            if event['relation'] not in ('external_eth', 'internal_eth') or event.get('success') is not True:
                continue
            day = event['timestamp'] // 86400
            values = fresh[event['tx_hash']].setdefault(day, [0, 0])
            values[0] += int(event['raw_amount']) if event['dst'] == root else 0
            values[1] += int(event['raw_amount']) if event['src'] == root else 0
        for tx, values in fresh.items():
            for direction, index in (('inflow', 0), ('outflow', 1)):
                for day, old in self.flows.get(tx, {}).items():
                    self.buckets[day][direction] -= old[index]
                    self.metrics[direction] -= old[index]
                for day, new in values.items():
                    self.buckets[day][direction] += new[index]
                    self.metrics[direction] += new[index]
            self.flows[tx] = values
        return updates

    async def publish(self, context, updates, completed_actions, complete=False):
        if any(self.metrics[key] < value for key, value in self.resume_counts.items()):
            # Rebuild counters from immutable cached pages without replacing
            # already-visible totals with an earlier prefix after a retry.
            return
        self.revision += 1
        metrics = {**self.metrics, 'counterparties': len(self.counterparties)}
        facts = basic_information(context, metrics=metrics)
        for field in facts['fields']:
            action = {'external': 'txlist', 'internal': 'txlistinternal'}.get(field['key'])
            if action and action not in completed_actions and field['key'] not in self.seen_sources:
                field.update(value='—', hint='Awaiting this source history.')
            if not self.identities and not complete and field['key'] in ('inflow', 'outflow', 'net', 'counterparties', 'first', 'last'):
                field['value'] = '—'
        points = []
        for day in range(context['window_start'] // 86400, context['cutoff'] // 86400 + 1):
            value = self.buckets[day]
            points.append({'date': datetime.fromtimestamp(day * 86400, timezone.utc).date().isoformat(),
                'covered': True, 'inflow_wei': str(value['inflow']), 'outflow_wei': str(value['outflow']),
                'external_count': value['external']})
        self.store.save(self.lease, {'basic_information': facts, 'window_start': utc(context['window_start']),
            'activity': {'scope': {'chain_id': 1, 'target': context['target'], 'window_start': utc(context['window_start']),
                'cutoff': utc(context['cutoff']), 'complete': complete, 'source': 'Etherscan'}, 'points': points},
            'transactions': {'items': [], 'category': 'external', 'total': metrics['external'],
                             'next_cursor': None, 'revision': self.revision}}, ledger_append=updates)
        service = LiveAnalysisService(self.store, self.collector.etherscan.budget, self.collector.settings)
        self.store.save(self.lease, {'transactions': await service.transactions(self.lease['id'], 30, None, 'external')})

    async def collect(self, context):
        if self.store.artifact(self.lease['id'], 'root_window_complete'):
            return
        started = self.store.artifact(self.lease['id'], 'root_window_started')
        if started:
            if started != {'policy': 'root-30d-1', 'snapshot_id': context['snapshot_id']}:
                raise ServiceError('data_incomplete')
            for category in self.resume_counts:
                _, self.resume_counts[category] = self.store.transactions(self.lease['id'], category, 0, 0)
            self.revision = (self.store.get(self.lease['id']).get('transactions') or {}).get('revision', 0)
        else:
            self.store.save(self.lease, {'graphs': {}, 'transactions': None, 'activity': None}, ledger=[],
                artifacts={('root_window_started', ''): {'policy': 'root-30d-1', 'snapshot_id': context['snapshot_id']}})
        completed = set()
        pending = []
        last_publish = time.monotonic()
        for action in ('txlist', 'txlistinternal'):
            async for _, rows in self.collector.blocks(context, action):
                pending.extend(r for r in rows if context['window_start'] < integer(r['timeStamp']) <= context['cutoff'])
                if len(pending) >= 1000 or pending and time.monotonic() - last_publish >= 1:
                    updates = await self.add(context, pending)
                    await self.publish(context, updates, completed)
                    pending = []
                    last_publish = time.monotonic()
            completed.add(action)
            updates = await self.add(context, pending) if pending else []
            await self.publish(context, updates, completed, complete=len(completed) == 2)
            pending = []
        self.store.save(self.lease, {}, artifacts={('root_window_complete', ''):
            {'policy': 'root-30d-1', 'external': self.metrics['external'], 'internal': self.metrics['internal']}})
