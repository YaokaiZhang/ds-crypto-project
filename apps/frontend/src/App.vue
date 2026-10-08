<template>
  <div id="app">
    <Header />
    <RouterView />
    <Footer />
  </div>
</template>

<script setup lang="ts">
import Header from './components/Header.vue';
import Footer from './components/Footer.vue';
</script>

<style scoped>
#app {
  text-align: center;
  margin-top: 60px;
}
</style>
