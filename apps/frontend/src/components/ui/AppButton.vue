<script setup lang="ts">
withDefaults(defineProps<{ disabled?: boolean; variant?: 'primary' | 'secondary'; type?: 'button' | 'submit' }>(), {
  disabled: false,
  variant: 'secondary',
  type: 'button',
});
</script>

<template>
  <button :type="type" class="app-button" :data-variant="variant" :disabled="disabled"><slot /></button>
</template>
