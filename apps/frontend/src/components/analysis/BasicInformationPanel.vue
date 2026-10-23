<script setup lang="ts">
import AppPanel from '@/components/ui/AppPanel.vue';
import { computed } from 'vue';
import type { AnalysisFamily, BasicInformation } from '@/api/contracts';
const props = defineProps<{ family: AnalysisFamily; information?: BasicInformation | null; loading?: boolean }>();
const fields = computed(() => props.information?.fields || (props.family === 'eth_scam' ? ['Account type', 'ETH balance', 'Observation window', 'Native inflow · ETH', 'Native outflow · ETH', 'Net flow · ETH', 'External transactions', 'Internal transfers', 'Native counterparties', 'First activity', 'Last activity', 'Contract metadata'] : ['Token identity', 'Total supply', 'Observation window', 'Selected pools', 'Transfer events', 'Transfer participants', 'Swap events', 'Mint events', 'Burn events', 'First activity', 'Last activity', 'Contract metadata']).map((label, index) => ({ key: String(index), label, value: '—', hint: 'Awaiting data' })));
</script>
<template><AppPanel title="Basic Information" class="information-panel" :aria-busy="loading"><dl class="information-grid"><div v-for="field in fields" :key="field.key"><dt>{{ field.label }}</dt><dd :title="field.hint">{{ field.value }}</dd></div></dl></AppPanel></template>
