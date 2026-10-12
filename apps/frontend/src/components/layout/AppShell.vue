<template>
  <div class="app-shell">
    <header class="app-header">
      <RouterLink to="/">Chainrisk</RouterLink>
      <nav aria-label="Main navigation">
        <RouterLink to="/">Home</RouterLink>
        <RouterLink to="/eth-scam">ETH Scam</RouterLink>
        <RouterLink to="/token-scam">Token Scam</RouterLink>
      </nav>
    </header>
    <main class="page-content"><slot /></main>
  </div>
</template>
