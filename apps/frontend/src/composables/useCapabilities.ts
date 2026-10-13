import { shallowRef } from 'vue';
import { analysisApi } from '@/api/analysis';
import type { Capabilities } from '@/api/contracts';
const capabilities = shallowRef<Capabilities | null>(null);
const capabilityError = shallowRef<unknown>(null);
let current: Promise<void> | null = null;
export function useCapabilities() {
  function loadCapabilities() {
    if (!current) current = analysisApi.capabilities().then(value => {
      capabilities.value = value; capabilityError.value = null;
    }).catch(cause => { capabilityError.value = cause; }).finally(() => { current = null; });
    return current;
  }
  return { capabilities, capabilityError, loadCapabilities };
}
