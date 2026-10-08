<template>
  <div class="feature">
    <div class="icon">
      <component :is="icon" size="40" color="#64d3ff" />
    </div>
    <h3>{{ title }}</h3>
    <p>{{ description }}</p>
  </div>
</template>

<script setup>
defineProps({
  title: String,
  description: String,
  icon: Object,
});
</script>

<style scoped>
.feature {
  background-color: rgba(0, 24, 72, 0.62);
  padding: 2rem;
  border-radius: 1rem;
  text-align: center;
  box-shadow: 0px 6px 12px rgba(0, 0, 0, 0.2);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.feature:hover {
  transform: translateY(-5px);
  box-shadow: 0 12px 24px rgba(0, 0, 0, 0.4);
}
.icon {
  margin-bottom: 1rem;
}
h3 {
  color: #64d3ff;
  margin-top: 0;
  font-size: 1.75rem;
}
</style>
