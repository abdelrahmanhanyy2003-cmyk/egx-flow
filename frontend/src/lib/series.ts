/**
 * Mutable, non-React market-data store per topic (symbol or replay).
 *
 * WebSocket messages are applied here directly; the canvas engine reads these
 * structures every frame. React panels subscribe through `useSeries` with a
 * throttle, so high-frequency data never drives React re-renders.
 */

import type {
  Bar,
  Book,
  FlowSignal,
  IcebergSignal,
  Instrument,
  LargeTrade,
  Profile,
  ReplayInfo,
  Stats,
  SymbolSnapshot,
  SymbolUpdate,
  Wall,
  WallEvent,
  WhaleScore,
} from "./types";

export interface Column {
  t: number;
  bb: number | null;
  ba: number | null;
  last: number | null;
  prices: Float64Array;
  qtys: Float64Array; // +bid / -ask
}

const MAX_COLUMNS = 20000;
const MAX_TRADES = 60000;

export class Series {
  topic: string;
  symbol = "";
  instrument: Instrument | null = null;
  stats: Stats | null = null;
  columns: Column[] = [];
  // struct-of-arrays trades for fast iteration
  tT: number[] = [];
  tP: number[] = [];
  tQ: number[] = [];
  tS: Uint8Array = new Uint8Array(MAX_TRADES); // 1 buy, 2 sell, 0 unknown
  tE: Uint8Array = new Uint8Array(MAX_TRADES); // 1 estimated side
  tId: string[] = [];
  cvd: [number, number][] = [];
  bars: Bar[] = [];
  book: Book | null = null;
  profile: Profile | null = null;
  walls: Wall[] = [];
  icebergs: IcebergSignal[] = [];
  largeTrades: LargeTrade[] = [];
  wallEvents: WallEvent[] = [];
  events: Record<string, any>[] = [];
  whale: WhaleScore | null = null;
  flow: FlowSignal | null = null;
  replay: ReplayInfo | null = null;
  version = 0; // bumps on any data change
  structureVersion = 0; // bumps when the whole history is replaced
  lastColumnsVersion = 0;
  private listeners = new Set<() => void>();

  constructor(topic: string) {
    this.topic = topic;
  }

  get tradeCount() {
    return this.tT.length;
  }

  applySnapshot(s: SymbolSnapshot) {
    this.symbol = s.symbol;
    this.instrument = s.instrument;
    this.stats = s.stats;
    this.columns = s.columns.map(toColumn);
    this.tT = [];
    this.tP = [];
    this.tQ = [];
    this.tId = [];
    this.seenTrades = new Set();
    this.seenEvents = new Set(s.large_trades.map((t) => eventKey({ type: "large_trade", ...t })));
    this.tS = new Uint8Array(MAX_TRADES);
    this.tE = new Uint8Array(MAX_TRADES);
    for (const w of s.trades) this.pushTrade(w);
    this.cvd = s.cvd.slice();
    this.bars = s.bars.slice();
    this.book = s.book;
    this.profile = s.profile;
    this.walls = s.walls;
    this.icebergs = s.icebergs;
    this.largeTrades = s.large_trades.slice();
    this.whale = s.whale;
    this.flow = s.flow;
    this.replay = s.replay ?? null;
    this.wallEvents = [];
    this.events = [];
    this.structureVersion++;
    this.bump();
  }

  // A snapshot can already contain items that are still pending in the server's next
  // incremental update; these sets make every apply idempotent (no double counting).
  private seenTrades = new Set<string>();
  private seenEvents = new Set<string>();

  private pushTrade(w: [string, number, number, number, string, string, number]) {
    if (this.seenTrades.has(w[0])) return;
    this.seenTrades.add(w[0]);
    if (this.tT.length >= MAX_TRADES) {
      const cut = Math.floor(MAX_TRADES * 0.2);
      for (let i = 0; i < cut; i++) this.seenTrades.delete(this.tId[i]);
      this.tT.splice(0, cut);
      this.tP.splice(0, cut);
      this.tQ.splice(0, cut);
      this.tId.splice(0, cut);
      this.tS.copyWithin(0, cut);
      this.tE.copyWithin(0, cut);
    }
    const i = this.tT.length;
    this.tId.push(w[0]);
    this.tT.push(w[1]);
    this.tP.push(w[2]);
    this.tQ.push(w[3]);
    this.tS[i] = w[4] === "b" ? 1 : w[4] === "s" ? 2 : 0;
    this.tE[i] = w[5] === "quote_rule" || w[5] === "tick_rule" ? 1 : 0;
  }

