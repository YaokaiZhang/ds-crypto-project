<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import AppIcon from '@/components/ui/AppIcon.vue';
import type { GraphView } from '@/api/contracts';
import { createGraphRenderer, type GraphRenderer } from '@/presenters/graph';
import { readDisplayGraph, taskNames, type GraphContext } from '@/presenters/graphDisplay';
import { resolveChartTheme } from '@/design/chartTheme';

const props = withDefaults(defineProps<{ graph?: GraphView | null; context?: GraphContext | null; loading?: boolean; error?: string | null }>(), { graph: null, context: null, loading: false, error: null });
defineEmits<{ retry: [] }>();
const host = ref<HTMLElement>();
let renderer: GraphRenderer | undefined;
let mountedHost: HTMLElement | undefined;
const parsed = computed(() => {
  if (!props.graph) return { graph: null, error: null };
  try { return { graph: readDisplayGraph(props.graph), error: null }; }
  catch (cause) { return { graph: null, error: cause instanceof Error ? cause.message : 'The graph could not be read.' }; }
});
const contextMatches = computed(() => props.context && props.graph && props.context.sampleId === props.graph.sample_id && props.context.taskId === props.graph.task_id);
const provenance = computed(() => contextMatches.value ? props.context : null);
const failure = computed(() => props.error || parsed.value.error);
function count(value: number | undefined) { return value !== undefined && Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('en-US') : 'Not supplied'; }
watch([host, () => props.graph], () => {
  if (mountedHost !== host.value) { renderer?.dispose(); renderer = undefined; mountedHost = host.value; }
  if (!host.value || !props.graph || !parsed.value.graph) return;
  if (!renderer) { renderer = createGraphRenderer(); renderer.mount(host.value); }
  renderer.update(props.graph, resolveChartTheme(host.value));
}, { flush: 'post' });
onBeforeUnmount(() => renderer?.dispose());
</script>

<template>
  <section class="transaction-graph-panel" aria-label="Transaction Graph" :aria-busy="loading">
    <header class="graph-panel-header">
      <div><h2>Graph View</h2></div>
      <slot name="actions"><span v-if="parsed.graph" class="graph-task-label"><AppIcon name="graph" :size="15" /> {{ taskNames[parsed.graph.taskId] }}</span></slot>
    </header>
    <div v-if="loading" class="graph-empty" role="status"><AppIcon name="graph" :size="32" /><h3>Preparing graph</h3><p>The graph will appear when its task sample is available.</p></div>
    <div v-else-if="failure" class="graph-empty" role="alert"><AppIcon name="graph" :size="32" /><h3>Graph unavailable</h3><p>{{ failure }}</p><button v-if="error" type="button" @click="$emit('retry')">Try again</button></div>
    <template v-else-if="parsed.graph?.nodes.length">
      <div ref="host" class="graph-render-host" />
      <details class="graph-provenance" open>
        <summary>Graph provenance <span>{{ parsed.graph.sampleId }}</span></summary>
        <p v-if="context && !contextMatches" role="status">Metadata belongs to a different task or sample and has not been applied.</p>
        <dl>
          <div><dt>Sample</dt><dd>{{ parsed.graph.sampleId }}</dd></div>
          <div><dt>Task</dt><dd>{{ taskNames[parsed.graph.taskId] }}</dd></div>
          <div><dt>Displayed nodes / edges</dt><dd>{{ parsed.graph.nodes.length }} / {{ parsed.graph.edges.length }}</dd></div>
          <div><dt>Model nodes / edges</dt><dd>{{ count(provenance?.modelNodes) }} / {{ count(provenance?.modelEdges) }}</dd></div>
          <div><dt>Observation window</dt><dd>{{ provenance?.window || 'Not supplied' }}</dd></div>
          <div><dt>Assessment cutoff</dt><dd>{{ provenance?.cutoff || 'Not supplied' }}</dd></div>
          <div><dt>Graph version</dt><dd>{{ provenance?.version || 'Not supplied' }}</dd></div>
          <div><dt>Sampling / display subset</dt><dd>{{ provenance?.sampling || 'Not supplied. Full-history coverage is not established.' }}</dd></div>
        </dl>
      </details>
    </template>
    <div v-else class="graph-empty" role="status"><AppIcon name="graph" :size="36" /><h3>{{ parsed.graph ? 'This sample has no graph nodes' : 'No graph sample available' }}</h3><p>{{ parsed.graph ? 'No relationships can be drawn from the supplied sample.' : 'A task-specific graph will appear here when analysis data is available. No model graph is connected yet.' }}</p></div>
  </section>
</template>

<style src="../../styles/transaction-graph.css"></style>
