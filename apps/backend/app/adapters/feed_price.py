"""Public ETH/USD reference quote; independent of RPC and receipt collection."""
from decimal import Decimal, InvalidOperation
import re
import httpx
from .feed_store import utc


class EthUsdPrice:
    def __init__(self, transport=None):
        self.client = httpx.AsyncClient(timeout=5, transport=transport)

    async def fetch(self):
        response = await self.client.get('https://api.coinbase.com/v2/prices/ETH-USD/spot')
        response.raise_for_status()
        data = response.json()['data']
        if data.get('base') != 'ETH' or data.get('currency') != 'USD':
            raise ValueError('Unexpected quote currency')
        raw = data['amount']
        if not isinstance(raw, str) or len(raw) > 40 or not re.fullmatch(r'\d+(\.\d+)?', raw):
            raise ValueError('Invalid reference price')
        try:
            price = Decimal(raw)
            if not price.is_finite() or price <= 0:
                raise ValueError('Invalid reference price')
        except InvalidOperation:
            raise ValueError('Invalid reference price') from None
        return {'price': format(price, 'f'), 'fetched_at': utc(), 'source': 'Coinbase spot'}

    async def close(self):
        await self.client.aclose()
