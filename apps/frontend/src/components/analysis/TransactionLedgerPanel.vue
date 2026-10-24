<script setup lang="ts">
import AppPanel from '@/components/ui/AppPanel.vue';
import AppButton from '@/components/ui/AppButton.vue';
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue';
import { analysisApi } from '@/api/analysis';
import { errorMessage } from '@/api/client';
import { formatUnits, formatUtc, shortenAddress } from '@/presenters/format';
import { ledgerAmounts } from '@/presenters/ledgerAmounts';
import type { AnalysisFamily, LedgerCategory, LedgerRow, TransactionPage } from '@/api/contracts';
const props = defineProps<{ family: AnalysisFamily; analysisId?: string; initialPage?: TransactionPage | null }>();
const selected = ref(0), pageIndex = ref(0), pending = ref(false);
const page = shallowRef<TransactionPage | null>(null), error = shallowRef<unknown>(null), detail = shallowRef<LedgerRow | null>(null);
let controller: AbortController | undefined;
const cursors = ref<(string | null)[]>([null]);
const tabs = computed(() => props.family === 'eth_scam' ? ['External Transactions', 'Internal Transfers'] : ['Token Transfers', 'Pool Events']);
const category = computed<LedgerCategory>(() => props.family === 'eth_scam' ? selected.value === 0 ? 'external' : 'internal' : selected.value === 0 ? 'token_transfer' : 'pool_event');
const columns = computed(() => category.value === 'pool_event' ? ['Time (UTC)', 'Transaction / Log', 'Pool', 'Event', 'Token amounts', 'Block', 'Details'] : ['Time (UTC)', 'Transaction / Event', 'From / To', ...(props.family === 'eth_scam' ? ['Direction'] : []), props.family === 'eth_scam' ? 'Amount' : 'Token amount', ...(props.family === 'eth_scam' ? ['Status', 'Method'] : []), 'Block', 'Details']);
async function load() {
  controller?.abort(); detail.value = null; error.value = null;
  if (!props.analysisId || !props.initialPage) { controller = undefined; page.value = null; pending.value = false; return; }
  const current = new AbortController(); controller = current; pending.value = true;
  try {
    const value = await analysisApi.transactions(props.analysisId, category.value, cursors.value[pageIndex.value], current.signal);
    if (!current.signal.aborted) page.value = value;
  } catch (cause) { if (!current.signal.aborted) error.value = cause; }
  finally { if (controller === current) pending.value = false; }
}
watch([() => props.analysisId, () => JSON.stringify(props.initialPage)], ([id], previousValues) => {
  if (id !== previousValues?.[0]) { selected.value = 0; pageIndex.value = 0; cursors.value = [null]; page.value = null; }
  void load();
}, { immediate: true });
watch(selected, () => { pageIndex.value = 0; cursors.value = [null]; page.value = null; void load(); });
function next() { if (page.value?.next_cursor) { cursors.value[pageIndex.value + 1] = page.value.next_cursor; pageIndex.value++; void load(); } }
function previous() { if (pageIndex.value > 0) { pageIndex.value--; void load(); } }
onUnmounted(() => controller?.abort());
</script>
<template><AppPanel title="Transaction Ledger" class="ledger-panel" :aria-busy="pending"><div class="ledger-tabs" role="group" aria-label="Ledger event type"><button v-for="(tab, index) in tabs" :key="tab" :aria-pressed="selected === index" @click="selected = index">{{ tab }}</button></div><div class="table-container" tabindex="0" aria-label="Scrollable transaction ledger"><table><caption class="sr-only">{{ tabs[selected] }}</caption><thead><tr><th v-for="column in columns" :key="column" scope="col">{{ column }}</th></tr></thead><tbody><tr v-for="row in page?.items || []" :key="row.id"><td>{{ formatUtc(row.block_time) }}</td><td class="mono" :title="row.hash">{{ shortenAddress(row.hash) }}<span class="event-reference">{{ row.trace_id ? `Trace ${row.trace_id}` : row.log_index !== null ? `Log ${row.log_index}` : '' }}</span></td><template v-if="category === 'pool_event'"><td class="mono" :title="row.pool || ''">{{ shortenAddress(row.pool || '') }}</td><td>{{ row.event }}</td><td><span v-for="(quantity, quantityIndex) in row.amounts" :key="quantityIndex" class="asset-quantity">{{ formatUnits(quantity.raw, quantity.decimals) }} {{ quantity.asset }}</span><span v-if="!row.amounts.length">Unknown</span></td></template><template v-else><td class="address-pair"><span :title="row.from_address || ''">{{ shortenAddress(row.from_address || 'Unknown') }}</span><span :title="row.to_address || ''">{{ shortenAddress(row.to_address || 'Contract creation') }}</span></td><td v-if="family === 'eth_scam'">{{ row.direction }}</td><td class="mono amount-cell"><span v-for="(amount, index) in ledgerAmounts(row)" :key="index" class="asset-quantity" :title="amount.title">{{ amount.text }}</span></td><td v-if="family === 'eth_scam'"><span class="execution-status" :data-status="row.status">{{ row.status }}</span></td><td v-if="family === 'eth_scam'">{{ row.method || '—' }}</td></template><td class="mono">{{ row.block_number }}</td><td><button class="text-link inline-action" @click="detail = row">Inspect</button></td></tr></tbody></table></div><div v-if="!page?.items.length" class="table-empty" role="status"><strong>{{ pending ? 'Loading records' : 'No records available' }}</strong><span>{{ error ? errorMessage(error) : 'Records appear after historical data has been prepared.' }}</span><AppButton v-if="error" @click="load">Retry</AppButton></div><div class="ledger-footer"><span>{{ page ? `${page.total} records · Page ${pageIndex + 1}` : 'Awaiting records' }}</span><div><AppButton :disabled="pending || pageIndex === 0" @click="previous">Previous</AppButton><AppButton :disabled="pending || !page?.next_cursor" @click="next">Next</AppButton></div></div><section v-if="detail" class="ledger-detail" aria-label="Selected record"><header><h3>Record details</h3><button class="text-link inline-action" @click="detail = null">Close</button></header><dl><div><dt>Transaction</dt><dd class="mono">{{ detail.hash }}</dd></div><div><dt>Event identity</dt><dd class="mono">{{ detail.id }}</dd></div><div><dt>Execution</dt><dd>{{ detail.status }}</dd></div><div><dt>Time</dt><dd>{{ formatUtc(detail.block_time) }}</dd></div><div v-if="family === 'eth_scam' && detail.value_raw !== null && detail.decimals !== null"><dt>Native value</dt><dd>{{ formatUnits(detail.value_raw, detail.decimals) }} {{ detail.asset }}</dd></div><div v-for="(amount, index) in detail.amounts" :key="`asset-${index}`"><dt>{{ amount.asset }} {{ amount.direction || '' }}</dt><dd>{{ formatUnits(amount.raw, amount.decimals) }}<span v-if="amount.contract_address" class="asset-quantity mono">{{ amount.contract_address }}</span></dd></div><div v-if="detail.trace_id"><dt>Trace</dt><dd>{{ detail.trace_id }}</dd></div><div v-if="detail.log_index !== null"><dt>Log index</dt><dd>{{ detail.log_index }}</dd></div><div v-if="detail.emitter"><dt>Event emitter</dt><dd class="mono">{{ detail.emitter }}</dd></div><div v-for="(entry, key) in detail.event_data || {}" :key="key"><dt>{{ key }}</dt><dd class="mono">{{ entry }}</dd></div><div v-if="detail.gas_used"><dt>Gas used / price</dt><dd>{{ detail.gas_used }} / {{ formatUnits(detail.gas_price_wei || '0', 9) }} Gwei</dd></div></dl></section><p class="panel-footnote">{{ family === 'eth_scam' ? 'Failed transaction values are attempted amounts; they are excluded from successful flow totals.' : 'Each row represents a log or pool event, not necessarily a unique transaction.' }}</p></AppPanel></template>
