"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { fmtCompact, fmtDateTime, fmtEGP, fmtNum, fmtPct, fmtPrice } from "@/lib/format";
import { DataTable } from "@/components/ui/DataTable";
import { Btn, cn, ErrorNote, Panel, QualityBadge, Stat } from "@/components/ui/primitives";
import { LineChart } from "@/components/charts/LineChart";

const COLORS = ["#2fb4ff", "#19c37d", "#f5b942", "#b48cff", "#ff4d5e", "#4dd0e1", "#ff8a65", "#9ccc65", "#8aa0b8"];

function Donut({ items }: { items: { symbol: string; weight_pct: number | null }[] }) {
  const r = 52,
    c = 2 * Math.PI * r;
  let off = 0;
  return (
    <div className="flex items-center gap-4 p-2">
      <svg viewBox="0 0 140 140" className="h-36 w-36 shrink-0 -rotate-90">
        <circle cx="70" cy="70" r={r} fill="none" stroke="#112136" strokeWidth="18" />
        {items.map((it, i) => {
          const len = ((it.weight_pct ?? 0) / 100) * c;
          const el = <circle key={it.symbol} cx="70" cy="70" r={r} fill="none" stroke={COLORS[i % COLORS.length]} strokeWidth="18" strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-off} />;
          off += len;
          return el;
        })}
      </svg>
      <div className="flex-1 space-y-0.5 text-[11px]">
        {items.map((it, i) => (
          <div key={it.symbol} className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-sm" style={{ background: COLORS[i % COLORS.length] }} />
            <span className="flex-1">{it.symbol}</span>
            <span className="num text-fg-dim">{fmtPct(it.weight_pct, 1, false)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function LocalTag({ fields, f }: { fields?: string[]; f: string }) {
  if (!fields?.includes(f)) return null;
  return <span title="Locally calculated by EGX Flow (not broker-reported)" className="ml-1 text-[8px] text-accent">CALC</span>;
}

export default function PortfolioPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"positions" | "orders" | "journal" | "reconcile">("positions");
  const sum = useQuery({ queryKey: ["portfolio"], queryFn: () => api("/api/portfolio/summary"), refetchInterval: 5000 });
  const risk = useQuery({ queryKey: ["risk"], queryFn: () => api("/api/portfolio/risk"), refetchInterval: 30000 });
  const refresh = useMutation({ mutationFn: () => api("/api/portfolio/refresh", { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolio"] }) });
  const v = sum.data;
  const s = v?.summary;
  const positions = (v?.positions ?? []) as any[];
  return (
    <div className="flex h-full flex-col gap-2 overflow-auto p-2">
      <div className="flex items-center gap-3 text-[11px]">
        <h1 className="text-[13px] font-semibold">Portfolio</h1>
        <QualityBadge q={v?.quality} />
        <span className="text-fg-mute">source: {v?.source} · last refresh {fmtDateTime(v?.last_refresh)}</span>
        {v?.error && <span className="text-warn">broker: {v.error}</span>}
        <Btn size="xs" className="ml-auto" onClick={() => refresh.mutate()}><RefreshCw size={11} /> Refresh</Btn>
      </div>
      {v?.quality === "simulated" && (
        <div className="border border-demo/40 bg-demo/10 px-2 py-1 text-[11px] text-demo">DEMO portfolio — simulated holdings priced from simulated market data. Connect EFG Hermes (DATA_MODE=live) to see your real account.</div>
      )}
      <ErrorNote error={sum.error} />
      <div className="grid grid-cols-8 gap-2">
        <Panel className="col-span-8" bodyClass="grid grid-cols-8 gap-3 p-2">
          <Stat label="Total value" value={fmtEGP(s?.total_value)} />
          <Stat label="Invested capital" value={<>{fmtEGP(s?.invested_capital)}<LocalTag fields={s?.local_fields} f="invested_capital" /></>} />
          <Stat label="Available cash" value={fmtEGP(s?.cash)} />
          <Stat label="Unrealized P&L" value={<span className={(s?.unrealized_pnl ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtEGP(s?.unrealized_pnl)}</span>} sub={fmtPct(s?.unrealized_pnl_pct)} />
          <Stat label="Realized P&L" value={<span className={(s?.realized_pnl ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtEGP(s?.realized_pnl)}</span>} />
          <Stat label={<>Daily P&L<LocalTag fields={s?.local_fields} f="daily_pnl" /></>} value={<span className={(s?.daily_pnl ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtEGP(s?.daily_pnl)}</span>} sub="vs prior close" />
          <Stat label={<>Overall return<LocalTag fields={s?.local_fields} f="overall_return_pct" /></>} value={fmtPct(s?.overall_return_pct)} />
          <Stat label="Stocks value" value={fmtEGP(s?.stocks_value)} />
        </Panel>
      </div>
      <div className="grid min-h-[260px] grid-cols-12 gap-2">
        <Panel title="Asset allocation" className="col-span-3"><Donut items={(v?.allocation ?? []) as any[]} /></Panel>
        <Panel title="Equity curve (recorded snapshots)" className="col-span-5" right={<span className="text-[9px] text-accent">CALC</span>}>
          <LineChart series={[{ data: (risk.data?.equity_curve ?? []) as [number, number][], color: "#2fb4ff", title: "Total value" }]} />
        </Panel>
        <Panel title="Risk analytics" className="col-span-4" right={<span className="text-[9px] text-accent">CALC</span>} bodyClass="overflow-auto p-2 text-[11px]">
          {risk.data && (
            <div className="space-y-2">
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Largest" value={risk.data.concentration.largest ?? "—"} sub={fmtPct(risk.data.concentration.largest_weight_pct, 1, false)} />
                <Stat label="Top 3 weight" value={fmtPct(risk.data.concentration.top3_weight_pct, 1, false)} />
                <Stat label="Eff. positions" value={risk.data.concentration.effective_positions ?? "—"} sub={`HHI ${risk.data.concentration.hhi}`} />
                <Stat label="Max drawdown" value={<span className="text-sell">{fmtPct(risk.data.drawdown.max_drawdown_pct)}</span>} />
                <Stat label="Current DD" value={fmtPct(risk.data.drawdown.current_drawdown_pct)} />
                <Stat label="Exposure 1d" value={fmtPct(risk.data.exposure_change.change_pct)} sub={fmtEGP(risk.data.exposure_change.change)} />
              </div>
              <div>
                <div className="panel-title mb-1">Sector concentration</div>
                {risk.data.sectors.map((x: any) => (
                  <div key={x.sector} className="mb-0.5">
                    <div className="flex justify-between"><span className="text-fg-dim">{x.sector}</span><span className="num">{fmtPct(x.weight_pct, 1, false)}</span></div>
                    <div className="h-1 bg-bg-3"><div className="h-full bg-accent" style={{ width: `${x.weight_pct}%` }} /></div>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-fg-mute">{risk.data.label}</p>
            </div>
          )}
        </Panel>
      </div>
      <Panel className="min-h-[300px] flex-1" title={
        <div className="flex gap-3 normal-case tracking-normal">
          {(["positions", "orders", "journal", "reconcile"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} className={cn("text-[11px] font-semibold", tab === t ? "text-accent" : "text-fg-mute")}>
              {{ positions: "Positions", orders: "Broker orders", journal: "Trading journal", reconcile: "Reconciliation" }[t]}
            </button>
          ))}
        </div>
      }>
        {tab === "positions" && <Positions rows={positions} />}
        {tab === "orders" && <Orders />}
        {tab === "journal" && <Journal />}
        {tab === "reconcile" && <Reconcile />}
      </Panel>
    </div>
  );
}

function Positions({ rows }: { rows: any[] }) {
  return (
    <DataTable rows={rows} rowKey={(r) => r.symbol} initialSort={{ key: "market_value", dir: "desc" }} empty="No open positions"
      cols={[
        { key: "symbol", label: "Symbol", render: (r) => <Link className="font-semibold text-accent" href={`/portfolio/${r.symbol}`}>{r.symbol}</Link> },
        { key: "name", label: "Company", render: (r) => <span className="text-fg-dim">{r.name ?? "—"}</span> },
        { key: "quantity", label: "Shares", align: "right", render: (r) => fmtNum(r.quantity) },
        { key: "avg_price", label: "Avg entry", align: "right", render: (r) => fmtPrice(r.avg_price) },
        { key: "current_price", label: "Price", align: "right", render: (r) => <>{fmtPrice(r.current_price)}<LocalTag fields={r.local_fields} f="current_price" /></> },
        { key: "invested", label: "Invested", align: "right", render: (r) => fmtCompact(r.invested) },
        { key: "market_value", label: "Value", align: "right", render: (r) => fmtCompact(r.market_value) },
        { key: "unrealized_pnl", label: "Unreal. P&L", align: "right", render: (r) => <span className={(r.unrealized_pnl ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtNum(r.unrealized_pnl)}<LocalTag fields={r.local_fields} f="unrealized_pnl" /></span> },
        { key: "realized_pnl", label: "Realized", align: "right", render: (r) => (r.realized_pnl == null ? "—" : fmtNum(r.realized_pnl)) },
        { key: "unrealized_pnl_pct", label: "Return", align: "right", render: (r) => <span className={(r.unrealized_pnl_pct ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtPct(r.unrealized_pnl_pct)}</span> },
        { key: "allocation_pct", label: "Weight", align: "right", render: (r) => fmtPct(r.allocation_pct, 1, false) },
      ]}
    />
  );
}

function Orders() {
  const open = useQuery({ queryKey: ["orders-open"], queryFn: () => api("/api/portfolio/orders/open") });
  const hist = useQuery({ queryKey: ["orders-hist"], queryFn: () => api("/api/portfolio/orders/history") });
  const cols = [
    { key: "order_id", label: "Order" },
    { key: "symbol", label: "Symbol" },
    { key: "side", label: "Side" },
    { key: "quantity", label: "Qty", align: "right" as const, render: (r: any) => fmtNum(r.quantity) },
    { key: "price", label: "Price", align: "right" as const, render: (r: any) => fmtPrice(r.price) },
    { key: "avg_price", label: "Avg", align: "right" as const, render: (r: any) => fmtPrice(r.avg_price) },
    { key: "status", label: "Status" },
    { key: "ts", label: "Date", render: (r: any) => fmtDateTime(r.ts) },
  ];
  return (
    <div className="grid h-full grid-cols-2 divide-x divide-line">
      <div className="flex min-h-0 flex-col"><div className="panel-title px-2 py-1">Open orders (read-only)</div><DataTable rows={open.data?.rows ?? []} rowKey={(r: any) => r.order_id} cols={cols} empty="No open orders" /></div>
      <div className="flex min-h-0 flex-col"><div className="panel-title px-2 py-1">Executed / closed orders</div><DataTable rows={hist.data?.rows ?? []} rowKey={(r: any) => r.order_id} cols={cols} initialSort={{ key: "ts", dir: "desc" }} empty="No order history" /></div>
    </div>
  );
}

const EMPTY = { symbol: "", side: "buy", trade_date: new Date().toISOString().slice(0, 10), quantity: "", price: "", fees: "0", notes: "", thesis: "", tags: "" };

function Journal() {
  const qc = useQueryClient();
  const j = useQuery({ queryKey: ["journal"], queryFn: () => api("/api/portfolio/journal") });
  const [form, setForm] = useState<any>(EMPTY);
  const [editing, setEditing] = useState<number | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: (body: any) => (editing ? api(`/api/portfolio/journal/${editing}`, { method: "PUT", json: body }) : api("/api/portfolio/journal", { method: "POST", json: body })),
    onSuccess: () => {
      setForm(EMPTY);
      setEditing(null);
      setErr(null);
      qc.invalidateQueries({ queryKey: ["journal"] });
    },
    onError: setErr,
  });
  const del = useMutation({ mutationFn: (id: number) => api(`/api/portfolio/journal/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["journal"] }) });
  const rows = (j.data?.rows ?? []) as any[];
  const stats = j.data?.stats;
  const closed = (stats?.symbols ?? []).flatMap((s: any) => s.closed.map((c: any, i: number) => ({ ...c, key: `${s.symbol}${i}` })));
  return (
    <div className="grid h-full grid-cols-[320px_1fr] divide-x divide-line">
      <form
        className="space-y-1.5 overflow-auto p-2 text-[11px]"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({ ...form, quantity: Number(form.quantity), price: Number(form.price), fees: Number(form.fees || 0), notes: form.notes || null, thesis: form.thesis || null, tags: form.tags || null });
        }}
      >
        <div className="panel-title">{editing ? `Edit entry #${editing}` : "New journal entry"}</div>
        <div className="grid grid-cols-2 gap-1.5">
          <input required placeholder="Symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} />
          <select value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value })}><option value="buy">Buy (entry)</option><option value="sell">Sell (exit)</option></select>
          <input required type="date" value={form.trade_date.slice(0, 10)} onChange={(e) => setForm({ ...form, trade_date: e.target.value })} />
          <input required type="number" step="any" min="0" placeholder="Quantity" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
          <input required type="number" step="any" min="0" placeholder="Avg price" value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />
          <input type="number" step="any" min="0" placeholder="Fees EGP" value={form.fees} onChange={(e) => setForm({ ...form, fees: e.target.value })} />
        </div>
        <textarea rows={3} className="w-full" placeholder="Trade thesis" value={form.thesis} onChange={(e) => setForm({ ...form, thesis: e.target.value })} />
        <textarea rows={2} className="w-full" placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        <input className="w-full" placeholder="Tags" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
        <div className="flex gap-1">
          <Btn type="submit" active>{editing ? "Update" : "Add entry"}</Btn>
          {editing && <Btn type="button" onClick={() => { setEditing(null); setForm(EMPTY); }}>Cancel</Btn>}
        </div>
        <ErrorNote error={err} />
        {stats && !stats.error && (
          <div className="space-y-0.5 border-t border-line pt-2">
            <div className="flex justify-between"><span className="text-fg-mute">Realized (net of fees)</span><span className={cn("num", stats.realized_total >= 0 ? "text-buy" : "text-sell")}>{fmtEGP(stats.realized_total, 2)}</span></div>
            <div className="flex justify-between"><span className="text-fg-mute">Fees paid</span><span className="num">{fmtEGP(stats.fees_total, 2)}</span></div>
            <p className="text-[10px] text-fg-mute">{stats.label}</p>
          </div>
        )}
        {stats?.error && <ErrorNote error={stats.error} />}
      </form>
      <div className="grid min-h-0 grid-rows-[1fr_auto]">
        <DataTable rows={rows} rowKey={(r) => String(r.id)} initialSort={{ key: "trade_date", dir: "desc" }} search searchKeys={[(r) => r.symbol, (r) => r.notes ?? "", (r) => r.thesis ?? "", (r) => r.tags ?? ""]}
          cols={[
            { key: "trade_date", label: "Date" },
            { key: "symbol", label: "Symbol", render: (r) => <span className="font-semibold">{r.symbol}</span> },
            { key: "side", label: "Side", render: (r) => <span className={r.side === "buy" ? "text-buy" : "text-sell"}>{r.side}</span> },
            { key: "quantity", label: "Qty", align: "right", render: (r) => fmtNum(r.quantity) },
            { key: "price", label: "Price", align: "right", render: (r) => fmtPrice(r.price) },
            { key: "fees", label: "Fees", align: "right", render: (r) => fmtNum(r.fees, 2) },
            { key: "origin", label: "Origin", render: (r) => <span className={r.origin === "broker" ? "text-accent" : "text-fg-dim"}>{r.origin}{r.broker_order_id ? ` #${r.broker_order_id}` : ""}</span> },
            { key: "thesis", label: "Thesis", render: (r) => <span className="line-clamp-1 max-w-64 text-fg-dim" title={r.thesis ?? ""}>{r.thesis ?? ""}</span> },
            { key: "act", label: "", render: (r) => (
              <span className="flex gap-1">
                <button className="text-accent" onClick={() => { setEditing(r.id); setForm({ ...r, quantity: String(r.quantity), price: String(r.price), fees: String(r.fees), notes: r.notes ?? "", thesis: r.thesis ?? "", tags: r.tags ?? "" }); }}>edit</button>
                <button className="text-fg-mute hover:text-sell" onClick={() => del.mutate(r.id)}><Trash2 size={11} /></button>
              </span>
            ) },
          ]}
          empty="No journal entries yet"
        />
        <div className="max-h-48 overflow-auto border-t border-line">
          <div className="panel-title px-2 py-1">Closed lots (FIFO) — exit date, net P&L, return</div>
          <DataTable rows={closed} rowKey={(r: any) => r.key} cols={[
            { key: "symbol", label: "Symbol" },
            { key: "entry_ts", label: "Entry" },
            { key: "exit_ts", label: "Exit" },
            { key: "quantity", label: "Qty", align: "right", render: (r: any) => fmtNum(r.quantity) },
            { key: "entry_price", label: "Entry px", align: "right", render: (r: any) => fmtPrice(r.entry_price) },
            { key: "exit_price", label: "Exit px", align: "right", render: (r: any) => fmtPrice(r.exit_price) },
            { key: "fees", label: "Fees", align: "right", render: (r: any) => fmtNum(r.fees, 2) },
            { key: "net_pnl", label: "Net P&L", align: "right", render: (r: any) => <span className={r.net_pnl >= 0 ? "text-buy" : "text-sell"}>{fmtNum(r.net_pnl, 2)}</span> },
            { key: "return_pct", label: "Return", align: "right", render: (r: any) => fmtPct(r.return_pct) },
          ]} empty="No closed lots" />
        </div>
      </div>
    </div>
  );
}

function Reconcile() {
  const qc = useQueryClient();
  const r = useQuery({ queryKey: ["reconcile"], queryFn: () => api("/api/portfolio/reconciliation") });
  const imp = useMutation({
    mutationFn: () => api("/api/portfolio/reconciliation/import", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reconcile"] });
      qc.invalidateQueries({ queryKey: ["journal"] });
    },
  });
  const rows = (r.data?.rows ?? []) as any[];
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-line p-2 text-[11px]">
        <span className="text-fg-dim">Broker-reported fills are matched to journal entries by broker order id. A broker fill is never imported twice.</span>
        <Btn size="xs" className="ml-auto" disabled={!r.data?.importable} onClick={() => imp.mutate()}>Import {r.data?.importable ?? 0} broker fill(s)</Btn>
        {imp.data && <span className="text-accent">created {imp.data.created}, skipped {imp.data.skipped}</span>}
      </div>
      <DataTable rows={rows} rowKey={(x, i) => `${x.status}${x.broker?.order_id ?? ""}${x.journal?.id ?? ""}${i}`}
        cols={[
          { key: "status", label: "Status", render: (x) => <span className={x.status === "matched" ? "text-buy" : x.status === "mismatch" ? "text-sell" : x.status === "broker_only" ? "text-warn" : "text-fg-dim"}>{x.status}</span> },
          { key: "sym", label: "Symbol", value: (x) => x.broker?.symbol ?? x.journal?.symbol },
          { key: "bo", label: "Broker order", value: (x) => x.broker ? `${x.broker.order_id} ${x.broker.side} ${x.broker.quantity}@${x.broker.avg_price ?? x.broker.price}` : "—" },
          { key: "je", label: "Journal entry", value: (x) => x.journal ? `#${x.journal.id} ${x.journal.side} ${x.journal.quantity}@${x.journal.price}` : "—" },
          { key: "note", label: "Note", render: (x) => <span className="text-fg-dim">{x.note}</span> },
        ]}
        empty="Nothing to reconcile"
      />
    </div>
  );
}
