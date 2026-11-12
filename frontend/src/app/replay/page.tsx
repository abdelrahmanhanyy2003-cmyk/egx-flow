"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Pause, Play, RotateCcw } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useSeriesTick, useTopicSeries } from "@/lib/hooks";
import { fmtDateTime, fmtNum, fmtTime } from "@/lib/format";
import type { ReplayInfo } from "@/lib/types";
import { DataTable } from "@/components/ui/DataTable";
import { Btn, Panel, QualityBadge } from "@/components/ui/primitives";
import { HeatmapChart } from "@/components/terminal/HeatmapChart";
import { LargeLotTracker, TimeAndSales } from "@/components/terminal/BottomPanels";
import { OrderBookPanel } from "@/components/terminal/SidePanels";

const SPEEDS = [0.5, 1, 2, 5, 10, 30, 60, 120];

function ReplayInner() {
  const params = useSearchParams();
  const [symbol, setSymbol] = useState(params.get("symbol") ?? "");
  const [rid, setRid] = useState<string | null>(null);
  const sessions = useQuery({ queryKey: ["sessions", symbol], queryFn: () => api(`/api/replay/sessions${symbol ? `?symbol=${symbol}` : ""}`) });
  const open = useMutation({ mutationFn: (id: number) => api<ReplayInfo>("/api/replay/open", { method: "POST", json: { session_id: id } }), onSuccess: (r) => setRid(r.id) });
  const series = useTopicSeries(rid ? `replay:${rid}` : null);
  useSeriesTick(series, 250);
  const info = series?.replay;
  const ctl = (action: string, value?: number) => rid && api(`/api/replay/${rid}/control`, { method: "POST", json: { action, value } });

  useEffect(() => {
    const s = params.get("session");
    if (s) open.mutate(Number(s));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rows = (sessions.data?.rows ?? []) as any[];
  return (
    <div className="grid h-full grid-cols-12 grid-rows-[auto_minmax(0,1fr)_240px] gap-2 p-2">
      <div className="col-span-12 flex items-center gap-3 text-[11px]">
        <h1 className="text-[13px] font-semibold">Historical Replay</h1>
        <span className="text-fg-mute">{sessions.data?.note}</span>
      </div>
      <Panel title="Recorded sessions" className="col-span-3 row-span-2" right={<input placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="h-5 w-20 py-0 text-[10px]" />}>
        <DataTable rows={rows} rowKey={(r) => String(r.id)} initialSort={{ key: "date", dir: "desc" }} onRowClick={(r) => open.mutate(r.id)} cols={[
          { key: "date", label: "Date" },
          { key: "symbol", label: "Sym", render: (r) => <span className="font-semibold">{r.symbol}</span> },
          { key: "quality", label: "Data", render: (r) => <QualityBadge q={r.quality} /> },
          { key: "trades", label: "Trades", align: "right", render: (r) => fmtNum(r.trades) },
          { key: "book_resolution", label: "Book", render: (r) => <span className="text-fg-dim" title={`snapshot every ${r.book_record_interval_ms}ms`}>{r.book_resolution === "l1_only" ? "L1" : "depth"}@{r.book_record_interval_ms / 1000}s</span> },
        ]} empty="No recorded sessions" />
      </Panel>
      <div className="col-span-9 flex min-h-0 flex-col border border-line">
        <div className="flex h-9 shrink-0 items-center gap-2 border-b border-line bg-bg-1 px-2 text-[11px]">
          {info ? (
            <>
              <span className="font-semibold">{info.symbol}</span>
              <QualityBadge q={info.quality} />
              <span className="text-fg-mute">book: {info.book_resolution} recorded every {info.book_record_interval_ms / 1000}s</span>
              <Btn size="xs" onClick={() => ctl(info.playing ? "pause" : "play")} active={info.playing}>{info.playing ? <Pause size={12} /> : <Play size={12} />}{info.playing ? "Pause" : "Play"}</Btn>
              <Btn size="xs" onClick={() => ctl("restart")}><RotateCcw size={12} /> Restart</Btn>
              <select value={info.speed} onChange={(e) => ctl("speed", Number(e.target.value))} className="h-6 py-0">
                {SPEEDS.map((s) => <option key={s} value={s}>{s}x</option>)}
              </select>
              <input type="range" className="flex-1 accent-[#2fb4ff]" min={info.start_ts} max={info.end_ts} step={1000} value={info.cursor} onChange={(e) => ctl("seek", Number(e.target.value))} />
              <span className="num w-40 text-right">{fmtTime(info.cursor)} / {fmtTime(info.end_ts)}</span>
            </>
          ) : (
            <span className="text-fg-mute">{open.isPending ? "Loading session…" : "Select a recorded session to replay"}</span>
          )}
        </div>
        <div className="min-h-0 flex-1">
          <HeatmapChart series={series} symbol={info?.symbol ?? "REPLAY"} />
        </div>
      </div>
      <div className="col-span-3 min-h-0 overflow-hidden"><OrderBookPanel series={series} /></div>
      <Panel title="Large trades & walls (replayed)" className="col-span-4"><LargeLotTracker series={series} /></Panel>
      <Panel title={`Tape ${info ? `· session ${fmtDateTime(info.start_ts)}` : ""}`} className="col-span-2"><TimeAndSales series={series} /></Panel>
    </div>
  );
}

export default function ReplayPage() {
  return (
    <Suspense fallback={<div className="p-4 text-fg-mute">Loading…</div>}>
      <ReplayInner />
    </Suspense>
  );
}
