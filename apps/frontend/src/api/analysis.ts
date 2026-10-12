import { apiClient } from './client';
import type { AnalysisRequest, AnalysisResult, GraphView, TaskId } from './contracts';

export const analysisApi = {
  create(request: AnalysisRequest, signal?: AbortSignal) {
    return apiClient.request<AnalysisResult>('/analyses', { method: 'POST', body: JSON.stringify(request), signal });
  },
  get(id: string, signal?: AbortSignal) {
    return apiClient.request<AnalysisResult>(`/analyses/${encodeURIComponent(id)}`, { signal });
  },
  graph(id: string, task: TaskId, signal?: AbortSignal) {
    return apiClient.request<GraphView>(`/analyses/${encodeURIComponent(id)}/graphs/${task}`, { signal });
  },
};
