"""Real ETH analysis orchestration; model scoring is explicitly simulated."""
import asyncio
import hashlib

from packages.graph import build_graph_sample, graph_is_usable, recent_neighbors

from ..adapters.analysis_rpc import AnalysisRpc
from ..adapters.etherscan_client import BackendEtherscan
from ..adapters.mock_predictor import EthInputRegistry, MockPredictor
from ..adapters.analysis_store import utc
from ..api.schemas import AnalysisRequest, AnalysisResult
from ..domain import EntityResolution
from ..errors import ServiceError
from .eth_collection import EthCollection
from .eth_window import RootWindow
from .eth_presentation import display, enrich_token_amounts
from .strategies import TASK_STRATEGIES


class EthPipeline:
    registry_class = EthInputRegistry

    def __init__(self, settings, store, budget, *, rpc=None, etherscan=None, predictor=None):
        self.settings, self.store, self.budget = settings, store, budget
        self.rpc = rpc or AnalysisRpc(settings)
        self.etherscan = etherscan or BackendEtherscan(settings, budget)
        self.registry = predictor.registry if predictor else self.registry_class(settings)
        self.predictor = predictor or MockPredictor(settings, self.registry)

    async def close(self):
        await self.rpc.close()
        await self.etherscan.close()
        await self.predictor.close()

    async def execute(self, lease):
        request = AnalysisRequest.model_validate(lease['command'])
        collector = EthCollection(self.store, lease, self.settings, self.etherscan, self.rpc)
        collector.stage('resolving', 'Resolving address and freezing the observation block')
        context = await collector.freeze(request)
        outcomes = {}
        eligible = []
        for task in request.tasks:
            valid, reason = TASK_STRATEGIES[task].check_applicability(EntityResolution(request.target, context['entity_type']))
            if valid:
                eligible.append(task)
                outcomes[task] = {'task_id': task, 'status': 'pending'}
            else:
                status = 'not_applicable' if context['entity_type'] == 'eoa' else 'unresolved_entity'
                outcomes[task] = {'task_id': task, 'status': status, 'reason_code': status, 'reason': reason, 'score': None}
        self.store.save(lease, {'tasks': [outcomes[t] for t in request.tasks]})

        collector.stage('collecting', 'Collecting the complete 30-day root-address activity')
        await RootWindow(collector).collect(context)
        from .live_analysis import LiveAnalysisService
        service = LiveAnalysisService(self.store, self.budget, self.settings)
        if not self.store.artifact(lease['id'], 'root_token_complete'):
            _, total = self.store.transactions(lease['id'], 'external', 1, 0)
            ledger, _ = self.store.transactions(lease['id'], 'external', total, 0)
            token_state = {'status': 'complete', 'source': 'Etherscan tokentx', 'records': 0}
            if ledger:
                try:
                    transfers = await collector.window(context, 'tokentx')
                    enrich_token_amounts(ledger, transfers, context['target'])
                    token_state['records'] = len(transfers)
                except ServiceError as error:
                    if error.code in ('quota_exhausted', 'quota_store_unavailable'):
                        raise
                    token_state.update(status='unavailable', reason_code=error.code)
                except ValueError:
                    token_state.update(status='unavailable', reason_code='data_incomplete')
            current = self.store.get(lease['id'])['transactions']
            self.store.save(lease, {'transactions': {**current, 'revision': current.get('revision', 0) + 1}},
                ledger_append=[r for r in ledger if r['amounts']],
                artifacts={('token_ledger', ''): token_state, ('root_token_complete', ''): token_state})
            self.store.save(lease, {'transactions': await service.transactions(lease['id'], 30, None, 'external')})

        # Publish one bounded graph only after the complete root ledger settles.
        display_context, display_raw = await collector.display_history(context)
        display_context['selected_window_start'] = display_context['window_start']
        display_context['window_start'] = context['window_start']
        display_events, display_audit, display_rows = await collector.normalize(display_raw)
        _, _, views, _ = await asyncio.to_thread(display, display_context, display_rows, display_events, request.tasks)
        self.store.save(lease, {'graphs': views, 'message': '30-day activity ready; collecting model neighborhoods'},
            artifacts={('display_audit', ''): display_audit, ('display_context', ''): display_context})

        histories, task_frontiers = {}, {}
        if eligible:
            histories[request.target] = await collector.recent(request.target, context)
            root_events, _, _ = await collector.normalize(histories[request.target])
            for task in eligible:
                recipe = self.registry.entries[task][0]['graph_recipe']['sampling']
                current = [r for r in root_events if context['cutoff'] - recipe['window_days'] * 86400 < r['timestamp'] <= context['cutoff']]
                task_frontiers[task] = recent_neighbors(request.target, current, recipe['fanouts'][0])
            neighbors = sorted({n for nodes in task_frontiers.values() for n in nodes} - {request.target})
            # Network starts remain globally paced; a few independent histories
            # may be in-flight without blocking progress/lease heartbeats.
            semaphore = asyncio.Semaphore(4)
            async def collect_neighbor(entity):
                async with semaphore:
                    histories[entity] = await collector.recent(entity, context)
            pending = [asyncio.create_task(collect_neighbor(n)) for n in neighbors]
            try:
                await asyncio.gather(*pending)
            except BaseException:
                for job in pending:
                    job.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                raise

        collector.stage('normalizing', 'Reconciling identities, native units and model coverage')
        task_data = {}
        for task in eligible:
            sampling = self.registry.entries[task][0]['graph_recipe']['sampling']
            entities = [request.target, *[n for n in task_frontiers[task] if n != request.target]]
            raw = [r for entity in entities for r in histories[entity]]
            events, audit, _ = await collector.normalize(raw)
            scopes = []
            for entity in entities:
                own, _, _ = await collector.normalize(histories[entity])
                own = [r for r in own if context['cutoff'] - sampling['window_days'] * 86400 < r['timestamp'] <= context['cutoff']]
                hop = 0 if entity == request.target else 1
                selected = task_frontiers[task] if hop == 0 else recent_neighbors(entity, own, sampling['fanouts'][1])
                scopes.append({'address': entity, 'hop': hop, 'selected_neighbors': selected})
            coverage = {'scope': sampling['sampling_mode'], 'complete': True, 'sampled_history_complete': True,
                'full_history_complete': False, 'neighborhood_history_complete': False,
                'cutoff': context['cutoff'], 'cutoff_block': context['cutoff_block'], 'frontier_scopes': scopes,
                'sources': [{'address': entity, 'action': action, 'complete': True}
                            for entity in entities for action in ('txlist', 'txlistinternal')],
                **{k: sampling[k] for k in ('hops', 'fanouts', 'seed', 'max_nodes', 'rows_per_action', 'pages_per_action')}}
            task_data[task] = events, audit, coverage

        collector.stage('building_graph', 'Building frozen model inputs and linking them to the display graph')
        samples = {}
        for task, (events, audit, coverage) in task_data.items():
            sampling = self.registry.entries[task][0]['graph_recipe']['sampling']
            sample_id = hashlib.sha256(f"{lease['id']}:{task}:{context['snapshot_id']}:model".encode()).hexdigest()
            target = {'target': request.target, 'task_id': task, 'sample_id': sample_id, 'chain_id': 1,
                      'cutoff': context['cutoff'], 'coverage': coverage, 'source_snapshot': context['snapshot_id']}
            sample = await asyncio.to_thread(build_graph_sample, target, events, **sampling)
            samples[task] = sample
            views[task]['context'].update(model_sample_id=sample_id, model_nodes=len(sample['node_refs']), model_edges=len(sample['edge_index'][0]))
            self.store.save(lease, {'graphs': views},
                            artifacts={('graph_sample', task): sample, ('model_audit', task): audit})

        collector.stage('predicting', 'Sending real model inputs to the temporary target; scores are simulated')
        for task in eligible:
            sample = samples[task]
            if not graph_is_usable(sample):
                outcomes[task] = {'task_id': task, 'status': sample['quality']['status'], 'score': None,
                    'sample_id': sample['sample_id'], 'reason_code': sample['quality']['status'],
                    'reason': 'No sufficient compatible activity was found for this model. No score was generated.'}
                continue
            cached = self.store.artifact(lease['id'], 'mock_outcome_fixed_0999_v1', task)
            if cached:
                if cached['sample_id'] != sample['sample_id']:
                    raise ServiceError('data_incomplete')
                outcomes[task] = cached
            else:
                try:
                    outcome, delivery = await self.predictor.predict(sample, collector.directory)
                    outcomes[task] = outcome
                    self.store.save(lease, {'tasks': [outcomes[t] for t in request.tasks]},
                        artifacts={('mock_outcome_fixed_0999_v1', task): outcome, ('model_delivery', task): delivery})
                except (ValueError, KeyError):
                    outcomes[task] = {'task_id': task, 'status': 'model_error', 'score': None,
                        'reason_code': 'model_input_mismatch', 'reason': 'Model input preparation failed. Real chain data remains available.'}
        header = await self.rpc.call('eth_getBlockByNumber', [hex(context['cutoff_block']), False])
        if not isinstance(header, dict) or header.get('hash') != context['cutoff_hash']:
            raise ServiceError('data_incomplete')
        complete = all(r['status'] in ('ok', 'not_applicable') for r in outcomes.values())
        result = self.store.get(lease['id'])
        result.update(status='completed' if complete else 'partial', stage='completed',
            tasks=[outcomes[t] for t in request.tasks],
            message='Real Ethereum data collected. Scores and labels use the fixed mock response (0.999).' if complete else
                    'Real chain data is available; one or more assessments have no score.',
            progress={'state': 'completed' if complete else 'partial', 'unit': 'tasks',
                      'completed': len(outcomes), 'total': len(outcomes), 'total_final': True})
        AnalysisResult.model_validate(result)
        self.store.save(lease, result, finish=True)
