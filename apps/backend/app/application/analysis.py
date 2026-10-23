from typing import Any
from ..domain import AnalysisCommand, AnalysisRecord, TaskId
from ..errors import FeatureNotImplemented
from ..ports.repositories import AnalysisRepository

class AnalysisService:
    """Browser-facing facade; durable jobs must exist before returning acceptance."""
    def __init__(self, repository: AnalysisRepository):
        self.repository = repository

    async def create(self, command: AnalysisCommand, idempotency_key: str | None = None) -> AnalysisRecord:
        """Validate eligibility, persist idempotent work; never return a fake queued ID."""
        raise FeatureNotImplemented('analysis.create')

    async def get(self, analysis_id: str) -> AnalysisRecord:
        return await self.repository.get(analysis_id)

    async def graph(self, analysis_id: str, task: TaskId) -> dict[str, Any]:
        return await self.repository.artifact(analysis_id, 'graph', task=task)

    async def activity(self, analysis_id: str) -> dict[str, Any]:
        return await self.repository.artifact(analysis_id, 'activity')

    async def transactions(self, analysis_id: str, limit: int, cursor: str | None) -> dict[str, Any]:
        return await self.repository.artifact(analysis_id, 'transactions', limit=limit, cursor=cursor)

    async def events(self, analysis_id: str, last_event_id: str | None) -> Any:
        """Implement durable progress replay/stream only after job events exist."""
        raise FeatureNotImplemented('analysis.events')
