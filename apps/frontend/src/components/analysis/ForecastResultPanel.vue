<script setup lang="ts">
import { computed } from 'vue';
import { formatScore } from '@/presenters/format';
import type { TaskResult } from '@/api/contracts';
const props = defineProps<{ result?: TaskResult; loading?: boolean }>();
const outcome = computed(() => props.result?.forecast
  ? props.result.forecast.outcome === 'continued_activity' ? 'Continued activity' : 'Low volume'
  : props.loading ? 'Evaluating' : 'Unavailable');
const scoreWidth = computed(() => `${Math.max(0, Math.min(1, props.result?.score ?? 0)) * 100}%`);
</script>
<template>
  <section class="risk-panel glass-pane" aria-label="Activity forecast score">
    <div class="risk-task">
      <h2>Activity forecast</h2>
      <div class="risk-signal">
        <div class="risk-value">
          <output aria-label="Continued-activity score">{{ formatScore(result?.score ?? null) }}</output>
          <div class="risk-meter" aria-label="Continued-activity score, scale zero to one"><span v-if="result?.score != null" :style="{ width: scoreWidth }"></span></div>
        </div>
        <span class="risk-class" role="status">{{ outcome }}</span>
      </div>
      <p class="panel-footnote">Continued-activity score · uncalibrated</p>
    </div>
  </section>
  <section class="risk-panel glass-pane" aria-label="Forecast details">
    <div class="risk-task">
      <h2>Forecast details</h2>
      <template v-if="result?.forecast">
        <dl class="analysis-context-data">
          <div><dt>Observation</dt><dd>First {{ result.forecast.observation_days }} days</dd></div>
          <div><dt>Forecast horizon</dt><dd>Following {{ result.forecast.horizon_days }} days</dd></div>
          <div><dt>Swap-volume boundary</dt><dd>USD {{ result.forecast.swap_volume_threshold_usd }}</dd></div>
        </dl>
        <p class="panel-footnote">{{ result.explanation }}</p>
      </template>
      <p v-else class="panel-footnote">{{ result?.reason || (loading ? 'Preparing forecast details' : 'Forecast details unavailable') }}</p>
    </div>
  </section>
</template>
