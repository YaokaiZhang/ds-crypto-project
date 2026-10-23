"""Focused Forecast HTTP lifecycle and point-in-time fixture checks."""
import asyncio
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from apps.backend.app.main import create_app
from apps.backend.app.settings import Settings
from apps.backend.app.api.schemas import AnalysisRequest, TaskResult
from apps.backend.app.demo.datasets import build_dataset, fixture_cutoff, POOL


class ForecastChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.path = Path(__file__).resolve().parents[1] / '.runtime' / f'forecast-check-{uuid4()}.sqlite3'
        self.app = create_app(Settings(analysis_mode='demo', demo_database_path=str(self.path), demo_delay_scale=.03))
        self.lifecycle = self.app.router.lifespan_context(self.app)
        await self.lifecycle.__aenter__()
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifecycle.__aexit__(None, None, None)
        self.path.unlink(missing_ok=True)

    async def test_http_stages_scope_replay_and_pagination(self):
        caps = (await self.client.get('/api/v1/capabilities')).json()
        task = next(t for t in caps['tasks'] if t['task_id'] == 'continued_activity')
        self.assertFalse(task['model_available']); self.assertTrue(task['assessment_available'])
        body = {'family': 'forecast', 'target': '0x' + 'ab' * 20, 'cutoff': '2030-01-01T00:00:00Z', 'pools': [POOL]}
        accepted = await self.client.post('/api/v1/analyses', json=body, headers={'Idempotency-Key':'forecast-one'})
        self.assertEqual(accepted.status_code, 202)
        initial = accepted.json(); identity = initial['analysis_id']; url = f'/api/v1/analyses/{identity}'
        self.assertEqual(initial['cutoff'], fixture_cutoff('forecast').isoformat().replace('+00:00','Z'))
        self.assertEqual(initial['tasks'][0]['task_id'], 'continued_activity')
        self.assertIsNone(initial['tasks'][0]['score'])
        self.assertEqual((await self.client.post('/api/v1/analyses', json=body, headers={'Idempotency-Key':'forecast-one'})).json()['analysis_id'], identity)
        self.assertEqual((await self.client.post('/api/v1/analyses', json={**body,'target':'0x'+'cd'*20}, headers={'Idempotency-Key':'forecast-one'})).status_code,409)
        self.assertEqual((await self.client.get(url+'/graphs/continued_activity')).status_code,409)
        seen = set()
        for _ in range(500):
            value = (await self.client.get(url)).json(); seen.add(value['stage'])
            if value['stage'] == 'building_graph':
                self.assertIsNotNone(value['activity']); self.assertTrue(value['transactions']['items'])
                self.assertFalse(value['graphs']); self.assertIsNone(value['tasks'][0]['score'])
            if value['stage'] == 'predicting':
                self.assertTrue(value['graphs']); self.assertIsNone(value['tasks'][0]['score'])
            if value['status'] in ('completed','failed'): break
            await asyncio.sleep(.002)
        self.assertEqual(value['status'],'completed'); self.assertTrue({'building_graph','predicting'} <= seen)
        result = value['tasks'][0]; graph = value['graphs']['continued_activity']
        self.assertEqual(result['sample_id'],graph['sample_id']); self.assertEqual(graph['sample_id'],graph['context']['sample_id'])
        self.assertEqual(graph['context']['cutoff'],value['cutoff'])
        self.assertIsNone(result['risk_band']); self.assertEqual(result['forecast']['horizon_days'],90)
        self.assertEqual(result['forecast']['score_target'],'continued_activity')
        self.assertEqual(result['decision'],'low_volume_dead')
        self.assertEqual((await self.client.get(url+'/graphs/honeypot')).status_code,404)
        self.assertEqual((await self.client.get(url+'/transactions?category=external')).status_code,422)
        first = (await self.client.get(url+'/transactions?limit=10&category=token_transfer')).json()
        self.assertEqual(len(first['items']),10); self.assertTrue(first['next_cursor'])
        second = (await self.client.get(url+'/transactions',params={'limit':10,'category':'token_transfer','cursor':first['next_cursor']})).json()
        self.assertFalse({r['id'] for r in first['items']} & {r['id'] for r in second['items']})
        self.assertEqual((await self.client.get(url+'/transactions',params={'category':'pool_event','cursor':first['next_cursor']})).status_code,400)
        stream = await self.client.get(url+'/events',headers={'Last-Event-ID':'4'})
        self.assertIn('id: 5',stream.text); self.assertNotIn('id: 4\n',stream.text); self.assertIn('completed',stream.text)
        for bad in ({'tasks':['honeypot']},{'tasks':['continued_activity','continued_activity']},{'target':'bad'},{'chain_id':137},{'pools':['0x'+'ff'*20]}):
            self.assertEqual((await self.client.post('/api/v1/analyses',json={**body,**bad})).status_code,422)

    def test_fixture_window_and_graph_reconcile_to_observations(self):
        request = AnalysisRequest(family='forecast',target='0x'+'ab'*20)
        data = build_dataset(request,'one'); again = build_dataset(request,'two')
        r = data['result']; start=datetime.fromisoformat(r['window_start']); cutoff=datetime.fromisoformat(r['cutoff'])
        self.assertEqual(cutoff-start,timedelta(days=7)); self.assertEqual(len(r['activity']['points']),7)
        for row in data['ledger']+data['graph_events']:
            self.assertTrue(start<=datetime.fromisoformat(row['block_time'].replace('Z','+00:00'))<=cutoff)
            self.assertLessEqual(row['block_number'],r['cutoff_block'])
        for point in r['activity']['points']:
            counts=Counter(x['event'] for x in data['ledger'] if x['block_time'][:10]==point['date'])
            for key,event in [('transfer_count','Transfer'),('swap_count','Swap'),('mint_count','Mint'),('burn_count','Burn')]:
                self.assertEqual(point[key],counts[event])
        graph=r['graphs']['continued_activity']; swaps=Counter(x['event_data']['sender'] for x in data['graph_events'])
        observed=[e for e in graph['edges'] if e['kind']=='observed']
        self.assertEqual({e['source']:e['event_count'] for e in observed},dict(swaps))
        self.assertEqual(graph['context']['model_edges'],len(graph['edges']))
        self.assertEqual(graph['context']['model_nodes'],len(graph['nodes']))
        self.assertEqual(data['ledger'],again['ledger']); self.assertEqual(r['tasks'][0]['score'],again['result']['tasks'][0]['score'])
        # Root aliases must not collide with a participant identity.
        participant=next(n['id'] for n in graph['nodes'] if n['role']=='wallet')
        collision=build_dataset(AnalysisRequest(family='forecast',target=participant),'collision')['result']['graphs']['continued_activity']
        self.assertEqual(len({n['id'] for n in collision['nodes']}),len(collision['nodes']))
        for edge in collision['edges']:
            self.assertIn(edge['source'],{n['id'] for n in collision['nodes']}); self.assertIn(edge['target'],{n['id'] for n in collision['nodes']})
        with self.assertRaises(ValidationError):
            TaskResult(**{**r['tasks'][0],'risk_band':'high','risk_band_policy_version':'bad'})

    async def test_template_forecast_remains_unavailable(self):
        app=create_app(Settings()); lifecycle=app.router.lifespan_context(app)
        await lifecycle.__aenter__()
        client=AsyncClient(transport=ASGITransport(app=app),base_url='http://test')
        try:
            caps=(await client.get('/api/v1/capabilities')).json()
            self.assertFalse(next(t for t in caps['tasks'] if t['task_id']=='continued_activity')['model_available'])
            self.assertEqual((await client.post('/api/v1/analyses',json={'family':'forecast','target':'0x'+'ab'*20})).status_code,501)
        finally:
            await client.aclose()
            await lifecycle.__aexit__(None,None,None)
