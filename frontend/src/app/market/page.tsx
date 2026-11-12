"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { api } from "@/lib/api";
import { useTopicData } from "@/lib/hooks";
import { fmtCompact, fmtNum, fmtPct, fmtPrice, fmtTime } from "@/lib/format";
import { useUi } from "@/store/ui";
import { DataTable } from "@/components/ui/DataTable";
import { Panel, QualityBadge, Stat } from "@/components/ui/primitives";

export default function MarketPage() {
  const ov = useTopicData<any>("market", "market");
  const stocks = useQuery({ queryKey: ["stocks"], queryFn: () => api("/api/stocks"), refetchInterval: 3000 });
  const rows = (stocks.data?.rows ?? []).filter((r: any) => r.streaming) as any[];
  const router = useRouter();
  const openSymbol = useUi((s) => s.openSymbol);
  const go = (s: string) => {
    openSymbol(s);
    router.push("/");
  };
  const sectors = useMemo(() => {
    const m = new Map<string, { n: number; chg: number; value: number }>();
    for (const r of rows) {
      const k = r.sector ?? "Unclassified";
      const x = m.get(k) ?? { n: 0, chg: 0, value: 0 };
      x.n++;
      x.chg += r.change_pct ?? 0;
      x.value += r.value ?? 0;
      m.set(k, x);
    }
    return [...m.entries()].map(([sector, x]) => ({ sector, n: x.n, change_pct: x.chg / x.n, value: x.value }));
  }, [rows]);
  const m = ov?.market;
  const b = m?.breadth;
  const total = (m?.advances ?? 0) + (m?.declines ?? 0) + (m?.unchanged ?? 0);
  const moverCols = [
    { key: "symbol", label: "Sym", render: (r: any) => <span className="font-semibold">{r.symbol}</span> },
    { key: "last", label: "Last", align: "right" as const, render: (r: any) => fmtPrice(r.last) },
    { key: "change_pct", label: "Chg", align: "right" as const, render: (r: any) => <span className={(r.change_pct ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtPct(r.change_pct)}</span> },
    { key: "value", label: "EGP", align: "right" as const, render: (r: any) => fmtCompact(r.value) },
  ];
  return (
    <div className="grid h-full auto-rows-min grid-cols-12 gap-2 overflow-auto p-2">
      <div className="col-span-12 flex items-center gap-3 text-[11px]">
        <h1 className="text-[13px] font-semibold">Market Overview</h1>
        <QualityBadge q={ov?.quality} />
        <span className="text-fg-mute">Session: {ov?.session?.state} ({ov?.session?.source}) · {ov?.cairo_time ? fmtTime(ov.ts) : ""} Cairo</span>
      </div>
      <Panel className="col-span-12" bodyClass="grid grid-cols-8 gap-3 p-2">
        <Stat label={ov?.index?.name ?? "EGX30"} value={fmtNum(ov?.index?.value, 2)} sub={<span className={(ov?.index?.change_pct ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtPct(ov?.index?.change_pct)} ({fmtNum(ov?.index?.net_change, 2)})</span>} />
        <Stat label="Market status" value={m?.status ?? "—"} />
        <Stat label="Turnover" value={`EGP ${fmtCompact(m?.traded_value)}`} />
        <Stat label="Volume" value={fmtCompact(m?.traded_volume)} />
        <Stat label="Trades" value={fmtNum(m?.trades_count)} />
        <Stat label="Advancers" value={<span className="text-buy">{m?.advances ?? "—"}</span>} sub={b?.pct_advancing != null ? `${b.pct_advancing.toFixed(0)}% of traded` : undefined} />
        <Stat label="Decliners" value={<span className="text-sell">{m?.declines ?? "—"}</span>} sub={b?.ad_ratio != null ? `A/D ratio ${b.ad_ratio.toFixed(2)}` : undefined} />
        <Stat label="Unchanged" value={m?.unchanged ?? "—"} sub={`A-D line ${b?.ad_line ?? "—"}`} />
        <div className="col-span-8 flex h-2 overflow-hidden rounded-sm">
          <div className="bg-buy" style={{ width: `${total ? ((m?.advances ?? 0) / total) * 100 : 0}%` }} />
          <div className="bg-fg-mute/40" style={{ width: `${total ? ((m?.unchanged ?? 0) / total) * 100 : 0}%` }} />
          <div className="bg-sell" style={{ width: `${total ? ((m?.declines ?? 0) / total) * 100 : 0}%` }} />
        </div>
      </Panel>
      <Panel title="Market map (streamed symbols, by change %)" className="col-span-7 row-span-2 h-[608px]" bodyClass="overflow-auto p-2">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(110px,1fr))] gap-1">
          {[...rows].sort((a, b) => (b.value ?? 0) - (a.value ?? 0)).map((r) => {
            const c = r.change_pct ?? 0;
            const a = Math.min(0.85, Math.abs(c) / 4 + 0.1);
            return (
              <button key={r.symbol} onClick={() => go(r.symbol)} className="p-2 text-left" style={{ background: c >= 0 ? `rgba(25,195,125,${a})` : `rgba(255,77,94,${a})` }}>
                <div className="font-semibold text-white">{r.symbol}</div>
                <div className="num text-[11px] text-white/90">{fmtPct(c)}</div>
                <div className="num text-[10px] text-white/70">EGP {fmtCompact(r.value)}</div>
              </button>
            );
          })}
        </div>
      </Panel>
      <Panel title="Top gainers" className="col-span-5 h-[300px]"><DataTable rows={ov?.gainers ?? []} rowKey={(r: any) => r.symbol} cols={moverCols} onRowClick={(r: any) => go(r.symbol)} /></Panel>
      <Panel title="Top losers" className="col-span-5 h-[300px]"><DataTable rows={ov?.losers ?? []} rowKey={(r: any) => r.symbol} cols={moverCols} onRowClick={(r: any) => go(r.symbol)} /></Panel>
      <Panel title="Most active by value" className="col-span-7 h-[300px]"><DataTable rows={ov?.most_active ?? []} rowKey={(r: any) => r.symbol} cols={moverCols} initialSort={{ key: "value", dir: "desc" }} onRowClick={(r: any) => go(r.symbol)} /></Panel>
      <Panel title="Sector performance (equal-weighted, streamed symbols)" className="col-span-5 h-[300px]">
        <DataTable rows={sectors} rowKey={(r) => r.sector} initialSort={{ key: "change_pct", dir: "desc" }} cols={[
          { key: "sector", label: "Sector" },
          { key: "n", label: "#", align: "right" },
          { key: "change_pct", label: "Avg chg", align: "right", render: (r) => <span className={r.change_pct >= 0 ? "text-buy" : "text-sell"}>{fmtPct(r.change_pct)}</span> },
          { key: "value", label: "Value EGP", align: "right", render: (r) => fmtCompact(r.value) },
        ]} />
      </Panel>
    </div>
  );
}
