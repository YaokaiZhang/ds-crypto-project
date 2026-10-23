import { onMounted, onUnmounted, ref, shallowRef } from 'vue';
import { feedApi } from '@/api/feed';
import { ApiError } from '@/api/client';
import type { FeedSnapshot } from '@/api/contracts';
import { appendFeedTransaction, readFeedMeta, readFeedSnapshot } from '@/presenters/feed';

export function useFeed() {
  const snapshot = shallowRef<FeedSnapshot | null>(null);
  const connected = ref(false); const paused = ref(false); const pending = ref(false);
  const error = shallowRef<unknown>(null);
  let stream: EventSource | undefined; let controller: AbortController | undefined;
  let watchdog: ReturnType<typeof setInterval> | undefined;
  let lastReceived = 0; let disabled = false; let disposed = false;

  function disconnect() { stream?.close(); stream = undefined; connected.value = false; }
  function connect() {
    disconnect();
    if (paused.value || disposed || document.hidden) return;
    const current = feedApi.events(); stream = current; lastReceived = Date.now();
    const handle = (kind: string) => (event: MessageEvent) => {
      if (stream !== current) return;
      try {
        const value: unknown = JSON.parse(event.data);
        if (kind === 'snapshot') snapshot.value = readFeedSnapshot(value);
        else if (kind === 'transaction' && snapshot.value) snapshot.value = appendFeedTransaction(snapshot.value, value);
        else if (kind === 'status' && snapshot.value) {
          const meta = readFeedMeta(value);
          // Status can race a publication; only transaction/reset events advance the cursor.
          if (meta.sequence >= snapshot.value.sequence) snapshot.value = { ...snapshot.value, ...meta, sequence: snapshot.value.sequence };
        }
        lastReceived = Date.now(); error.value = null; connected.value = true;
      } catch (cause) { error.value = cause; disconnect(); }
    };
    current.addEventListener('snapshot', handle('snapshot'));
    current.addEventListener('transaction', handle('transaction'));
    current.addEventListener('status', handle('status'));
    current.onerror = event => { if (stream === current) { connected.value = false; error.value = event; } };
  }
  async function refresh() {
    controller?.abort(); disconnect(); disabled = false;
    const current = new AbortController(); controller = current; pending.value = true;
    const timeout = setTimeout(() => {
      current.abort();
      if (controller === current) error.value = new Error('Feed request timed out');
    }, 10000);
    try {
      const value = readFeedSnapshot(await feedApi.recent(current.signal));
      if (current.signal.aborted || disposed) return;
      snapshot.value = value; error.value = null; lastReceived = Date.now(); connect();
    } catch (cause) {
      if (!current.signal.aborted) {
        error.value = cause;
        disabled = cause instanceof ApiError && cause.status === 501;
      }
    } finally { clearTimeout(timeout); if (controller === current) pending.value = false; }
  }
  function togglePause() {
    paused.value = !paused.value;
    if (paused.value) { controller?.abort(); pending.value = false; disconnect(); }
    else void refresh();
  }
  function visibility() {
    if (document.hidden) { controller?.abort(); pending.value = false; disconnect(); }
    else if (!paused.value) void refresh();
  }
  onMounted(() => {
    void refresh();
    document.addEventListener('visibilitychange', visibility);
    watchdog = setInterval(() => {
      if (!paused.value && !document.hidden && !pending.value && !disabled && (!connected.value || Date.now() - lastReceived > 16000)) void refresh();
    }, 10000);
  });
  onUnmounted(() => {
    disposed = true; controller?.abort(); disconnect(); clearInterval(watchdog);
    document.removeEventListener('visibilitychange', visibility);
  });
  return { snapshot, connected, paused, pending, error, refresh, togglePause };
}
