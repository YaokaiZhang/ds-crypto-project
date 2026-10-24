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
        allowed = {'eth_scam': ('phishing', 'ponzi'), 'token_scam': ('honeypot', 'rug_pull'),
                   'forecast': ('continued_activity',)}[self.family]
        if not self.tasks:
            self.tasks = list(allowed)
        if len(set(self.tasks)) != len(self.tasks) or any(task not in allowed for task in self.tasks):
            raise ValueError('Tasks must be unique and belong to the selected family')
        if self.family == 'eth_scam' and self.pools:
            raise ValueError('Pool scope is only supported for token analyses')
        if len(set(self.pools)) != len(self.pools):
            raise ValueError('Pool addresses must be unique')
        return self

    def to_command(self) -> AnalysisCommand:
        return AnalysisCommand(self.target, self.family, tuple(self.tasks), self.cutoff, tuple(self.pools), self.chain_id)

class ForecastDefinition(ApiModel):
    observation_days: Literal[7] = 7
    horizon_days: Literal[90] = 90
    swap_volume_threshold_usd: Literal['1000'] = '1000'
    score_target: Literal['continued_activity'] = 'continued_activity'
    outcome: Literal['continued_activity', 'low_volume_dead']
    decision_policy_version: str

class TaskResult(ApiModel):
    task_id: TaskId
    status: str
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None
    reason_code: str | None = None
    sample_id: str | None = None
    model_version: str | None = None
    risk_band: Literal['low', 'medium', 'high'] | None = None
    risk_band_policy_version: str | None = None
    decision: str | None = None
    calibration: str | None = None
    explanation: str | None = None
    forecast: ForecastDefinition | None = None
    result_origin: str | None = None

    @model_validator(mode='after')
    def validate_score_provenance(self) -> 'TaskResult':
        if self.score is not None and (self.status != 'ok' or not self.sample_id or not self.model_version):
            raise ValueError('Scores require an ok status, input sample and model version')
        if self.risk_band is not None and (self.score is None or not self.risk_band_policy_version):
            raise ValueError('Risk bands require a score and an admitted band policy version')
        if self.task_id == 'continued_activity':
            if self.risk_band is not None or self.risk_band_policy_version is not None:
                raise ValueError('Activity forecasts cannot carry scam risk bands')
            if self.score is not None and (self.forecast is None or self.decision != self.forecast.outcome):
                raise ValueError('Forecast scores require matching outcome semantics')
        elif self.forecast is not None:
            raise ValueError('Forecast semantics belong only to continued_activity')
        return self

class AnalysisProgress(ApiModel):
    """Actual work counters within a stage, never a fabricated overall percent."""
    state: Literal['queued', 'running', 'retrying', 'waiting_quota', 'completed', 'partial', 'failed'] = 'running'
    unit: Literal['requests', 'pages', 'records', 'tasks'] = 'requests'
    completed: int = Field(default=0, ge=0)
    total: int | None = Field(default=None, ge=0)
    total_final: bool = False
    records_collected: int = Field(default=0, ge=0)
    retry_at: AwareDatetime | None = None
    task_id: TaskId | None = None

    @model_validator(mode='after')
    def validate_work(self) -> 'AnalysisProgress':
        if self.total is not None and self.completed > self.total:
            raise ValueError('Completed work exceeds the discovered work count')
        if self.total_final and self.total is None:
            raise ValueError('A final work denominator is required')
        if self.state == 'waiting_quota' and self.retry_at is None:
            raise ValueError('Quota pauses require an explicit resume time')
        return self


class AnalysisResult(ApiModel):
    analysis_id: str
    status: str
    target: str
    tasks: list[TaskResult]
    family: AnalysisFamily | None = None
    result_origin: str = 'unavailable'
    snapshot_id: str | None = None
    stage: str = 'queued'
    message: str | None = None
    progress: AnalysisProgress | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    cutoff: AwareDatetime | None = None
    cutoff_block: int | None = None
    cutoff_block_hash: str | None = None
    window_start: AwareDatetime | None = None
    basic_information: 'BasicInformation | None' = None
    graphs: dict[TaskId, 'GraphView'] = Field(default_factory=dict)
    activity: 'ActivitySeries | None' = None
    transactions: 'TransactionPage | None' = None

