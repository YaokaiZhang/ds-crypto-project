"""Incremental complete 30-day token/pool logs, independent of graph limits."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import time

from packages.token import annotate_token_events, token_scope
from ..adapters.analysis_store import utc
from ..errors import ServiceError
from .token_presentation import DisplayGraph, basic_information, ledger_row, pools


class TokenWindow:
    graph_class = DisplayGraph
    information = staticmethod(basic_information)
    family = 'token_scam'
    policy = 'token-full30-1'

    def __init__(self, collector):
        self.collector = collector
        self.store, self.lease = collector.store, collector.lease

    async def collect(self, context):
        if self.store.artifact(self.lease['id'], 'token_window_complete'):
            return self.store.artifact(self.lease['id'], 'token_display_selection')
        root = context['target']
        selected = context.get('pools', [])
        scope = token_scope(context) if selected else None
        graph = self.graph_class(context)
        emitters = [root, *selected]
        sources = {e: False for e in emitters}
        stats = {'transfers': 0, 'participants': 0, 'swap': 0, 'mint': 0, 'burn': 0, 'first': None, 'last': None}
        participants, seen = set(), {}
        buckets = defaultdict(lambda: {'transfer_count': 0, 'swap_count': 0, 'mint_count': 0, 'burn_count': 0})
        dirty = []
        previous = self.store.get(self.lease['id'])
        revision = (previous.get('transactions') or {}).get('revision', 0)
        prior_counts = {cat: self.store.transactions(self.lease['id'], cat, 0, 0)[1] for cat in ('token_transfer', 'pool_event')}
        counts = {'token_transfer': 0, 'pool_event': 0}
        started = self.store.artifact(self.lease['id'], 'token_window_started')
        if not started:
            self.store.save(self.lease, {'graphs': {}}, ledger=[],
                artifacts={('token_window_started', ''): {'policy': self.policy, 'snapshot_id': context['snapshot_id']}})
        last_publish = time.monotonic()
        async def publish(final=False):
            nonlocal revision, dirty, last_publish
            # Reconstruct unfinished windows from immutable provider pages without
            # moving persisted counts backward after a retry/UTC quota pause.
            if any(counts[k] < prior_counts[k] for k in counts):
                return
            revision += 1
            points = [{'date': datetime.fromtimestamp(day*86400, timezone.utc).date().isoformat(), 'covered': True,
                       **buckets[day]} for day in range(context['window_start']//86400, context['cutoff']//86400+1)]
            activity = {'scope': {'family': self.family, 'chain_id': 1, 'target': root,
                'window_start': utc(context['window_start']), 'cutoff': utc(context['cutoff']), 'timezone': 'UTC',
                'complete': final, 'source': 'Etherscan getLogs', 'sources': dict(sources), 'pools': pools(context),
                'boundary_buckets': 'Partial first and last UTC days'}, 'points': points}
            artifacts = {('token_window_progress', ''): {'counts': counts, 'sources': sources}}
            if final:
                artifacts.update({('token_window_complete', ''): {'policy': self.policy, 'counts': counts},
                    ('token_display_selection', ''): graph.payload()})
            self.store.save(self.lease, {'basic_information': self.information(context, stats), 'activity': activity,
                'transactions': {'items': [], 'total': counts['token_transfer'], 'category': 'token_transfer', 'revision': revision}},
                ledger_append=dirty, artifacts=artifacts)
            from .live_analysis import LiveAnalysisService
            service = LiveAnalysisService(self.store, None, self.collector.settings)
            page = await service.transactions(self.lease['id'], 30, category='token_transfer')
            self.store.save(self.lease, {'transactions': page})
            dirty, last_publish = [], time.monotonic()
        for entity in emitters:
            async for raw in self.collector.log_batches(entity, context['start_block'], context['cutoff_block'], context['cutoff']):
                raw = [r for r in raw if (context['window_start'] <= int(r['timeStamp']) if context.get('boundary_inclusive')
                        else context['window_start'] < int(r['timeStamp'])) and int(r['timeStamp']) <= context['cutoff']]
                events, _, _ = await self.collector.normalize(raw)
                if scope:
                    events = annotate_token_events(events, scope)
                else:
                    events = [e for e in events if e['relation'] == 'erc20_transfer' and e.get('asset') == root]
                    for event in events:
                        event['decimals'] = context['token_metadata']['decimals']
                fresh = []
                for event in events:
                    row = ledger_row(context, event)
                    if row is None:
                        continue
                    fingerprint = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                    if row['id'] in seen:
                        if seen[row['id']] != fingerprint:
                            raise ServiceError('data_incomplete')
                        continue
                    seen[row['id']] = fingerprint
                    dirty.append(row); fresh.append(event)
                    counts[row['category']] += 1
                    stamp, relation = event['timestamp'], event['relation']
                    day = stamp//86400
                    if row['category'] == 'token_transfer':
                        stats['transfers'] += 1; buckets[day]['transfer_count'] += 1
                        participants.update((event['src'], event['dst']))
                        stats['participants'] = len(participants)
                    elif relation in ('swap', 'mint', 'burn'):
                        stats[relation] += 1; buckets[day][relation+'_count'] += 1
                    iso = utc(stamp)
                    stats['first'] = min(stats['first'] or iso, iso)
                    stats['last'] = max(stats['last'] or iso, iso)
                graph.observe(fresh)
                if len(dirty) >= 1000 or time.monotonic()-last_publish >= 1:
                    await publish()
            sources[entity] = True
            if entity == root:
                graph.locked = True
            await publish()
        await publish(final=True)
        return graph.payload()
