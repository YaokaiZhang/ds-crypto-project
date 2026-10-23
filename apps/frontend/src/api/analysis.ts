import { apiClient } from './client';
import type { AnalysisRequest, AnalysisResult, GraphView, TaskId, Capabilities, ActivitySeries, TransactionPage, LedgerCategory } from './contracts';

export const analysisApi = {
  create(request: AnalysisRequest, signal?: AbortSignal, idempotencyKey?: string) {
    return apiClient.request<AnalysisResult>('/analyses', { method: 'POST', body: JSON.stringify(request), signal, headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined });
  },
  get(id: string, signal?: AbortSignal) {
    return apiClient.request<AnalysisResult>(`/analyses/${encodeURIComponent(id)}`, { signal });
  },
  graph(id: string, task: TaskId, signal?: AbortSignal) {
    return apiClient.request<GraphView>(`/analyses/${encodeURIComponent(id)}/graphs/${task}`, { signal });
  },
  capabilities(signal?: AbortSignal) { return apiClient.request<Capabilities>('/capabilities', { signal }); },
  activity(id: string, signal?: AbortSignal) { return apiClient.request<ActivitySeries>(`/analyses/${encodeURIComponent(id)}/activity`, { signal }); },
  transactions(id: string, category: LedgerCategory, cursor?: string | null, signal?: AbortSignal) {
    const query = new URLSearchParams({ category, limit: '10' });
    if (cursor) query.set('cursor', cursor);
    return apiClient.request<TransactionPage>(`/analyses/${encodeURIComponent(id)}/transactions?${query}`, { signal });
  },
  events(id: string) { return new EventSource(apiClient.streamUrl(`/analyses/${encodeURIComponent(id)}/events`)); },
};
