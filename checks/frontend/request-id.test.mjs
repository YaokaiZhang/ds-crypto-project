import { test } from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { load } from './helpers.mjs';

const { createRequestId } = await load('api/requestId.ts');
const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test('secure contexts can use their native UUID implementation', () => {
  const source = {
    randomUUID() { return 'native-request-id'; },
    getRandomValues() { assert.fail('Native UUID must not consume fallback entropy'); },
  };
  assert.equal(createRequestId(source), 'native-request-id');
});

test('HTTP contexts without randomUUID produce RFC UUID v4 identifiers', () => {
  const source = { getRandomValues(bytes) { assert.equal(bytes.length, 16); return bytes.fill(255); } };
  assert.equal(createRequestId(source), 'ffffffff-ffff-4fff-bfff-ffffffffffff');
  assert.match(createRequestId(source), uuidV4);
});

test('HTTP fallback uses fresh cryptographic randomness for every request', () => {
  const source = { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) };
  const ids = Array.from({ length: 100 }, () => createRequestId(source));
  assert.equal(new Set(ids).size, ids.length);
  assert.ok(ids.every(id => uuidV4.test(id)));
});

test('a missing randomness source fails explicitly instead of inventing weak IDs', () => {
  assert.throws(() => createRequestId(null), /cannot generate request identifiers/);
});
