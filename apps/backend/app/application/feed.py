from typing import Any
from ..errors import FeatureNotImplemented
from ..ports.providers import RpcProvider
from ..ports.repositories import FeedRepository

class FeedService:
    def __init__(self, repository: FeedRepository):
        self.repository = repository

    async def recent(self, limit: int) -> dict[str, Any]:
        return await self.repository.recent(limit)

    async def events(self, last_event_id: str | None) -> Any:
        raise FeatureNotImplemented('feed.events')

class FeedCollector:
    """Single-owned block scanner; publish at most one fresh sampled row/second."""
    def __init__(self, rpc: RpcProvider, repository: FeedRepository):
        self.rpc = rpc
        self.repository = repository

    async def poll_block(self) -> None:
        """Resume cursor, verify block continuity, collect new blocks and handle reorg."""
        raise FeatureNotImplemented('feed.poll_block')

    async def publish_sample(self) -> None:
        """Select new transactions without stale backlog; no scam verdicts."""
        raise FeatureNotImplemented('feed.publish_sample')