  applyUpdate(u: SymbolUpdate) {
    if (u.columns?.length) {
      for (const c of u.columns) {
        const last = this.columns[this.columns.length - 1];
        if (!last || c[0] > last.t) this.columns.push(toColumn(c));
      }
      if (this.columns.length > MAX_COLUMNS) this.columns.splice(0, this.columns.length - MAX_COLUMNS);
    }
    if (u.trades?.length) for (const w of u.trades) this.pushTrade(w);
    if (u.cvd?.length) {
      for (const p of u.cvd) {
        const last = this.cvd[this.cvd.length - 1];
        if (last && last[0] === p[0]) last[1] = p[1];
        else if (!last || p[0] > last[0]) this.cvd.push(p);
      }
    }
    if (u.stats) this.stats = u.stats;
    if (u.book) this.book = u.book;
    if (u.profile) this.profile = u.profile;
    if (u.bar) {
      const last = this.bars[this.bars.length - 1];
      if (last && last.t === u.bar.t) this.bars[this.bars.length - 1] = u.bar;
      else this.bars.push(u.bar);
    }
    if (u.icebergs) this.icebergs = u.icebergs;
    if (u.walls) this.walls = u.walls;
    if (u.whale !== undefined) this.whale = u.whale;
    if (u.flow !== undefined) this.flow = u.flow;
    if (u.replay) this.replay = u.replay;
    if (u.events?.length) {
      for (const e of u.events) {
        const key = eventKey(e);
        if (this.seenEvents.has(key)) continue;
        this.seenEvents.add(key);
        if (this.seenEvents.size > 5000) this.seenEvents = new Set([...this.seenEvents].slice(-2500));
        this.events.push(e);
        if (e.type === "large_trade") this.largeTrades.push(e as LargeTrade);
        if (e.type === "wall") this.wallEvents.push(e as WallEvent);
      }
      if (this.events.length > 500) this.events.splice(0, this.events.length - 500);
      if (this.largeTrades.length > 500) this.largeTrades.splice(0, this.largeTrades.length - 500);
      if (this.wallEvents.length > 300) this.wallEvents.splice(0, this.wallEvents.length - 300);
    }
    this.bump();
  }

  private bump() {
    this.version++;
    for (const l of this.listeners) l();
  }

  listen(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** binary search: first trade index with ts >= t */
  tradeIndexAt(t: number): number {
    let lo = 0,
      hi = this.tT.length;
    while (lo < hi) {
      const m = (lo + hi) >> 1;
      if (this.tT[m] < t) lo = m + 1;
      else hi = m;
    }
    return lo;
  }

  columnIndexAt(t: number): number {
    let lo = 0,
      hi = this.columns.length;
    while (lo < hi) {
      const m = (lo + hi) >> 1;
      if (this.columns[m].t < t) lo = m + 1;
      else hi = m;
    }
    return lo;
  }
}

function eventKey(e: Record<string, any>): string {
  if (e.type === "large_trade") return `lt:${e.symbol}:${e.trade_id}`;
  if (e.type === "wall") return `w:${e.wall?.id}:${e.kind}:${e.ts}`;
  if (e.type === "iceberg") return `ice:${e.side}:${e.price}:${e.first_ts}`;
  if (e.type === "absorption") return `abs:${e.kind}:${e.price}:${e.window_start}`;
  return `${e.type}:${e.kind ?? ""}:${e.ts ?? e.last_ts ?? ""}`;
}

function toColumn(c: [number, number | null, number | null, number | null, number[], number[]]): Column {
  return { t: c[0], bb: c[1], ba: c[2], last: c[3], prices: Float64Array.from(c[4]), qtys: Float64Array.from(c[5]) };
}

const registry = new Map<string, Series>();

export function getSeries(topic: string): Series {
  let s = registry.get(topic);
  if (!s) {
    s = new Series(topic);
    registry.set(topic, s);
  }
  return s;
}

export function dropSeries(topic: string) {
  registry.delete(topic);
}
