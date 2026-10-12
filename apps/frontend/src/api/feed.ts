import { apiClient } from './client';
import type { FeedSnapshot } from './contracts';

export const feedApi = {
  recent(signal?: AbortSignal) { return apiClient.request<FeedSnapshot>('/feed/recent', { signal }); },
  events() { return new EventSource(apiClient.streamUrl('/feed/events')); },
};
