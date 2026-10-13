<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { createSceneSequence, crossfade, drawSpaceScene } from '@/design/spaceMotion';
import { imageFadeMs, imageHoldMs, spaceImages } from '@/design/spaceImages';
const props = defineProps<{ quiet: boolean }>();
const canvas = ref<HTMLCanvasElement>();
const reduced = ref(false), photoIndex = ref(0), photoBlend = ref(0);
const ready = new Set<number>(), failed = reactive(new Set<number>());
const nextScene = createSceneSequence(Math.random, 0);
let current = 0, next = nextScene(), elapsed = 0, sceneTime = 0, photoTime = 0;
let last = 0, rendered = 0, frame = 0, maskFrame = 0, width = 0, height = 0;
let media: MediaQueryList, readingMask: HTMLCanvasElement, observer: ResizeObserver | undefined;
const duration = 40000, blendDuration = 10000;
function nextPhoto(index: number) {
  for (let offset = 1; offset < spaceImages.length; offset++) {
    const candidate = (index + offset) % spaceImages.length;
    if (!failed.has(candidate)) return candidate;
  }
  return index;
}
const slides = computed(() => {
  const index = photoIndex.value, nextIndex = nextPhoto(index);
  const active = [{ index, photo: spaceImages[index]!, opacity: 1 - photoBlend.value }];
  if (!reduced.value && nextIndex !== index) active.push({ index: nextIndex, photo: spaceImages[nextIndex]!, opacity: photoBlend.value });
  return active.filter(slide => !failed.has(slide.index));
});
function imageError(index: number) {
  failed.add(index);
  if (photoIndex.value === index) photoIndex.value = nextPhoto(index);
  photoTime = 0; photoBlend.value = 0;
}
async function imageLoaded(index: number, event: Event) {
  try { await (event.target as HTMLImageElement).decode(); ready.add(index); }
  catch { imageError(index); }
}
function measureReadingZones() {
  maskFrame = 0;
  if (!readingMask) return;
  readingMask.width = width; readingMask.height = height;
  const ctx = readingMask.getContext('2d');
  if (!ctx) return;
  // Keep the landing hero on a continuous background; only shared chrome and page headings attenuate bands.
  ctx.fillStyle = 'rgba(0,0,0,.94)'; ctx.filter = 'blur(22px)';
  for (const element of document.querySelectorAll('.page-heading, .app-header')) {
    const box = element.getBoundingClientRect();
    if (box.bottom < 0 || box.top > height) continue;
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    let node: Node | null;
    while ((node = walker.nextNode())) {
      if (!node.textContent?.trim()) continue;
      const range = document.createRange(); range.selectNodeContents(node);
      for (const rect of range.getClientRects()) ctx.fillRect(rect.left - 16, rect.top - 12, rect.width + 32, rect.height + 24);
    }
  }
}
function queueMask() { cancelAnimationFrame(maskFrame); maskFrame = requestAnimationFrame(measureReadingZones); }
function draw() {
  const ctx = canvas.value?.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, width, height);
  const blend = reduced.value ? 0 : crossfade((sceneTime - duration + blendDuration) / blendDuration);
  drawSpaceScene(ctx, reduced.value ? 0 : current, reduced.value ? 0 : elapsed / 1000, 1 - blend, width, height);
  if (blend) drawSpaceScene(ctx, next, elapsed / 1000, blend, width, height);
  if (readingMask) {
    ctx.save(); ctx.globalCompositeOperation = 'destination-out';
    ctx.drawImage(readingMask, 0, 0, width, height); ctx.restore();
  }
}
function tick(now: number) {
  const delta = last ? Math.min(now - last, 100) : 0; last = now;
  elapsed += delta; sceneTime += delta;
  if (sceneTime >= duration) { sceneTime -= duration; current = next; next = nextScene(); }
  if (ready.has(photoIndex.value)) photoTime += delta;
  const upcoming = nextPhoto(photoIndex.value);
  if (upcoming === photoIndex.value) photoTime = 0;
  // Hold the decoded image if the next asset is delayed; never fade to an unloaded frame.
  if (!ready.has(upcoming)) photoTime = Math.min(photoTime, imageHoldMs);
  if (photoTime >= imageHoldMs + imageFadeMs) {
    photoTime -= imageHoldMs + imageFadeMs; photoBlend.value = 0; photoIndex.value = upcoming;
  }
  if (now - rendered > (width < 640 ? 50 : 33)) {
    photoBlend.value = crossfade((photoTime - imageHoldMs) / imageFadeMs);
    draw(); rendered = now;
  }
  frame = requestAnimationFrame(tick);
}
function schedule() {
  cancelAnimationFrame(frame); last = 0; draw();
  if (!reduced.value && !document.hidden) frame = requestAnimationFrame(tick);
}
function resize() {
  if (!canvas.value) return;
  width = innerWidth; height = innerHeight;
  const ratio = Math.min(devicePixelRatio || 1, 1.5);
  canvas.value.width = Math.round(width * ratio); canvas.value.height = Math.round(height * ratio);
  canvas.value.getContext('2d')?.setTransform(ratio, 0, 0, ratio, 0, 0);
  measureReadingZones(); draw();
}
function preference() {
  reduced.value = media.matches;
  if (reduced.value) { photoTime = 0; photoBlend.value = 0; }
  schedule();
}
watch(() => props.quiet, async () => { await nextTick(); queueMask(); }, { flush: 'post' });
onMounted(() => {
  readingMask = document.createElement('canvas');
  media = matchMedia('(prefers-reduced-motion: reduce)'); media.addEventListener('change', preference);
  window.addEventListener('resize', resize); window.addEventListener('scroll', queueMask, { passive: true });
  document.addEventListener('visibilitychange', schedule);
  const main = document.querySelector('#main-content');
  if (main) { observer = new ResizeObserver(queueMask); observer.observe(main); }
  resize(); preference();
});
onUnmounted(() => {
  cancelAnimationFrame(frame); cancelAnimationFrame(maskFrame); observer?.disconnect();
  media?.removeEventListener('change', preference); window.removeEventListener('resize', resize);
  window.removeEventListener('scroll', queueMask); document.removeEventListener('visibilitychange', schedule);
});
</script>
<template>
  <div class="space-backdrop" :class="{ quiet }" aria-hidden="true">
    <div class="starfield-layer"><img v-for="slide in slides" :key="slide.index" :src="slide.photo.src" alt="" decoding="async" :fetchpriority="slide.index === 0 ? 'high' : 'low'" :style="{ opacity: slide.opacity, objectPosition: slide.photo.position }" @load="imageLoaded(slide.index, $event)" @error="imageError(slide.index)" /></div>
    <div class="space-veil"></div><canvas ref="canvas" />
  </div>
</template>
<style scoped>
.space-backdrop { position: fixed; inset: 0; z-index: -1; pointer-events: none; background: #030609; overflow: hidden; }
.starfield-layer, .starfield-layer img, .space-veil, canvas { position: absolute; inset: 0; width: 100%; height: 100%; }
.starfield-layer { opacity: .72; transition: opacity 900ms ease; }
.starfield-layer img { object-fit: cover; filter: grayscale(1) brightness(.9) contrast(1.12); }
.space-veil { background: linear-gradient(180deg, rgb(3 6 9 / 30%), rgb(3 6 9 / 8%) 48%, rgb(3 6 9 / 35%)), linear-gradient(90deg, rgb(3 6 9 / 12%), transparent 55%); }
canvas { opacity: .96; transition: opacity 900ms ease; }
.quiet canvas { opacity: .58; }
.quiet .starfield-layer { opacity: .55; }
@media (prefers-reduced-motion: reduce) { canvas, .starfield-layer { transition: none; } }
</style>
