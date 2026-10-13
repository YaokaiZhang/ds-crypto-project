<script setup lang="ts">
import { formatScore } from '@/presenters/format';
import type { TaskResult } from '@/api/contracts';
defineProps<{ result?: TaskResult; loading?: boolean }>();
</script>
<template>
  <section class="risk-panel glass-pane" aria-label="Activity forecast">
    <div class="risk-task">
      <h2>Activity forecast</h2>
      <p role="status">{{ result?.forecast ? result.forecast.outcome === 'continued_activity' ? 'Continued activity' : 'Low-volume outcome' : loading ? 'Preparing forecast' : 'Forecast unavailable' }}</p>
      <template v-if="result?.forecast">
        <dl class="analysis-context-data">
          <div><dt>Continued-activity score</dt><dd><output>{{ formatScore(result.score) }}</output></dd></div>
          <div><dt>Observation</dt><dd>First {{ result.forecast.observation_days }} days</dd></div>
          <div><dt>Forecast horizon</dt><dd>Following {{ result.forecast.horizon_days }} days</dd></div>
          <div><dt>Swap-volume boundary</dt><dd>USD {{ result.forecast.swap_volume_threshold_usd }}</dd></div>
        </dl>
        <p class="panel-footnote">{{ result.explanation }}</p>
      </template>
      <p v-else-if="result?.reason" class="panel-footnote">{{ result.reason }}</p>
    </div>
  </section>
</template>
