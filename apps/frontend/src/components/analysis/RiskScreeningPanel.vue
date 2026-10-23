<script setup lang="ts">
import { computed } from 'vue';
import { formatScore } from '@/presenters/format';
import type { AnalysisFamily, TaskResult, TaskId } from '@/api/contracts';
const props = defineProps<{ family: AnalysisFamily; results?: TaskResult[]; loading?: boolean }>();
const definitions = computed<{ id: TaskId; name: string }[]>(() => props.family === 'eth_scam'
  ? [{ id: 'ponzi', name: 'Ponzi' }, { id: 'phishing', name: 'Phishing' }]
  : [{ id: 'honeypot', name: 'Honeypot' }, { id: 'rug_pull', name: 'Rug Pull' }]);
const tasks = computed(() => definitions.value.map(task => ({ ...task, result: props.results?.find(item => item.task_id === task.id) })));
const bandName = (band: string | null | undefined) => band ? `${band[0].toUpperCase()}${band.slice(1)} Risk` : props.loading ? 'Evaluating' : 'Unavailable';
function accessibleSummary(task: typeof tasks.value[number]) {
  return `${task.name}. Score ${formatScore(task.result?.score ?? null)}. ${bandName(task.result?.risk_band)}. ${task.result?.reason || ''} ${task.result?.calibration === 'uncalibrated' ? 'Uncalibrated model score, not a probability.' : ''}`;
}
</script>
<template>
  <section class="risk-panel glass-pane" aria-label="Risk Screening">
    <div class="risk-task" v-for="task in tasks" :key="task.id" :aria-label="accessibleSummary(task)">
      <h2>{{ task.name }}</h2>
      <div class="risk-signal"><div class="risk-value"><output>{{ formatScore(task.result?.score ?? null) }}</output><div class="risk-meter" :data-tone="task.result?.risk_band" :aria-label="`${task.name} score`"><span v-if="task.result?.score != null" :style="{ width: `${Math.max(0, Math.min(1, task.result.score)) * 100}%` }"></span></div></div><span class="risk-class" :data-tone="task.result?.risk_band">{{ bandName(task.result?.risk_band) }}</span></div>
    </div>
  </section>
</template>
