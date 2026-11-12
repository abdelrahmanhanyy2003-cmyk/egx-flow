/** Colour lookup tables for liquidity intensity (0..255) -> packed RGBA (little-endian ABGR). */

type Stop = [number, [number, number, number]];

const PALETTES: Record<string, Stop[]> = {
  // navy -> blue -> cyan -> yellow -> orange -> red -> near-white
  classic: [
    [0.0, [5, 11, 22]],
    [0.06, [8, 30, 70]],
    [0.18, [10, 80, 160]],
    [0.32, [20, 170, 220]],
    [0.48, [120, 220, 200]],
    [0.6, [245, 225, 70]],
    [0.75, [250, 150, 30]],
    [0.88, [240, 60, 30]],
    [1.0, [255, 235, 225]],
  ],
  thermal: [
    [0.0, [5, 11, 22]],
    [0.15, [40, 10, 90]],
    [0.35, [150, 20, 120]],
    [0.55, [235, 80, 60]],
    [0.75, [250, 180, 40]],
    [1.0, [255, 255, 220]],
  ],
  mono: [
    [0.0, [5, 11, 22]],
    [0.4, [40, 90, 140]],
    [1.0, [230, 245, 255]],
  ],
};

export const BG_RGB: [number, number, number] = [5, 11, 22];

export function buildLut(name: string): Uint32Array {
  const stops = PALETTES[name] ?? PALETTES.classic;
  const lut = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    const v = i / 255;
    let k = 0;
    while (k < stops.length - 2 && v > stops[k + 1][0]) k++;
    const [p0, c0] = stops[k];
    const [p1, c1] = stops[k + 1];
    const f = p1 === p0 ? 0 : Math.min(1, Math.max(0, (v - p0) / (p1 - p0)));
    const r = Math.round(c0[0] + (c1[0] - c0[0]) * f);
    const g = Math.round(c0[1] + (c1[1] - c0[1]) * f);
    const b = Math.round(c0[2] + (c1[2] - c0[2]) * f);
    lut[i] = ((255 << 24) | (b << 16) | (g << 8) | r) >>> 0;
  }
  return lut;
}

export const BG_PIXEL = ((255 << 24) | (BG_RGB[2] << 16) | (BG_RGB[1] << 8) | BG_RGB[0]) >>> 0;
