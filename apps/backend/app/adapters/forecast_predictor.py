"""Temporary Forecast predictor with a replaceable binary decision policy."""
import asyncio
import hashlib
import json
import math
from pathlib import Path
import secrets

import httpx
from packages.io import atomic_bytes
from scripts.build_wallet_graph import validate_graph


class ForecastPolicy:
    def __init__(self,path):
        self.data = json.loads(Path(path).read_text())
        d = self.data
        threshold = d.get('threshold')
        if (isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold)
                or not 0 <= threshold <= 1 or not d.get('policy_version')
                or d.get('model_version') != 'forecast-wallet-graph-mock-v1' or d.get('score_target') != 'continued_activity'
                or d.get('positive_outcome') != 'continued_activity' or d.get('negative_outcome') != 'low_volume_dead'
                or d.get('observation_days') != 7 or d.get('horizon_days') != 90 or d.get('swap_volume_threshold_usd') != '1000'):
            raise ValueError('Invalid Forecast decision policy')

    def outcome(self,score):
        if not isinstance(score,(int,float)) or isinstance(score,bool) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid Forecast score')
        return self.data['positive_outcome'] if score >= self.data['threshold'] else self.data['negative_outcome']


class ForecastMockPredictor:
    def __init__(self,settings,*,transport=None,rng=None):
        self.url = settings.mock_predictor_url
        self.policy = ForecastPolicy(settings.forecast_policy_path)
        self.client = httpx.AsyncClient(transport=transport,timeout=.8,trust_env=False)
        self.rng = rng or secrets.SystemRandom().random

    async def close(self):
        await self.client.aclose()

    async def predict(self,payload,directory):
        validate_graph(payload['graph_sample'])
        if (not payload['quality']['observation_complete'] or not payload['quality']['model_ready']
                or payload['graph_sample']['stats']['window_swap_count'] < 1
                or payload['model_version'] != self.policy.data['model_version']):
            raise ValueError('Forecast input is not eligible for mock prediction')
        body = json.dumps(payload,sort_keys=True,allow_nan=False).encode()
        digest = hashlib.sha256(body).hexdigest()
        path = Path(directory)/'model_inputs'/f'continued_activity-{digest}.json'
        await asyncio.to_thread(atomic_bytes,path,body,immutable=True)
        delivery = 'target_unavailable'
        try:
            await self.client.post(self.url,content=body,headers={'Content-Type':'application/json'})
            delivery = 'target_responded_ignored'
        except httpx.HTTPError:
            pass
        score = float(self.rng())
        decision = self.policy.outcome(score)
        metadata = {k:self.policy.data[k] for k in ('observation_days','horizon_days','swap_volume_threshold_usd','score_target')}
        metadata.update(outcome=decision,decision_policy_version=self.policy.data['policy_version'])
        outcome = {'task_id':'continued_activity','status':'ok','score':score,'sample_id':payload['sample_id'],
            'model_version':'simulated:'+payload['model_version'],'calibration':'uncalibrated','decision':decision,
            'result_origin':'simulated','forecast':metadata,
            'explanation':'Selected-pool swap volume is forecast '+('at least' if decision=='continued_activity' else 'below')+
                ' USD 1,000 over the following 90 days.',
            'reason':None}
        return outcome, {'input_sha256':digest,'input_path':str(path),'delivery':delivery,'target':self.url,
            'result_origin':'simulated','preprocessing':payload['preprocessing'],'decision_policy':self.policy.data}
