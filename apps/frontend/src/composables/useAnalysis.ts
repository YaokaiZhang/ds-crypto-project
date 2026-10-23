import { onUnmounted, shallowRef, ref } from 'vue';
import { analysisApi } from '@/api/analysis';
import type { AnalysisRequest, AnalysisResult } from '@/api/contracts';

const terminal = (value: AnalysisResult) => ['completed', 'partial', 'failed'].includes(value.status);

export function useAnalysis() {
  const result = shallowRef<AnalysisResult | null>(null);
  const pending = ref(false);
  const error = shallowRef<unknown>(null);
  const streamConnected = ref(false);
  let controller: AbortController | undefined;
  let stream: EventSource | undefined;
  let poll: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;
  let reading = false;

  function stopTracking() {
    stream?.close(); stream = undefined; streamConnected.value = false;
    clearTimeout(poll); poll = undefined;
  }
  function accept(value: AnalysisResult) {
    result.value = value; error.value = null; pending.value = !terminal(value);
    if (terminal(value)) stopTracking();
  }
  function track(id: string, version: number) {
    if (stream || terminal(result.value!)) return;
    const source = analysisApi.events(id); stream = source;
    async function read() {
      if (version !== generation || reading) return;
      reading = true;
      try {
        const value = await analysisApi.get(id, controller?.signal);
        if (version === generation) accept(value);
      } catch (cause) { if (version === generation && !controller?.signal.aborted) error.value = cause; }
      finally {
        reading = false;
        if (version === generation && result.value && !terminal(result.value)) {
          clearTimeout(poll); poll = setTimeout(read, 1200);
        }
      }
    }
    source.onopen = () => { if (version === generation) { streamConnected.value = true; void read(); } };
    source.addEventListener('progress', () => { void read(); });
    source.onerror = () => { if (version === generation) streamConnected.value = false; };
    poll = setTimeout(read, 1200);
  }

  async function load(operation: (signal: AbortSignal) => Promise<AnalysisResult>) {
    const version = ++generation;
    stopTracking(); controller?.abort(); reading = false;
    const current = new AbortController();
    controller = current;
    result.value = null; error.value = null; pending.value = true;
    try {
      const response = await operation(current.signal);
      if (version === generation) { accept(response); if (!terminal(response)) track(response.analysis_id, version); }
    } catch (cause) {
      if (version === generation && !current.signal.aborted) { error.value = cause; pending.value = false; }
    }
  }
  onUnmounted(() => { generation++; controller?.abort(); stopTracking(); });
  return {
    result, pending, error, streamConnected,
    reset: () => { generation++; stopTracking(); controller?.abort(); result.value = null; error.value = null; pending.value = false; reading = false; },
    create: (request: AnalysisRequest) => load(signal => analysisApi.create(request, signal, crypto.randomUUID())),
  };
}
