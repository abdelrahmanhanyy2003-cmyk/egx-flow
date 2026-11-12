"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useTopicData } from "@/lib/hooks";
import { fmtCompact, fmtDuration, fmtNum, fmtPct, fmtPrice, fmtTime } from "@/lib/format";
import type { LargeTrade, WhaleFactor } from "@/lib/types";
import { useUi } from "@/store/ui";
import { DataTable, type Col } from "@/components/ui/DataTable";
import { EstBadge, Panel, QualityBadge } from "@/components/ui/primitives";
import { ScoreBar } from "@/components/ui/ScoreBar";

interface Dashboard {
  ts: number;
  quality: string;
  feed: LargeTrade[];
  most_active: { symbol: string; count: number; value: number; buy_value: number; sell_value: number }[];
  largest_buys: LargeTrade[];
  largest_sells: LargeTrade[];
  largest_resting: any[];
  new_walls: any[];
  removed_walls: any[];
  icebergs: any[];
  absorptions: any[];
  accumulation: any[];
  distribution: any[];
  ranking: { symbol: string; name: string; score: number; band: string; factors: WhaleFactor[]; flow: string | null; last: number | null; change_pct: number | null }[];
  disclaimer: string;
}

const tradeCols: Col<LargeTrade>[] = [
  { key: "ts", label: "Time", render: (r) => <span className="text-fg-dim">{fmtTime(r.ts)}</span> },
  { key: "symbol", label: "Sym", render: (r) => <span className="font-semibold">{r.symbol}</span> },
  { key: "side", label: "Side", render: (r) => <span className={r.side === "buy" ? "text-buy" : r.side === "sell" ? "text-sell" : "text-fg-dim"}>{r.side.toUpperCase()} {r.estimated && <EstBadge />}</span> },
  { key: "price", label: "Price", align: "right", render: (r) => fmtPrice(r.price) },
  { key: "quantity", label: "Qty", align: "right", render: (r) => fmtNum(r.quantity) },
  { key: "value", label: "EGP", align: "right", render: (r) => fmtCompact(r.value) },
  { key: "percentile_rank", label: "Pctl", align: "right", render: (r) => r.percentile_rank.toFixed(1) },
  { key: "multiple_of_avg", label: "×avg", align: "right", render: (r) => r.multiple_of_avg.toFixed(1) },
];

