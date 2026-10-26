"""HTTP facade for durable real-chain analysis and explicit scoring modes."""
import asyncio
import base64
import json
import time
from pathlib import Path

import httpx

from fastapi.responses import StreamingResponse

from ..api.schemas import AnalysisRequest
from ..errors import ServiceError
from ..settings import BACKEND_ROOT
from ..adapters.remote_predictor import forecast_input_contract


class LiveAnalysisService:
    def __init__(self, store, budget, settings):
        self.store, self.budget, self.settings = store, budget, settings
        self.models = set()
        self.models_checked_at = float('-inf')
        self.model_lock = asyncio.Lock()

    async def refresh_models(self):
        async with self.model_lock:
            if time.monotonic() - self.models_checked_at < 60:
                return
            available = set()
            if self.settings.inference_url and self.settings.inference_api_key:
                try:
                    expected = {'continued_activity': forecast_input_contract()}
                    for setting, filename in (('model_registry_path', 'eth_models.json'),
                                              ('token_model_registry_path', 'token_models.json')):
                        index = Path(getattr(self.settings, setting) or BACKEND_ROOT / 'config' / filename)
                        for task, bundle in json.loads(index.read_text())['tasks'].items():
                            expected[task] = json.loads((index.parent / bundle / 'manifest.json').read_text())
                    async with httpx.AsyncClient(timeout=self.settings.inference_timeout, trust_env=False) as client:
                        response = await client.get(self.settings.inference_url.rstrip('/') + '/models',
                            headers={'X-Inference-Key': self.settings.inference_api_key})
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict) or not isinstance(data.get('tasks'), list):
                        raise ValueError('Invalid model catalog')
                    if data['status'] == 'ready':
                        available = {item['task_id'] for item in data['tasks']
                            if isinstance(item, dict) and item.get('model_available') is True and item['task_id'] in expected and
                            all(item.get(key) == expected[item['task_id']][key]
                                for key in ('model_version', 'scaler_sha256'))}
                except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError):
                    pass
            self.models, self.models_checked_at = available, time.monotonic()

    def capabilities(self):
        configured = bool(self.settings.ethereum_rpc_url and self.settings.etherscan_api_key)
        return {'mode': self.settings.analysis_mode,
                'analysis_enabled': configured and self.store.worker_alive() and (len(self.models) == 5),
                'supported_families': ['eth_scam', 'token_scam', 'forecast'], 'score_mode': 'model', 'events_enabled': True,
                'result_origin': 'chain_data_model_scores',
                'tasks': [{'task_id': task, 'entity': entity, 'model_available': task in self.models,
                           'assessment_available': task in self.models, 'result_origin': 'model'}
                          for task, entity in [('phishing', 'address'), ('ponzi', 'contract'),
                                               ('honeypot', 'token'), ('rug_pull', 'token'), ('continued_activity', 'token')]]}

    async def create(self, command, idempotency_key=None):
        if command.family not in ('eth_scam', 'token_scam', 'forecast'):
            raise ServiceError('unsupported_family')
        payload = AnalysisRequest(target=command.target, family=command.family, tasks=list(command.tasks),
                                  cutoff=command.cutoff, pools=list(command.pools)).model_dump(mode='json')
        previous = self.store.existing(payload, idempotency_key)
        if previous is not None:
            return previous
        if not self.settings.ethereum_rpc_url or not self.settings.etherscan_api_key:
            raise ServiceError('provider_authentication')
        if not self.settings.inference_url or not self.settings.inference_api_key:
            raise ServiceError('model_unavailable')
        await asyncio.to_thread(self.budget.check_admission)
        return self.store.create(payload, idempotency_key)

    async def get(self, identity):
        return self.store.get(identity)

    async def graph(self, identity, task):
        result = self.store.get(identity)
        if task not in [r['task_id'] for r in result['tasks']]:
            raise ServiceError('analysis_not_found')
        graph = result.get('graphs', {}).get(task)
        if graph is None:
            raise ServiceError('artifact_not_ready')
        return graph

    async def activity(self, identity):
        result = self.store.get(identity)
        if result.get('activity') is None:
            raise ServiceError('artifact_not_ready')
        return result['activity']

    async def transactions(self, identity, limit, cursor=None, category=None):
        result = self.store.get(identity)
        if result.get('transactions') is None:
            raise ServiceError('artifact_not_ready')
        categories = ('external', 'internal') if result['family'] == 'eth_scam' else ('token_transfer', 'pool_event')
        category = category or categories[0]
        if category not in categories:
            raise ServiceError('invalid_request')
        offset = 0
        if cursor:
            try:
                data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if data['analysis_id'] != identity or data['category'] != category:
                    raise ValueError
                offset = data['offset']
                if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                    raise ValueError
            except (ValueError, KeyError, TypeError, UnicodeError):
                raise ServiceError('invalid_cursor') from None
        rows, total = self.store.transactions(identity, category, limit, offset)
        next_offset = offset + len(rows)
        next_cursor = base64.urlsafe_b64encode(json.dumps({
            'analysis_id': identity, 'category': category, 'offset': next_offset}).encode()).decode() if next_offset < total else None
        return {'items': rows, 'category': category, 'total': total, 'next_cursor': next_cursor,
                'revision': result['transactions'].get('revision', 0)}

    async def events(self, identity, last_event_id=None):
        self.store.get(identity)
        try:
            after = int(last_event_id or '0')
            if after < 0:
                raise ValueError
        except ValueError:
            raise ServiceError('invalid_cursor') from None
        self.store.replay(identity, after)

        async def stream():
            nonlocal after
            ticks = 0
            while True:
                rows = self.store.replay(identity, after)
                for seq, event in rows:
                    after = seq
                    yield f'id: {seq}\nevent: progress\ndata: {json.dumps(event)}\n\n'
                if len(rows) < 200 and self.store.get(identity)['status'] in ('completed', 'partial', 'failed'):
                    return
                ticks += 1
                if ticks % 20 == 0:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(.5)
        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
