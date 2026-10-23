<script setup lang="ts">
withDefaults(defineProps<{ label: string; tone?: 'neutral' | 'low' | 'medium' | 'high' }>(), { tone: 'neutral' });
</script>

<template><span class="status-badge" :data-tone="tone">{{ label }}</span></template>
