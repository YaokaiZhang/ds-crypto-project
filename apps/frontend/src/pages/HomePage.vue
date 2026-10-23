<script setup lang="ts">
import FeedPanel from '@/components/feed/FeedPanel.vue';
import AppIcon from '@/components/ui/AppIcon.vue';
</script>

<template>
  <section class="home-intro" aria-label="Ethereum overview">
    <h1>Ethereum,<br /><span>in perspective.</span></h1>
    <div class="home-intro-copy"><p>Follow the activity.<br />Understand the evidence.</p><p class="muted">Explore Ethereum transactions and inspect the signals behind an address or token.</p><div class="hero-actions"><RouterLink class="app-button" data-variant="primary" to="/eth-scam">Explore ETH <AppIcon name="arrow-right" :size="16" /></RouterLink><RouterLink class="app-button" to="/token-scam">Explore ERC-20 <AppIcon name="arrow-right" :size="16" /></RouterLink></div></div>
  </section>
  <FeedPanel />
</template>
