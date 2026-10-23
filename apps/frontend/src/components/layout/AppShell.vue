<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import SpaceBackdrop from './SpaceBackdrop.vue';
const route = useRoute();
const home = computed(() => route.name === 'home');
</script>
<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">Skip to content</a>
    <SpaceBackdrop :quiet="!home" />
    <header class="app-header">
      <RouterLink to="/" class="brand" aria-label="Chainrisk home">Chainrisk<span class="brand-period">.</span></RouterLink>
      <nav aria-label="Main navigation">
        <RouterLink to="/forecast">Forecast</RouterLink>
        <RouterLink to="/eth-scam">ETH</RouterLink>
        <RouterLink to="/token-scam">ERC-20</RouterLink>
      </nav>
      <div class="header-tools"><span class="network-label">Ethereum mainnet</span></div>
    </header>
    <main id="main-content" class="page-content" :class="{ 'is-home': home }" tabindex="-1"><slot /></main>
    <footer class="app-footer"><span>Chainrisk <span class="muted">/ Evidence before conclusions.</span></span><span class="muted">Ethereum mainnet</span></footer>
  </div>
</template>
