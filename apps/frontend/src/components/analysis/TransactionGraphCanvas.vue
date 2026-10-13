<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AppIcon from '@/components/ui/AppIcon.vue';
import { edgeAmount, layoutGraph, relationLabel, shortRef, type DisplayGraph, type PositionedEdge, type PositionedNode } from '@/presenters/graphDisplay';

const props = defineProps<{ graph: DisplayGraph }>();
const scene = computed(() => layoutGraph(props.graph));
const nodesById = computed(() => new Map(scene.value.nodes.map(node => [node.id, node])));
const svg = ref<SVGSVGElement>();
const plot = ref<HTMLElement>();
const plotSize = ref({ width: 900, height: 560 });
const zoom = ref(1);
const pan = ref({ x: 0, y: 0 });
const reducedMotion = ref(false);
const motionOff = ref(false);
const replayKey = ref(0);
const focusIndex = ref(0);
const nodeChoice = ref('');
const edgeChoice = ref('');
type Inspection = { kind: 'node'; item: PositionedNode } | { kind: 'edge'; item: PositionedEdge };
const selected = ref<Inspection | null>(null);
const hovered = ref<Inspection | null>(null);
const tooltip = ref({ x: 16, y: 16 });
const active = computed(() => hovered.value ?? selected.value);
const renderScale = computed(() => Math.max(.01, Math.min(plotSize.value.width / scene.value.width, plotSize.value.height / scene.value.height) * zoom.value));
const viewBox = computed(() => {
  const width = scene.value.width / zoom.value; const height = scene.value.height / zoom.value;
  return `${scene.value.minX + (scene.value.width - width) / 2 - pan.value.x} ${scene.value.minY + (scene.value.height - height) / 2 - pan.value.y} ${width} ${height}`;
});
// Unique per renderer, so markers remain isolated when multiple panels are mounted.
const markerId = `graph-arrow-${Math.random().toString(36).slice(2)}`;
let media: MediaQueryList | undefined;
let resizeObserver: ResizeObserver | undefined;
let tooltipTimer: ReturnType<typeof setTimeout> | undefined;
let drag: { id: number; x: number; y: number; panX: number; panY: number; scale: number } | undefined;
const updateMotion = () => { reducedMotion.value = !!media?.matches; };
onMounted(() => {
  media = window.matchMedia('(prefers-reduced-motion: reduce)');
  updateMotion(); media.addEventListener('change', updateMotion);
  resizeObserver = new ResizeObserver(entries => {
    const { width, height } = entries[0].contentRect;
    if (width && height) plotSize.value = { width, height };
  });
  if (svg.value) resizeObserver.observe(svg.value);
});
onBeforeUnmount(() => { media?.removeEventListener('change', updateMotion); resizeObserver?.disconnect(); clearTimeout(tooltipTimer); });
watch(() => props.graph, () => {
  selected.value = null; hovered.value = null; nodeChoice.value = ''; edgeChoice.value = '';
  focusIndex.value = 0; drag = undefined; fit(); replayKey.value++;
});
function fit() { zoom.value = 1; pan.value = { x: 0, y: 0 }; }
function changeZoom(factor: number) { zoom.value = Math.max(.6, Math.min(6, zoom.value * factor)); }
function wheel(event: WheelEvent) {
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault(); changeZoom(event.deltaY < 0 ? 1.12 : 1 / 1.12);
}
function panStart(event: PointerEvent) {
  if (event.button !== 0 || (event.target as Element).closest('[data-graph-item]')) return;
  const matrix = svg.value?.getScreenCTM();
  if (!matrix) return;
  drag = { id: event.pointerId, x: event.clientX, y: event.clientY, panX: pan.value.x, panY: pan.value.y, scale: matrix.a };
  svg.value?.setPointerCapture(event.pointerId); hovered.value = null;
}
function panMove(event: PointerEvent) {
  if (!drag || drag.id !== event.pointerId) return;
  pan.value = { x: drag.panX + (event.clientX - drag.x) / drag.scale, y: drag.panY + (event.clientY - drag.y) / drag.scale };
}
function panEnd() { drag = undefined; }
function keepTooltip() { clearTimeout(tooltipTimer); }
function hideTooltip() { clearTimeout(tooltipTimer); tooltipTimer = setTimeout(() => { hovered.value = null; }, 180); }
function showSummary(inspection: Inspection, event: MouseEvent | FocusEvent) {
  if (drag) return;
  keepTooltip(); hovered.value = inspection;
  const bounds = plot.value?.getBoundingClientRect();
  if (!bounds) return;
  const anchor = (event.currentTarget as Element).getBoundingClientRect();
  const x = 'clientX' in event ? event.clientX : anchor.x + anchor.width / 2;
  const y = 'clientY' in event ? event.clientY : anchor.y + anchor.height / 2;
  tooltip.value = { x: Math.max(8, Math.min(x - bounds.x + 16, bounds.width - 264)), y: Math.max(8, Math.min(y - bounds.y + 16, bounds.height - 184)) };
}
function pin(inspection: Inspection) { selected.value = inspection; hovered.value = null; }
function dismiss() { selected.value = null; hovered.value = null; nodeChoice.value = ''; edgeChoice.value = ''; }
function connectedNode(id: string) {
  if (!active.value) return true;
  if (active.value.kind === 'edge') return active.value.item.source === id || active.value.item.target === id;
  return active.value.item.id === id || props.graph.edges.some(edge =>
    edge.source === active.value!.item.id && edge.target === id || edge.target === active.value!.item.id && edge.source === id);
}
function connectedEdge(edge: PositionedEdge) {
  if (!active.value) return true;
  return active.value.kind === 'edge' ? active.value.item.id === edge.id : edge.source === active.value.item.id || edge.target === active.value.item.id;
}
function nodeName(node: PositionedNode) { return node.label ? (node.label.length > 24 ? `${node.label.slice(0, 22)}…` : node.label) : shortRef(node.ref); }
function edgeName(edge: PositionedEdge) {
  const source = nodesById.value.get(edge.source)!;
  const target = nodesById.value.get(edge.target)!;
  return `${nodeName(source)} → ${nodeName(target)}`;
}
function assessment(node: PositionedNode) {
  return node.assessed === true ? 'Individually assessed' : node.assessed === false ? 'Not individually assessed' : 'Assessment status unknown';
}
function inspectChoice(kind: 'node' | 'edge') {
  if (kind === 'node') {
    const item = scene.value.nodes.find(node => node.id === nodeChoice.value);
    if (item) pin({ kind, item });
  } else {
    const item = scene.value.edges.find(edge => edge.id === edgeChoice.value);
    if (item) pin({ kind, item });
  }
}
async function nodeKey(event: KeyboardEvent, index: number) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
  event.preventDefault();
  focusIndex.value = (index + (['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1) + scene.value.nodes.length) % scene.value.nodes.length;
  await nextTick(); svg.value?.querySelector<SVGGElement>(`[data-node-index="${focusIndex.value}"]`)?.focus();
}
function formatTime(value: string | null) { return value ? new Date(value).toISOString().replace('T', ' ').replace('.000Z', ' UTC') : 'Not supplied'; }
</script>

<template>
  <div class="graph-renderer" :class="{ 'graph-no-motion': reducedMotion || motionOff, 'graph-dense': graph.nodes.length > 28 }" @keydown.esc="dismiss">
    <div class="graph-toolbar">
      <p><span class="graph-live-dot" /> {{ graph.nodes.length }} nodes <span class="graph-divider">/</span> {{ graph.edges.length }} directed relations</p>
      <div class="graph-controls" aria-label="Graph controls">
        <button type="button" aria-label="Zoom out" :disabled="zoom <= .6" @click="changeZoom(1 / 1.25)"><AppIcon name="zoom-out" /></button>
        <output aria-label="Zoom level">{{ Math.round(zoom * 100) }}%</output>
        <button type="button" aria-label="Zoom in" :disabled="zoom >= 6" @click="changeZoom(1.25)"><AppIcon name="zoom-in" /></button>
        <button type="button" aria-label="Fit graph" @click="fit"><AppIcon name="fit" /><span>Fit</span></button>
        <button type="button" aria-label="Replay graph entrance" :disabled="reducedMotion || motionOff" @click="replayKey++"><AppIcon name="refresh" /><span>Replay</span></button>
        <button type="button" :aria-pressed="motionOff" :disabled="reducedMotion" :aria-label="reducedMotion ? 'Reduced motion enabled' : motionOff ? 'Enable graph motion' : 'Disable graph motion'" @click="motionOff = !motionOff"><AppIcon :name="motionOff || reducedMotion ? 'play' : 'pause'" /></button>
      </div>
    </div>

    <div ref="plot" class="graph-plot">
      <svg ref="svg" class="graph-svg" :viewBox="viewBox" :style="{ aspectRatio: `${scene.width} / ${scene.height}` }" aria-label="Interactive transaction graph. Use arrow keys between nodes, or the inspect lists below for nodes and relations." role="group"
        @wheel="wheel" @pointerdown="panStart" @pointermove="panMove" @pointerup="panEnd" @pointercancel="panEnd" @lostpointercapture="panEnd">
        <defs><marker :id="markerId" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M 1 1 L 9 5 L 1 9" class="graph-arrow" /></marker></defs>
        <g :key="`${graph.sampleId}-${replayKey}`">
          <g v-for="edge in scene.edges" :key="edge.id" data-graph-item="edge" :class="['graph-edge', { 'is-dim': !connectedEdge(edge), 'is-active': active && connectedEdge(edge), 'is-structural': edge.kind === 'structural' }]"
            :style="{ '--enter-delay': `${edge.delay}ms` }" role="button" :aria-label="`${edgeName(edge)}: ${relationLabel(edge.relation)}`" tabindex="-1"
            @mouseenter="showSummary({ kind: 'edge', item: edge }, $event)" @mouseleave="hideTooltip" @focus="showSummary({ kind: 'edge', item: edge }, $event)" @blur="hideTooltip"
            @click.stop="pin({ kind: 'edge', item: edge })" @keydown.enter.prevent="pin({ kind: 'edge', item: edge })">
            <path class="graph-edge-line" :d="edge.path" :marker-end="`url(#${markerId})`" pathLength="1" />
            <path class="graph-edge-hit" :d="edge.path" />
          </g>
          <g v-for="(node, index) in scene.nodes" :key="node.id" data-graph-item="node" :data-node-index="index" :transform="`translate(${node.x}, ${node.y})`"
            :class="['graph-node', `role-${node.role}`, { 'is-root': node.root, 'is-dim': !connectedNode(node.id), 'is-active': active?.kind === 'node' && active.item.id === node.id }]"
            :style="{ '--enter-delay': `${node.delay}ms` }" role="button" :tabindex="focusIndex === index ? 0 : -1" :aria-label="`${node.root ? 'Root, ' : ''}${nodeName(node)}, ${node.role}. ${assessment(node)}`"
            @mouseenter="showSummary({ kind: 'node', item: node }, $event)" @mouseleave="hideTooltip" @focus="focusIndex = index; showSummary({ kind: 'node', item: node }, $event)" @blur="hideTooltip"
            @click.stop="pin({ kind: 'node', item: node })" @keydown.enter.prevent="pin({ kind: 'node', item: node })" @keydown.space.prevent="pin({ kind: 'node', item: node })" @keydown="nodeKey($event, index)">
            <g class="graph-node-body">
              <circle class="graph-node-hit" :r="Math.max(node.radius + 10, 16 / renderScale)" />
              <circle v-if="node.root" class="graph-root-orbit" :r="node.radius + 9" />
              <rect v-if="node.role === 'pool' || node.role === 'contract'" class="graph-node-shape" :x="-node.radius" :y="-node.radius" :width="node.radius * 2" :height="node.radius * 2" :rx="node.role === 'pool' ? 7 : 3" />
              <path v-else-if="node.role === 'token'" class="graph-node-shape" :d="`M 0 ${-node.radius - 3} L ${node.radius + 3} 0 L 0 ${node.radius + 3} L ${-node.radius - 3} 0 Z`" />
              <circle v-else class="graph-node-shape" :r="node.radius" />
              <path v-if="node.root" class="graph-node-glyph" d="M 0 -11 L 7 0 L 0 4 L -7 0 Z M -7 3 L 0 12 L 7 3" />
              <rect v-else-if="node.role === 'pool'" class="graph-node-glyph" x="-6" y="-6" width="12" height="12" rx="3" />
              <path v-else-if="node.role === 'contract'" class="graph-node-glyph" d="M -3 -6 L -8 0 L -3 6 M 3 -6 L 8 0 L 3 6" />
              <circle v-else class="graph-node-core" r="3.5" />
            </g>
          </g>
        </g>
      </svg>
      <div v-if="hovered" class="graph-tooltip" :style="{ left: `${tooltip.x}px`, top: `${tooltip.y}px` }" @mouseenter="keepTooltip" @mouseleave="hideTooltip">
        <template v-if="hovered.kind === 'node'">
          <span class="graph-tooltip-kind">{{ hovered.item.root ? 'Root' : hovered.item.role }} node</span>
          <strong>{{ nodeName(hovered.item) }}</strong>
          <code>{{ shortRef(hovered.item.ref) }}</code>
          <p>{{ assessment(hovered.item) }}</p>
        </template>
        <template v-else>
          <span class="graph-tooltip-kind">{{ hovered.item.kind === 'structural' ? 'Structural relation' : 'Observed relation' }}</span>
          <strong>{{ relationLabel(hovered.item.relation) }}</strong>
          <p>{{ edgeName(hovered.item) }}</p>
          <code>{{ edgeAmount(hovered.item) }}</code>
          <p>{{ hovered.item.count === null ? 'Event count unavailable' : `${hovered.item.count} observed events` }}</p>
        </template>
        <button type="button" @click="pin(hovered)">Keep details <AppIcon name="arrow-right" :size="14" /></button>
      </div>
    </div>

    <div class="graph-legend" aria-label="Graph legend">
      <span><i class="legend-root" /> Assessment target</span><span><i class="legend-wallet" /> Address</span>
      <span><i class="legend-contract" /> Contract</span><span><i class="legend-token" /> Token</span>
      <span><i class="legend-pool" /> Pool</span><span><i class="legend-structural" /> Structural link</span>
    </div>
    <details class="graph-inspection" open><summary>Inspect graph</summary><div class="graph-inspect-controls">
      <label>Inspect node<select v-model="nodeChoice" @change="inspectChoice('node')"><option value="" disabled>Select a node</option><option v-for="node in scene.nodes" :key="node.id" :value="node.id">{{ nodeName(node) }} · {{ node.role }}</option></select></label>
      <label>Inspect relation<select v-model="edgeChoice" @change="inspectChoice('edge')"><option value="" disabled>Select a relation</option><option v-for="edge in scene.edges" :key="edge.id" :value="edge.id">{{ edgeName(edge) }} · {{ relationLabel(edge.relation) }} · {{ edge.id }}</option></select></label>
    </div></details>
    <section v-if="selected" class="graph-details" aria-label="Selected graph details" aria-live="polite">
      <button class="graph-details-close" type="button" aria-label="Close graph details" @click="dismiss"><AppIcon name="close" /></button>
      <template v-if="selected.kind === 'node'">
        <h3>{{ selected.item.label || shortRef(selected.item.ref) }}</h3><p class="graph-detail-ref">{{ selected.item.ref }}</p>
        <dl><div><dt>Role</dt><dd>{{ selected.item.role }}</dd></div><div><dt>Assessment</dt><dd>{{ assessment(selected.item) }}</dd></div><div><dt>Sample</dt><dd>{{ graph.sampleId }}</dd></div></dl>
      </template>
      <template v-else>
        <h3>{{ relationLabel(selected.item.relation) }}</h3><p>{{ edgeName(selected.item) }}</p>
        <dl><div><dt>Source</dt><dd>{{ nodesById.get(selected.item.source)?.ref }}</dd></div><div><dt>Target</dt><dd>{{ nodesById.get(selected.item.target)?.ref }}</dd></div><div><dt>Direction</dt><dd>Original source → target</dd></div><div><dt>Amount</dt><dd>{{ edgeAmount(selected.item) }}</dd></div><div><dt>Observed events</dt><dd>{{ selected.item.count ?? 'Not supplied' }}</dd></div><div><dt>First observed</dt><dd>{{ formatTime(selected.item.firstSeen) }}</dd></div><div><dt>Last observed</dt><dd>{{ formatTime(selected.item.lastSeen) }}</dd></div><div><dt>Relation ID</dt><dd>{{ selected.item.id }}</dd></div></dl>
      </template>
    </section>
  </div>
</template>

<style src="../../styles/transaction-graph.css"></style>
