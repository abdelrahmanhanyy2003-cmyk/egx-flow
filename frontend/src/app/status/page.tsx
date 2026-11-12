"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { fmtDateTime, fmtDuration, fmtNum, fmtTime } from "@/lib/format";
import { useWsStatus } from "@/lib/hooks";
import { Btn, cn, ErrorNote, Panel, QualityBadge } from "@/components/ui/primitives";

const CAP_LABELS: Record<string, string> = {
  level1_quotes: "Level 1 quotes",
  depth_levels: "Level 2 depth levels",
  book_resolution: "Order-book resolution",
  trades: "Trade executions",
  trade_side: "Trade-side classification",
  historical_candles: "Historical OHLCV",
  historical_trades: "Historical trades",
  historical_book: "Historical order book",
  streaming: "Streaming",
  market_stats: "Market statistics",
  index_values: "Index values",
  portfolio: "Portfolio",
  open_orders: "Open orders",
  order_history: "Order history",
  investor_type_stats: "Investor-type statistics",
};

function Cap({ v }: { v: unknown }) {
  if (v === true) return <span className="text-buy">available</span>;
  if (v === false || v === 0 || v === "none") return <span className="text-sell">not available</span>;
  if (v === "unverified") return <span className="text-warn">unverified (estimated)</span>;
  if (v === "l1_only") return <span className="text-warn">L1 only</span>;
  return <span className="text-fg">{String(v)}</span>;
}

