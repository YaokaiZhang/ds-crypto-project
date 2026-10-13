"""Task strategies share mechanics, not model state or positive meanings."""
from dataclasses import dataclass
from chainrisk.tasks import TASK_REGISTRY
from ..domain import EntityResolution, TaskId
from ..errors import FeatureNotImplemented

@dataclass(frozen=True)
class TaskStrategy:
    task_id: TaskId
    entity: str
    graph_family: str
    stage: str

    def check_applicability(self, entity: EntityResolution) -> tuple[bool, str | None]:
        """Check resolved roles and admitted bundle scope, not just bytecode presence."""
        raise FeatureNotImplemented('tasks.check_applicability')

TASK_STRATEGIES = {
    task_id: TaskStrategy(task_id, spec.entity, spec.graph_family, spec.stage)
    for task_id, spec in TASK_REGISTRY.items()
}

# Task A metadata only: no research model or provider is loaded.
TASK_STRATEGIES['continued_activity'] = TaskStrategy('continued_activity', 'token', 'wallet_pool_token', 'unavailable')
