"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BriefcaseBusiness, ChevronDown, ChevronRight, Fish, Plus, Save, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { fmtPct, fmtPrice } from "@/lib/format";
import { useUi } from "@/store/ui";
import { Btn, cn } from "@/components/ui/primitives";

export interface SavedLayout {
  name: string;
  layout: ReturnType<typeof useUi.getState>["layout"];
  heat: ReturnType<typeof useUi.getState>["heat"];
  bubbles: ReturnType<typeof useUi.getState>["bubbles"];
}

export function useSavedLayouts() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["prefs"], queryFn: () => api("/api/prefs") });
  const layouts: SavedLayout[] = q.data?.layouts ?? [];
  const save = useMutation({
    mutationFn: (v: SavedLayout[]) => api("/api/prefs/layouts", { method: "PUT", json: { value: v } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prefs"] }),
  });
  return { layouts, save: (v: SavedLayout[]) => save.mutate(v) };
}

export function applyLayout(l: SavedLayout) {
  const ui = useUi.getState();
  ui.setLayout(l.layout);
  ui.setHeat(l.heat);
  ui.setBubbles(l.bubbles);
}

export function TerminalSidebar() {
  const active = useUi((s) => s.active);
  const openSymbol = useUi((s) => s.openSymbol);
  const watchlist = useUi((s) => s.watchlist);
  const setWatchlist = useUi((s) => s.setWatchlist);
  const [add, setAdd] = useState("");
  const [openSector, setOpenSector] = useState<string | null>(null);
  const [tab, setTab] = useState<"watch" | "all" | "sectors">("watch");
  const { layouts, save } = useSavedLayouts();
  const stocks = useQuery({ queryKey: ["stocks"], queryFn: () => api("/api/stocks"), refetchInterval: 3000 });
  const rows = (stocks.data?.rows ?? []) as any[];
  const bySym = useMemo(() => Object.fromEntries(rows.map((r) => [r.symbol, r])), [rows]);

  // load / persist the default watchlist on the backend
  const wl = useQuery({ queryKey: ["watchlists"], queryFn: () => api("/api/prefs/watchlists") });
  useEffect(() => {
    const d = (wl.data?.rows ?? []).find((r: any) => r.name === "Default");
    if (d?.symbols?.length) setWatchlist(d.symbols);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wl.data]);
  const persistWl = (w: string[]) => {
    setWatchlist(w);
    api("/api/prefs/watchlists", { method: "PUT", json: { name: "Default", symbols: w } }).catch(() => undefined);
  };

  const sectors = useMemo(() => {
    const m = new Map<string, any[]>();
    for (const r of rows) {
      const k = r.sector ?? "Unclassified";
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(r);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [rows]);

  const Row = ({ sym, removable }: { sym: string; removable?: boolean }) => {
    const r = bySym[sym];
    return (
      <div onClick={() => openSymbol(sym)} className={cn("group flex cursor-pointer items-center gap-2 px-2 py-[3px] hover:bg-bg-3", active === sym && "bg-accent/10")}>
        <span className={cn("w-11 font-semibold", active === sym ? "text-accent" : "text-fg")}>{sym}</span>
        <span className="num flex-1 text-right text-fg-dim">{fmtPrice(r?.last)}</span>
        <span className={cn("num w-14 text-right", (r?.change_pct ?? 0) >= 0 ? "text-buy" : "text-sell")}>{fmtPct(r?.change_pct, 2)}</span>
        {removable && (
          <button className="hidden text-fg-mute hover:text-sell group-hover:block" onClick={(e) => { e.stopPropagation(); persistWl(watchlist.filter((x) => x !== sym)); }}>
            <X size={11} />
          </button>
        )}
      </div>
    );
  };

  const saveCurrent = () => {
    const name = window.prompt("Layout name", `Layout ${layouts.length + 1}`);
    if (!name) return;
    const ui = useUi.getState();
    save([...layouts.filter((l) => l.name !== name), { name, layout: ui.layout, heat: ui.heat, bubbles: ui.bubbles }]);
  };

  return (
    <div className="flex h-full flex-col bg-bg-1">
      <div className="flex border-b border-line">
        {(["watch", "all", "sectors"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={cn("flex-1 py-1.5 text-[10px] font-semibold uppercase tracking-wider", tab === t ? "border-b border-accent text-accent" : "text-fg-mute")}>
            {t === "watch" ? "Watchlist" : t === "all" ? "EGX stocks" : "Sectors"}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto text-[11px]">
        {tab === "watch" && (
          <>
            {watchlist.map((s) => <Row key={s} sym={s} removable />)}
            <form
              className="flex gap-1 p-2"
              onSubmit={(e) => {
                e.preventDefault();
                const s = add.trim().toUpperCase();
                if (s && bySym[s] && !watchlist.includes(s)) persistWl([...watchlist, s]);
                setAdd("");
              }}
            >
              <input value={add} onChange={(e) => setAdd(e.target.value)} placeholder="Add symbol" className="h-6 min-w-0 flex-1 text-[11px]" list="egx-syms" />
              <datalist id="egx-syms">{rows.map((r) => <option key={r.symbol} value={r.symbol}>{r.name}</option>)}</datalist>
              <Btn size="xs" type="submit"><Plus size={11} /></Btn>
            </form>
          </>
        )}
        {tab === "all" && rows.map((r) => <Row key={r.symbol} sym={r.symbol} />)}
        {tab === "sectors" &&
          sectors.map(([sec, list]) => {
            const avg = list.filter((r) => r.change_pct != null).reduce((a, r, _, arr) => a + r.change_pct / arr.length, 0);
            return (
              <div key={sec}>
                <button onClick={() => setOpenSector(openSector === sec ? null : sec)} className="flex w-full items-center gap-1 border-b border-line px-2 py-1 text-left hover:bg-bg-3">
                  {openSector === sec ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  <span className="flex-1 truncate text-fg-dim">{sec}</span>
                  <span className="text-fg-mute">{list.length}</span>
                  <span className={cn("num w-14 text-right", avg >= 0 ? "text-buy" : "text-sell")}>{fmtPct(avg)}</span>
                </button>
                {openSector === sec && list.map((r) => <Row key={r.symbol} sym={r.symbol} />)}
              </div>
            );
          })}
      </div>
      <div className="border-t border-line p-2">
        <div className="mb-1 flex items-center justify-between">
          <span className="panel-title">Saved layouts</span>
          <Btn size="xs" onClick={saveCurrent} title="Save current layout"><Save size={11} /> Save</Btn>
        </div>
        <div className="max-h-28 space-y-0.5 overflow-auto">
          {layouts.map((l, i) => (
            <div key={l.name} className="group flex items-center justify-between text-[11px]">
              <button className="truncate text-left text-fg-dim hover:text-accent" onClick={() => applyLayout(l)} title={i < 4 ? `Ctrl+${i + 1}` : undefined}>
                {i < 4 && <span className="num mr-1 text-fg-mute">{i + 1}</span>}{l.name}
              </button>
              <button className="hidden text-fg-mute hover:text-sell group-hover:block" onClick={() => save(layouts.filter((x) => x.name !== l.name))}><X size={11} /></button>
            </div>
          ))}
          {!layouts.length && <div className="text-[10px] text-fg-mute">No saved layouts</div>}
        </div>
      </div>
      <div className="grid grid-cols-3 gap-1 border-t border-line p-2">
        <Link href="/portfolio"><Btn size="xs" className="w-full justify-center"><BriefcaseBusiness size={11} /> Portfolio</Btn></Link>
        <Link href="/whales"><Btn size="xs" className="w-full justify-center"><Fish size={11} /> Whales</Btn></Link>
        <Link href="/alerts"><Btn size="xs" className="w-full justify-center"><Bell size={11} /> Alerts</Btn></Link>
      </div>
    </div>
  );
}
