"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { fmtCompact, fmtDate, fmtEGP, fmtNum, fmtPrice, fmtTime } from "@/lib/format";
import { useSeriesTick } from "@/lib/hooks";
import type { Series } from "@/lib/series";
import { Btn, Empty, EstBadge } from "@/components/ui/primitives";
import { LineChart } from "@/components/charts/LineChart";

export function TimeAndSales({ series, minValue = 0 }: { series: Series | null; minValue?: number }) {
  useSeriesTick(series, 250);
  const [filter, setFilter] = useState(minValue);
  if (!series || !series.tradeCount) return <Empty>No trades yet</Empty>;
  const rows: { i: number }[] = [];
  for (let i = series.tradeCount - 1; i >= 0 && rows.length < 250; i--) {
    if (series.tP[i] * series.tQ[i] >= filter) rows.push({ i });
  }
  const tick = series.stats?.tick;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-line px-2 py-1 text-[10px] text-fg-mute">
        Min value
        <select value={filter} onChange={(e) => setFilter(Number(e.target.value))} className="h-5 py-0 text-[10px]">
          {[0, 50_000, 100_000, 250_000, 500_000, 1_000_000].map((v) => (
            <option key={v} value={v}>{v ? fmtEGP(v) : "All"}</option>
          ))}
        </select>
        <span className="ml-auto">EST = side inferred by quote/tick rule</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="dense num w-full text-[11px]">
          <thead>
            <tr><th>Time (Cairo)</th><th>Price</th><th className="text-right">Qty</th><th className="text-right">Value EGP</th><th>Side</th></tr>
          </thead>
          <tbody>
            {rows.map(({ i }) => {
              const s = series.tS[i];
              const cls = s === 1 ? "text-buy" : s === 2 ? "text-sell" : "text-fg-dim";
              const v = series.tP[i] * series.tQ[i];
              return (
                <tr key={series.tId[i]} className={v >= 1_000_000 ? "bg-warn/5" : ""}>
                  <td className="text-fg-dim">{fmtTime(series.tT[i])}</td>
                  <td className={cls}>{fmtPrice(series.tP[i], tick)}</td>
                  <td className="text-right">{fmtNum(series.tQ[i])}</td>
                  <td className="text-right">{fmtNum(v)}</td>
                  <td className={cls}>
                    {s === 1 ? "BUY" : s === 2 ? "SELL" : "—"} {series.tE[i] ? <EstBadge /> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function LargeLotTracker({ series }: { series: Series | null }) {
  useSeriesTick(series, 500);
  if (!series) return <Empty>—</Empty>;
  const large = [...series.largeTrades].reverse().slice(0, 100);
  const walls = [...series.wallEvents].reverse().slice(0, 60);
  const tick = series.stats?.tick;
  return (
    <div className="grid h-full grid-cols-[1.3fr_1fr_0.9fr] divide-x divide-line">
      <div className="min-h-0 overflow-auto">
        <div className="panel-title sticky top-0 z-20 bg-bg-1 px-2 py-1">Large executed trades (aggregated prints)</div>
        <table className="dense num w-full text-[11px]">
          <thead><tr><th>Time</th><th>Side</th><th>Price</th><th className="text-right">Qty</th><th className="text-right">EGP</th><th className="text-right">Pctl</th><th className="text-right">×avg</th></tr></thead>
          <tbody>
            {large.map((t) => (
              <tr key={t.trade_id}>
                <td className="text-fg-dim">{fmtTime(t.ts)}</td>
                <td className={t.side === "buy" ? "text-buy" : t.side === "sell" ? "text-sell" : "text-fg-dim"}>{t.side.toUpperCase()} {t.estimated && <EstBadge />}</td>
                <td>{fmtPrice(t.price, tick)}</td>
                <td className="text-right">{fmtNum(t.quantity)}</td>
                <td className="text-right">{fmtCompact(t.value)}</td>
                <td className="text-right">{t.percentile_rank.toFixed(1)}</td>
                <td className="text-right">{t.multiple_of_avg.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!large.length && <Empty>No large transactions yet (dynamic threshold)</Empty>}
      </div>
      <div className="min-h-0 overflow-auto">
        <div className="panel-title sticky top-0 z-20 bg-bg-1 px-2 py-1">Resting liquidity changes (walls)</div>
        <table className="dense num w-full text-[11px]">
          <thead><tr><th>Time</th><th>Event</th><th>Side</th><th>Price</th><th className="text-right">Size</th></tr></thead>
          <tbody>
            {walls.map((e, k) => (
              <tr key={k}>
                <td className="text-fg-dim">{fmtTime(e.ts)}</td>
                <td className={e.kind === "new" ? "text-accent" : e.kind === "pulled" ? "text-warn" : e.kind === "consumed" ? "text-fg" : "text-fg-dim"}>{e.kind.toUpperCase()}</td>
                <td className={e.wall.side === "bid" ? "text-buy" : "text-sell"}>{e.wall.side.toUpperCase()}</td>
                <td>{fmtPrice(e.wall.price, tick)}</td>
                <td className="text-right">{fmtCompact(e.kind === "resized" ? e.wall.qty : e.wall.max_qty)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!walls.length && <Empty>No wall changes yet</Empty>}
      </div>
      <div className="min-h-0 overflow-auto">
        <div className="panel-title sticky top-0 z-20 bg-bg-1 px-2 py-1">Active walls · potential icebergs</div>
        <div className="space-y-1 p-2">
          {series.walls.map((w) => (
            <div key={w.id} className="flex justify-between text-[11px]">
              <span className={w.side === "bid" ? "text-buy" : "text-sell"}>{w.side.toUpperCase()} {fmtPrice(w.price, tick)}</span>
              <span className="num text-fg-dim">{fmtCompact(w.qty)} · {fmtCompact(w.value)} EGP · {Math.round(w.persistence_ms / 1000)}s</span>
            </div>
          ))}
          {series.icebergs.map((s) => (
            <div key={`${s.side}${s.price}`} className="rounded-sm border border-warn/30 p-1 text-[11px]">
              <div className="flex justify-between"><span className="text-warn">ICEBERG? {s.side.toUpperCase()} {fmtPrice(s.price, tick)}</span><span className="num">{Math.round(s.confidence * 100)}%</span></div>
              <div className="num text-[10px] text-fg-dim">exec {fmtCompact(s.executed)} vs shown ≤{fmtCompact(s.max_displayed)} · est. hidden {fmtCompact(s.estimated_hidden)} · {s.replenishments} refills</div>
            </div>
          ))}
          {!series.walls.length && !series.icebergs.length && <Empty>None active</Empty>}
          <p className="pt-1 text-[10px] text-fg-mute">Iceberg flags are heuristic estimates, never confirmed hidden orders.</p>
        </div>
      </div>
    </div>
  );
}

export function VolumeAnalysis({ series }: { series: Series | null }) {
  useSeriesTick(series, 1000);
  if (!series?.bars.length) return <Empty>No bars yet</Empty>;
  const bars = [...series.bars].reverse().slice(0, 120);
  const avg = series.bars.reduce((a, b) => a + b.volume, 0) / series.bars.length;
  return (
    <div className="h-full overflow-auto">
      <table className="dense num w-full text-[11px]">
        <thead><tr><th>1-min bar</th><th>Close</th><th className="text-right">Volume</th><th className="text-right">Buy</th><th className="text-right">Sell</th><th className="text-right">Delta</th><th className="text-right">VWAP</th><th className="text-right">Trades</th><th>Spike</th></tr></thead>
        <tbody>
          {bars.map((b) => (
            <tr key={b.t}>
              <td className="text-fg-dim">{fmtTime(b.t)}</td>
              <td>{fmtPrice(b.close)}</td>
              <td className="text-right">{fmtNum(b.volume)}</td>
              <td className="text-right text-buy">{fmtNum(b.buy_volume)}</td>
              <td className="text-right text-sell">{fmtNum(b.sell_volume)}</td>
              <td className={`text-right ${b.delta >= 0 ? "text-buy" : "text-sell"}`}>{fmtNum(b.delta)}</td>
              <td className="text-right">{fmtPrice(b.vwap)}</td>
              <td className="text-right">{b.trades}</td>
              <td>{b.volume > avg * 2.5 ? <span className="text-warn">▲ {(b.volume / avg).toFixed(1)}x</span> : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CvdPanel({ series }: { series: Series | null }) {
  useSeriesTick(series, 1000);
  const st = series?.stats;
  if (!st) return <Empty>—</Empty>;
  const c = st.cvd;
  let cum = 0;
  const pts = series!.bars.map((b) => [b.t, (cum += b.delta)] as [number, number]);
  return (
    <div className="grid h-full grid-cols-[260px_1fr]">
      <div className="space-y-1 border-r border-line p-2 text-[11px]">
        <Row k="Cumulative delta" v={fmtNum(c.cvd)} cls={c.cvd >= 0 ? "text-buy" : "text-sell"} />
        <Row k="Session delta" v={fmtNum(c.session_delta)} cls={c.session_delta >= 0 ? "text-buy" : "text-sell"} />
        <Row k="Aggressive buys" v={fmtNum(c.buy_volume)} cls="text-buy" />
        <Row k="Aggressive sells" v={fmtNum(c.sell_volume)} cls="text-sell" />
        <Row k="Unknown side (excluded)" v={fmtNum(c.unknown_volume)} />
        <Row k="Buy %" v={c.buy_pct != null ? c.buy_pct.toFixed(1) + "%" : "—"} />
        <Row k="Side estimated" v={(c.estimated_share * 100).toFixed(1) + "%"} cls={c.estimated_share > 0.01 ? "text-warn" : ""} />
        <Row k="Reset period" v={c.reset} />
        <Row k="Divergence" v={series!.events.filter((e) => e.type === "cvd_divergence").slice(-1)[0]?.kind ?? "none"} />
      </div>
      <div className="min-h-0 p-1">
        <LineChart series={[{ data: pts, color: "#2fb4ff", title: "CVD (1m)" }]} />
      </div>
    </div>
  );
}

function Row({ k, v, cls = "" }: { k: string; v: string; cls?: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-fg-mute">{k}</span>
      <span className={`num ${cls}`}>{v}</span>
    </div>
  );
}

export function StudiesPanel({ symbol }: { symbol: string }) {
  const [p, setP] = useState({ rsi: 14, sma: 20, ema: 50, atr: 14, src: "intraday" });
  const q = useQuery({
    queryKey: ["ind", symbol, p],
    queryFn: () => api(`/api/stocks/${symbol}/indicators?source=${p.src}&rsi_period=${p.rsi}&sma_period=${p.sma}&ema_period=${p.ema}&atr_period=${p.atr}`),
    refetchInterval: 15000,
  });
  const d = q.data;
  const zip = (vals: (number | null)[]) => (d ? (d.ts as number[]).map((t, i) => [t, vals[i]] as [number, number | null]).filter((x) => x[1] != null) as [number, number][] : []);
  const last = (a?: (number | null)[]) => (a ? [...a].reverse().find((x) => x != null) ?? null : null);
  return (
    <div className="grid h-full grid-cols-[230px_1fr_1fr]">
      <div className="space-y-1.5 border-r border-line p-2 text-[11px]">
        <label className="flex justify-between">Source
          <select value={p.src} onChange={(e) => setP({ ...p, src: e.target.value })} className="h-5 py-0">
            <option value="intraday">1-min bars</option><option value="daily">Daily candles</option>
          </select>
        </label>
        {(["rsi", "sma", "ema", "atr"] as const).map((k) => (
          <label key={k} className="flex justify-between uppercase">{k} period
            <input type="number" min={2} max={400} value={p[k]} onChange={(e) => setP({ ...p, [k]: Number(e.target.value) || 2 })} className="h-5 w-16 py-0" />
          </label>
        ))}
        <div className="border-t border-line pt-1.5">
          <Row k={`RSI(${p.rsi})`} v={last(d?.rsi)?.toFixed(1) ?? "—"} />
          <Row k={`SMA(${p.sma})`} v={fmtPrice(last(d?.sma))} />
          <Row k={`EMA(${p.ema})`} v={fmtPrice(last(d?.ema))} />
          <Row k={`ATR(${p.atr})`} v={last(d?.atr)?.toFixed(3) ?? "—"} />
          <Row k="MACD" v={last(d?.macd?.line)?.toFixed(3) ?? "—"} />
          <Row k="MACD signal" v={last(d?.macd?.signal)?.toFixed(3) ?? "—"} />
          <Row k="RVOL" v={last(d?.rvol)?.toFixed(2) ?? "—"} />
          <Row k="Session VWAP" v={fmtPrice(d?.vwap)} />
        </div>
      </div>
      <div className="min-h-0 border-r border-line p-1">
        <LineChart series={[
          { data: zip(d?.close ?? []), color: "#d6e2f0", title: "Close" },
          { data: zip(d?.sma ?? []), color: "#f5b942", title: "SMA" },
          { data: zip(d?.ema ?? []), color: "#b48cff", title: "EMA" },
        ]} />
      </div>
      <div className="min-h-0 p-1">
        <LineChart series={[
          { data: zip(d?.rsi ?? []), color: "#2fb4ff", title: "RSI" },
          { data: zip(d?.macd?.hist ?? []), color: "#19c37d", title: "MACD hist", histogram: true },
        ]} />
      </div>
    </div>
  );
}

export function FlowPanel({ series }: { series: Series | null }) {
  useSeriesTick(series, 2000);
  const w = series?.whale;
  const f = series?.flow;
  if (!w) return <Empty>Whale score is computed after a few seconds of data</Empty>;
  return (
    <div className="grid h-full grid-cols-2 divide-x divide-line overflow-auto">
      <div className="p-2">
        <div className="flex items-baseline gap-2">
          <span className="panel-title">Whale activity score</span>
          <span className="num text-xl text-fg">{w.score.toFixed(0)}</span>
          <span className="text-[10px] uppercase text-warn">{w.band}</span>
        </div>
        <table className="dense num mt-1 w-full text-[11px]">
          <thead><tr><th>Factor</th><th className="text-right">Input</th><th className="text-right">Sub</th><th className="text-right">Wt</th><th className="text-right">Pts</th></tr></thead>
          <tbody>
            {w.factors.map((x) => (
              <tr key={x.factor} title={x.description}>
                <td>{x.factor.replace(/_/g, " ")}</td>
                <td className="text-right">{x.input == null ? "—" : x.input.toFixed(2)}</td>
                <td className="text-right">{x.subscore.toFixed(2)}</td>
                <td className="text-right">{x.weight}</td>
                <td className="text-right text-accent">{x.contribution.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-[10px] text-fg-mute">{w.disclaimer}</p>
      </div>
      <div className="p-2">
        <div className="flex items-baseline gap-2">
          <span className="panel-title">Accumulation / distribution</span>
          <span className={`text-[12px] ${f?.kind === "accumulation" ? "text-buy" : f?.kind === "distribution" ? "text-sell" : "text-fg-dim"}`}>{f?.label ?? "—"}</span>
          {f && <span className="num text-[11px] text-fg-dim">conf {(f.confidence * 100).toFixed(0)}%</span>}
        </div>
        {f && (
          <table className="dense num mt-1 w-full text-[11px]">
            <thead><tr><th>Evidence</th><th className="text-right">Value</th><th>Note</th></tr></thead>
            <tbody>
              {f.evidence.map((e) => (
                <tr key={e.factor}>
                  <td>{e.factor.replace(/_/g, " ")}</td>
                  <td className={`text-right ${e.value > 0 ? "text-buy" : e.value < 0 ? "text-sell" : ""}`}>{e.value.toFixed(2)}</td>
                  <td className="text-fg-dim">{e.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="mt-1 text-[10px] text-fg-mute">{f?.disclaimer}</p>
      </div>
    </div>
  );
}

export function ReplayLauncher({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ["sessions", symbol], queryFn: () => api(`/api/replay/sessions?symbol=${symbol}`) });
  const rows = (q.data?.rows ?? []) as any[];
  return (
    <div className="h-full overflow-auto p-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="panel-title">Recorded sessions for {symbol}</span>
        <Link href={`/replay?symbol=${symbol}`}><Btn size="xs">Open replay workspace</Btn></Link>
      </div>
      <table className="dense num w-full text-[11px]">
        <thead><tr><th>Date</th><th>Source</th><th>Quality</th><th>Book</th><th className="text-right">Trades</th><th className="text-right">Snapshots</th><th /></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td>{r.date}</td><td>{r.source}</td><td>{r.quality}</td><td>{r.book_resolution} @{r.book_record_interval_ms}ms</td>
              <td className="text-right">{fmtNum(r.trades)}</td><td className="text-right">{fmtNum(r.book_snapshots)}</td>
              <td><Link className="text-accent" href={`/replay?session=${r.id}`}>Replay ▶</Link></td>
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <Empty>No recorded sessions yet. Recording starts automatically while the backend runs.</Empty>}
      <p className="pt-2 text-[10px] text-fg-mute">Replay uses only stored events. Unavailable historical depth is never reconstructed from candles. Last recorded: {fmtDate(rows[0]?.last_ts)}</p>
    </div>
  );
}
