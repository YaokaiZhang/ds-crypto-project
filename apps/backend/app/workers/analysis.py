"""Durable single-host ETH worker with real collection and simulated scoring."""
import argparse
import asyncio
import logging
import os
import sys
import time

from ..adapters.analysis_store import LeaseLost, utc
from ..application.live_pipeline import LivePipeline
from ..container import build_container
from ..errors import FeatureNotImplemented, QuotaExhausted, ServiceError
from ..settings import Settings

log = logging.getLogger(__name__)


class AnalysisWorker:
    def __init__(self, services, worker_id, *, pipeline=None):
        self.services = services
        self.worker_id = f'{worker_id}-{os.getpid()}'
        self.real = services.real
        if self.real:
            self.store, self.settings = self.real.store, self.real.settings
            self.pipeline = pipeline or LivePipeline(self.settings, self.store, self.real.budget)

    async def _heartbeat(self, lease):
        while True:
            await asyncio.sleep(self.settings.analysis_lease_seconds / 3)
            self.store.heartbeat(lease, self.settings.analysis_lease_seconds)

    async def _execute(self, lease):
        heartbeat = asyncio.create_task(self._heartbeat(lease))
        try:
            await self.pipeline.execute(lease)
        except QuotaExhausted as error:
            result = self.store.get(lease['id'])
            progress = result.get('progress') or {'unit': 'requests', 'completed': 0}
            self.store.save(lease, {'status': 'waiting_quota', 'message': str(error),
                'progress': {**progress, 'state': 'waiting_quota', 'retry_at': utc(error.retry_at)}},
                retry_at=error.retry_at, finish=True)
        except asyncio.CancelledError:
            try:
                self.store.save(lease, {'status': 'queued', 'message': 'Worker stopped; queued for recovery.',
                    'progress': {'state': 'queued', 'unit': 'requests', 'completed': 0}}, finish=True)
            except LeaseLost:
                pass
            raise
        except LeaseLost:
            pass
        except Exception as failure:
            error = failure if isinstance(failure, ServiceError) else ServiceError('internal_error')
            count = lease['failures'] + 1
            if error.retryable and count < 5:
                when = time.time() + min(60, 2 ** count)
                progress = self.store.get(lease['id']).get('progress') or {'unit': 'requests', 'completed': 0}
                self.store.save(lease, {'status': 'running', 'message': str(error),
                    'progress': {**progress, 'state': 'retrying', 'retry_at': utc(when)}},
                    retry_at=when, failures=count, finish=True)
            else:
                result = self.store.get(lease['id'])
                tasks = []
                for task in result['tasks']:
                    if task['status'] == 'not_applicable' or task['status'] == 'ok' and error.code != 'data_incomplete':
                        tasks.append(task)
                    else:
                        tasks.append({'task_id': task['task_id'], 'status': error.code, 'reason_code': error.code,
                                      'reason': str(error), 'score': None})
                status = 'partial' if result.get('basic_information') else 'failed'
                self.store.save(lease, {'status': status, 'message': str(error), 'tasks': tasks,
                    'progress': {'state': status, 'unit': 'tasks', 'completed': 0}}, finish=True, failures=count)
            log.warning('Chain analysis interrupted (%s; attempt %d; type %s)', error.code, count, type(failure).__name__)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def run_once(self):
        if not self.real:
            raise FeatureNotImplemented('worker.analysis.run_once')
        self.store.worker_tick(self.worker_id)
        lease = self.store.claim(self.worker_id, self.settings.analysis_lease_seconds, self.settings.analysis_concurrency)
        if not lease:
            return False
        await self._execute(lease)
        return True

    async def run_forever(self):
        if not self.real:
            raise FeatureNotImplemented('worker.analysis.run_forever')
        active = set()
        last_tick = 0
        try:
            while True:
                if time.time() - last_tick >= 5:
                    self.store.worker_tick(self.worker_id)
                    last_tick = time.time()
                for task in list(active):
                    if task.done():
                        active.remove(task)
                        try:
                            task.result()
                        except LeaseLost:
                            pass
                while len(active) < self.settings.analysis_concurrency:
                    lease = self.store.claim(self.worker_id, self.settings.analysis_lease_seconds, self.settings.analysis_concurrency)
                    if lease is None:
                        break
                    active.add(asyncio.create_task(self._execute(lease)))
                await asyncio.sleep(.25)
        finally:
            for task in active:
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            self.store.worker_remove(self.worker_id)
            await self.pipeline.close()


async def _run(worker_id, once=False):
    services = build_container(Settings.from_environment())
    worker = AnalysisWorker(services, worker_id)
    try:
        if once:
            try:
                await worker.run_once()
            finally:
                if worker.real:
                    worker.store.worker_remove(worker.worker_id)
                    await worker.pipeline.close()
        else:
            await worker.run_forever()
    finally:
        services.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-id', default='analysis-worker')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    try:
        asyncio.run(_run(args.worker_id, args.once))
    except FeatureNotImplemented as error:
        print(error, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
