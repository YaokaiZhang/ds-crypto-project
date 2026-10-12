<script setup lang="ts">
import AppInput from '@/components/ui/AppInput.vue';
import AppButton from '@/components/ui/AppButton.vue';
import RiskScreeningPanel from './RiskScreeningPanel.vue';
import BasicInformationPanel from './BasicInformationPanel.vue';
import TransactionGraphPanel from './TransactionGraphPanel.vue';
import ActivityPanel from './ActivityPanel.vue';
import TransactionLedgerPanel from './TransactionLedgerPanel.vue';
import { workbenchLabels } from '@/presenters/workbench';
import type { AnalysisFamily } from '@/api/contracts';
const props = defineProps<{ family: AnalysisFamily }>();
</script>

<template>
  <div class="workbench">
    <div class="query-bar">
      <AppInput :label="workbenchLabels[props.family].input" placeholder="0x…" disabled />
      <AppButton disabled variant="primary">Analyze</AppButton>
    </div>
    <div class="workbench-panels">
      <RiskScreeningPanel />
      <BasicInformationPanel />
      <TransactionGraphPanel />
      <ActivityPanel :title="workbenchLabels[props.family].activity" />
      <TransactionLedgerPanel />
    </div>
  </div>
</template>
