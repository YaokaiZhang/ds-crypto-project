<script setup lang="ts">
import { computed, ref } from 'vue';
import TransactionGraphPanel from '../src/components/analysis/TransactionGraphPanel.vue';
import type { GraphView } from '../src/api/contracts';
import '../src/design/tokens.css';
const mode = ref('eth');
const address = (i: number) => `0x${i.toString(16).padStart(40, '0')}`;
const graph = computed<GraphView>(() => {
  const token = mode.value === 'token';
  const roles = token ? ['token', 'pool', 'pool', 'deployer', 'wallet', 'lp', 'wallet'] : ['wallet', 'contract', 'wallet', 'wallet', 'contract', 'wallet', 'wallet'];
  const names = token ? ['Example token', 'Pool A', 'Pool B', 'Deployer', 'Wallet A', 'LP address', 'Wallet B'] : ['Target address', 'Contract A', 'Wallet A', 'Wallet B', 'Contract B', 'Wallet C', 'Wallet D'];
  const nodes = Array.from({ length: 19 }, (_, i) => ({ id: `n${i}`, ref: address(i + 1), role: roles[i] ?? 'wallet', label: names[i] ?? null, is_root: i === 0, individually_assessed: false }));
  const edges = Array.from({ length: 18 }, (_, i) => {
    const target = i + 1; const parent = target <= 6 ? 0 : Math.floor((target - 7) / 2) + 1;
    const structural = token && target <= 3;
    return { id: `e${i}`, source: `n${parent}`, target: `n${target}`, direction: 'original', kind: structural ? 'structural' : 'observed', relation: structural ? 'participates' : token ? 'erc20_transfer' : i % 4 === 0 ? 'call' : 'external_eth', event_count: structural ? null : (i + 1) * 3, amount: structural || i % 4 === 0 ? null : `${i + 1}.024`, asset: token ? 'EXAMPLE' : 'ETH', first_seen: '2026-09-01T12:00:00Z', last_seen: '2026-09-28T18:00:00Z' };
  });
  edges.push({ ...edges[3], id: 'e-reverse', source: 'n4', target: 'n0' });
  edges.push({ ...edges[4], id: 'e-parallel', relation: 'internal_eth' });
  if (mode.value === 'invalid') edges[0].target = 'missing-node';
  return { sample_id: `synthetic-${token ? 'token' : 'address'}-sample`, task_id: token ? 'honeypot' : 'phishing', nodes: mode.value === 'empty' ? [] : nodes, edges: mode.value === 'empty' ? [] : edges };
});
const context = computed(() => ({ sampleId: graph.value.sample_id, taskId: graph.value.task_id, modelNodes: graph.value.nodes.length, modelEdges: graph.value.edges.length, version: 'synthetic-display-v1', window: '2026-09-01 — 2026-09-30 UTC', cutoff: '2026-09-30 00:00 UTC', sampling: 'Synthetic design fixture. No chain collection, trained model or live assessment.' }));
</script>

<template>
  <main class="graph-preview-page">
    <header class="graph-preview-header"><a href="/">Chainrisk</a><span>Component study</span></header>
    <div class="graph-preview-intro"><div><h1>Follow the connections.</h1><p>Synthetic design preview · Not a live assessment or a model result.</p></div><label>Preview state<select v-model="mode"><option value="eth">ETH graph</option><option value="token">ERC-20 graph</option><option value="empty">Empty sample</option><option value="missing">Unavailable sample</option><option value="loading">Loading</option><option value="invalid">Invalid graph</option></select></label></div>
    <TransactionGraphPanel :graph="mode === 'missing' ? null : graph" :context="context" :loading="mode === 'loading'" />
    <footer>Nodes and relations are illustrative. Animation describes presentation order only.</footer>
  </main>
</template>

<style>
* { box-sizing: border-box; }
body { margin: 0; background: #060a10; color: #e8eff8; font-family: system-ui, sans-serif; }
.graph-preview-page { max-width: 1280px; margin: auto; padding: 32px 48px; }
.graph-preview-header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 48px; }
.graph-preview-header a { font-size: 22px; color: #e8eff8; text-decoration: none; letter-spacing: -.03em; }
.graph-preview-header span { color: #abb9c9; font-size: 13px; }
.graph-preview-intro { display: flex; justify-content: space-between; align-items: end; gap: 24px; margin-bottom: 28px; }
.graph-preview-intro h1 { font-size: 34px; font-weight: 450; letter-spacing: -.035em; margin: 0 0 12px; }
.graph-preview-intro p, .graph-preview-page footer { color: #abb9c9; font-size: 13px; line-height: 1.5; }
.graph-preview-intro label { display: grid; gap: 8px; min-width: 160px; color: #abb9c9; font-size: 12px; }
.graph-preview-intro select { background: #13202d; color: #e8eff8; padding: 10px; border: 1px solid #718197; border-radius: 8px; font: inherit; }
.graph-preview-page footer { padding-top: 20px; }
@media (max-width: 640px) { .graph-preview-page { padding: 24px 16px; } .graph-preview-header { padding-bottom: 32px; } .graph-preview-intro { display: block; } .graph-preview-intro h1 { font-size: 28px; } .graph-preview-intro label { margin-top: 20px; } }
</style>
