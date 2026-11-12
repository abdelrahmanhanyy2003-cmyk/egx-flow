"use client";

import { useEffect, useMemo, useRef } from "react";
import { useSeriesTick } from "@/lib/hooks";
import type { Series } from "@/lib/series";
import { fmtCompact, fmtEGP, fmtNum, fmtPct, fmtPrice } from "@/lib/format";
import { useUi } from "@/store/ui";
import { Empty, EstBadge, Panel, QualityBadge, Stat } from "@/components/ui/primitives";

export function OrderBookPanel({ series }: { series: Series | null }) {
  useSeriesTick(series, 200);
  const book = series?.book;
  const st = series?.stats;
  if (!book || !st) return <Panel title="Order book"><Empty>No book yet</Empty></Panel>;
  const rows = 14;
  const asks = book.asks.slice(0, rows).reverse();
  const bids = book.bids.slice(0, rows);
  const max = Math.max(1, ...book.asks.slice(0, rows).map((x) => x[1]), ...book.bids.slice(0, rows).map((x) => x[1]));
  const wallPrices = new Set(series!.walls.map((w) => `${w.side}:${w.price}`));
  const ice = new Set(series!.icebergs.map((w) => `${w.side}:${w.price}`));
  const res = book.resolution;
  return (
    <Panel
      title="Order book"
      right={
        <>
          {res === "l1_only" && <span className="text-[9px] text-warn" title="Provider supplies best bid/ask only">L1 ONLY</span>}
          <QualityBadge q={st.quality} />
        </>
      }
      bodyClass="overflow-hidden"
    >
      <table className="num w-full text-[11px]">
        <tbody>
          {asks.map(([p, q]) => (
            <tr key={`a${p}`} className="relative h-[17px]">
              <td className="relative w-1/2 px-2 text-right text-fg-dim">
                <div className="absolute inset-y-0 right-0 bg-sell/20" style={{ width: `${(q / max) * 100}%` }} />
                <span className="relative">{fmtNum(q)}</span>
              </td>
              <td className="w-1/2 px-2 text-sell">
                {fmtPrice(p, st.tick)}
                {wallPrices.has(`ask:${p}`) && <span className="ml-1 text-[9px] text-warn">WALL</span>}
                {ice.has(`ask:${p}`) && <span className="ml-1 text-[9px] text-warn">ICE?</span>}
              </td>
            </tr>
          ))}
          <tr className="h-[20px] border-y border-line bg-bg-2">
            <td className="px-2 text-right text-[10px] text-fg-mute">spread {fmtPrice(book.spread, st.tick)}</td>
            <td className="px-2 text-fg">{fmtPrice(st.last, st.tick)}</td>
          </tr>
          {bids.map(([p, q]) => (
            <tr key={`b${p}`} className="relative h-[17px]">
              <td className="relative w-1/2 px-2 text-right text-buy">
                {wallPrices.has(`bid:${p}`) && <span className="mr-1 text-[9px] text-warn">WALL</span>}
                {ice.has(`bid:${p}`) && <span className="mr-1 text-[9px] text-warn">ICE?</span>}
                {fmtPrice(p, st.tick)}
              </td>
              <td className="relative w-1/2 px-2 text-fg-dim">
                <div className="absolute inset-y-0 left-0 bg-buy/20" style={{ width: `${(q / max) * 100}%` }} />
                <span className="relative">{fmtNum(q)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

export function ImbalancePanel({ series }: { series: Series | null }) {
  useSeriesTick(series, 300);
  const levels = useUi((s) => s.imbalanceLevels);
  const setLevels = useUi((s) => s.setImbalanceLevels);
  const hist = useRef<number[]>([]);
  const book = series?.book;
  const m = useMemo(() => {
    if (!book) return null;
    const b = book.bids.slice(0, levels).map((x) => x[1]);
    const a = book.asks.slice(0, levels).map((x) => x[1]);
    const bv = b.reduce((x, y) => x + y, 0);
    const av = a.reduce((x, y) => x + y, 0);
    const tot = bv + av;
    const hhi = (q: number[], s: number) => (s ? q.reduce((x, y) => x + (y / s) ** 2, 0) : 0);
    return { bv, av, imb: tot ? (bv - av) / tot : 0, pct: tot ? (bv / tot) * 100 : 50, bc: hhi(b, bv), ac: hhi(a, av) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [book, levels, series?.version]);
  useEffect(() => {
    if (!m) return;
    hist.current.push(m.imb);
    if (hist.current.length > 120) hist.current.shift();
  }, [m]);
  if (!m) return <Panel title="Imbalance"><Empty>—</Empty></Panel>;
  const prev = hist.current.length > 20 ? hist.current[hist.current.length - 21] : null;
  return (
    <Panel
      title="Bid/ask imbalance"
      right={
        <select className="h-5 py-0 text-[10px]" value={levels} onChange={(e) => setLevels(Number(e.target.value))}>
          {[1, 3, 5, 10, 20, 40].map((n) => (
            <option key={n} value={n}>{n} lvls</option>
          ))}
        </select>
      }
      bodyClass="p-2 space-y-2"
    >
      <div className="relative h-3 overflow-hidden rounded-sm bg-sell/60">
        <div className="absolute inset-y-0 left-0 bg-buy/80" style={{ width: `${m.pct}%` }} />
        <div className="absolute inset-y-0 left-1/2 w-px bg-white/50" />
      </div>
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Bid vol" value={<span className="text-buy">{fmtCompact(m.bv)}</span>} />
        <Stat label="Imbalance" value={<span className={m.imb >= 0 ? "text-buy" : "text-sell"}>{(m.imb * 100).toFixed(1)}%</span>} sub={prev != null ? `Δ ${((m.imb - prev) * 100).toFixed(1)} pts` : undefined} />
        <Stat label="Ask vol" value={<span className="text-sell">{fmtCompact(m.av)}</span>} />
        <Stat label="Bid conc. (HHI)" value={m.bc.toFixed(2)} />
        <Stat label="Bid share" value={`${m.pct.toFixed(1)}%`} />
        <Stat label="Ask conc. (HHI)" value={m.ac.toFixed(2)} />
      </div>
      <Sparkline values={hist.current} />
    </Panel>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const w = 220,
    h = 26;
  if (values.length < 2) return null;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h / 2 - v * (h / 2)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-[26px] w-full">
      <line x1="0" x2={w} y1={h / 2} y2={h / 2} stroke="#1a2b42" />
      <polyline points={pts} fill="none" stroke="#2fb4ff" strokeWidth="1.2" />
    </svg>
  );
}

export function DepthPanel({ series }: { series: Series | null }) {
  useSeriesTick(series, 400);
  const ref = useRef<HTMLCanvasElement>(null);
  const book = series?.book;
  useEffect(() => {
    const c = ref.current;
    if (!c || !book) return;
    const dpr = window.devicePixelRatio || 1;
    const r = c.getBoundingClientRect();
    c.width = r.width * dpr;
    c.height = r.height * dpr;
    const ctx = c.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, r.width, r.height);
    const bids = book.bids.slice(0, 40);
    const asks = book.asks.slice(0, 40);
    if (!bids.length || !asks.length) return;
    const cum = (a: [number, number][]) => {
      let s = 0;
      return a.map(([p, q]) => [p, (s += q)] as [number, number]);
    };
    const cb = cum(bids);
    const ca = cum(asks);
    const pMin = cb[cb.length - 1][0];
    const pMax = ca[ca.length - 1][0];
    const vMax = Math.max(cb[cb.length - 1][1], ca[ca.length - 1][1]);
    const x = (p: number) => ((p - pMin) / (pMax - pMin || 1)) * r.width;
    const y = (v: number) => r.height - (v / vMax) * (r.height - 4);
    const draw = (pts: [number, number][], fill: string, stroke: string) => {
      ctx.beginPath();
      ctx.moveTo(x(pts[0][0]), r.height);
      for (const [p, v] of pts) ctx.lineTo(x(p), y(v));
      ctx.lineTo(x(pts[pts.length - 1][0]), r.height);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = stroke;
      ctx.stroke();
    };
    draw(cb, "rgba(25,195,125,0.25)", "#19c37d");
    draw(ca, "rgba(255,77,94,0.25)", "#ff4d5e");
  }, [book, series?.version]);
  return (
    <Panel title="Bid/ask depth" bodyClass="p-1">
      {book ? <canvas ref={ref} className="h-[90px] w-full" /> : <Empty>—</Empty>}
    </Panel>
  );
}

export function ProfileStatsPanel({ series }: { series: Series | null }) {
  useSeriesTick(series, 500);
  const st = series?.stats;
  const pr = series?.profile;
  if (!st) return <Panel title="Session"><Empty>—</Empty></Panel>;
  return (
    <Panel title="Session · profile" bodyClass="grid grid-cols-2 gap-x-3 gap-y-2 p-2">
      <Stat label="Last" value={fmtPrice(st.last, st.tick)} sub={<span className={(st.change_pct ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtPct(st.change_pct)}</span>} />
      <Stat label="Spread" value={fmtPrice(st.spread, st.tick)} sub={`tick ${st.tick ?? "?"} (${st.tick_source})`} />
      <Stat label="VWAP" value={fmtPrice(st.vwap, st.tick)} />
      <Stat label="POC" value={fmtPrice(pr?.poc, st.tick)} />
      <Stat label="VAH" value={fmtPrice(pr?.vah, st.tick)} />
      <Stat label="VAL" value={fmtPrice(pr?.val, st.tick)} />
      <Stat label="Volume" value={fmtCompact(st.volume)} sub={st.rvol ? `RVOL ${st.rvol.toFixed(2)}x` : undefined} />
      <Stat label="Value" value={fmtCompact(st.value)} sub="EGP" />
      <Stat label="Session delta" value={<span className={st.cvd.session_delta >= 0 ? "text-buy" : "text-sell"}>{fmtCompact(st.cvd.session_delta)}</span>} sub={st.cvd.estimated_share > 0.01 ? <span className="inline-flex items-center gap-1"><EstBadge /> {(st.cvd.estimated_share * 100).toFixed(0)}% est.</span> : "provider side"} />
      <Stat label="Whale score" value={st.whale_score?.toFixed(0) ?? "—"} sub={st.flow ?? undefined} />
      <Stat label="High / Low" value={`${fmtPrice(st.high, st.tick)} / ${fmtPrice(st.low, st.tick)}`} className="col-span-2" />
      <Stat label="Trades" value={fmtNum(st.trades)} sub={fmtEGP(st.value)} className="col-span-2" />
    </Panel>
  );
}
