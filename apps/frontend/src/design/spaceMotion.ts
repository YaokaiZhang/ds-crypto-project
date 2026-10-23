export const spaceScenes = ['Orbital arc', 'Lower horizon', 'Diagonal filament', 'Polar crescent', 'Double orbit', 'Open spiral', 'Luminous sine', 'Braided ribbons', 'Long wave', 'Vertical veil', 'Offset ripple', 'Distant sweep'] as const;

/** A shuffled bag guarantees every composition appears before the bag repeats. */
export function createSceneSequence(random = Math.random, first = 6) {
  let previous = first;
  let bag = spaceScenes.map((_, index) => index).filter(index => index !== first);
  function shuffle() {
    for (let i = bag.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      [bag[i], bag[j]] = [bag[j]!, bag[i]!];
    }
    if (bag[bag.length - 1] === previous) [bag[0], bag[bag.length - 1]] = [bag[bag.length - 1]!, bag[0]!];
  }
  shuffle();
  return () => {
    if (!bag.length) { bag = spaceScenes.map((_, index) => index); shuffle(); }
    previous = bag.pop()!;
    return previous;
  };
}

export function crossfade(value: number) {
  const t = Math.max(0, Math.min(1, value));
  return t * t * (3 - 2 * t);
}

function point(id: number, u: number, lane: number, w: number, h: number, time: number) {
  const phase = time * .018;
  const angle = u * Math.PI * 2 + phase;
  switch (id) {
    case 0: return [w * (-.12 + Math.cos(angle) * .4), h * (.91 + Math.sin(angle) * .52)];
    case 1: return [w * (u * 1.2 - .1), h * (.89 - Math.sin(u * Math.PI + phase) * .12) + lane * 6];
    case 2: return [u * w, h * (1.2 - 1.4 * u + Math.sin(u * 5 + phase) * .12) + lane * 5];
    case 3: return [w * (1.1 + Math.cos(angle) * .36), h * (.48 + Math.sin(angle) * .78)];
    case 4: return [w * ((lane ? .87 : .1) + Math.cos(angle) * .3), h * (.5 + Math.sin(angle * (lane ? -1 : 1)) * .57)];
    case 5: return [w * (.88 + Math.cos(angle * 1.7) * (.05 + u * .54)), h * (.72 + Math.sin(angle * 1.7) * (.05 + u * .54))];
    case 6: return [w * (u * 1.2 - .1), h * (.72 + Math.sin(u * 7.5 - phase) * .19) + lane * 5];
    case 7: return [u * w, h * (.6 + Math.sin(u * 6.4 + phase + lane * .6) * .19)];
    case 8: return [w * (u * 1.2 - .1), h * (.53 + Math.sin(u * 6 - phase) * .3) + lane * 4];
    case 9: return [w * (.83 + Math.sin(u * 5 + phase + lane * .3) * .09) + lane * 12, h * (u * 1.4 - .2)];
    case 10: return [w * (.16 + Math.cos(angle) * (.2 + lane * .08)), h * (.9 + Math.sin(angle) * (.3 + lane * .1))];
    default: return [u * w, h * (.22 + Math.sin(u * 2 + phase) * .06) + lane * 3];
  }
}

export function drawSpaceScene(ctx: CanvasRenderingContext2D, id: number, time: number, opacity: number, width: number, height: number) {
  if (opacity < .001) return;
  ctx.save();
  const brightness = opacity * (.83 + Math.sin(time * .42) * .13 + Math.sin(time * .84) * .025);
  const band = Math.max(13, Math.min(24, width * .016)) * (1 + Math.sin(time * .42) * .035);
  const lanes = id === 4 || id === 7 ? 2 : id === 9 || id === 10 ? 3 : 1;
  ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  for (let lane = 0; lane < lanes; lane++) {
    ctx.beginPath();
    for (let i = 0; i <= 160; i++) {
      const [x, y] = point(id, i / 160, lane, width, height, time);
      if (!i) ctx.moveTo(x!, y!); else ctx.lineTo(x!, y!);
    }
    // Three soft passes give the band a continuous blue bloom and white-blue core.
    ctx.shadowColor = '#86caff';
    for (const [scale, blur, alpha, color] of [[1.65, 2.6, .3, '#68baf5'], [.95, .85, .78, '#bae6ff'], [.45, .35, .98, '#eefaff']] as const) {
      ctx.lineWidth = band * scale;
      ctx.shadowBlur = band * blur;
      ctx.globalAlpha = brightness * alpha / Math.sqrt(lanes);
      ctx.strokeStyle = color; ctx.stroke();
    }
    ctx.shadowBlur = 0;
  }
  ctx.restore();
}
