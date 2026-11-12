"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, Search, Wifi, WifiOff } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useTopicData, useNow, useWsStatus } from "@/lib/hooks";
import { fmtCompact, fmtNum, fmtPct, fmtTime } from "@/lib/format";
import { useUi } from "@/store/ui";
import { QualityBadge } from "@/components/ui/primitives";

interface Overview {
  quality: string;
  session: { state: string; source: string };
  market: { status: string | null; traded_value: number | null; traded_volume: number | null; advances: number | null; declines: number | null; unchanged: number | null } | null;
  index: { name: string | null; value: number | null; change_pct: number | null } | null;
  provider: { state: string; detail: string };
}

export function TopBar() {
  const ov = useTopicData<Overview>("market", "market");
  const wsSt = useWsStatus();
  const now = useNow(1000);
  const unread = useUi((s) => s.unread);
  const setSearchOpen = useUi((s) => s.setSearchOpen);
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<{ public_demo: boolean }>("/api/health"), staleTime: 60_000 });
  const m = ov?.market;
  const idx = ov?.index;
  const st = ov?.session?.state ?? "—";
  const stColor = st === "open" ? "text-buy" : st === "pre_open" ? "text-warn" : "text-fg-dim";
  const prov = ov?.provider?.state;
  return (
    <header className="flex h-9 shrink-0 items-center gap-4 border-b border-line bg-bg-1 px-3 text-[11px]">
      <Link href="/" className="flex items-center gap-1.5 font-semibold tracking-wide text-fg">
        <span className="inline-block h-3 w-3 rounded-[2px] bg-gradient-to-br from-accent to-buy" />
        EGX<span className="text-accent">FLOW</span>
      </Link>
      <QualityBadge q={ov?.quality} />
      {health.data?.public_demo && (
        <span className="rounded-sm border border-warn/60 px-1 py-px text-[9px] font-bold tracking-wider text-warn" title="Shared public demo: simulated data, changes are not saved">
          PUBLIC DEMO · READ-ONLY
        </span>
      )}
      <div className="flex items-center gap-1">
        <span className="text-fg-mute">EGX</span>
        <span className={`font-semibold uppercase ${stColor}`}>{st.replace(/_/g, " ")}</span>
        {ov?.session?.source && <span className="text-[9px] text-fg-mute">({ov.session.source})</span>}
      </div>
      <div className="num flex items-center gap-1">
        <span className="text-fg-mute">{idx?.name ?? "EGX30"}</span>
        <span className="text-fg">{fmtNum(idx?.value, 2)}</span>
        <span className={(idx?.change_pct ?? 0) >= 0 ? "text-buy" : "text-sell"}>{fmtPct(idx?.change_pct)}</span>
      </div>
      <div className="num hidden items-center gap-1 lg:flex">
        <span className="text-fg-mute">Turnover</span>
        <span>EGP {fmtCompact(m?.traded_value)}</span>
      </div>
      <div className="num hidden items-center gap-1 lg:flex">
        <span className="text-fg-mute">Volume</span>
        <span>{fmtCompact(m?.traded_volume)}</span>
      </div>
      <div className="num hidden items-center gap-1 xl:flex">
        <span className="text-fg-mute">A/D</span>
        <span className="text-buy">{m?.advances ?? "—"}</span>/<span className="text-sell">{m?.declines ?? "—"}</span>/<span className="text-fg-dim">{m?.unchanged ?? "—"}</span>
      </div>
      <button onClick={() => setSearchOpen(true)} className="ml-auto flex w-56 items-center gap-2 rounded-sm border border-line bg-bg px-2 py-1 text-fg-mute hover:border-line-2">
        <Search size={12} /> Search symbol… <span className="ml-auto text-[9px]">Ctrl K</span>
      </button>
      <Link href="/status" className="flex items-center gap-1" title={`WebSocket ${wsSt.state}; provider ${prov ?? "?"}: ${ov?.provider?.detail ?? ""}`}>
        {wsSt.state === "open" ? <Wifi size={13} className={prov === "connected" ? "text-buy" : "text-warn"} /> : <WifiOff size={13} className="text-sell" />}
        <span className="num text-fg-dim">{wsSt.latencyMs != null ? `${wsSt.latencyMs}ms` : wsSt.state}</span>
      </Link>
      <Link href="/alerts" className="relative" title="Alerts (Alt+A)">
        <Bell size={14} className="text-fg-dim" />
        {unread > 0 && <span className="absolute -right-2 -top-1.5 rounded-full bg-sell px-1 text-[9px] text-white">{unread > 99 ? "99+" : unread}</span>}
      </Link>
      <div className="num text-fg" title="Cairo time (Africa/Cairo)">
        {fmtTime(now)} <span className="text-[9px] text-fg-mute">CAI</span>
      </div>
    </header>
  );
}
