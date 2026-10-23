"""Template boundary checks: never advertise a working analysis or live feed."""
import unittest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from apps.backend.app.main import create_app
from apps.backend.app.api.schemas import AnalysisRequest, TaskResult
from apps.backend.app.settings import Settings


class TemplateBoundaryChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.application = create_app(Settings())
        self.lifespan = self.application.router.lifespan_context(self.application)
        await self.lifespan.__aenter__()
        self.client = AsyncClient(transport=ASGITransport(app=self.application), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    async def test_liveness_does_not_imply_service_readiness(self):
        self.assertEqual((await self.client.get('/api/v1/health/live')).status_code, 200)
        ready = await self.client.get('/api/v1/health/ready')
        self.assertEqual(ready.status_code, 503)
        self.assertFalse(any(ready.json()['components'].values()))
        capabilities = (await self.client.get('/api/v1/capabilities')).json()
        self.assertFalse(capabilities['analysis_enabled'])
        self.assertFalse(capabilities['feed_enabled'])
        self.assertFalse(any(task['model_available'] for task in capabilities['tasks']))

    async def test_create_never_returns_a_fake_accepted_job(self):
        for family in ('eth_scam', 'token_scam'):
            with self.subTest(family=family):
                response = await self.client.post('/api/v1/analyses', json={
                    'target': '0x' + '11' * 20, 'family': family,
                })
                self.assertEqual(response.status_code, 501)
                self.assertEqual(response.json()['code'], 'not_implemented')
                self.assertNotIn('analysis_id', response.json())
                self.assertNotIn('score', response.json())

    async def test_reads_and_streams_do_not_simulate_completed_data(self):
        identity = str(uuid4())
        paths = [f'/analyses/{identity}', f'/analyses/{identity}/graphs/phishing',
                 f'/analyses/{identity}/activity', f'/analyses/{identity}/transactions',
                 f'/analyses/{identity}/events', '/feed/recent', '/feed/events']
        for path in paths:
            with self.subTest(path=path):
                response = await self.client.get('/api/v1' + path)
                self.assertEqual(response.status_code, 501)
                self.assertEqual(response.json()['code'], 'not_implemented')

    async def test_request_scope_is_validated_before_template_execution(self):
        valid = {'target': '0x' + '11' * 20, 'family': 'eth_scam'}
        invalid = [
            {**valid, 'target': 'not-an-address'},
            {**valid, 'chain_id': 137},
            {**valid, 'tasks': ['honeypot']},
            {**valid, 'tasks': ['phishing', 'phishing']},
            {**valid, 'pools': ['0x' + '22' * 20]},
            {**valid, 'model_path': '/tmp/arbitrary-model'},
            {**valid, 'cutoff': '2026-10-12T12:00:00'},
        ]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual((await self.client.post('/api/v1/analyses', json=body)).status_code, 422)

    def test_request_adapter_preserves_family_scope_and_normalizes_addresses(self):
        request = AnalysisRequest(target='0x' + 'AB' * 20, family='token_scam',
                                  pools=['0x' + 'CD' * 20], cutoff='2026-10-12T12:00:00Z')
        command = request.to_command()
        self.assertEqual(command.target, '0x' + 'ab' * 20)
        self.assertEqual(command.tasks, ('honeypot', 'rug_pull'))
        self.assertEqual(command.pools, ('0x' + 'cd' * 20,))
        self.assertIsNotNone(command.cutoff.tzinfo)

    def test_score_schema_rejects_unavailable_or_unversioned_outputs(self):
        invalid = [
            {'status': 'model_unavailable', 'score': 0.8},
            {'status': 'ok', 'score': 0.8},
            {'status': 'data_only', 'score': None, 'risk_band': 'low'},
            {'status': 'ok', 'score': 0.8, 'sample_id': 'sample', 'model_version': 'model', 'risk_band': 'high'},
        ]
        for result in invalid:
            with self.subTest(result=result), self.assertRaises(ValidationError):
                TaskResult(task_id='phishing', **result)
        unavailable = TaskResult(task_id='honeypot', status='data_only')
        self.assertIsNone(unavailable.score)
        scored = TaskResult(task_id='phishing', status='ok', score=0.8,
                            sample_id='sample', model_version='model')
        self.assertEqual(scored.score, 0.8)


if __name__ == '__main__':
    unittest.main()
