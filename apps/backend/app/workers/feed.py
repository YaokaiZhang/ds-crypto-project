"""Single-owned, real Ethereum feed: python -m app.workers.feed."""
import argparse
import asyncio
import logging
import random
import time
from ..adapters.feed_rpc import FeedRpc
from ..adapters.feed_store import FeedStore
from ..adapters.feed_price import EthUsdPrice
from ..application.live_feed import LiveFeedCollector
from ..settings import Settings

log = logging.getLogger(__name__)


class FeedWorker:
    def __init__(self, settings: Settings):
        if not settings.feed_enabled:
            raise RuntimeError('Set FEED_ENABLED=true to start the Ethereum feed')
        self.store = FeedStore(settings.feed_database_path)
        self.rpc = FeedRpc(settings.ethereum_rpc_url)
        self.collector = LiveFeedCollector(self.rpc, self.store)
        self.price = EthUsdPrice()

    async def update_price(self):
        while True:
            try:
                self.store.update(usd_quote=await self.price.fetch())
            except Exception:
                log.warning('ETH/USD reference quote unavailable; retaining only fresh cached quotes')
            await asyncio.sleep(60)

    async def run_once(self):
        if self.store.owner is None:
            self.store.acquire()
        await self.collector.poll_block()
        await self.collector.publish_sample()

    async def run_forever(self):
        next_poll, failures = 0.0, 0
        price_task = None
        try:
            if self.store.owner is None:
                self.store.acquire()
            self.store.apply_positive_filter()
            price_task = asyncio.create_task(self.update_price())
            while True:
                try:
                    if time.monotonic() >= next_poll:
                        await self.collector.poll_block()
                        failures = 0
                        next_poll = time.monotonic() + 4
                    await self.collector.publish_sample()
                except Exception as error:
                    # Never log raw RPC errors/URLs: provider URLs can contain credentials.
                    log.warning('Feed collection interrupted (%s); retrying', type(error).__name__)
                    failures += 1
                    self.collector.discard_candidates()
                    self.store.update(source_status='degraded', message='RPC connection interrupted; retrying automatically')
                    next_poll = time.monotonic() + min(60, 2 ** min(failures, 6)) + random.random()
                await asyncio.sleep(.05)
        finally:
            if price_task:
                price_task.cancel()
                await asyncio.gather(price_task, return_exceptions=True)
            await self.collector.close()
            await self.price.close()
            await self.rpc.close()
            self.store.close()


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        asyncio.run(FeedWorker(Settings.from_environment()).run_forever())
    except KeyboardInterrupt:
        pass
    except RuntimeError as error:
        print(error)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
