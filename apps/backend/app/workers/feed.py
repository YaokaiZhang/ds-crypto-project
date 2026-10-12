"""Homepage feed entrypoint; no RPC scanning occurs in this template."""
import argparse
import asyncio
import sys
from ..container import Container, build_container
from ..errors import FeatureNotImplemented
from ..settings import Settings

class FeedWorker:
    def __init__(self, services: Container):
        self.services = services

    async def run_once(self) -> None:
        """Acquire single-owner lease, poll block and publish a bounded fresh sample."""
        raise FeatureNotImplemented('worker.feed.run_once')

    async def run_forever(self) -> None:
        """Implement cursor recovery, reorg handling and <=1 sampled row/second."""
        raise FeatureNotImplemented('worker.feed.run_forever')

async def _run() -> None:
    services = build_container(Settings.from_environment())
    try:
        await FeedWorker(services).run_forever()
    finally:
        services.close()

def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    try:
        asyncio.run(_run())
    except FeatureNotImplemented as error:
        print(error, file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
