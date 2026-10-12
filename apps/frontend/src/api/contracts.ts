// Starter DTOs mirror apps/backend/app/api/schemas.py.
// Replace with generated OpenAPI types when the contract is extended.
export type AnalysisFamily = 'eth_scam' | 'token_scam';
export type TaskId = 'phishing' | 'ponzi' | 'honeypot' | 'rug_pull';
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
  sample_id: string | null;
  model_version: string | null;
  risk_band: 'low' | 'medium' | 'high' | null;
  risk_band_policy_version: string | null;
}
export interface AnalysisResult {
  analysis_id: string;
  status: string;
  target: string;
  tasks: TaskResult[];
}
export interface GraphView {
  sample_id: string;
  task_id: TaskId;
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
}
export interface FeedTransaction {
  hash: string;
  from_address: string;
  to_address: string | null;
  block_number: number;
  block_time: string;
  value_wei: string;
  gas_limit: string;
  gas_used: string | null;
  status: string | null;
}
export interface FeedSnapshot {
  status: string;
  transactions: FeedTransaction[];
  updated_at: string | null;
}
