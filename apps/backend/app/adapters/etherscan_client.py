"""Backend Etherscan transport with shared accounting and safe failure types."""
import asyncio
from typing import Any

import httpx

from ..errors import ServiceError
from ..settings import Settings
from .etherscan_budget import EtherscanBudget


class BackendEtherscan:
    def __init__(self, settings: Settings, budget: EtherscanBudget, *, transport=None,
                 sleep=asyncio.sleep, retries: int = 3):
        if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 5:
            raise ValueError('Provider retries must be between zero and five')
        self.key = settings.etherscan_api_key
        self.budget, self.sleep, self.retries = budget, sleep, retries
        self.client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(30, connect=5))

    async def close(self):
        await self.client.aclose()

    @staticmethod
    def result(payload: Any, action: str) -> Any:
        if not isinstance(payload, dict):
            raise ServiceError('provider_response_invalid')
        result = payload.get('result')
        if payload.get('error') or str(payload.get('status')) == '0':
            message = (str(payload.get('message', '')) + ' ' + str(result)).lower()
            # Only an explicit, successful empty-history shape means no activity.
            empty = ('no transactions found', 'no records found', 'no logs found')
            if action in {'txlist', 'txlistinternal', 'tokentx', 'getLogs'} and any(x in message for x in empty):
                if result == [] or isinstance(result, str) and result.lower() in ('', *empty):
                    return []
            if any(x in message for x in ('invalid api key', 'missing api key', 'invalid apikey',
                                           'not supported for this chain', 'upgrade your', 'paid plan')):
                raise ServiceError('provider_authentication')
            if any(x in message for x in ('rate limit', 'max rate', 'too many requests', 'daily limit')):
                raise ServiceError('provider_rate_limited')
            raise ServiceError('provider_response_invalid')
        if 'result' not in payload:
            raise ServiceError('provider_response_invalid')
        if action in {'txlist', 'txlistinternal', 'tokentx', 'getLogs'}:
            if str(payload.get('status')) != '1' or not isinstance(result, list) or any(not isinstance(r, dict) for r in result):
                raise ServiceError('provider_response_invalid')
        return result

    async def request(self, module: str, action: str, **params) -> Any:
        if not self.key:
            raise ServiceError('provider_authentication')
        if {'apikey', 'chainid', 'module', 'action'} & params.keys():
            raise ValueError('Provider identity and credentials are server-owned')
        # Callers use frozen block bounds. Caching is owned by the collection
        # layer, and only cache misses reach this attempt-counting transport.
        for attempt in range(self.retries + 1):
            await self.budget.acquire()
            try:
                response = await self.client.get('https://api.etherscan.io/v2/api', params={
                    'chainid': 1, 'module': module, 'action': action, **params, 'apikey': self.key})
                if response.status_code in (401, 403):
                    raise ServiceError('provider_authentication')
                if response.status_code == 429:
                    raise ServiceError('provider_rate_limited')
                if response.status_code >= 500:
                    raise ServiceError('provider_unavailable')
                if response.status_code != 200:
                    raise ServiceError('provider_response_invalid')
                try:
                    payload = response.json()
                except ValueError:
                    raise ServiceError('provider_response_invalid') from None
                return self.result(payload, action)
            except httpx.HTTPError:
                error = ServiceError('provider_unavailable')
            except ServiceError as failure:
                error = failure
            if error.code not in {'provider_unavailable', 'provider_rate_limited'} or attempt == self.retries:
                raise error from None
            await self.sleep(min(8, 0.5 * 2 ** attempt))
        raise ServiceError('provider_unavailable')
