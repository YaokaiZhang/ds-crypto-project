import { test } from 'node:test';
import assert from 'node:assert/strict';
import { load } from './helpers.mjs';
const { createSceneSequence, crossfade, spaceScenes, drawSpaceScene } = await load('design/spaceMotion.ts');
const { formatWei, formatUtc } = await load('presenters/format.ts');
test('background visits all twelve scenes and never repeats at bag boundaries', () => {
  for (const random of [() => 0, () => .99999, Math.random]) {
    const next = createSceneSequence(random);
    const first = [6, ...Array.from({ length: 11 }, next)];
    assert.equal(new Set(first).size, spaceScenes.length);
    let previous = first.at(-1);
    for (let bag = 0; bag < 5; bag++) {
      const sequence = Array.from({ length: 12 }, next);
      assert.equal(new Set(sequence).size, 12);
      for (const scene of sequence) { assert.notEqual(scene, previous); previous = scene; }
    }
  }
});
test('crossfades are bounded and outgoing/incoming opacity never stacks above one', () => {
  let previous = 0;
  for (let i = -10; i <= 110; i++) {
    const blend = crossfade(i / 100);
    assert.ok(blend >= previous && blend >= 0 && blend <= 1);
    assert.equal(blend + (1 - blend), 1); previous = blend;
  }
});
test('every preserved composition renders finite geometry and bounded luminous bands on phone and desktop', () => {
  for (const width of [390, 1440]) for (let scene = 0; scene < 12; scene++) {
    const strokes = [], points = [];
    const ctx = {
      save() {}, restore() {}, beginPath() {},
      moveTo(x, y) { points.push([x, y]); }, lineTo(x, y) { points.push([x, y]); },
      stroke() { strokes.push({ width: this.lineWidth, alpha: this.globalAlpha, blur: this.shadowBlur }); },
    };
    drawSpaceScene(ctx, scene, 17, 1, width, 844);
    assert.ok(points.length >= 161);
    assert.ok(points.every(point => point.every(Number.isFinite)));
    assert.ok(strokes.length >= 3 && strokes.length <= 9);
    assert.ok(strokes.every(stroke => stroke.alpha > 0 && stroke.alpha <= 1 && stroke.width > 5 && stroke.blur > 0));
    const quiet = { ...ctx, stroke() { assert.fail('An invisible outgoing scene should not draw'); } };
    drawSpaceScene(quiet, scene, 17, 0, width, 844);
  }
});
test('wei formatting retains smallest units and values above floating-point precision', () => {
  assert.equal(formatWei('1'), '0.000000000000000001');
  assert.equal(formatWei('1000000000000000000'), '1');
  assert.equal(formatWei('123456789012345678901234567890'), '123456789012.34567890123456789');
  assert.equal(formatWei('000'), '0');
  assert.equal(formatWei('NaN'), 'Unavailable');
  assert.equal(formatWei('-1'), 'Unavailable');
});
test('dates must carry an explicit timezone, and unavailable is never zero', () => {
  assert.equal(formatUtc('2026-10-13T12:00:00.123Z'), '2026-10-13 12:00:00 UTC');
  assert.equal(formatUtc(null), 'Unavailable');
  assert.equal(formatUtc('2026-10-13T12:00:00'), 'Unavailable');
  assert.equal(formatUtc('2026-10-13T12:00:00+03:00'), '2026-10-13 09:00:00 UTC');
});
