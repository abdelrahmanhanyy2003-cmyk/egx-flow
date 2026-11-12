"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { api } from "@/lib/api";
import { useTopicSeries } from "@/lib/hooks";
import { fmtCompact, fmtEGP, fmtNum, fmtPct, fmtPrice, fmtTime } from "@/lib/format";
import { DataTable } from "@/components/ui/DataTable";
import { EstBadge, Panel, QualityBadge, Stat } from "@/components/ui/primitives";
import { CandleChart, LineChart } from "@/components/charts/LineChart";
import { HeatmapChart } from "@/components/terminal/HeatmapChart";
import { ImbalancePanel } from "@/components/terminal/SidePanels";

export default function PositionDetail({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol: raw } = use(params);
  const symbol = raw.toUpperCase();
  const d = useQuery({ queryKey: ["position", symbol], queryFn: () => api(`/api/positions/${symbol}`), refetchInterval: 5000 });
  const daily = useQuery({ queryKey: ["candles", symbol], queryFn: () => api(`/api/stocks/${symbol}/candles?period=Year`) });
  const series = useTopicSeries(`symbol:${symbol}`);
  const p = d.data?.position;
  const st = d.data?.stats;
  const entry = p?.avg_price ?? null;
  const lines = entry ? [{ price: entry, color: "#b48cff", title: "Entry" }] : [];
  return (
    <div className="grid h-full auto-rows-min grid-cols-12 gap-2 overflow-auto p-2">
      <div className="col-span-12 flex items-center gap-3 text-[11px]">
        <Link href="/portfolio" className="text-accent">← Portfolio</Link>
        <h1 className="text-[14px] font-semibold">{symbol}</h1>
        <QualityBadge q={d.data?.quality} />
        {!d.data?.is_holding && <span className="text-fg-mute">Not currently held — showing market analysis only</span>}
      </div>
      <Panel className="col-span-12" bodyClass="grid grid-cols-10 gap-3 p-2">
        <Stat label="Shares" value={fmtNum(p?.quantity)} />
        <Stat label="Avg entry" value={fmtPrice(entry)} />
        <Stat label="Current price" value={fmtPrice(st?.last)} sub={fmtPct(st?.change_pct)} />
        <Stat label="Invested" value={fmtEGP(p?.invested)} />
        <Stat label="Position value" value={fmtEGP(p?.market_value)} />
        <Stat label="Unrealized P&L" value={<span className={(p?.unrealized_pnl ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtEGP(p?.unrealized_pnl)}</span>} sub={fmtPct(p?.unrealized_pnl_pct)} />
        <Stat label="Realized P&L" value={fmtEGP(p?.realized_pnl)} />
        <Stat label="Weight" value={fmtPct(p?.allocation_pct, 1, false)} />
        <Stat label="Whale score" value={d.data?.whale?.score?.toFixed(0) ?? "—"} sub={d.data?.flow?.label} />
        <Stat label="Session CVD" value={<span className={(d.data?.cvd?.session_delta ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtCompact(d.data?.cvd?.session_delta)}</span>} />
      </Panel>
      <Panel title="Order flow (heatmap · entry reference)" className="col-span-8 h-[540px]">
        <HeatmapChart series={series} symbol={symbol} entryPrice={entry} />
      </Panel>
      <div className="col-span-4 grid h-[540px] grid-rows-2 gap-2">
        <Panel title="Daily price chart with entry">
          <CandleChart daily candles={(daily.data?.candles ?? []).map((c: any) => ({ t: c.ts, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume }))} priceLines={lines} />
        </Panel>
        <Panel title="Intraday 1-min bars">
          <CandleChart candles={(d.data?.bars ?? []).map((b: any) => ({ t: b.t, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume }))} priceLines={lines} />
        </Panel>
      </div>
      <div className="col-span-3 h-[260px]"><ImbalancePanel series={series} /></div>
      <Panel title="Volume profile (session)" className="col-span-3 h-[260px]" bodyClass="overflow-auto p-2">
        <ProfileBars prof={d.data?.profile} entry={entry} />
      </Panel>
      <Panel title="Large participant activity" className="col-span-3 h-[260px]">
        <DataTable rows={(d.data?.large_trades ?? []).slice().reverse()} rowKey={(r: any) => r.trade_id} cols={[
          { key: "ts", label: "Time", render: (r: any) => fmtTime(r.ts) },
          { key: "side", label: "Side", render: (r: any) => <span className={r.side === "buy" ? "text-buy" : "text-sell"}>{r.side} {r.estimated && <EstBadge />}</span> },
          { key: "price", label: "Px", align: "right", render: (r: any) => fmtPrice(r.price) },
          { key: "value", label: "EGP", align: "right", render: (r: any) => fmtCompact(r.value) },
        ]} empty="No large trades this session" />
      </Panel>
      <Panel title="Liquidity walls" className="col-span-3 h-[260px]">
        <DataTable rows={d.data?.walls ?? []} rowKey={(r: any) => r.id} cols={[
          { key: "side", label: "Side", render: (r: any) => <span className={r.side === "bid" ? "text-buy" : "text-sell"}>{r.side}</span> },
          { key: "price", label: "Px", align: "right", render: (r: any) => fmtPrice(r.price) },
          { key: "qty", label: "Size", align: "right", render: (r: any) => fmtCompact(r.qty) },
          { key: "value", label: "EGP", align: "right", render: (r: any) => fmtCompact(r.value) },
        ]} empty="No active walls" />
      </Panel>
      <Panel title="CVD" className="col-span-6 h-[260px]">
        <LineChart series={[{ data: (d.data?.cvd_series ?? []) as [number, number][], color: "#2fb4ff", title: "CVD" }]} />
      </Panel>
      <Panel title="Historical transactions (recent prints)" className="col-span-6 h-[260px]">
        <DataTable rows={(d.data?.recent_trades ?? []).slice().reverse()} rowKey={(r: any) => r.trade_id} cols={[
          { key: "ts", label: "Time", render: (r: any) => fmtTime(r.ts) },
          { key: "price", label: "Price", align: "right", render: (r: any) => fmtPrice(r.price) },
          { key: "quantity", label: "Qty", align: "right", render: (r: any) => fmtNum(r.quantity) },
          { key: "value", label: "EGP", align: "right", render: (r: any) => fmtNum(r.value) },
          { key: "side", label: "Side", render: (r: any) => <span className={r.side === "buy" ? "text-buy" : r.side === "sell" ? "text-sell" : ""}>{r.side} {r.estimated && <EstBadge />}</span> },
        ]} />
      </Panel>
    </div>
  );
}

function ProfileBars({ prof, entry }: { prof: any; entry: number | null }) {
  if (!prof?.levels?.length) return <div className="text-fg-mute">No volume yet</div>;
  const lv = [...prof.levels].sort((a: number[], b: number[]) => b[0] - a[0]);
  const max = Math.max(...lv.map((l: number[]) => l[1] + l[2] + l[3]));
  return (
    <div className="num space-y-px text-[10px]">
      {lv.map(([p, b, s, u]: number[]) => {
        const tot = b + s + u;
        const near = entry != null && Math.abs(p - entry) < 1e-6;
        return (
          <div key={p} className={`flex items-center gap-1 ${p === prof.poc ? "text-warn" : near ? "text-demo" : "text-fg-dim"}`}>
            <span className="w-12 text-right">{p.toFixed(2)}</span>
            <div className="flex h-2 flex-1">
              <div className="bg-buy/70" style={{ width: `${(b / max) * 100}%` }} />
              <div className="bg-sell/70" style={{ width: `${(s / max) * 100}%` }} />
              <div className="bg-fg-mute/50" style={{ width: `${(u / max) * 100}%` }} />
            </div>
            <span className="w-10 text-right">{fmtCompact(tot)}</span>
            {p === prof.poc && <span>POC</span>}
          </div>
        );
      })}
    </div>
  );
}
