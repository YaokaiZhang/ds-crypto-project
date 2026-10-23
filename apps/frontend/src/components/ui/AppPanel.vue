<script setup lang="ts">
defineProps<{ title: string }>();
</script>

<template>
  <section class="app-panel" :aria-label="title">
    <header><h2>{{ title }}</h2><slot name="actions" /></header>
    <slot />
  </section>
</template>
