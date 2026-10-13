"""Small, read-only Ethereum JSON-RPC adapter. Credentials never leave the server."""
from typing import Any
import httpx


class RpcUnavailable(RuntimeError):
    pass


class FeedRpc:
    def __init__(self, url: str | None, transport=None):
        self.client = httpx.AsyncClient(
            base_url=url or 'https://ethereum-rpc.publicnode.com',
            timeout=httpx.Timeout(8, connect=4), transport=transport,
        )
        self.sequence = 0

    async def call(self, method: str, params: list) -> Any:
        self.sequence += 1
        identity = self.sequence
        try:
            response = await self.client.post('', json={
                'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params,
            })
            response.raise_for_status()
            data = response.json()
            if data.get('id') != identity or data.get('error') or 'result' not in data:
                raise ValueError('Invalid RPC response')
            return data['result']
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as from_error:
            # Provider errors can contain the authenticated endpoint: expose only a safe message.
            raise RpcUnavailable('Ethereum RPC is temporarily unavailable') from from_error

    async def verify_chain(self):
        if await self.call('eth_chainId', []) != '0x1':
            raise RpcUnavailable('Feed requires Ethereum mainnet (chain ID 1)')

    async def block(self, number: int | str, full: bool = True) -> dict:
        block = await self.call('eth_getBlockByNumber', [hex(number) if isinstance(number, int) else number, full])
        if not isinstance(block, dict) or block.get('number') is None or not block.get('hash'):
            raise RpcUnavailable('Requested Ethereum block is not available')
        return block

    async def receipt(self, tx_hash: str) -> dict | None:
        return await self.call('eth_getTransactionReceipt', [tx_hash])

    async def close(self):
        await self.client.aclose()
