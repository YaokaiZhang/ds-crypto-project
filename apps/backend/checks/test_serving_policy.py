"""Quota boundaries, provider failure semantics and actual-progress contracts."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from apps.backend.app.adapters.analysis_rpc import AnalysisRpc
from apps.backend.app.adapters.etherscan_budget import EtherscanBudget
from apps.backend.app.adapters.etherscan_client import BackendEtherscan
from apps.backend.app.api.schemas import AnalysisProgress, TaskResult
from apps.backend.app.application.risk import RiskPolicy
from apps.backend.app.application.strategies import TASK_STRATEGIES
from apps.backend.app.domain import EntityResolution
from apps.backend.app.errors import QuotaExhausted, ServiceError
from apps.backend.app.main import create_app
from apps.backend.app.settings import PROJECT_ROOT, Settings, server_credential
from packages.provider_access import SerialRequestBudget


def reserve_in_process(path):
    budget = EtherscanBudget(path, limit=3)
    try:
        asyncio.run(budget.acquire())
        return 'reserved', time.time()
    except QuotaExhausted:
        return 'exhausted', time.time()


class Clock:
    def __init__(self, now=86400 * 10 + 1000):
        self.now = float(now)

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        self.now += delay


class BudgetChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'quota.sqlite3'
        self.clock = Clock()

    def budget(self, **options):
        return EtherscanBudget(self.path, clock=self.clock, sleep=self.clock.sleep, **options)

    async def test_pacing_retries_restart_and_utc_midnight(self):
        self.clock.now = 11 * 86400 - .2
        budget = self.budget(limit=2)
        self.assertFalse(self.path.exists())
        await budget.acquire()
        self.assertEqual(budget.snapshot().used, 1)
        # A new object must respect the previous request's spacing across midnight.
        await self.budget(limit=2).acquire()
        self.assertGreater(self.clock.now, 11 * 86400)
        self.assertEqual(budget.snapshot().used, 1)
        await budget.acquire()
        with self.assertRaises(QuotaExhausted) as error:
            await budget.acquire()
        self.assertEqual(error.exception.retry_at, 12 * 86400)
        self.assertEqual(budget.snapshot().used, 2)
        with self.assertRaises(QuotaExhausted):
            self.budget(limit=2).check_admission()
        # Resumption keeps old ledger rows for the trainer's rolling window.
        self.clock.now = 12 * 86400
        self.assertEqual(budget.check_admission().remaining, 2)
        await budget.acquire()
        self.assertEqual(budget.snapshot().used, 1)

    async def test_admission_does_not_consume_requests_and_failed_attempts_do(self):
        budget = self.budget(limit=1)
        for _ in range(3):
            self.assertEqual(budget.check_admission().used, 0)
        await budget.acquire()
        # An HTTP failure after reservation never refunds the consumed quota.
        self.assertEqual(self.budget(limit=1).snapshot().used, 1)
        with self.assertRaises(QuotaExhausted):
            self.budget(limit=1).reserve()

    async def test_legacy_training_and_backend_share_account_ledger(self):
        legacy = SerialRequestBudget(self.path, clock=self.clock, sleep=lambda delay: None)
        with legacy.request_slot():
            pass
        budget = self.budget()
        self.assertEqual(budget.snapshot().used, 1)
        self.assertGreater(budget.reserve(), 0)
        self.clock.now += .4
        self.assertEqual(budget.reserve(), 0)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT SUM(calls) FROM buckets').fetchone()[0], 2)

    def test_processes_cannot_each_spend_the_same_remaining_quota(self):
        EtherscanBudget(self.path, limit=3).snapshot()
        with ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve_in_process, [str(self.path)] * 6))
        self.assertEqual(sum(state == 'reserved' for state, _ in results), 3)
        self.assertEqual(EtherscanBudget(self.path, limit=3).snapshot().used, 3)
        starts = sorted(stamp for state, stamp in results if state == 'reserved')
        self.assertTrue(all(b - a >= .30 for a, b in zip(starts, starts[1:])))

    def test_store_failure_is_explicit_and_does_not_disable_limits(self):
        self.path.mkdir()
        with self.assertRaises(ServiceError) as error:
            self.budget().check_admission()
        self.assertEqual(error.exception.code, 'quota_store_unavailable')


class ProviderChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.budget = EtherscanBudget(Path(self.temp.name) / 'quota.sqlite3',
                                     clock=self.clock, sleep=self.clock.sleep)
        self.settings = Settings(etherscan_api_key='private-test-key',
                                 ethereum_rpc_url='https://rpc.example/private-test-token')

    async def test_empty_history_is_distinct_from_auth_rate_and_malformed_responses(self):
        payloads = [
            ({'status': '0', 'message': 'No transactions found', 'result': []}, None),
            ({'status': '0', 'message': 'NOTOK', 'result': 'Invalid API Key private-test-key'}, 'provider_authentication'),
            ({'status': '0', 'message': 'NOTOK', 'result': 'Max rate limit reached'}, 'provider_rate_limited'),
            ({'status': '0', 'message': 'NOTOK', 'result': []}, 'provider_response_invalid'),
            ({'status': '1', 'result': ['bad-row']}, 'provider_response_invalid'),
        ]
        for payload, code in payloads:
            client = BackendEtherscan(self.settings, self.budget, retries=0,
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
            try:
                if code is None:
                    self.assertEqual(await client.request('account', 'txlist'), [])
                else:
                    with self.assertRaises(ServiceError) as error:
                        await client.request('account', 'txlist')
                    self.assertEqual(error.exception.code, code)
                    self.assertNotIn('private-test-key', json.dumps(error.exception.public_body()))
            finally:
                await client.close()
        self.assertEqual(self.budget.snapshot().used, len(payloads))

    async def test_retries_share_quota_and_exhaustion_stops_before_another_attempt(self):
        calls = []
        def response(request):
            calls.append(request)
            return httpx.Response(503, text='upstream failure private-test-key')
        budget = EtherscanBudget(Path(self.temp.name) / 'small.sqlite3', limit=2,
                                 clock=self.clock, sleep=self.clock.sleep)
        client = BackendEtherscan(self.settings, budget, sleep=self.clock.sleep,
                                 transport=httpx.MockTransport(response))
        try:
            with self.assertRaises(QuotaExhausted):
                await client.request('account', 'txlist')
            self.assertEqual(len(calls), 2)
            self.assertEqual(budget.snapshot().used, 2)
        finally:
            await client.close()

    async def test_rpc_classification_is_cutoff_bound_and_does_not_spend_etherscan_quota(self):
        for code, expected in [('0x', 'eoa'), ('0x60016000', 'contract'), ('0xef0100' + '22' * 20, 'delegated')]:
            requests = []
            def response(request):
                body = json.loads(request.content); requests.append(body)
                return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'],
                    'result': '0x1' if body['method'] == 'eth_chainId' else code})
            rpc = AnalysisRpc(self.settings, transport=httpx.MockTransport(response))
            try:
                entity = await rpc.classify_address('0x' + 'AB' * 20, 123)
                self.assertEqual(entity.entity_type, expected)
                self.assertEqual(requests[-1]['params'], ['0x' + 'ab' * 20, '0x7b'])
                self.assertEqual(self.budget.snapshot().used, 0)
            finally:
                await rpc.close()

    async def test_rpc_failure_never_becomes_an_ordinary_wallet(self):
        def timeout(request):
            raise httpx.ReadTimeout('private-test-token', request=request)
        rpc = AnalysisRpc(self.settings, transport=httpx.MockTransport(timeout))
        try:
            with self.assertRaises(ServiceError) as error:
                await rpc.classify_address('0x' + '11' * 20, 123)
            self.assertEqual(error.exception.code, 'provider_unavailable')
            self.assertNotIn('private-test-token', str(error.exception))
        finally:
            await rpc.close()


class ContractChecks(unittest.IsolatedAsyncioTestCase):
    def test_applicability_does_not_equate_contract_with_guaranteed_score(self):
        for kind, expected in [('eoa', False), ('contract', True), ('token', True), ('unresolved', False), ('delegated', False)]:
            entity = EntityResolution('0x' + '11' * 20, kind)
            self.assertEqual(TASK_STRATEGIES['ponzi'].check_applicability(entity)[0], expected)
            self.assertEqual(TASK_STRATEGIES['phishing'].check_applicability(entity)[0], kind in ('eoa', 'contract', 'token'))
        token = EntityResolution('0x' + '11' * 20, 'token')
        self.assertFalse(TASK_STRATEGIES['rug_pull'].check_applicability(token)[0])

    def test_no_data_and_unavailable_outputs_cannot_be_zero_score_or_low(self):
        for status in ('no_activity', 'insufficient_history', 'not_applicable', 'model_unavailable'):
            value = TaskResult(task_id='ponzi', status=status, reason='No applicable assessment.')
            self.assertIsNone(value.score)
            self.assertIsNone(value.risk_band)
            with self.assertRaises(ValidationError):
                TaskResult(task_id='ponzi', status=status, score=0, risk_band='low',
                           sample_id='sample', model_version='model', risk_band_policy_version='policy')

    def test_progress_requires_valid_counts_and_quota_resume_time(self):
        AnalysisProgress(completed=42, total=60, total_final=False, records_collected=4000)
        AnalysisProgress(state='waiting_quota', completed=42, retry_at='2026-10-25T00:00:00Z')
        for invalid in ({'completed': 5, 'total': 4}, {'total_final': True}, {'state': 'waiting_quota'}):
            with self.assertRaises(ValidationError):
                AnalysisProgress(**invalid)

    def test_risk_boundaries_use_raw_scores_and_exact_model_versions(self):
        policy = RiskPolicy.load(PROJECT_ROOT / 'deploy/registry/risk_policies.json')
        for task, entry in policy.models.items():
            version = entry['model_version']; low = entry['L']; high = entry['H']
            self.assertEqual(policy.classify(task, version, low - .00001), 'low')
            self.assertEqual(policy.classify(task, version, low), 'medium')
            self.assertEqual(policy.classify(task, version, high), 'high')
            self.assertIsNone(policy.classify(task, 'different-weights', high))
        self.assertEqual(policy.models['rug_pull']['L'], .4)

    def test_backend_local_credentials_are_literal_only_and_hidden_in_repr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'local_secrets.py'
            path.write_text('raise RuntimeError("never execute")\nETHERSCAN_API_KEY = "local-only-secret"\n')
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(server_credential('ETHERSCAN_API_KEY', path=path), 'local-only-secret')
            with patch.dict(os.environ, {'ETHERSCAN_API_KEY': ''}):
                self.assertIsNone(server_credential('ETHERSCAN_API_KEY', path=path))
            path.write_text('ETHERSCAN_API_KEY = str("private-value")\n')
            with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError) as error:
                server_credential('ETHERSCAN_API_KEY', path=path)
            self.assertNotIn('private-value', str(error.exception))
        self.assertNotIn('private-value', repr(Settings(etherscan_api_key='private-value', ethereum_rpc_url='private-value')))

    async def test_public_errors_and_unexpected_exceptions_never_expose_upstream_details(self):
        app = create_app(Settings())
        @app.get('/quota-check')
        async def quota():
            raise QuotaExhausted(time.time() + 60)
        @app.get('/broken-check')
        async def broken():
            raise RuntimeError('private-token-in-upstream-url')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
            response = await client.get('/quota-check')
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json()['code'], 'quota_exhausted')
            self.assertIn('Retry-After', response.headers)
            response = await client.get('/broken-check')
            self.assertEqual(response.status_code, 500)
            self.assertNotIn('private-token', response.text)


if __name__ == '__main__':
    unittest.main()
