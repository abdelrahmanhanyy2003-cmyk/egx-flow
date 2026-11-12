export type Quality = "live" | "delayed" | "historical" | "simulated";

/** [t, bestBid, bestAsk, last, prices[], qtys[] (+bid / -ask)] */
export type WireColumn = [number, number | null, number | null, number | null, number[], number[]];
/** [id, ts, price, qty, side 'b'|'s'|'u', method, confidence] */
export type WireTrade = [string, number, number, number, "b" | "s" | "u", string, number];

export interface Instrument {
  symbol: string;
  name: string;
  exchange: string;
  currency: string;
  tick_size: number | null;
  tick_size_source: string;
  sector: string | null;
  lower_limit?: number | null;
  upper_limit?: number | null;
}

export interface Imbalance {
  levels: number;
  bid_volume: number;
  ask_volume: number;
  imbalance: number;
  imbalance_pct: number;
  bid_concentration: number;
  ask_concentration: number;
  largest_bid_share: number;
  largest_ask_share: number;
}

export interface CvdSummary {
  cvd: number;
  session_delta: number;
  buy_volume: number;
  sell_volume: number;
  unknown_volume: number;
  buy_pct: number | null;
  estimated_share: number;
  reset: string;
}

export interface Stats {
  symbol: string;
  last: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
  change_pct: number | null;
  volume: number;
  value: number;
  trades: number;
  vwap: number | null;
  vwap_bands: [number | null, number | null];
  best_bid: number | null;
  best_ask: number | null;
  spread: number | null;
  tick: number | null;
  tick_source: string;
  book_resolution: string;
  quality: Quality;
  last_event_ms: number;
  rvol: number | null;
  cvd: CvdSummary;
  imbalance: Imbalance | null;
  whale_score: number | null;
  flow: string | null;
}

export interface Book {
  symbol: string;
  ts: number;
  bids: [number, number][];
  asks: [number, number][];
  best_bid: number | null;
  best_ask: number | null;
  spread: number | null;
  resolution: string;
}

export interface Profile {
  levels: [number, number, number, number][]; // price, buy, sell, unknown
  total: number;
  poc: number | null;
  val: number | null;
  vah: number | null;
  value_area_pct: number;
}

export interface Bar {
  t: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  buy_volume: number;
  sell_volume: number;
  unknown_volume: number;
  estimated_volume: number;
  value: number;
  trades: number;
  delta: number;
  vwap: number;
}

export interface Wall {
  id: string;
  symbol: string;
  side: "bid" | "ask";
  price: number;
  qty: number;
  max_qty: number;
  value: number;
  max_value: number;
  first_seen: number;
  last_seen: number;
  persistence_ms: number;
  status: string;
  distance_pct: number | null;
  distance_ticks: number | null;
  traded_at_level: number;
}

export interface WallEvent {
  kind: "new" | "resized" | "pulled" | "consumed";
  wall: Wall;
  ts: number;
  detail: Record<string, number>;
}

export interface IcebergSignal {
  symbol: string;
  side: "bid" | "ask";
  price: number;
  displayed: number;
  max_displayed: number;
  executed: number;
  estimated_hidden: number;
  replenishments: number;
  executions: number;
  confidence: number;
  first_ts: number;
  last_ts: number;
  resolution: string;
  label: string;
}

export interface LargeTrade {
  trade_id: string;
  symbol: string;
  price: number;
  quantity: number;
  value: number;
  ts: number;
  side: "buy" | "sell" | "unknown";
  method: string;
  estimated: boolean;
  confidence: number;
  threshold: number;
  percentile_rank: number;
  multiple_of_avg: number;
  pct_of_adv: number | null;
  threshold_method: string;
  fills?: number;
}

export interface WhaleFactor {
  factor: string;
  input: number | null;
  subscore: number;
  weight: number;
  contribution: number;
  description: string;
}
export interface WhaleScore {
  score: number;
  band: string;
  factors: WhaleFactor[];
  disclaimer: string;
}

export interface FlowSignal {
  kind: "accumulation" | "distribution" | "neutral";
  label: string;
  confidence: number;
  accumulation_score: number;
  distribution_score: number;
  evidence: { factor: string; value: number; weight: number; note: string; direction?: string }[];
  disclaimer: string;
}

export interface SymbolSnapshot {
  symbol: string;
  instrument: Instrument;
  stats: Stats;
  columns: WireColumn[];
  trades: WireTrade[];
  cvd: [number, number][];
  bars: Bar[];
  book: Book;
  profile: Profile;
  walls: Wall[];
  icebergs: IcebergSignal[];
  large_trades: LargeTrade[];
  absorptions: Record<string, unknown>[];
  flow: FlowSignal | null;
  whale: WhaleScore | null;
  divergence: Record<string, unknown> | null;
  replay?: ReplayInfo;
}

export interface SymbolUpdate {
  symbol: string;
  trades?: WireTrade[];
  columns?: WireColumn[];
  cvd?: [number, number][];
  events?: Record<string, any>[];
  stats?: Stats;
  book?: Book;
  profile?: Profile;
  bar?: Bar | null;
  icebergs?: IcebergSignal[];
  walls?: Wall[];
  whale?: WhaleScore | null;
  flow?: FlowSignal | null;
  replay?: ReplayInfo;
}

export interface ReplayInfo {
  id: string;
  symbol: string;
  speed: number;
  playing: boolean;
  cursor: number;
  start_ts: number;
  end_ts: number;
  events: number;
  position: number;
  quality: Quality;
  book_resolution: string;
  book_record_interval_ms: number;
  session: Record<string, any>;
}

export interface AlertItem {
  id?: number;
  ts: number;
  symbol: string | null;
  rule: string;
  severity: "info" | "warning" | "critical";
  message: string;
  payload?: any;
  acknowledged?: boolean;
  quality: Quality;
  sound?: boolean;
  label?: string;
}
