import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const transpile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText;
const asUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const source = transpile('../src/presenters/ledgerAmounts.ts')
  .replace("'./format'", JSON.stringify(asUrl(transpile('../src/presenters/format.ts'))));
const { ledgerAmounts } = await import(asUrl(source));
const row = extra => ({ category: 'external', value_raw: '0', decimals: 18, asset: 'ETH', status: 'success', amounts: [], ...extra });

test('unidentified zero-native transactions say Unknown while positive wei stays exact', () => {
  assert.equal(ledgerAmounts(row())[0].text, 'Unknown');
  assert.equal(ledgerAmounts(row({ value_raw: '1' }))[0].text, '0.000000000000000001 ETH');
  assert.equal(ledgerAmounts(row({ category: 'internal' }))[0].text, '0 ETH');
});

test('token and mixed-asset amounts retain precision, direction and contract identity', () => {
  const tokens = [
    { asset: 'USDT', raw: '3000001', decimals: 6, contract_address: '0x111', direction: 'outgoing' },
    { asset: 'USDT', raw: '500', decimals: 6, contract_address: '0x222', direction: 'incoming' },
  ];
  const values = ledgerAmounts(row({ value_raw: '1', amounts: tokens }));
  assert.deepEqual(values.map(v => v.text), ['0.000000000000000001 ETH', '3.000001 USDT (outgoing)', '0.0005 USDT (incoming)']);
  assert.equal(values[1].title, '0x111');
  assert.equal(values[2].title, '0x222');
  assert.equal(ledgerAmounts(row({ amounts: tokens, status: 'failed' }))[0].text, 'Unknown');
});

test('missing or invalid units never invent a token quantity', () => {
  assert.equal(ledgerAmounts(row({ amounts: [{ asset: 'USDT', raw: '100', decimals: -1 }] }))[0].text, 'Unknown');
});
