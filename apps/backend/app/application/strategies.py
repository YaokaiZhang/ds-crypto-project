"""Task strategies share mechanics, not model state or positive meanings."""
from dataclasses import dataclass
from packages.tasks import TASK_REGISTRY
from ..domain import EntityResolution, TaskId

@dataclass(frozen=True)
class TaskStrategy:
    task_id: TaskId
    entity: str
    graph_family: str
    stage: str

    def check_applicability(self, entity: EntityResolution) -> tuple[bool, str | None]:
        """Check resolved roles and admitted bundle scope, not just bytecode presence."""
        if entity.entity_type in ('unresolved', 'delegated'):
            return False, 'Address type could not be established for this model scope.'
        if self.task_id == 'phishing':
            return entity.entity_type in ('eoa', 'contract', 'token'), None
        if self.task_id == 'ponzi':
            if entity.entity_type == 'eoa':
                return False, 'Ponzi assesses smart contracts; this address is an ordinary wallet.'
            return entity.entity_type in ('contract', 'token'), None
        if entity.entity_type != 'token':
            return False, 'This task requires a verified ERC-20 token.'
        if not entity.pools:
            return False, 'No supported Ethereum Uniswap v2 pool was found for this token.'
        return True, None

TASK_STRATEGIES = {
    task_id: TaskStrategy(task_id, spec.entity, spec.graph_family, spec.stage)
    for task_id, spec in TASK_REGISTRY.items()
}

# Forecast has its own first-week resolver and remote predictor; no trainer is loaded.
TASK_STRATEGIES['continued_activity'] = TaskStrategy('continued_activity', 'token', 'wallet_pool_token', 'forecast')
