"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { fmtCompact, fmtNum, fmtPct, fmtPrice } from "@/lib/format";
import { useUi } from "@/store/ui";
import { DataTable, type Col } from "@/components/ui/DataTable";
import { ErrorNote, Panel, QualityBadge } from "@/components/ui/primitives";
import { ScoreBar } from "@/components/ui/ScoreBar";

interface Row {
  symbol: string;
  name: string;
  sector: string | null;
  streaming: boolean;
  last?: number;
  change_pct?: number;
  volume?: number;
  value?: number;
  rvol?: number | null;
  spread?: number | null;
  spread_bps?: number | null;
  liquidity_score?: number | null;
  whale_score?: number | null;
  flow?: string | null;
  quality?: string;
}

export default function ExplorerPage() {
  const q = useQuery({ queryKey: ["stocks"], queryFn: () => api("/api/stocks"), refetchInterval: 3000 });
  const rows: Row[] = q.data?.rows ?? [];
  const [sector, setSector] = useState("all");
  const [minLiq, setMinLiq] = useState(0);
  const [onlyStreaming, setOnlyStreaming] = useState(false);
  const openSymbol = useUi((s) => s.openSymbol);
  const router = useRouter();
  const sectors = useMemo(() => [...new Set(rows.map((r) => r.sector ?? "Unclassified"))].sort(), [rows]);
  const filtered = rows.filter(
    (r) => (sector === "all" || (r.sector ?? "Unclassified") === sector) && (r.liquidity_score ?? 0) >= minLiq && (!onlyStreaming || r.streaming),
  );
  const cols: Col<Row>[] = [
    { key: "symbol", label: "Symbol", render: (r) => <span className="font-semibold text-fg">{r.symbol}</span> },
    { key: "name", label: "Company", render: (r) => <span className="text-fg-dim">{r.name}</span> },
    { key: "sector", label: "Sector", render: (r) => <span className="text-fg-dim">{r.sector ?? "—"}</span> },
    { key: "last", label: "Last", align: "right", render: (r) => fmtPrice(r.last) },
    { key: "change_pct", label: "Chg %", align: "right", render: (r) => <span className={(r.change_pct ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtPct(r.change_pct)}</span> },
    { key: "volume", label: "Volume", align: "right", render: (r) => fmtCompact(r.volume) },
    { key: "value", label: "Value EGP", align: "right", render: (r) => fmtCompact(r.value) },
    { key: "rvol", label: "RVOL", align: "right", title: "Time-of-day adjusted relative volume", render: (r) => (r.rvol != null ? r.rvol.toFixed(2) + "x" : "—") },
    { key: "spread_bps", label: "Spread", align: "right", render: (r) => (r.spread != null ? `${fmtPrice(r.spread)} (${fmtNum(r.spread_bps, 0)}bp)` : "—") },
    { key: "liquidity_score", label: "Liquidity", align: "right", title: "Local heuristic: near-touch depth value + spread tightness", render: (r) => <ScoreBar v={r.liquidity_score} /> },
    { key: "whale_score", label: "Whale", align: "right", render: (r) => <ScoreBar v={r.whale_score} hot /> },
    { key: "flow", label: "Flow", render: (r) => <span className={r.flow === "accumulation" ? "text-buy" : r.flow === "distribution" ? "text-sell" : "text-fg-mute"}>{r.flow ?? "—"}</span> },
    { key: "streaming", label: "Feed", value: (r) => (r.streaming ? 1 : 0), render: (r) => (r.streaming ? <QualityBadge q={r.quality} /> : <span className="text-fg-mute">not streamed</span>) },
  ];
  return (
    <div className="flex h-full flex-col gap-2 p-2">
      <div className="flex items-center gap-3 text-[11px]">
        <h1 className="text-[13px] font-semibold">Stock Explorer</h1>
        <QualityBadge q={q.data?.quality} />
        <label className="flex items-center gap-1 text-fg-dim">Sector
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value="all">All sectors</option>
            {sectors.map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1 text-fg-dim">Min liquidity score
          <input type="number" min={0} max={100} value={minLiq} onChange={(e) => setMinLiq(Number(e.target.value))} className="w-16" />
        </label>
        <label className="flex items-center gap-1 text-fg-dim"><input type="checkbox" checked={onlyStreaming} onChange={(e) => setOnlyStreaming(e.target.checked)} /> Streaming only</label>
        <span className="ml-auto text-fg-mute">{filtered.length} / {rows.length} instruments · click a row to open in terminal</span>
      </div>
      <ErrorNote error={q.error} />
      <Panel className="flex-1">
        <DataTable rows={filtered} cols={cols} rowKey={(r) => r.symbol} initialSort={{ key: "value", dir: "desc" }} search searchKeys={[(r) => r.symbol, (r) => r.name ?? ""]}
          onRowClick={(r) => { openSymbol(r.symbol); router.push("/"); }} />
      </Panel>
    </div>
  );
}
