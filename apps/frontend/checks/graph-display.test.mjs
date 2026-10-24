import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/presenters/graphDisplay.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
const { readDisplayGraph, layoutGraph, edgeAmount, graphRenderKey } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const fixture = () => ({ sample_id: 'sample-1', task_id: 'phishing', nodes: [
  { id: 'root', ref: 'root-reference', is_root: true }, { id: 'other', ref: 'other-reference', role: 'wallet' },
], edges: [{ id: 'edge', source: 'root', target: 'other', relation: 'external_eth', kind: 'observed', direction: 'original', amount: '12345678901234567890.000001', asset: 'ETH' }] });

test('progress and model provenance updates do not change the graph render identity', () => {
  const input = fixture();
  const key = graphRenderKey(input);
  assert.equal(graphRenderKey(structuredClone(input)), key);
  assert.equal(graphRenderKey({ ...input, context: { model_nodes: 512, model_edges: 4096 } }), key);
  assert.notEqual(graphRenderKey({ ...input, sample_id: 'another-sample' }), key);
  assert.notEqual(graphRenderKey({ ...input, edges: [] }), key);
  assert.equal(graphRenderKey(null), '');
});

test('sample identity, original direction and exact amounts survive layout without mutation', () => {
  const input = fixture(); const before = structuredClone(input);
  const graph = readDisplayGraph(input); const scene = layoutGraph(graph);
  assert.equal(graph.sampleId, input.sample_id); assert.equal(graph.taskId, input.task_id);
  assert.equal(scene.edges[0].source, 'root'); assert.equal(scene.edges[0].target, 'other');
  assert.equal(edgeAmount(scene.edges[0]), '12345678901234567890.000001 ETH');
  assert.deepEqual(input, before); assert.deepEqual(layoutGraph(graph), scene);
});
test('invalid direction, duplicate identity, missing root and dangling endpoints fail closed', () => {
  for (const mutate of [g => g.edges[0].direction = 'reverse', g => g.nodes.push(g.nodes[0]), g => g.nodes[0].is_root = false, g => g.edges[0].target = 'absent', g => g.edges.push(g.edges[0])]) {
    const graph = fixture(); mutate(graph); assert.throws(() => readDisplayGraph(graph));
  }
});
test('unknown metadata stays unknown; log attributes never become readable amounts', () => {
  const input = fixture(); delete input.edges[0].amount; input.edges[0].log_amount = 8;
  input.edges[0].event_count = -1; input.edges[0].first_seen = 'yesterday'; input.nodes[1].role = 'unverified-role';
  const graph = readDisplayGraph(input);
  assert.equal(graph.edges[0].amount, null); assert.equal(graph.edges[0].count, null);
  assert.equal(graph.edges[0].firstSeen, null); assert.equal(graph.nodes[1].role, 'unknown');
  assert.equal(graph.nodes[1].assessed, null); assert.equal(edgeAmount(graph.edges[0]), 'Amount unavailable');
});
test('parallel edges, reverse edges, loops and disconnected nodes remain separately inspectable', () => {
  const input = fixture(); input.nodes.push({ id: 'isolated', ref: 'isolated' });
  input.edges.push({ ...input.edges[0], id: 'parallel' }, { ...input.edges[0], id: 'reverse', source: 'other', target: 'root' }, { ...input.edges[0], id: 'loop', target: 'root' });
  const scene = layoutGraph(readDisplayGraph(input));
  assert.equal(scene.nodes.length, 3); assert.equal(scene.edges.length, 4);
  assert.equal(new Set(scene.edges.map(e => e.path)).size, 4);
  assert.ok(scene.nodes.every(n => Number.isFinite(n.x) && Number.isFinite(n.y)));
});
test('structural participation is never presented as a monetary transfer', () => {
  const input = fixture(); input.edges[0].kind = 'structural'; input.edges[0].relation = 'participates';
  assert.equal(edgeAmount(readDisplayGraph(input).edges[0]), 'Not a transfer');
});
test('Fit bounds contain self-loops and large parallel bundles, including control geometry', () => {
  const input = fixture();
  input.edges = Array.from({ length: 50 }, (_, i) => ({ ...input.edges[0], id: `curve-${i}`, target: i < 10 ? 'root' : 'other' }));
  const scene = layoutGraph(readDisplayGraph(input));
  for (const edge of scene.edges) {
    const values = edge.path.match(/-?(?:\d*\.?\d+)(?:e[+-]?\d+)?/gi).map(Number);
    for (let i = 0; i < values.length; i += 2) {
      assert.ok(values[i] >= scene.minX && values[i] <= scene.minX + scene.width);
      assert.ok(values[i + 1] >= scene.minY && values[i + 1] <= scene.minY + scene.height);
    }
  }
  assert.ok(scene.minY < 0, 'Repeated loops expand the original top bound');
});
test('empty samples and documented density retain all supplied records', () => {
  assert.equal(layoutGraph(readDisplayGraph({ ...fixture(), nodes: [], edges: [] })).nodes.length, 0);
  const input = fixture();
  input.nodes = Array.from({ length: 64 }, (_, i) => ({ id: `n${i}`, ref: `reference-${i}`, is_root: i === 0 }));
  input.edges = Array.from({ length: 4096 }, (_, i) => ({ id: `e${i}`, source: `n${i % 64}`, target: `n${(i * 7 + 1) % 64}`, relation: 'call', kind: 'observed', direction: 'original' }));
  const scene = layoutGraph(readDisplayGraph(input));
  assert.equal(scene.nodes.length, 64); assert.equal(scene.edges.length, 4096);
  assert.ok(scene.edges.every(e => !/NaN|Infinity/.test(e.path)));
});

test('oversized legacy results are rejected before layout instead of freezing the page', () => {
  for (const count of [65, 512, 4001]) {
    const input = fixture();
    input.nodes = Array.from({ length: count }, (_, i) => ({ id: `n${i}`, ref: `reference-${i}`, is_root: i === 0 }));
    assert.throws(() => readDisplayGraph(input), /display limit.*new analysis/);
  }
  const input = fixture();
  input.edges = Array.from({ length: 4097 }, (_, i) => ({ ...input.edges[0], id: `edge-${i}` }));
  assert.throws(() => readDisplayGraph(input), /display limit/);
});

test('layout remains stable when API record order changes and supports irregular branches', () => {
  const input = fixture();
  input.nodes.push(...Array.from({ length: 12 }, (_, i) => ({ id: `branch-${i}`, ref: `wallet-${i}`, role: 'wallet' })));
  input.edges.push(...Array.from({ length: 12 }, (_, i) => ({ ...input.edges[0], id: `branch-edge-${i}`, source: i < 4 ? 'root' : `branch-${i % 4}`, target: `branch-${i}` })));
  const scene = layoutGraph(readDisplayGraph(input));
  const shuffled = { ...input, nodes: [...input.nodes].reverse(), edges: [...input.edges].reverse() };
  assert.deepEqual(layoutGraph(readDisplayGraph(shuffled)).nodes, scene.nodes);
  const root = scene.nodes.find(node => node.root);
  const distances = scene.nodes.filter(node => node.depth === 1).map(node => Math.hypot(node.x - root.x, node.y - root.y));
  assert.ok(Math.max(...distances) - Math.min(...distances) > 20, 'Neighbors are not forced onto an equal-radius ring');
});
