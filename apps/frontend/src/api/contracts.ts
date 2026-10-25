// Starter DTOs mirror apps/backend/app/api/schemas.py.
// Replace with generated OpenAPI types when the contract is extended.
export type AnalysisFamily = 'eth_scam' | 'token_scam' | 'forecast';
export type TaskId = 'phishing' | 'ponzi' | 'honeypot' | 'rug_pull' | 'continued_activity';
export interface AnalysisRequest {
  target: string;
  family: AnalysisFamily;
  chain_id?: 1;
  tasks?: TaskId[];
  cutoff?: string | null;
  pools?: string[];
}
export interface TaskResult {
  task_id: TaskId;
  status: string;
  score: number | null;
  reason: string | null;
  reason_code?: string | null;
  sample_id: string | null;
  model_version: string | null;
  risk_band: 'low' | 'medium' | 'high' | null;
  label?: 'Low Risk' | 'Medium Risk' | 'High Risk' | 'Continued activity' | 'Low volume' | null;
  risk_band_policy_version: string | null;
  decision: string | null;
  calibration: string | null;
  explanation: string | null;
  forecast: { observation_days: 7; horizon_days: 90; swap_volume_threshold_usd: '1000'; score_target: 'continued_activity'; outcome: 'continued_activity' | 'low_volume_dead'; decision_policy_version: string } | null;
  result_origin?: string | null;
}
export interface AnalysisResult {
  analysis_id: string;
  status: string;
  target: string;
  tasks: TaskResult[];
  family: AnalysisFamily | null;
  result_origin: string;
  snapshot_id: string | null;
  stage: string;
  message: string | null;
  progress?: AnalysisProgress | null;
  created_at: string | null;
  updated_at: string | null;
  cutoff: string | null;
  cutoff_block: number | null;
  cutoff_block_hash: string | null;
  window_start: string | null;
  basic_information: BasicInformation | null;
  graphs: Partial<Record<TaskId, GraphView>>;
  activity: ActivitySeries | null;
  transactions: TransactionPage | null;
}
export interface AnalysisProgress {
  state: 'queued' | 'running' | 'retrying' | 'waiting_quota' | 'completed' | 'partial' | 'failed';
  unit: 'requests' | 'pages' | 'records' | 'tasks';
  completed: number;
  total: number | null;
  total_final: boolean;
  records_collected: number;
  retry_at: string | null;
  task_id: TaskId | null;
}
export interface GraphView {
  sample_id: string;
  task_id: TaskId;
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  context?: { sample_id: string; task_id: TaskId; model_nodes: number | null; model_edges: number | null; window: string; cutoff: string; version: string; sampling: string; model_sample_id?: string | null; view_scope?: string | null } | null;
}
export interface InformationField { key: string; label: string; value: string; hint: string }
export interface SelectedPool { address: string; token0: string; token1: string; protocol: string; paired_asset: string }
export interface BasicInformation {
  entity_type: string; name: string; symbol: string | null; decimals: number | null;
  balance_wei: string | null; total_supply_raw: string | null; state_time: string; state_block: number;
  source_verification: string | null; compiler: string | null; deployment_transaction: string | null; deployer: string | null;
  pools: SelectedPool[]; fields: InformationField[];
}
export interface ActivityPoint {
  date: string; covered: boolean; inflow_wei: string | null; outflow_wei: string | null;
  external_count: number | null; transfer_count: number | null; swap_count: number | null; mint_count: number | null; burn_count: number | null;
}
export interface ActivitySeries { scope: Record<string, unknown>; points: ActivityPoint[] }
export type LedgerCategory = 'external' | 'internal' | 'token_transfer' | 'pool_event';
export interface AssetAmount { asset: string; raw: string; decimals: number; contract_address?: string | null; direction?: 'incoming' | 'outgoing' | 'self' | null }
export interface LedgerRow {
  id: string; category: LedgerCategory; hash: string; block_number: number; block_time: string;
  from_address: string | null; to_address: string | null; direction: string | null;
  value_raw: string | null; decimals: number | null; asset: string | null;
  status: 'success' | 'failed' | 'unknown'; method: string | null; trace_id: string | null;
  log_index: number | null; pool: string | null; event: string | null; amounts: AssetAmount[];
  gas_used: string | null; gas_price_wei: string | null;
  transaction_index: number | null; emitter: string | null; event_data: Record<string, string> | null;
}
export interface TransactionPage { items: LedgerRow[]; next_cursor: string | null; category: LedgerCategory; total: number; revision?: number }
export interface Capabilities {
  mode: string; analysis_enabled: boolean; feed_enabled: boolean; events_enabled?: boolean;
  supported_families?: AnalysisFamily[];
  score_mode?: string;
  profiles?: { family: AnalysisFamily; target: string; name: string; pools: string[] }[];
  tasks: { task_id: TaskId; entity: string; model_available: boolean; assessment_available?: boolean }[];
}
export interface FeedTransaction {
  hash: string; block_hash: string; transaction_index: number;
  from_address: string; to_address: string | null;
  block_number: number; block_time: string; value_wei: string; gas_limit: string;
  gas_used: string | null; effective_gas_price_wei: string | null; execution_fee_wei: string | null;
  status: 'success' | 'failed' | null;
}
export interface FeedUsdQuote { price: string; fetched_at: string; source: string }
export interface FeedMeta {
  status: 'connecting' | 'live' | 'degraded' | 'stale' | 'recovering';
  updated_at: string | null; checked_at: string | null; head_block: number | null;
  head_time: string | null; sequence: number; message: string | null;
  last_gap_at: string | null; source: string; usd_quote: FeedUsdQuote | null;
}
export interface FeedSnapshot extends FeedMeta { transactions: FeedTransaction[] }
