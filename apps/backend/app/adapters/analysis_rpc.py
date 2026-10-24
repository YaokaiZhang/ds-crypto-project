"""Cutoff-bound address classification; independent from the feed lifecycle.

No application rate/quota limiter is applied to RPC. Concurrency/timeouts and
provider errors still apply; an empty code result is not proof of activity.
"""
import re

import httpx

from ..domain import EntityResolution
from ..errors import ServiceError
from ..settings import Settings

ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
BYTECODE = re.compile(r'^0x(?:[0-9a-fA-F]{2})*$')


class AnalysisRpc:
    def __init__(self, settings: Settings, *, transport=None):
        self.url = settings.ethereum_rpc_url
        self.client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(15, connect=5))
        self.sequence = 0

    async def close(self):
        await self.client.aclose()

    async def call(self, method: str, params: list):
        if not self.url:
            raise ServiceError('provider_authentication')
        self.sequence += 1
        identity = self.sequence
        try:
            response = await self.client.post(self.url, json={
                'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params})
            if response.status_code in (401, 403):
                raise ServiceError('provider_authentication')
            if response.status_code == 429:
                raise ServiceError('provider_rate_limited')
            if response.status_code != 200:
                raise ServiceError('provider_unavailable')
            payload = response.json()
        except httpx.HTTPError:
            raise ServiceError('provider_unavailable') from None
        except ValueError:
            raise ServiceError('provider_response_invalid') from None
        if not isinstance(payload, dict) or payload.get('id') != identity:
            raise ServiceError('provider_response_invalid')
        if payload.get('error'):
            message = str(payload['error']).lower()
            if any(x in message for x in ('missing trie', 'historical state', 'state is not available', 'pruned')):
                raise ServiceError('historical_state_unavailable')
            raise ServiceError('provider_response_invalid')
        if 'result' not in payload:
            raise ServiceError('provider_response_invalid')
        return payload['result']

    async def classify_address(self, address: str, cutoff_block: int) -> EntityResolution:
        if not ADDRESS.fullmatch(address):
            raise ServiceError('invalid_address')
        if isinstance(cutoff_block, bool) or not isinstance(cutoff_block, int) or cutoff_block < 0:
            raise ServiceError('invalid_request')
        if await self.call('eth_chainId', []) != '0x1':
            raise ServiceError('provider_response_invalid')
        address = address.lower()
        code = await self.call('eth_getCode', [address, hex(cutoff_block)])
        if not isinstance(code, str) or not BYTECODE.fullmatch(code):
            raise ServiceError('provider_response_invalid')
        if code == '0x':
            kind = 'eoa'
        elif len(code) == 48 and code.lower().startswith('0xef0100'):
            # Resolve these explicitly later; do not silently treat a delegated
            # account as an ordinary contract eligible for the Ponzi model.
            kind = 'delegated'
        else:
            kind = 'contract'
        return EntityResolution(address=address, entity_type=kind)
