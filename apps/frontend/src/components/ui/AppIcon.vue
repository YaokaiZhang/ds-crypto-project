<script setup lang="ts">
import { computed } from 'vue';
import { iconRegistry, type IconName } from '@/design/icons';
const props = withDefaults(defineProps<{ name: IconName; label?: string; size?: number }>(), { size: 18 });
const icon = computed(() => iconRegistry[props.name]);
</script>

<template>
  <component :is="icon" :size="size" :aria-hidden="label ? undefined : true" :aria-label="label" :role="label ? 'img' : undefined" />
</template>
