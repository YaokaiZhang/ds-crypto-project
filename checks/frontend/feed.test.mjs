import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './helpers.mjs';
const { readFeedSnapshot, appendFeedTransaction, readFeedMeta, formatFeedUsd } = await load('presenters/feed.ts');
const hash = i => `0x${i.toString(16).padStart(64, '0')}`;
const row = i => ({ hash: hash(i), block_hash: hash(999), from_address: `0x${'11'.repeat(20)}`, to_address: null,
  block_number: 100, transaction_index: i, block_time: '2026-10-13T10:00:00Z',
  value_wei: '100000000000000000001', gas_limit: '90000', gas_used: null,
  effective_gas_price_wei: null, execution_fee_wei: null, status: null });
const meta = seq => ({ sequence: seq, status: 'live', updated_at: '2026-10-13T10:00:00Z', checked_at: '2026-10-13T10:00:00Z',
  head_block: 100, head_time: '2026-10-13T10:00:00Z', last_gap_at: null, source: 'Ethereum Mainnet RPC', message: null });

test('feed preserves exact quantities, contract creation and unknown receipt fields', () => {
  const snapshot = readFeedSnapshot({ ...meta(1), transactions: [row(1)] });
  assert.equal(snapshot.transactions[0].value_wei, '100000000000000000001');
  assert.equal(snapshot.transactions[0].to_address, null);
  assert.equal(snapshot.transactions[0].gas_used, null);
});
test('SSE duplicate and out-of-order delivery cannot add or repeat rows', () => {
  const original = readFeedSnapshot({ ...meta(10), transactions: [row(10)] });
  assert.equal(appendFeedTransaction(original, { meta: meta(9), transaction: row(9) }), original);
  assert.equal(appendFeedTransaction(original, { meta: meta(10), transaction: row(10) }), original);
  const next = appendFeedTransaction(original, { meta: meta(11), transaction: row(10) });
  assert.equal(next.transactions.length, 1); assert.equal(next.sequence, 11);
  assert.equal(original.sequence, 10);
});
test('updates cap visible rows at 30; authoritative reset removes orphan records', () => {
  let snapshot = readFeedSnapshot({ ...meta(0), transactions: [] });
  for (let i = 1; i < 50; i++) snapshot = appendFeedTransaction(snapshot, { meta: meta(i), transaction: row(i) });
  assert.equal(snapshot.transactions.length, 30);
  assert.equal(snapshot.transactions[0].hash, hash(49));
  snapshot = readFeedSnapshot({ ...meta(50), transactions: [row(1)] });
  assert.equal(snapshot.transactions.length, 1); assert.equal(snapshot.transactions[0].hash, hash(1));
});
test('invalid amounts, addresses, timestamps, states and duplicate hashes fail validation', () => {
  for (const mutate of [s => s.transactions[0].value_wei = 0.1, s => s.transactions[0].gas_used = '-1',
    s => s.transactions[0].from_address = 'javascript:alert(1)', s => s.transactions[0].block_time = '2026-10-13',
    s => s.sequence = -1, s => s.transactions.push(s.transactions[0])]) {
    const snapshot = { ...meta(1), transactions: [row(1)] }; mutate(snapshot);
    assert.throws(() => readFeedSnapshot(snapshot));
  }
  assert.throws(() => readFeedMeta({ ...meta(1), status: 'finalized' }));
});

test('zero ETH rows are omitted from snapshots and old incremental delivery', () => {
  const snapshot = readFeedSnapshot({ ...meta(1), transactions: [{ ...row(1), value_wei: '0' }, row(2)] });
  assert.equal(snapshot.transactions.length, 1);
  const next = appendFeedTransaction(snapshot, { meta: meta(2), transaction: { ...row(3), value_wei: '0' } });
  assert.equal(next.transactions.length, 1); assert.equal(next.sequence, 2);
});
test('USD estimates round to cents without loss of wei precision or tiny amounts', () => {
  assert.equal(formatFeedUsd('50000000000000000', '2493.055'), '$124.65');
  assert.equal(formatFeedUsd('1000000000000000000', '2493.055'), '$2,493.06');
  assert.equal(formatFeedUsd('1', '2493.055'), '<$0.01');
  assert.equal(formatFeedUsd('9007199254740993123456789', '2000'), '$18,014,398,509.48');
  assert.equal(formatFeedUsd('bad', '2000'), 'Unavailable');
  assert.throws(() => readFeedMeta({ ...meta(1), usd_quote: { price: 'NaN', source: 'Coinbase spot', fetched_at: '2026-10-13T10:00:00Z' } }));
});
