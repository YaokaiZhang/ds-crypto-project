"""Versioned HTTP DTOs. Native integer amounts serialize as decimal strings."""
from typing import Annotated, Literal, Any
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, AfterValidator, model_validator
from ..domain import AnalysisCommand, AnalysisFamily, TaskId

Address = Annotated[str, Field(pattern=r'^0x[0-9a-fA-F]{40}$'), AfterValidator(str.lower)]

class ApiModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class AnalysisRequest(ApiModel):
    target: Address
    family: AnalysisFamily
    chain_id: Literal[1] = 1
    tasks: list[TaskId] = Field(default_factory=list, max_length=2)
    cutoff: AwareDatetime | None = None
    pools: list[Address] = Field(default_factory=list, max_length=16)

    @model_validator(mode='after')
    def validate_scope(self) -> 'AnalysisRequest':
        allowed = ('phishing', 'ponzi') if self.family == 'eth_scam' else ('honeypot', 'rug_pull')
        if not self.tasks:
            self.tasks = list(allowed)
        if len(set(self.tasks)) != len(self.tasks) or any(task not in allowed for task in self.tasks):
            raise ValueError('Tasks must be unique and belong to the selected family')
        if self.family == 'eth_scam' and self.pools:
            raise ValueError('Pool scope is only supported for token_scam')
        if len(set(self.pools)) != len(self.pools):
            raise ValueError('Pool addresses must be unique')
        return self

    def to_command(self) -> AnalysisCommand:
        return AnalysisCommand(self.target, self.family, tuple(self.tasks), self.cutoff, tuple(self.pools), self.chain_id)

class TaskResult(ApiModel):
    task_id: TaskId
    status: str
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None
    sample_id: str | None = None
    model_version: str | None = None
    risk_band: Literal['low', 'medium', 'high'] | None = None
    risk_band_policy_version: str | None = None

    @model_validator(mode='after')
    def validate_score_provenance(self) -> 'TaskResult':
        if self.score is not None and (self.status != 'ok' or not self.sample_id or not self.model_version):
            raise ValueError('Scores require an ok status, input sample and model version')
        if self.risk_band is not None and (self.score is None or not self.risk_band_policy_version):
            raise ValueError('Risk bands require a score and an admitted band policy version')
        return self

class AnalysisResult(ApiModel):
    analysis_id: str
    status: str
    target: str
    tasks: list[TaskResult]

class GraphView(ApiModel):
    sample_id: str
    task_id: TaskId
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]

class ActivitySeries(ApiModel):
    scope: dict[str, Any]
    points: list[dict[str, Any]]

class TransactionPage(ApiModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None

class FeedTransaction(ApiModel):
    hash: str
    from_address: str
    to_address: str | None
    block_number: int
    block_time: AwareDatetime
    value_wei: str
    gas_limit: str
    gas_used: str | None = None
    status: str | None = None

class FeedSnapshot(ApiModel):
    status: str
    transactions: list[FeedTransaction]
    updated_at: AwareDatetime | None = None
