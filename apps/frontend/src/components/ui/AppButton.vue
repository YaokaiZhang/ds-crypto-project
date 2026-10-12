<script setup lang="ts">
withDefaults(defineProps<{ disabled?: boolean; variant?: 'primary' | 'secondary' }>(), {
  disabled: false,
  variant: 'secondary',
});
</script>

<template>
  <button type="button" class="app-button" :data-variant="variant" :disabled="disabled"><slot /></button>
</template>
