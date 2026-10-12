<script setup lang="ts">
import AppPanel from '@/components/ui/AppPanel.vue';
defineProps<{ title: string }>();
</script>

<template><AppPanel :title="title"><div class="panel-content"><slot /></div></AppPanel></template>