export default function StatusPage() {
  const s = useQuery({ queryKey: ["sys"], queryFn: () => api("/api/system/status"), refetchInterval: 2000 });
  const wsSt = useWsStatus();
  const check = useMutation({ mutationFn: () => api("/api/auth/live-check", { method: "POST" }) });
  const d = s.data;
  const integ = d?.integration;
  const caps = d?.capabilities ?? {};
  return (
    <div className="grid h-full grid-cols-12 gap-2 overflow-auto p-2 text-[11px]">
      <div className="col-span-12 flex items-center gap-3">
        <h1 className="text-[13px] font-semibold">API Connection Status</h1>
        <QualityBadge q={d?.quality} />
        <span className="text-fg-mute">Cairo {d?.cairo_time ? fmtTime(Date.parse(d.cairo_time)) : "—"}</span>
      </div>
      <ErrorNote error={s.error} />
      <Panel title="EFG Hermes Younit integration" className="col-span-4" bodyClass="space-y-1 p-2">
        <Row k="Data mode" v={integ?.data_mode} />
        <Row k="Younit SDK installed" v={integ?.sdk_installed ? `yes (${integ?.sdk_version})` : "no"} bad={!integ?.sdk_installed} />
        <Row k="Lightstreamer client" v={integ?.lightstreamer_installed ? "yes" : "no"} bad={!integ?.lightstreamer_installed} />
        <Row k="Credentials configured (server-side)" v={integ?.credentials_configured ? "yes" : "no"} bad={!integ?.credentials_configured} />
        <Row k="Read-only mode" v={integ?.read_only ? "enforced" : "?"} />
        <Row k="Init error" v={integ?.init_error ?? "—"} bad={!!integ?.init_error} />
        <Row k="Portfolio error" v={integ?.portfolio_error ?? "—"} bad={!!integ?.portfolio_error} />
        <div className="pt-2">
          <Btn size="xs" disabled={integ?.data_mode !== "live"} onClick={() => check.mutate()}>Run authorized live check</Btn>
          {check.data && <pre className="mt-1 whitespace-pre-wrap text-[10px] text-fg-dim">{JSON.stringify(check.data, null, 2)}</pre>}
          <ErrorNote error={check.error} />
          {integ?.data_mode !== "live" && <p className="mt-1 text-fg-mute">Live checks run only with DATA_MODE=live and credentials in backend/.env.</p>}
        </div>
      </Panel>
      <Panel title="Provider" className="col-span-4" bodyClass="space-y-1 p-2">
        <Row k="Provider" v={d?.provider?.name} />
        <Row k="State" v={d?.provider?.state} bad={d?.provider?.state !== "connected"} />
        <Row k="Detail" v={d?.provider?.detail} />
        <Row k="Connected since" v={fmtDateTime(d?.provider?.connected_since_ms)} />
        <Row k="Last event" v={fmtTime(d?.provider?.last_event_ms)} />
        <Row k="Reconnects / errors / 429s" v={`${d?.provider?.reconnects ?? 0} / ${d?.provider?.errors ?? 0} / ${d?.provider?.rate_limited ?? 0}`} />
        <Row k="Subscriptions" v={(d?.provider?.subscriptions ?? []).join(", ") || "—"} />
        <Row k="Session" v={`${d?.session?.state} (${d?.session?.source})`} />
        <Row k="Browser WebSocket" v={`${wsSt.state} · ${wsSt.latencyMs ?? "?"}ms · ${wsSt.reconnects} reconnects`} />
      </Panel>
      <Panel title="Engine health" className="col-span-4" bodyClass="space-y-1 p-2">
        <Row k="Uptime" v={fmtDuration((d?.uptime_s ?? 0) * 1000)} />
        <Row k="Events processed" v={fmtNum(d?.events_processed)} />
        <Row k="Event loop lag" v={`${d?.loop_lag_ms ?? "—"} ms`} bad={(d?.loop_lag_ms ?? 0) > 100} />
        <Row k="Buffer depth / max" v={`${d?.buffer?.depth ?? 0} / ${d?.buffer?.max_depth ?? 0}`} />
        <Row k="Coalesced / overflow" v={`${fmtNum(d?.buffer?.coalesced)} / ${d?.buffer?.overflow ?? 0}`} bad={(d?.buffer?.overflow ?? 0) > 0} />
        <Row k="Symbols with gaps" v={(d?.buffer?.gap_symbols ?? []).join(", ") || "none"} bad={(d?.buffer?.gap_symbols ?? []).length > 0} />
        <Row k="Stale symbols" v={(d?.stale_symbols ?? []).join(", ") || "none"} bad={(d?.stale_symbols ?? []).length > 0} />
        <Row k="WS clients" v={d?.ws_clients} />
        <Row k="Recorded" v={Object.entries(d?.recorder ?? {}).map(([k, v]) => `${k} ${fmtNum(v as number)}`).join(" · ") || "—"} />
        <Row k="DB rows" v={Object.entries(d?.db ?? {}).map(([k, v]) => `${k} ${fmtNum(v as number)}`).join(" · ")} />
      </Panel>
      <Panel title="Capability matrix (what the connected provider actually delivers)" className="col-span-5">
        <table className="dense w-full">
          <tbody>
            {Object.entries(CAP_LABELS).map(([k, l]) => (
              <tr key={k}><td className="text-fg-dim">{l}</td><td><Cap v={caps[k]} /></td></tr>
            ))}
          </tbody>
        </table>
        <ul className="list-disc space-y-1 p-2 pl-5 text-fg-dim">
          {(caps.notes ?? []).map((n: string) => <li key={n}>{n}</li>)}
        </ul>
      </Panel>
      <Panel title="Data integrity per stream" className="col-span-7">
        <table className="dense num w-full">
          <thead><tr><th>Stream</th><th className="text-right">Gaps</th><th className="text-right">Duplicates</th><th className="text-right">Late</th><th>Last event</th><th>Last received</th></tr></thead>
          <tbody>
            {Object.entries(d?.integrity ?? {}).map(([k, v]: [string, any]) => (
              <tr key={k}>
                <td>{k}</td>
                <td className={cn("text-right", v.gaps && "text-warn")}>{v.gaps}</td>
                <td className="text-right">{v.duplicates}</td>
                <td className={cn("text-right", v.late && "text-warn")}>{v.late}</td>
                <td>{fmtTime(v.last_ts)}</td>
                <td>{fmtTime(v.last_received)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="Provider events" className="col-span-12">
        <table className="dense w-full">
          <tbody>
            {(d?.provider_events ?? []).slice().reverse().map((e: any, i: number) => (
              <tr key={i}><td className="num">{fmtDateTime(e.ts)}</td><td>{e.provider}</td><td>{e.state}</td><td className="text-fg-dim">{e.detail}</td></tr>
            ))}
          </tbody>
        </table>
        {!(d?.provider_events ?? []).length && <div className="p-2 text-fg-mute">No provider state changes recorded</div>}
      </Panel>
    </div>
  );
}

function Row({ k, v, bad }: { k: string; v: unknown; bad?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-fg-mute">{k}</span>
      <span className={cn("num truncate text-right", bad ? "text-warn" : "text-fg")}>{v == null ? "—" : String(v)}</span>
    </div>
  );
}
