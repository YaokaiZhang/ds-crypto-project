"""Replace with durable PostgreSQL/artifact adapters before accepting jobs."""
from typing import Any
from ..domain import AnalysisCommand, AnalysisRecord
from ..errors import FeatureNotImplemented
from ..settings import Settings

class PostgresAnalysisRepository:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def create(self, command: AnalysisCommand, idempotency_key: str | None) -> AnalysisRecord:
        raise FeatureNotImplemented('repository.create')

    async def get(self, analysis_id: str) -> AnalysisRecord:
        raise FeatureNotImplemented('repository.get')

    async def claim(self, worker_id: str) -> AnalysisRecord | None:
        """Atomically lease a job; implement crash-safe reclaim and heartbeat."""
        raise FeatureNotImplemented('repository.claim')

    async def save(self, record: AnalysisRecord) -> None:
        raise FeatureNotImplemented('repository.save')

    async def artifact(self, analysis_id: str, kind: str, **filters: Any) -> dict[str, Any]:
        raise FeatureNotImplemented(f'repository.{kind}')

class PostgresFeedRepository:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def recent(self, limit: int) -> dict[str, Any]:
        raise FeatureNotImplemented('feed.recent')

    async def save_cursor(self, number: int, block_hash: str) -> None:
        raise FeatureNotImplemented('feed.save_cursor')

    async def publish(self, transaction: dict[str, Any]) -> None:
        raise FeatureNotImplemented('feed.publish')
