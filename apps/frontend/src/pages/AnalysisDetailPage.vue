<script setup lang="ts">
import { useRoute } from 'vue-router';
const route = useRoute();
</script>

<template><h1>Analysis</h1><p class="muted">{{ route.params.id }}</p><div aria-label="Analysis result"><slot /></div></template>
