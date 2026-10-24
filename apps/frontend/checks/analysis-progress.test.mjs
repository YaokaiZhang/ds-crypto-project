import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const transpile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext },
}).outputText;
const asUrl = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const source = transpile('../src/presenters/analysisProgress.ts')
  .replace("'./format'", JSON.stringify(asUrl(transpile('../src/presenters/format.ts'))));
const { progressDetail } = await import(asUrl(source));
const fixture = extra => ({ state: 'running', unit: 'pages', completed: 12, total: 20,
  total_final: false, records_collected: 4182, retry_at: null, task_id: null, ...extra });

test('discovered work is not presented as a final denominator or overall percentage', () => {
  const text = progressDetail(fixture());
  assert.match(text, /12 pages completed/);
  assert.match(text, /4182 records collected/);
  assert.match(text, /discovering remaining work/);
  assert.doesNotMatch(text, /12 \/ 20|%/);
  assert.equal(progressDetail(fixture({ total: 200 })), text);
  assert.match(progressDetail(fixture({ total_final: true })), /12 \/ 20 pages completed/);
});

test('quota pauses disclose UTC resume time while queued and retrying work remain explicit', () => {
  const paused = progressDetail(fixture({ state: 'waiting_quota', retry_at: '2026-10-25T00:00:00Z' }));
  assert.match(paused, /Paused.*2026-10-25 00:00:00 UTC/);
  assert.doesNotMatch(paused, /%|discovering/);
  assert.match(progressDetail(fixture({ state: 'queued' })), /Waiting/);
  assert.match(progressDetail(fixture({ state: 'retrying' })), /Retrying/);
});

test('terminal work and demo responses never invent ongoing or percentage progress', () => {
  assert.equal(progressDetail(null), '');
  assert.equal(progressDetail(undefined), '');
  for (const state of ['completed', 'partial', 'failed']) {
    assert.doesNotMatch(progressDetail(fixture({ state })), /discovering|%/);
  }
});
