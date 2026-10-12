<script setup lang="ts">
withDefaults(defineProps<{ label: string; modelValue?: string; placeholder?: string; disabled?: boolean }>(), {
  modelValue: '', placeholder: '', disabled: false,
});
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
function update(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).value);
}
</script>

<template>
  <label class="app-field">
    <span>{{ label }}</span>
    <input :value="modelValue" :placeholder="placeholder" :disabled="disabled" @input="update" />
  </label>
</template>
