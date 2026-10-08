<template>
  <header>
    <router-link to="/" class="logo">TrxLLM</router-link>
    <nav>
      <router-link to="/trade-identification" active-class="active-nav">交易甄别</router-link>
      <router-link to="/address-detection" active-class="active-nav">地址检测</router-link>
      <router-link to="/real-time-data" active-class="active-nav">实时数据</router-link>
    </nav>
  </header>
</template>

<script setup>
</script>

<style scoped>
header {
  background-color: rgba(0, 24, 72, 0.8);
  backdrop-filter: blur(8px);
  padding: 1.5rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.logo {
  font-size: 2rem;
  font-weight: bold;
  color: #64d3ff;
  text-decoration: none;
  transition: text-decoration 0.3s ease, transform 0.2s ease;
}

.logo:hover {
  transform: translateY(-2px);
}

nav a {
  color: #f0f4f8;
  text-decoration: none;
  margin-left: 1rem;
  padding: 0.75rem 1.25rem;
  border-radius: 10px;
  transition: background-color 0.3s ease, transform 0.2s ease;
  font-weight: 500;
}

nav a:hover {
  background-color: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
}

.active-nav {
  font-weight: bold;
  background-color: rgba(255, 255, 255, 0.055);
  color: #fff;
}
</style>
