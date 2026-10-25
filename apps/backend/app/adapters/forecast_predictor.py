"""Real Forecast input with an explicit fixed service-shaped mock response."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
from packages.io import atomic_bytes
from scripts.build_wallet_graph import validate_graph
from .model_response import fixed_mock_response, read_model_response


class ForecastMockPredictor:
    def __init__(self,settings,*,transport=None):
        self.url = settings.mock_predictor_url
        self.client = httpx.AsyncClient(transport=transport,timeout=.8,trust_env=False)

    async def close(self):
        await self.client.aclose()

    async def predict(self,payload,directory):
        validate_graph(payload['graph_sample'])
        if (not payload['quality']['observation_complete'] or not payload['quality']['model_ready']
                or payload['graph_sample']['stats']['window_swap_count'] < 1
                or payload['model_version'] != 'forecast-wallet-graph-mock-v1'):
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
        response = fixed_mock_response(payload)
        outcome = read_model_response(payload,response,origin='simulated')
        return outcome, {'input_sha256':digest,'input_path':str(path),'delivery':delivery,'target':self.url,
            'result_origin':'simulated','preprocessing':payload['preprocessing'],'response':response}
