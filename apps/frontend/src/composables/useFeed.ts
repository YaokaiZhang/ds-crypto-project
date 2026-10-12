import { onUnmounted, ref, shallowRef } from 'vue';
import { feedApi } from '@/api/feed';
import type { FeedSnapshot } from '@/api/contracts';

export function useFeed() {
  const snapshot = shallowRef<FeedSnapshot | null>(null);
  const connected = ref(false);
  const error = shallowRef<unknown>(null);
  let stream: EventSource | undefined;
  let controller: AbortController | undefined;

  function disconnect() { stream?.close(); stream = undefined; connected.value = false; }
  async function refresh() {
    controller?.abort();
    const current = new AbortController(); controller = current;
    try {
      const value = await feedApi.recent(current.signal);
      if (!current.signal.aborted) { snapshot.value = value; error.value = null; }
    } catch (cause) { if (!current.signal.aborted) error.value = cause; }
  }
  function connect() {
    disconnect();
    const current = feedApi.events(); stream = current;
    current.onopen = () => { if (stream === current) connected.value = true; };
    current.onerror = event => { if (stream === current) { connected.value = false; error.value = event; } };
    // Attach typed transaction/snapshot handlers after implementing the SSE contract.
  }
  onUnmounted(() => { controller?.abort(); disconnect(); });
  return { snapshot, connected, error, refresh, connect, disconnect };
}