export default function WhaleRadarPage() {
  const live = useTopicData<Dashboard>("whales", "whales");
  const initial = useQuery({ queryKey: ["whales"], queryFn: () => api<Dashboard>("/api/whales/dashboard"), enabled: !live });
  const d = live ?? initial.data;
  const router = useRouter();
  const openSymbol = useUi((s) => s.openSymbol);
  const [f, setF] = useState({ symbol: "", side: "", minValue: 0, minQty: 0, pctl: 0, sinceMin: 0 });
  const [selected, setSelected] = useState<string | null>(null);
  const part = useQuery({ queryKey: ["participants"], queryFn: () => api("/api/whales/participants") });
  if (!d) return <div className="p-4 text-fg-mute">Loading Whale Radar…</div>;
  const go = (s: string) => {
    openSymbol(s);
    router.push("/");
  };
  const since = f.sinceMin ? Date.now() - f.sinceMin * 60_000 : 0;
  const feed = d.feed.filter(
    (t) =>
      (!f.symbol || t.symbol.includes(f.symbol.toUpperCase())) &&
      (!f.side || t.side === f.side) &&
      t.value >= f.minValue &&
      t.quantity >= f.minQty &&
      t.percentile_rank >= f.pctl &&
      t.ts >= since,
  );
  const sel = d.ranking.find((r) => r.symbol === (selected ?? d.ranking[0]?.symbol));
  return (
    <div className="grid h-full auto-rows-min grid-cols-12 gap-2 overflow-auto p-2">
      <div className="col-span-12 flex items-center gap-3 text-[11px]">
        <h1 className="text-[13px] font-semibold">Whale Radar</h1>
        <QualityBadge q={d.quality} />
        <span className="text-fg-mute">{d.disclaimer}</span>
        <span className="num ml-auto text-fg-mute">updated {fmtTime(d.ts)}</span>
      </div>

      <Panel title="Whale activity ranking (explainable score)" className="col-span-4 h-[300px]">
        <DataTable rows={d.ranking} rowKey={(r) => r.symbol} initialSort={{ key: "score", dir: "desc" }} search searchKeys={[(r) => r.symbol, (r) => r.name]}
          onRowClick={(r) => setSelected(r.symbol)}
          cols={[
            { key: "symbol", label: "Sym", render: (r) => <button className="font-semibold text-accent" onClick={(e) => { e.stopPropagation(); go(r.symbol); }}>{r.symbol}</button> },
            { key: "score", label: "Score", align: "right", render: (r) => <ScoreBar v={r.score} hot /> },
            { key: "band", label: "Band", render: (r) => <span className="uppercase text-fg-dim">{r.band}</span> },
            { key: "flow", label: "Flow", render: (r) => <span className={r.flow === "accumulation" ? "text-buy" : r.flow === "distribution" ? "text-sell" : "text-fg-mute"}>{r.flow ?? "—"}</span> },
            { key: "change_pct", label: "Chg", align: "right", render: (r) => <span className={(r.change_pct ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtPct(r.change_pct)}</span> },
          ]}
        />
      </Panel>

      <Panel title={`Score factors · ${sel?.symbol ?? ""}`} className="col-span-3 h-[300px]">
        {sel && (
          <div className="overflow-auto p-2">
            <div className="num mb-1 text-2xl">{sel.score.toFixed(0)} <span className="text-[11px] uppercase text-warn">{sel.band}</span></div>
            {sel.factors.map((x) => (
              <div key={x.factor} className="mb-1" title={x.description}>
                <div className="flex justify-between text-[11px]"><span className="text-fg-dim">{x.factor.replace(/_/g, " ")}</span><span className="num">{x.contribution.toFixed(1)} / {x.weight}</span></div>
                <div className="h-1 bg-bg-3"><div className="h-full bg-accent" style={{ width: `${x.subscore * 100}%` }} /></div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="Most active by large transactions (60 min)" className="col-span-5 h-[300px]">
        <DataTable rows={d.most_active} rowKey={(r) => r.symbol} initialSort={{ key: "value", dir: "desc" }} onRowClick={(r) => go(r.symbol)}
          cols={[
            { key: "symbol", label: "Sym", render: (r) => <span className="font-semibold">{r.symbol}</span> },
            { key: "count", label: "Large trades", align: "right" },
            { key: "value", label: "Value EGP", align: "right", render: (r) => fmtCompact(r.value) },
            { key: "buy_value", label: "Buy EGP", align: "right", render: (r) => <span className="text-buy">{fmtCompact(r.buy_value)}</span> },
            { key: "sell_value", label: "Sell EGP", align: "right", render: (r) => <span className="text-sell">{fmtCompact(r.sell_value)}</span> },
            { key: "net", label: "Net", align: "right", value: (r) => r.buy_value - r.sell_value, render: (r) => <span className={r.buy_value >= r.sell_value ? "text-buy" : "text-sell"}>{fmtCompact(r.buy_value - r.sell_value)}</span> },
          ]}
        />
      </Panel>

      <Panel
        title="Large transaction feed"
        className="col-span-6 h-[380px]"
        right={
          <div className="flex items-center gap-1 text-[10px]">
            <input placeholder="Symbol" value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value })} className="h-5 w-16 py-0" />
            <select value={f.side} onChange={(e) => setF({ ...f, side: e.target.value })} className="h-5 py-0"><option value="">Any side</option><option value="buy">Buy</option><option value="sell">Sell</option><option value="unknown">Unknown</option></select>
            <input type="number" placeholder="Min EGP" value={f.minValue || ""} onChange={(e) => setF({ ...f, minValue: Number(e.target.value) })} className="h-5 w-20 py-0" />
            <input type="number" placeholder="Min qty" value={f.minQty || ""} onChange={(e) => setF({ ...f, minQty: Number(e.target.value) })} className="h-5 w-16 py-0" />
            <input type="number" placeholder="Pctl ≥" value={f.pctl || ""} onChange={(e) => setF({ ...f, pctl: Number(e.target.value) })} className="h-5 w-14 py-0" />
            <select value={f.sinceMin} onChange={(e) => setF({ ...f, sinceMin: Number(e.target.value) })} className="h-5 py-0"><option value={0}>Session</option><option value={15}>15m</option><option value={60}>1h</option></select>
          </div>
        }
      >
        <DataTable rows={feed} rowKey={(r) => r.trade_id + r.symbol} cols={tradeCols} initialSort={{ key: "ts", dir: "desc" }} onRowClick={(r) => go(r.symbol)} empty="No large transactions match" />
      </Panel>

      <div className="col-span-3 grid h-[380px] grid-rows-2 gap-2">
        <Panel title="Largest buying transactions"><DataTable rows={d.largest_buys} rowKey={(r) => r.trade_id + r.symbol} cols={tradeCols.filter((c) => c.key !== "side" && c.key !== "multiple_of_avg")} initialSort={{ key: "value", dir: "desc" }} onRowClick={(r) => go(r.symbol)} /></Panel>
        <Panel title="Largest selling transactions"><DataTable rows={d.largest_sells} rowKey={(r) => r.trade_id + r.symbol} cols={tradeCols.filter((c) => c.key !== "side" && c.key !== "multiple_of_avg")} initialSort={{ key: "value", dir: "desc" }} onRowClick={(r) => go(r.symbol)} /></Panel>
      </div>

      <div className="col-span-3 grid h-[380px] grid-rows-2 gap-2">
        <Panel title="Potential accumulation">
          <FlowList items={d.accumulation} onGo={go} />
        </Panel>
        <Panel title="Potential distribution">
          <FlowList items={d.distribution} onGo={go} />
        </Panel>
      </div>

      <Panel title="Largest resting liquidity concentrations" className="col-span-4 h-[280px]">
        <DataTable rows={d.largest_resting} rowKey={(r) => r.id} initialSort={{ key: "value", dir: "desc" }} onRowClick={(r) => go(r.symbol)}
          cols={[
            { key: "symbol", label: "Sym", render: (r) => <span className="font-semibold">{r.symbol}</span> },
            { key: "side", label: "Side", render: (r) => <span className={r.side === "bid" ? "text-buy" : "text-sell"}>{r.side.toUpperCase()}</span> },
            { key: "price", label: "Price", align: "right", render: (r) => fmtPrice(r.price) },
            { key: "qty", label: "Size", align: "right", render: (r) => fmtCompact(r.qty) },
            { key: "value", label: "EGP", align: "right", render: (r) => fmtCompact(r.value) },
            { key: "distance_pct", label: "Dist", align: "right", render: (r) => fmtPct(r.distance_pct) },
            { key: "persistence_ms", label: "Age", align: "right", render: (r) => fmtDuration(r.persistence_ms) },
          ]}
        />
      </Panel>
      <Panel title="New liquidity walls" className="col-span-2 h-[280px]">
        <WallEvents rows={d.new_walls} onGo={go} />
      </Panel>
      <Panel title="Removed walls (pulled / consumed)" className="col-span-3 h-[280px]">
        <WallEvents rows={d.removed_walls} onGo={go} />
      </Panel>
      <Panel title="Potential icebergs (estimated)" className="col-span-3 h-[280px]">
        <DataTable rows={d.icebergs} rowKey={(r) => `${r.symbol}${r.side}${r.price}`} initialSort={{ key: "confidence", dir: "desc" }} onRowClick={(r) => go(r.symbol)}
          cols={[
            { key: "symbol", label: "Sym", render: (r) => <span className="font-semibold">{r.symbol}</span> },
            { key: "side", label: "Side", render: (r) => <span className={r.side === "bid" ? "text-buy" : "text-sell"}>{r.side.toUpperCase()}</span> },
            { key: "price", label: "Price", align: "right", render: (r) => fmtPrice(r.price) },
            { key: "executed", label: "Exec", align: "right", render: (r) => fmtCompact(r.executed) },
            { key: "estimated_hidden", label: "Est. hidden", align: "right", render: (r) => fmtCompact(r.estimated_hidden) },
            { key: "replenishments", label: "Refills", align: "right" },
            { key: "confidence", label: "Conf", align: "right", render: (r) => `${Math.round(r.confidence * 100)}%` },
          ]}
          empty="No potential iceberg activity"
        />
      </Panel>
      <Panel title="Market participant statistics" className="col-span-12">
        <div className="p-2 text-[11px] text-fg-dim">
          {part.data?.available ? "Available" : part.data?.note ?? "—"}
        </div>
      </Panel>
    </div>
  );
}

function FlowList({ items, onGo }: { items: any[]; onGo: (s: string) => void }) {
  if (!items.length) return <div className="p-2 text-[11px] text-fg-mute">None detected</div>;
  return (
    <div className="space-y-1 overflow-auto p-2">
      {items.map((a) => (
        <button key={a.symbol} onClick={() => onGo(a.symbol)} className="block w-full border border-line p-1 text-left hover:border-line-2">
          <div className="flex justify-between text-[11px]"><span className="font-semibold">{a.symbol}</span><span className="num">conf {(a.confidence * 100).toFixed(0)}%</span></div>
          <div className="truncate text-[10px] text-fg-mute">{a.evidence.filter((e: any) => e.weight).map((e: any) => e.factor.replace(/_/g, " ")).join(" · ")}</div>
        </button>
      ))}
    </div>
  );
}

function WallEvents({ rows, onGo }: { rows: any[]; onGo: (s: string) => void }) {
  return (
    <DataTable rows={rows} rowKey={(r, i) => `${r.wall.id}${r.kind}${i}`} initialSort={{ key: "ts", dir: "desc" }} onRowClick={(r) => onGo(r.wall.symbol)}
      cols={[
        { key: "ts", label: "Time", render: (r) => <span className="text-fg-dim">{fmtTime(r.ts)}</span> },
        { key: "sym", label: "Sym", value: (r) => r.wall.symbol, render: (r) => <span className="font-semibold">{r.wall.symbol}</span> },
        { key: "kind", label: "Event", render: (r) => <span className={r.kind === "pulled" ? "text-warn" : "text-fg-dim"}>{r.kind}</span> },
        { key: "side", label: "Side", value: (r) => r.wall.side, render: (r) => <span className={r.wall.side === "bid" ? "text-buy" : "text-sell"}>{r.wall.side}</span> },
        { key: "price", label: "Price", align: "right", value: (r) => r.wall.price, render: (r) => fmtPrice(r.wall.price) },
        { key: "val", label: "EGP", align: "right", value: (r) => r.wall.max_value, render: (r) => fmtCompact(r.wall.max_value) },
      ]}
      empty="None yet"
    />
  );
}
