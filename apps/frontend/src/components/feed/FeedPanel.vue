<script setup lang="ts">
import { computed, ref } from 'vue';
import AppPanel from '@/components/ui/AppPanel.vue';
import AppButton from '@/components/ui/AppButton.vue';
import AppIcon from '@/components/ui/AppIcon.vue';
import { formatFeedUsd } from '@/presenters/feed';
import { useFeed } from '@/composables/useFeed';
import { formatWei, formatUtc, shortenAddress } from '@/presenters/format';
const { snapshot, connected, paused, pending, error, refresh, togglePause } = useFeed();
const inspected = ref<string | null>(null);
const statusLabel = computed(() => {
  if (paused.value) return 'Paused';
  if (pending.value) return 'Connecting';
  if (error.value) return 'Reconnecting';
  if (snapshot.value?.status === 'live') return connected.value ? 'Live · sampled' : 'Connecting';
  return { connecting: 'Waiting for collector', degraded: 'Connection interrupted', stale: 'Data out of date', recovering: 'Refreshing chain data' }[snapshot.value?.status ?? 'connecting'];
});
</script>

<template><AppPanel title="Latest Transactions" class="feed-panel" :aria-busy="pending">
  <template #actions>
    <div class="feed-actions">
    <AppButton :aria-pressed="paused" @click="togglePause">{{ paused ? 'Resume' : 'Pause' }}</AppButton>
    <AppButton :disabled="pending || paused" @click="refresh"><AppIcon name="refresh" :size="14" />{{ pending ? 'Refreshing' : 'Refresh' }}</AppButton>
    </div>
  </template>
  <div class="feed-summary"><p>Sampled Ethereum activity, straight from the chain · Amount > 0.</p><span class="status-badge" :data-feed-status="paused ? 'paused' : snapshot?.status">{{ statusLabel }}</span></div>
  <div class="feed-metadata"><span>Ethereum Mainnet · Included transactions<span v-if="snapshot?.head_block"> · Block {{ snapshot.head_block }}</span></span><span>Last update <strong>{{ formatUtc(snapshot?.updated_at ?? null) }}</strong></span></div>
  <p v-if="!paused && (error || snapshot?.status === 'stale' || snapshot?.status === 'degraded')" class="feed-error" role="status">Updates are interrupted. Showing the last received data; reconnecting automatically.</p>
  <p v-if="snapshot?.last_gap_at" class="feed-note">The collector refreshed its chain view at {{ formatUtc(snapshot.last_gap_at) }}. Some earlier samples may have been skipped or replaced.</p>
  <div class="table-container" tabindex="0" aria-label="Scrollable Ethereum transaction feed"><table><caption class="sr-only">Latest sampled Ethereum transactions</caption><thead><tr><th scope="col">Transaction</th><th scope="col">From / To</th><th scope="col">Amount · ETH</th><th scope="col">Block</th><th scope="col">Block Time · UTC</th><th scope="col">Gas Limit</th><th scope="col">Gas Used</th><th scope="col">Execution</th></tr></thead><tbody>
    <template v-for="transaction in snapshot?.transactions ?? []" :key="transaction.hash">
      <tr>
        <td><a :href="`https://etherscan.io/tx/${transaction.hash}`" target="_blank" rel="noopener noreferrer" class="mono" :title="transaction.hash">{{ shortenAddress(transaction.hash) }} <AppIcon name="external-link" :size="12" /></a><button type="button" class="feed-inspect" :aria-expanded="inspected === transaction.hash" :aria-label="`Inspect transaction ${transaction.hash}`" @click="inspected = inspected === transaction.hash ? null : transaction.hash">{{ inspected === transaction.hash ? 'Close' : 'Inspect' }}</button></td>
        <td class="address-pair"><a :href="`https://etherscan.io/address/${transaction.from_address}`" target="_blank" rel="noopener noreferrer" :title="`From: ${transaction.from_address}`">{{ shortenAddress(transaction.from_address) }}</a><a v-if="transaction.to_address" :href="`https://etherscan.io/address/${transaction.to_address}`" target="_blank" rel="noopener noreferrer" :title="`To: ${transaction.to_address}`">{{ shortenAddress(transaction.to_address) }}</a><span v-else>Contract creation</span></td>
        <td class="mono amount-cell" :title="transaction.status === 'failed' ? 'Attempted value; this transaction failed' : 'Native ETH carried by this transaction'">{{ formatWei(transaction.value_wei) }} ETH <span v-if="snapshot?.usd_quote" class="feed-usd" :title="`Current reference estimate · ${snapshot.usd_quote.source} · ${formatUtc(snapshot.usd_quote.fetched_at)}`">(≈ {{ formatFeedUsd(transaction.value_wei, snapshot.usd_quote.price) }})</span><span v-if="transaction.status === 'failed'" class="feed-attempted">Attempted</span></td>
        <td class="mono">{{ transaction.block_number }}</td><td>{{ formatUtc(transaction.block_time) }}</td><td class="mono">{{ transaction.gas_limit }}</td><td class="mono">{{ transaction.gas_used ?? 'Unavailable' }}</td><td :data-execution="transaction.status">{{ transaction.status === 'success' ? 'Success' : transaction.status === 'failed' ? 'Failed' : 'Receipt unavailable' }}</td>
      </tr>
      <tr v-if="inspected === transaction.hash" class="feed-detail"><td colspan="8"><dl>
        <div><dt>Transaction Hash</dt><dd class="mono">{{ transaction.hash }}</dd></div><div><dt>From</dt><dd class="mono">{{ transaction.from_address }}</dd></div><div><dt>To</dt><dd class="mono">{{ transaction.to_address ?? 'Contract creation' }}</dd></div>
        <div><dt>Block Hash</dt><dd class="mono">{{ transaction.block_hash }}</dd></div><div><dt>Transaction Index</dt><dd>{{ transaction.transaction_index }}</dd></div>
        <div><dt>Effective Gas Price</dt><dd>{{ transaction.effective_gas_price_wei === null ? 'Unavailable' : `${transaction.effective_gas_price_wei} Wei / gas` }}</dd></div><div><dt>Execution Fee · ETH</dt><dd>{{ transaction.execution_fee_wei === null ? 'Unavailable' : formatWei(transaction.execution_fee_wei) }}</dd></div>
      </dl><p>Included in a recent block. Inclusion is not finality. Amount is native ETH; token transfers and internal calls are outside this feed.</p></td></tr>
    </template>
  </tbody></table></div>
  <div v-if="!snapshot?.transactions.length" class="table-empty feed-empty" role="status"><AppIcon name="graph" :size="28" /><strong>{{ pending ? 'Connecting to the transaction feed' : error ? 'The feed is not available yet' : 'Waiting for Ethereum activity' }}</strong><span>{{ error ? 'The transaction service could not provide a snapshot. Refresh to try again.' : 'Newly included transactions appear here as the collector receives them.' }}</span></div>
  <p v-if="snapshot?.usd_quote" class="feed-note">USD estimates use {{ snapshot.usd_quote.source }} · Updated {{ formatUtc(snapshot.usd_quote.fetched_at) }}.</p>
  <p v-else class="feed-note">USD reference price is temporarily unavailable.</p>
  <div class="feed-footer"><span>Sampled coverage · up to two new rows per second · latest 30 rows</span><span>Transaction value is not a scam assessment.</span></div>
</AppPanel></template>
