<script setup lang="ts">
import AppPanel from '@/components/ui/AppPanel.vue';
import ActivityChart from './ActivityChart.vue';
import { computed, ref } from 'vue';
import { formatWei } from '@/presenters/format';
import type { ActivitySeries, AnalysisFamily, ActivityPoint } from '@/api/contracts';
const props = defineProps<{ title: string; family: AnalysisFamily; activity?: ActivitySeries | null; loading?: boolean }>();
const range = ref(props.family === 'forecast' ? 7 : 30);
const points = computed(() => props.family === 'forecast' || range.value === 30 ? props.activity?.points || [] : props.activity?.points.slice(-range.value) || []);
const dates = computed(() => points.value.map(point => point.date));
function counts(label: string, key: 'external_count' | 'transfer_count' | 'swap_count' | 'mint_count' | 'burn_count') {
  return { label, values: points.value.map(point => point.covered ? point[key] : null), display: points.value.map(point => point.covered && point[key] !== null ? String(point[key]) : 'Unavailable') };
}
function flows(label: string, key: keyof Pick<ActivityPoint, 'inflow_wei' | 'outflow_wei'>) {
  return { label, values: points.value.map(point => point.covered && point[key] !== null ? Number(point[key]) / 1e18 : null), display: points.value.map(point => point.covered && point[key] !== null ? `${formatWei(point[key]!)} ETH` : 'Unavailable') };
}
const flowLines = computed(() => [flows('Inflow', 'inflow_wei'), flows('Outflow', 'outflow_wei')]);
const countLines = computed(() => props.family === 'eth_scam' ? [counts('Transactions', 'external_count')] : [counts('Transfer events', 'transfer_count')]);
const poolLines = computed(() => [counts('Swap', 'swap_count'), counts('Mint', 'mint_count'), counts('Burn', 'burn_count')]);
</script>
<template><AppPanel :title="title" class="activity-panel"><template #actions><div class="range-control" aria-label="Display range"><button v-for="days in family === 'forecast' ? [7] : [7, 30]" :key="days" :aria-pressed="range === days" @click="range = days">{{ days }}D</button></div></template><template v-if="points.length"><ActivityChart v-if="family === 'eth_scam'" title="Native ETH flow" :dates="dates" :series="flowLines" unit="ETH" /><ActivityChart :title="family === 'eth_scam' ? 'External transactions' : 'Token transfers'" :dates="dates" :series="countLines" unit="events" /><ActivityChart v-if="family !== 'eth_scam'" title="Pool activity" :dates="dates" :series="poolLines" unit="events" /></template><div v-else class="chart-empty"><span>{{ loading ? 'Preparing activity data' : 'Awaiting activity data' }}</span><span class="chart-baseline" aria-hidden="true"></span></div><p class="panel-footnote">{{ family === 'eth_scam' ? 'Successful native transfers · excludes gas.' : family === 'forecast' ? 'First 7 days only · no follow-up observations.' : 'Event counts within selected pools.' }} Display range does not change the assessment.</p></AppPanel></template>
