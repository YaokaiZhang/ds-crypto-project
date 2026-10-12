<script setup lang="ts">
defineProps<{ columns: readonly { key: string; label: string }[]; rows: readonly Record<string, unknown>[]; caption: string }>();
</script>

<template>
  <div class="table-container">
    <table>
      <caption>{{ caption }}</caption>
      <thead><tr><th v-for="column in columns" :key="column.key" scope="col">{{ column.label }}</th></tr></thead>
      <tbody><tr v-for="(row, index) in rows" :key="index"><td v-for="column in columns" :key="column.key">{{ row[column.key] }}</td></tr></tbody>
    </table>
  </div>
</template>