class InformationField(ApiModel):
    key: str
    label: str
    value: str
    hint: str

class SelectedPool(ApiModel):
    address: Address
    token0: Address
    token1: Address
    protocol: str
    paired_asset: str

class BasicInformation(ApiModel):
    entity_type: str
    name: str
    symbol: str | None = None
    decimals: int | None = None
    balance_wei: str | None = None
    total_supply_raw: str | None = None
    state_time: AwareDatetime
    state_block: int
    source_verification: str | None
    compiler: str | None
    deployment_transaction: str | None
    deployer: Address | None
    pools: list[SelectedPool] = Field(default_factory=list)
    fields: list[InformationField]

class GraphContext(ApiModel):
    sample_id: str
    task_id: TaskId
    model_nodes: int | None
    model_edges: int | None
    window: str
    cutoff: AwareDatetime
    version: str
    sampling: str
    view_scope: str | None = None
    model_sample_id: str | None = None

class GraphView(ApiModel):
    sample_id: str
    task_id: TaskId
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    context: GraphContext | None = None

class ActivityPoint(ApiModel):
    date: str
    covered: bool
    inflow_wei: str | None = None
    outflow_wei: str | None = None
    external_count: int | None = None
    transfer_count: int | None = None
    swap_count: int | None = None
    mint_count: int | None = None
    burn_count: int | None = None

class ActivitySeries(ApiModel):
    scope: dict[str, Any]
    points: list[ActivityPoint]

class AssetAmount(ApiModel):
    asset: str
    raw: str
    decimals: int
    contract_address: Address | None = None
    direction: Literal['incoming', 'outgoing', 'self'] | None = None

class LedgerRow(ApiModel):
    id: str
    category: Literal['external', 'internal', 'token_transfer', 'pool_event']
    hash: str
    block_number: int
    block_time: AwareDatetime
    from_address: Address | None = None
    to_address: Address | None = None
    direction: str | None = None
    value_raw: str | None = None
    decimals: int | None = None
    asset: str | None = None
    status: Literal['success', 'failed', 'unknown']
    method: str | None = None
    trace_id: str | None = None
    log_index: int | None = None
    pool: Address | None = None
    event: str | None = None
    amounts: list[AssetAmount] = Field(default_factory=list)
    gas_used: str | None = None
    gas_price_wei: str | None = None
    transaction_index: int | None = None
    emitter: Address | None = None
    event_data: dict[str, str] | None = None

class TransactionPage(ApiModel):
    items: list[LedgerRow]
    next_cursor: str | None = None
    category: str | None = None
    total: int = 0
    revision: int = Field(default=0, ge=0)

AnalysisResult.model_rebuild()

class FeedTransaction(ApiModel):
    hash: str
    block_hash: str
    transaction_index: int
    from_address: str
    to_address: str | None
    block_number: int
    block_time: AwareDatetime
    value_wei: str
    gas_limit: str
    gas_used: str | None = None
    effective_gas_price_wei: str | None = None
    execution_fee_wei: str | None = None
    status: Literal['success', 'failed'] | None = None

class FeedUsdQuote(ApiModel):
    price: str = Field(pattern=r'^\d+(\.\d+)?$', max_length=40)
    fetched_at: AwareDatetime
    source: str

class FeedSnapshot(ApiModel):
    status: str
    transactions: list[FeedTransaction]
    updated_at: AwareDatetime | None = None
    checked_at: AwareDatetime | None = None
    head_block: int | None = None
    head_time: AwareDatetime | None = None
    sequence: int = 0
    message: str | None = None
    last_gap_at: AwareDatetime | None = None
    source: str = 'Ethereum Mainnet RPC'
    usd_quote: FeedUsdQuote | None = None
