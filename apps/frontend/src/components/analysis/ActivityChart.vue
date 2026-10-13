<script setup lang="ts">
import { computed, ref } from 'vue';
const props = defineProps<{ title: string; dates: string[]; series: { label: string; values: (number | null)[]; display: string[] }[]; unit: string }>();
const index = ref<number | null>(null);
const selected = computed(() => Math.min(index.value ?? props.dates.length - 1, props.dates.length - 1));
const max = computed(() => Math.max(1, ...props.series.flatMap(line => line.values.filter((value): value is number => value !== null))));
const x = (i: number) => 30 + i / Math.max(1, props.dates.length - 1) * 300;
const y = (value: number) => 136 - value / max.value * 110;
const paths = computed(() => props.series.map(line => {
  let drawing = false;
  return line.values.map((value, i) => {
    if (value === null) { drawing = false; return ''; }
    const segment = `${drawing ? 'L' : 'M'}${x(i).toFixed(2)},${y(value).toFixed(2)}`;
    drawing = true; return segment;
  }).join(' ');
}));
function hover(event: PointerEvent) {
  const element = event.currentTarget as SVGSVGElement;
  const bounds = element.getBoundingClientRect();
  index.value = Math.max(0, Math.min(props.dates.length - 1, Math.round(((event.clientX - bounds.left) / bounds.width * 360 - 30) / 300 * (props.dates.length - 1))));
}
function key(event: KeyboardEvent) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
  event.preventDefault(); index.value = Math.max(0, Math.min(props.dates.length - 1, selected.value + (event.key === 'ArrowLeft' ? -1 : 1)));
}
</script>
<template><div class="activity-plot"><h3>{{ title }}</h3><div class="plot-legend"><span v-for="line in series" :key="line.label">{{ line.label }}</span></div><svg class="activity-svg" viewBox="0 0 360 174" role="img" :aria-label="`${title}, ${dates.length} daily intervals. Use arrow keys to inspect dates.`" tabindex="0" @pointermove="hover" @keydown="key"><title>{{ title }}</title><line v-for="height in [26, 81, 136]" :key="height" x1="30" x2="330" :y1="height" :y2="height" class="chart-grid" /><text x="28" y="17" class="chart-axis">{{ max.toLocaleString('en-US', { maximumFractionDigits: 2 }) }} {{ unit }}</text><path v-for="(path, i) in paths" :key="i" :d="path" class="activity-line" :data-line="i" /><line v-if="selected >= 0" :x1="x(selected)" :x2="x(selected)" y1="26" y2="136" class="chart-crosshair" /><circle v-for="(line, i) in series" v-show="line.values[selected] != null" :key="line.label" :cx="x(selected)" :cy="y(line.values[selected] || 0)" r="3" class="activity-point" :data-line="i" /><text x="30" y="161" class="chart-axis">{{ dates[0]?.slice(5) }}</text><text x="330" y="161" text-anchor="end" class="chart-axis">{{ dates[dates.length - 1]?.slice(5) }}</text></svg><div class="chart-readout" aria-live="polite"><strong>{{ dates[selected] }} UTC</strong><span v-for="line in series" :key="line.label">{{ line.label }} <b>{{ line.display[selected] || 'Unavailable' }}</b></span></div></div></template>
