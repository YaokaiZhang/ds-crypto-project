"""Live ERC-20 observations and frozen token model inputs; simulated scoring."""
import asyncio
import hashlib

from packages.graph import build_graph_sample, graph_is_usable
from packages.token import token_scope, TOKEN_RECENT_SCOPE_VERSION
from packages.token_recent import sampling_recipe

from ..adapters.mock_predictor import TokenInputRegistry
from ..api.schemas import AnalysisRequest, AnalysisResult
from ..errors import ServiceError
from .eth_pipeline import EthPipeline
from .token_collection import TokenCollection
from .token_presentation import DisplayGraph
from .token_window import TokenWindow


class TokenPipeline(EthPipeline):
    registry_class = TokenInputRegistry

    async def execute(self, lease):
        request = AnalysisRequest.model_validate(lease['command'])
        collector = TokenCollection(self.store, lease, self.settings, self.etherscan, self.rpc)
        collector.stage('resolving', 'Verifying ERC-20 identity and cutoff-bound Uniswap v2 pools')
        context = await collector.freeze(request)
        outcomes = {task: {'task_id': task, 'status': 'pending', 'score': None} for task in request.tasks}
        if not context['pools']:
            outcomes = {task: {'task_id': task, 'status': 'not_applicable', 'score': None,
                'reason_code': 'unsupported_pool', 'reason': 'No supported Ethereum Uniswap v2 pool was found. Token activity remains available.'} for task in request.tasks}
        self.store.save(lease, {'tasks': list(outcomes.values())})
        collector.stage('collecting', 'Collecting the complete 30-day token and selected-pool events')
        selection = await TokenWindow(collector).collect(context)
        views = DisplayGraph.restore(context, selection).views(request.tasks)
        self.store.save(lease, {'graphs': views, 'message': '30-day activity ready; collecting frozen token model inputs'})
        samples = {}
        if context['pools']:
            scope = token_scope(context)
            emitters = sorted({context['target'], *context['pools']})
            # Different frozen window_days are applied per task; underlying
            # bounded raw emitter queries can be shared without changing recipes.
            remaining = set(request.tasks)
            maximum = max(self.registry.entries[t][0]['graph_recipe']['sampling']['pages_per_action'] for t in request.tasks)
            for round_number in range(1, maximum+1):
                raw, sources = [], []
                for entity in emitters:
                    logs = []
                    limit = 100 * round_number
                    async for batch in collector.log_batches(entity, 0, context['cutoff_block'], context['cutoff'],
                            limit=limit, max_queries=96):
                        logs.extend(batch)
                    sources.append({'address': entity, 'action': 'getLogs', 'complete': True, 'gaps': [],
                        'start_block': 0, 'end_block': context['cutoff_block'], 'rows': len(logs), 'history_exhausted': len(logs) < limit})
                    raw.extend(logs)
                    for action in ('txlist', 'txlistinternal'):
                        rows, exhausted = await collector.model_account(context, entity, action, round_number, 100)
                        raw.extend(rows)
                        sources.append({'address': entity, 'action': action, 'complete': True, 'gaps': [],
                            'start_block': 0, 'end_block': context['cutoff_block'], 'rows': len(rows), 'history_exhausted': exhausted})
                events, audit, _ = await collector.normalize(raw)
                for task in sorted(remaining):
                    manifest = self.registry.entries[task][0]
                    sampling = manifest['graph_recipe']['sampling']
                    # mandatory_selected_pools is derived by the token builder,
                    # recorded in graph_recipe; it is not a builder argument.
                    options = {k: v for k, v in sampling.items() if k != 'mandatory_selected_pools'}
                    coverage = {'complete': True, 'scope_version': TOKEN_RECENT_SCOPE_VERSION,
                        'scope_sha256': scope['sha256'], 'required_emitters': emitters,
                        'start_timestamp': context['cutoff'] - sampling['window_days']*86400,
                        'end_timestamp': context['cutoff'], 'start_block': 0, 'end_block': context['cutoff_block'],
                        'full_history_complete': False, 'neighborhood_history_complete': False,
                        'sampling': sampling_recipe(sampling), 'rounds_used': round_number, 'sources': sources,
                        'stop_reason': 'record_budget_reached'}
                    sample_id = hashlib.sha256(f"{lease['id']}:{task}:{context['snapshot_id']}:token-model".encode()).hexdigest()
                    target = {**context, 'task_id': task, 'sample_id': sample_id, 'chain_id': 1, 'coverage': coverage,
                              'source_snapshot': context['snapshot_id']}
                    sample = await asyncio.to_thread(build_graph_sample, target, events, **options)
                    full = len(sample['node_refs']) >= sampling['max_nodes'] or len(sample['edge_index'][0]) >= sampling['max_edges']
                    exhausted = all(s['history_exhausted'] for s in sources)
                    if full or exhausted or round_number == sampling['pages_per_action']:
                        coverage['stop_reason'] = 'graph_budget_reached' if full else 'source_exhausted' if exhausted else 'record_budget_reached'
                        sample = await asyncio.to_thread(build_graph_sample, target, events, **options)
                        samples[task] = sample
                        self.store.save(lease, {}, artifacts={('graph_sample', task): sample, ('model_audit', task): audit})
                        remaining.remove(task)
                if not remaining:
                    break
        collector.stage('normalizing', 'Reconciling token, LP and pool event identities and units')
        collector.stage('building_graph', 'Preparing separately scaled Honeypot and Rug Pull inputs')
        for task, sample in samples.items():
            views[task]['context'].update(model_sample_id=sample['sample_id'], model_nodes=len(sample['node_refs']), model_edges=len(sample['edge_index'][0]))
        self.store.save(lease, {'graphs': views})
        collector.stage('predicting', 'Sending real token model inputs to the temporary predictor target')
        for task, sample in samples.items():
            if not graph_is_usable(sample):
                outcomes[task] = {'task_id': task, 'status': sample['quality']['status'], 'score': None,
                    'sample_id': sample['sample_id'], 'reason_code': sample['quality']['status'],
                    'reason': 'No sufficient compatible token/pool activity was found. No score was generated.'}
                continue
            cached = self.store.artifact(lease['id'], 'mock_outcome', task)
            if cached:
                if cached['sample_id'] != sample['sample_id']:
                    raise ServiceError('data_incomplete')
                outcomes[task] = cached
            else:
                try:
                    outcome, delivery = await self.predictor.predict(sample, collector.directory)
                    outcomes[task] = outcome
                    self.store.save(lease, {'tasks': list(outcomes.values())},
                        artifacts={('mock_outcome', task): outcome, ('model_delivery', task): delivery})
                except (ValueError, KeyError):
                    outcomes[task] = {'task_id': task, 'status': 'model_error', 'score': None, 'reason_code': 'model_input_mismatch',
                        'reason': 'Model input preparation failed. Real token data remains available.'}
        header = await self.rpc.call('eth_getBlockByNumber', [hex(context['cutoff_block']), False])
        if not isinstance(header, dict) or header.get('hash') != context['cutoff_hash']:
            raise ServiceError('data_incomplete')
        complete = all(t['status'] == 'ok' for t in outcomes.values())
        result = self.store.get(lease['id'])
        result.update(status='completed' if complete else 'partial', stage='completed', tasks=list(outcomes.values()),
            message='Real token data collected. All scores are random test values.' if complete else 'Real token data is available; one or more assessments have no score.',
            progress={'state': 'completed' if complete else 'partial', 'unit': 'tasks', 'completed': len(outcomes),
                      'total': len(outcomes), 'total_final': True})
        AnalysisResult.model_validate(result)
        self.store.save(lease, result, finish=True)
