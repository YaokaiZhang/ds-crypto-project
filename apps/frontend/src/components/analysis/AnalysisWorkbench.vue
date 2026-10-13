<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import AppButton from '@/components/ui/AppButton.vue';
import AppIcon from '@/components/ui/AppIcon.vue';
import RiskScreeningPanel from './RiskScreeningPanel.vue';
import BasicInformationPanel from './BasicInformationPanel.vue';
import TransactionGraphPanel from './TransactionGraphPanel.vue';
import ActivityPanel from './ActivityPanel.vue';
import TransactionLedgerPanel from './TransactionLedgerPanel.vue';
import { workbenchLabels } from '@/presenters/workbench';
import { useAnalysis } from '@/composables/useAnalysis';
import { useCapabilities } from '@/composables/useCapabilities';
import { errorMessage } from '@/api/client';
import { formatUtc, shortenAddress } from '@/presenters/format';
import type { AnalysisFamily, TaskId } from '@/api/contracts';
import '@/styles/workbench.css';
const props = defineProps<{ family: AnalysisFamily }>();
const { result, pending, error, create, reset } = useAnalysis();
const { capabilities, capabilityError, loadCapabilities } = useCapabilities();
const target = ref(''), selectedPool = ref(''), submittedTarget = ref('');
const started = ref(false), touched = ref(false), copied = ref(false);
const input = ref<HTMLInputElement>();
const activeTask = ref<TaskId>(props.family === 'eth_scam' ? 'phishing' : 'honeypot');
const family = computed(() => result.value?.family || props.family);
const tasks = computed<TaskId[]>(() => family.value === 'eth_scam' ? ['phishing', 'ponzi'] : ['honeypot', 'rug_pull']);
const profile = computed(() => capabilities.value?.profiles?.find(item => item.family === family.value));
const valid = computed(() => /^0x[\da-f]{40}$/i.test(target.value.trim()));
const graph = computed(() => result.value?.graphs[activeTask.value] || null);
const graphContext = computed(() => {
  const value = graph.value?.context;
  return value ? { sampleId: value.sample_id, taskId: value.task_id, modelNodes: value.model_nodes,
    modelEdges: value.model_edges, window: value.window, cutoff: value.cutoff, version: value.version, sampling: value.sampling } : null;
});
const stages = [
  { id: 'queued', label: 'Queued' }, { id: 'resolving', label: 'Identifying address' },
  { id: 'collecting', label: 'Collecting activity' }, { id: 'normalizing', label: 'Reconciling records' },
  { id: 'building_graph', label: 'Building graphs' }, { id: 'predicting', label: 'Evaluating tasks' },
  { id: 'completed', label: 'Analysis complete' },
];
const stageIndex = computed(() => stages.findIndex(stage => stage.id === result.value?.stage));
const stageLabel = computed(() => error.value || result.value?.status === 'failed' ? 'Analysis unavailable' : stages[stageIndex.value]?.label || 'Starting analysis');
watch(profile, value => { if (value) selectedPool.value = value.pools[0] || ''; }, { immediate: true });
watch(family, value => { activeTask.value = value === 'eth_scam' ? 'phishing' : 'honeypot'; });
onMounted(() => { void loadCapabilities(); input.value?.focus({ preventScroll: true }); });
function analyze() {
  touched.value = true;
  if (!valid.value || pending.value || !capabilities.value?.analysis_enabled) return;
  submittedTarget.value = target.value.trim(); started.value = true;
  void create({ target: submittedTarget.value, family: family.value, tasks: tasks.value,
    pools: family.value === 'token_scam' && selectedPool.value ? [selectedPool.value] : [] });
}
async function newAnalysis() {
  reset(); started.value = false; target.value = ''; submittedTarget.value = ''; touched.value = false; copied.value = false;
  await nextTick(); input.value?.focus({ preventScroll: true });
}
async function copyAddress() {
  try { await navigator.clipboard.writeText(submittedTarget.value); copied.value = true; }
  catch { copied.value = false; }
}
const taskName = (task: TaskId) => ({ phishing: 'Phishing', ponzi: 'Ponzi', honeypot: 'Honeypot', rug_pull: 'Rug Pull' })[task];
</script>
<template>
  <div class="workbench" :class="{ 'workbench-entry': !started }">
    <section v-if="!started" class="analysis-entry" aria-label="Enter analysis address">
      <h1 class="sr-only">{{ family === 'eth_scam' ? 'ETH analysis' : 'ERC-20 analysis' }}</h1>
      <form class="address-entry" @submit.prevent="analyze">
        <label for="analysis-address" class="sr-only">{{ workbenchLabels[family].input }}</label>
        <div class="address-entry-field"><AppIcon :name="family === 'eth_scam' ? 'wallet' : 'token'" :size="22" /><input id="analysis-address" ref="input" v-model="target" :placeholder="workbenchLabels[family].input" autocomplete="off" autocapitalize="off" spellcheck="false" :aria-invalid="touched && !!target && !valid" :aria-describedby="touched && target && !valid ? 'address-error' : undefined" @blur="touched = true" /><button type="submit" :disabled="!valid || !capabilities?.analysis_enabled" :aria-label="family === 'eth_scam' ? 'Analyze Ethereum address' : 'Analyze ERC-20 token'"><AppIcon name="arrow-right" :size="22" /></button></div>
        <p v-if="touched && target && !valid" id="address-error" class="entry-message" role="alert">Enter a 42-character Ethereum address starting with 0x.</p>
        <p v-if="capabilityError" class="entry-message" role="alert">{{ errorMessage(capabilityError) }} <button type="button" class="text-link inline-action" @click="loadCapabilities">Retry connection</button></p>
        <p v-else-if="capabilities && !capabilities.analysis_enabled" class="entry-message" role="status">Analysis service is unavailable.</p>
      </form>
    </section>
    <div v-else class="analysis-layout">
      <aside class="analysis-sidebar" aria-label="Analysis context and risk">
        <section class="analysis-context glass-pane" aria-label="Analysis progress" :aria-busy="pending">
          <h1>{{ result?.basic_information?.name || (family === 'eth_scam' ? 'ETH analysis' : 'ERC-20 analysis') }}</h1>
          <p class="analysis-address mono">{{ submittedTarget }}</p>
          <div class="analysis-stage" role="status" :data-status="error || result?.status === 'failed' ? 'failed' : result?.status"><span>{{ stageLabel }}</span><ol class="stage-segments" aria-label="Analysis stages"><li v-for="(stage, index) in stages" :key="stage.id" :data-state="index < stageIndex ? 'complete' : index === stageIndex ? 'current' : 'pending'" :aria-label="`${stage.label}: ${index < stageIndex ? 'complete' : index === stageIndex ? 'current' : 'pending'}`" :title="stage.label"></li></ol></div>
          <dl class="analysis-context-data"><div><dt>Network</dt><dd>Ethereum mainnet</dd></div><div v-if="result?.cutoff"><dt>Cutoff · UTC</dt><dd>{{ formatUtc(result.cutoff).replace(' UTC', '') }}</dd></div><div v-if="family === 'token_scam' && selectedPool"><dt>Selected pool</dt><dd class="mono" :title="selectedPool">{{ shortenAddress(selectedPool) }}</dd></div></dl>
          <p v-if="error" class="query-error" role="alert">{{ errorMessage(error) }}</p>
          <AppButton v-if="error || result?.status === 'failed'" class="analysis-retry" :disabled="pending" @click="analyze">Retry analysis</AppButton>
          <div class="analysis-context-actions"><button class="text-link inline-action" @click="newAnalysis"><AppIcon name="search" :size="14" />New analysis</button><button class="context-copy" :aria-label="copied ? 'Address copied' : 'Copy analyzed address'" :title="copied ? 'Address copied' : 'Copy address'" @click="copyAddress"><AppIcon name="copy" :size="15" /></button></div>
        </section>
        <RiskScreeningPanel :family="family" :results="result?.tasks" :loading="pending" />
      </aside>
      <TransactionGraphPanel class="graph-workspace" :graph="graph" :context="graphContext" :loading="pending && !graph"><template #actions><div class="task-selector" role="group" aria-label="Graph task"><button v-for="task in tasks" :key="task" :aria-pressed="activeTask === task" @click="activeTask = task">{{ taskName(task) }}</button></div></template></TransactionGraphPanel>
      <div class="analysis-metrics"><BasicInformationPanel :family="family" :information="result?.basic_information" :loading="pending" /><ActivityPanel :title="family === 'eth_scam' ? 'Flow Activity' : 'Token Activity'" :family="family" :activity="result?.activity" :loading="pending" /></div>
      <TransactionLedgerPanel :family="family" :analysis-id="result?.analysis_id" :initial-page="result?.transactions" />
    </div>
  </div>
</template>
