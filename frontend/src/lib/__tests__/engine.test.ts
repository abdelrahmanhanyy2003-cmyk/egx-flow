import { describe, expect, it } from "vitest";
import { niceStep, priceStep, timeStep } from "../../components/terminal/engine/scales";
import { buildLut, BG_PIXEL } from "../../components/terminal/engine/palette";
import { Series } from "../series";

describe("axis scales", () => {
  it("nice steps", () => {
    expect(niceStep(0.7)).toBe(1);
    expect(niceStep(3)).toBe(5);
    expect(niceStep(17)).toBe(20);
    expect(niceStep(0)).toBe(1);
  });
  it("price labels are multiples of the tick and >= min spacing", () => {
    const s = priceStep(0.01, 2, 20); // need 10 ticks
    expect(Math.round(s / 0.01)).toBe(10);
    expect(priceStep(0.01, 50, 20)).toBeCloseTo(0.01);
  });
  it("time steps cover the requested pixel spacing", () => {
    expect(timeStep(100, 80)).toBe(10_000);
    expect(timeStep(1, 80)).toBe(1_000);
  });
});

describe("palette", () => {
  it("builds an opaque 256-entry LUT starting at the background", () => {
    const lut = buildLut("classic");
    expect(lut.length).toBe(256);
    expect(lut[0]).toBe(BG_PIXEL);
    expect(lut[255] >>> 24).toBe(255);
  });
});

describe("Series store", () => {
  const snap = {
    symbol: "COMI",
    instrument: { symbol: "COMI", name: "CIB", exchange: "EGX", currency: "EGP", tick_size: 0.01, tick_size_source: "x", sector: "Banks" },
    stats: null as any,
    columns: [[1000, 10, 10.01, 10, [10, 10.01], [100, -50]]] as any,
    trades: [["a", 1000, 10.01, 5, "b", "provider", 1], ["b", 2000, 10, 7, "s", "quote_rule", 0.9]] as any,
    cvd: [[1000, 5]] as [number, number][],
    bars: [],
    book: null as any,
    profile: null as any,
    walls: [],
    icebergs: [],
    large_trades: [],
    absorptions: [],
    flow: null,
    whale: null,
    divergence: null,
  };
  it("applies snapshot and incremental updates without duplicating CVD buckets", () => {
    const s = new Series("symbol:COMI");
    s.applySnapshot(snap as any);
    expect(s.tradeCount).toBe(2);
    expect(s.tS[0]).toBe(1);
    expect(s.tS[1]).toBe(2);
    expect(s.tE[1]).toBe(1); // quote_rule -> estimated
    s.applyUpdate({ symbol: "COMI", cvd: [[1000, 6], [2000, -1]], trades: [["c", 3000, 10.02, 1, "u", "unknown", 0]] as any });
    expect(s.cvd).toEqual([[1000, 6], [2000, -1]]);
    expect(s.tradeCount).toBe(3);
    expect(s.tradeIndexAt(1500)).toBe(1);
    expect(s.columns[0].qtys[1]).toBe(-50);
  });

  it("ignores trades, columns and events already delivered in the snapshot", () => {
    const s = new Series("symbol:COMI");
    s.applySnapshot(snap as any);
    const lt = { type: "large_trade", symbol: "COMI", trade_id: "x1", ts: 2000 };
    s.applyUpdate({ symbol: "COMI", trades: snap.trades, columns: snap.columns, events: [lt, lt] as any });
    expect(s.tradeCount).toBe(2);
    expect(s.columns.length).toBe(1);
    expect(s.largeTrades.length).toBe(1);
  });
});
