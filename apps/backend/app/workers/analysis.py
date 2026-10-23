"""Analysis worker entrypoint; fail fast until durable claim/pipeline exists."""
import argparse
import asyncio
import sys
from ..container import Container, build_container
from ..errors import FeatureNotImplemented
from ..settings import Settings

class AnalysisWorker:
    def __init__(self, services: Container, worker_id: str):
        self.services = services
        self.worker_id = worker_id

    async def run_once(self) -> None:
        """Claim one leased job, execute pipeline and atomically persist results."""
        raise FeatureNotImplemented('worker.analysis.run_once')

    async def run_forever(self) -> None:
        """Implement bounded polling, heartbeat, recovery and graceful shutdown."""
        raise FeatureNotImplemented('worker.analysis.run_forever')

async def _run(worker_id: str) -> None:
    services = build_container(Settings.from_environment())
    try:
        await AnalysisWorker(services, worker_id).run_forever()
    finally:
        services.close()

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-id', default='analysis-worker')
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.worker_id))
    except FeatureNotImplemented as error:
        print(error, file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
