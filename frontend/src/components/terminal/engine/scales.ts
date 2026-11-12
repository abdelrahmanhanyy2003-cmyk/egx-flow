/** Axis step helpers (pure; unit-tested). */

export function niceStep(raw: number): number {
  if (!(raw > 0) || !isFinite(raw)) return 1;
  const exp = Math.floor(Math.log10(raw));
  const f = raw / 10 ** exp;
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nf * 10 ** exp;
}

/** Price label step: a multiple of the tick giving at least `minPx` between labels. */
export function priceStep(tick: number, pxPerTick: number, minPx: number): number {
  const ticksNeeded = Math.max(1, minPx / Math.max(1e-6, pxPerTick));
  const mult = niceStep(ticksNeeded);
  return Math.max(tick, Math.round(mult) * tick || tick);
}

const TIME_STEPS = [1e3, 2e3, 5e3, 10e3, 15e3, 30e3, 60e3, 120e3, 300e3, 600e3, 900e3, 1800e3, 3600e3, 7200e3];

export function timeStep(msPerPx: number, minPx: number): number {
  const need = msPerPx * minPx;
  for (const s of TIME_STEPS) if (s >= need) return s;
  return TIME_STEPS[TIME_STEPS.length - 1];
}
