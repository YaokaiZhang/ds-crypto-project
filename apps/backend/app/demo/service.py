"""SQLite-backed demo jobs and replayable SSE; no provider/model side effects."""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from ..api.schemas import AnalysisRequest
from ..settings import Settings
from .datasets import CUTOFF, POOL, PROFILES, build_dataset, iso


class DemoAnalysisService:
    def __init__(self, settings: Settings):
        self.scale = settings.demo_delay_scale
        path = Path(settings.demo_database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, idem TEXT UNIQUE, fingerprint TEXT, payload TEXT NOT NULL)')
        self.db.commit()
        self.running: dict[str, asyncio.Task] = {}
        self.slots = asyncio.Semaphore(4)

    async def start(self):
        for identity, payload in self.db.execute('SELECT id, payload FROM jobs').fetchall():
            if json.loads(payload)['result']['status'] not in ('completed', 'failed'):
                self._schedule(identity)

    async def close(self):
        tasks = list(self.running.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.db.close()

    def capabilities(self) -> dict:
        return {'mode': 'demo', 'result_origin': 'synthetic', 'analysis_enabled': True,
                'feed_enabled': False, 'events_enabled': True, 'profiles': PROFILES,
                'tasks': [{'task_id': task, 'entity': 'contract' if task == 'ponzi' else 'address' if task == 'phishing' else 'token',
                           'model_available': False, 'assessment_available': True,
                           'result_origin': 'synthetic'} for task in ('phishing', 'ponzi', 'honeypot', 'rug_pull')]}

    def _read(self, identity: str) -> dict:
        row = self.db.execute('SELECT payload FROM jobs WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Analysis not found')
        return json.loads(row[0])

    def _write(self, identity: str, payload: dict):
        self.db.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(payload), identity))
        self.db.commit()

    def _stage(self, identity: str, stage: str, message: str, patch: dict | None = None):
        job = self._read(identity)
        result = job['result']
        result.update(patch or {})
        result.update(stage=stage, status=stage if stage in ('completed', 'failed') else 'running',
                      message=message, updated_at=iso(datetime.now(timezone.utc)))
        job['events'].append({'sequence': len(job['events']) + 1, 'analysis_id': identity,
                              'stage': stage, 'status': result['status'], 'message': message,
                              'timestamp': result['updated_at']})
        self._write(identity, job)

    def _schedule(self, identity: str):
        if identity in self.running:
            return
        task = asyncio.create_task(self._execute(identity))
        self.running[identity] = task
        task.add_done_callback(lambda _task: self.running.pop(identity, None))

    async def create(self, command, idempotency_key: str | None = None) -> dict:
        if command.pools and command.pools != (POOL,):
            raise HTTPException(422, 'Pool is outside the configured token scope')
        request = AnalysisRequest(target=command.target, family=command.family, tasks=list(command.tasks),
                                  cutoff=command.cutoff or CUTOFF, pools=list(command.pools))
        body = request.model_dump(mode='json')
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if idempotency_key:
            existing = self.db.execute('SELECT id, fingerprint FROM jobs WHERE idem=?', (idempotency_key,)).fetchone()
            if existing:
                if existing[1] != fingerprint:
                    raise HTTPException(409, 'Idempotency key was already used for a different request')
                return await self.get(existing[0])
        identity = str(uuid4())
        now = iso(datetime.now(timezone.utc))
        result = {'analysis_id': identity, 'target': command.target, 'family': command.family,
                  'status': 'queued', 'stage': 'queued', 'result_origin': 'synthetic',
                  'created_at': now, 'updated_at': now, 'cutoff': iso(CUTOFF),
                  'message': 'Analysis accepted', 'tasks': [{'task_id': task, 'status': 'pending'} for task in command.tasks],
                  'graphs': {}, 'activity': None, 'transactions': None, 'basic_information': None}
        job = {'command': body, 'result': result, 'ledger': [], 'events': [
            {'sequence': 1, 'analysis_id': identity, 'stage': 'queued', 'status': 'queued',
             'message': 'Analysis accepted', 'timestamp': now}]}
        self.db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?)', (identity, idempotency_key, fingerprint, json.dumps(job)))
        self.db.commit()
        self._schedule(identity)
        return deepcopy(result)

    async def _execute(self, identity: str):
        try:
            async with self.slots:
                command = AnalysisRequest.model_validate(self._read(identity)['command'])
                for stage, message, delay in (
                    ('resolving', 'Identifying contract and observation scope', .6),
                    ('collecting', 'Retrieving transactions and indexed events', 2.6),
                    ('normalizing', 'Reconciling event identities, units and coverage', .8),
                ):
                    self._stage(identity, stage, message)
                    await asyncio.sleep(delay * self.scale)
                dataset = build_dataset(command, identity)
                job = self._read(identity)
                job['ledger'] = dataset['ledger']
                self._write(identity, job)
                prepared = dataset['result']
                facts = {key: prepared[key] for key in ('snapshot_id', 'cutoff', 'cutoff_block', 'cutoff_block_hash',
                                                        'window_start', 'basic_information', 'activity')}
                facts['transactions'] = await self.transactions(identity, 30, None)
                self._stage(identity, 'building_graph', 'Preparing task-specific transaction graphs', facts)
                await asyncio.sleep(1.3 * self.scale)
                self._stage(identity, 'predicting', 'Transaction graphs ready; evaluating independent task models',
                            {'graphs': prepared['graphs'], 'tasks': [
                                {'task_id': task, 'status': 'predicting', 'sample_id': prepared['graphs'][task]['sample_id']}
                                for task in command.tasks]})
                await asyncio.sleep(2.4 * self.scale)
                self._stage(identity, 'completed', 'Analysis complete', {'tasks': prepared['tasks']})
        except asyncio.CancelledError:
            raise  # Persisted unfinished jobs resume on the next demo startup.
        except Exception:
            self._stage(identity, 'failed', 'Analysis could not be completed',
                        {'tasks': [{'task_id': task['task_id'], 'status': 'failed', 'reason': 'Analysis processing failed'}
                                   for task in self._read(identity)['result']['tasks']]})

    async def get(self, identity: str) -> dict:
        return self._read(identity)['result']

    async def graph(self, identity: str, task: str) -> dict:
        result = await self.get(identity)
        if task not in [item['task_id'] for item in result['tasks']]:
            raise HTTPException(404, 'Task is not part of this analysis')
        if task not in result['graphs']:
            raise HTTPException(409, 'Graph is not ready')
        return result['graphs'][task]

    async def activity(self, identity: str) -> dict:
        result = await self.get(identity)
        if not result['activity']:
            raise HTTPException(409, 'Activity data is not ready')
        return result['activity']

    async def transactions(self, identity: str, limit: int, cursor: str | None, category: str | None = None) -> dict:
        job = self._read(identity)
        family = job['command']['family']
        allowed = ('external', 'internal') if family == 'eth_scam' else ('token_transfer', 'pool_event')
        category = category or allowed[0]
        if category not in allowed:
            raise HTTPException(422, 'Record category does not belong to this analysis')
        if not job['ledger']:
            raise HTTPException(409, 'Ledger is not ready')
        offset = 0
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if decoded['analysis_id'] != identity or decoded['category'] != category:
                    raise ValueError()
                offset = decoded['offset']
                if not isinstance(offset, int) or offset < 0:
                    raise ValueError()
            except (ValueError, KeyError, TypeError, UnicodeError):
                raise HTTPException(400, 'Invalid pagination cursor') from None
        rows = [item for item in job['ledger'] if item['category'] == category]
        next_offset = offset + limit
        next_cursor = base64.urlsafe_b64encode(json.dumps({'analysis_id': identity, 'category': category,
                                                         'offset': next_offset}).encode()).decode() if next_offset < len(rows) else None
        return {'items': rows[offset:next_offset], 'next_cursor': next_cursor, 'category': category, 'total': len(rows)}

    async def events(self, identity: str, last_event_id: str | None):
        self._read(identity)
        try:
            sequence = int(last_event_id or '0')
            if sequence < 0 or sequence > len(self._read(identity)['events']):
                raise ValueError()
        except ValueError:
            raise HTTPException(400, 'Invalid event cursor') from None

        async def stream():
            nonlocal sequence
            ticks = 0
            while True:
                job = self._read(identity)
                for event in job['events'][sequence:]:
                    sequence = event['sequence']
                    yield f"id: {sequence}\nevent: progress\ndata: {json.dumps(event)}\n\n"
                if job['result']['status'] in ('completed', 'failed'):
                    return
                ticks += 1
                if ticks % 100 == 0:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(.15)
        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
