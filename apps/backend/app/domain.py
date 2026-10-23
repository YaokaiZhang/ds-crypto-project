"""Framework-independent values. GraphSample remains the chainrisk protocol."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypeAlias

TaskId: TypeAlias = Literal['phishing', 'ponzi', 'honeypot', 'rug_pull', 'continued_activity']
AnalysisFamily: TypeAlias = Literal['eth_scam', 'token_scam', 'forecast']
GraphSample: TypeAlias = dict[str, Any]

@dataclass(frozen=True)
class AnalysisCommand:
    target: str
    family: AnalysisFamily
    tasks: tuple[TaskId, ...]
    cutoff: datetime | None = None
    pools: tuple[str, ...] = ()
    chain_id: int = 1

@dataclass(frozen=True)
class AssessmentContext:
    analysis_id: str
    snapshot_id: str
    target: str
    task_id: TaskId
    cutoff: datetime
    cutoff_block: int
    cutoff_block_hash: str
    graph_recipe: dict[str, Any]
    model_version: str | None
    chain_id: int = 1

@dataclass(frozen=True)
class EntityResolution:
    address: str
    entity_type: Literal['eoa', 'contract', 'token', 'delegated', 'unresolved']
    pools: tuple[str, ...] = ()

@dataclass(frozen=True)
class CollectedHistory:
    events: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]
    source_snapshot: str

@dataclass(frozen=True)
class TaskOutcome:
    task_id: TaskId
    status: str
    score: float | None = None
    reason: str | None = None
    sample_id: str | None = None
    model_version: str | None = None
    risk_band: Literal['low', 'medium', 'high'] | None = None
    risk_band_policy_version: str | None = None

@dataclass(frozen=True)
class AnalysisRecord:
    analysis_id: str
    status: str
    target: str
    tasks: tuple[TaskOutcome, ...] = field(default_factory=tuple)
