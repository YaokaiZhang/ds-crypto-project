import { onUnmounted, shallowRef, ref } from 'vue';
import { analysisApi } from '@/api/analysis';
import type { AnalysisRequest, AnalysisResult } from '@/api/contracts';

export function useAnalysis() {
  const result = shallowRef<AnalysisResult | null>(null);
  const pending = ref(false);
  const error = shallowRef<unknown>(null);
  let controller: AbortController | undefined;

  async function load(operation: (signal: AbortSignal) => Promise<AnalysisResult>) {
    controller?.abort();
    const current = new AbortController();
    controller = current;
    result.value = null; error.value = null; pending.value = true;
    try {
      const response = await operation(current.signal);
      if (!current.signal.aborted) result.value = response;
    } catch (cause) {
      if (!current.signal.aborted) error.value = cause;
    } finally {
      if (controller === current) pending.value = false;
    }
  }
  onUnmounted(() => controller?.abort());
  return {
    result, pending, error,
    create: (request: AnalysisRequest) => load(signal => analysisApi.create(request, signal)),
    refresh: (id: string) => load(signal => analysisApi.get(id, signal)),
  };
}
