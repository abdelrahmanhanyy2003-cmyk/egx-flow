"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { fmtPct, fmtPrice } from "@/lib/format";
import { useUi } from "@/store/ui";

export function SymbolSearch() {
  const open = useUi((s) => s.searchOpen);
  const setOpen = useUi((s) => s.setSearchOpen);
  const openSymbol = useUi((s) => s.openSymbol);
  const router = useRouter();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const data = useQuery({ queryKey: ["stocks"], queryFn: () => api("/api/stocks"), enabled: open, refetchInterval: open ? 5000 : false });
  const rows = useMemo(() => {
    const all = (data.data?.rows ?? []) as any[];
    const s = q.trim().toUpperCase();
    return all.filter((r) => !s || r.symbol.includes(s) || (r.name ?? "").toUpperCase().includes(s)).slice(0, 12);
  }, [data.data, q]);
  useEffect(() => {
    if (open) {
      setQ("");
      setSel(0);
      setTimeout(() => input.current?.focus(), 10);
    }
  }, [open]);
  if (!open) return null;
  const choose = (sym: string) => {
    openSymbol(sym);
    setOpen(false);
    router.push("/");
  };
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-24" onClick={() => setOpen(false)}>
      <div className="w-[520px] border border-line-2 bg-bg-2 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <input
          ref={input}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setSel(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") setSel((s) => Math.min(rows.length - 1, s + 1));
            else if (e.key === "ArrowUp") setSel((s) => Math.max(0, s - 1));
            else if (e.key === "Enter" && rows[sel]) choose(rows[sel].symbol);
            else if (e.key === "Escape") setOpen(false);
          }}
          placeholder="Search EGX symbol or company…"
          className="w-full rounded-none border-0 border-b border-line bg-bg-2 px-3 py-2.5 text-[13px]"
        />
        <ul className="max-h-96 overflow-auto">
          {rows.map((r, i) => (
            <li key={r.symbol} onMouseEnter={() => setSel(i)} onClick={() => choose(r.symbol)} className={`flex cursor-pointer items-center gap-3 px-3 py-1.5 ${i === sel ? "bg-accent/15" : ""}`}>
              <span className="w-14 font-semibold text-fg">{r.symbol}</span>
              <span className="flex-1 truncate text-fg-dim">{r.name}</span>
              <span className="num w-16 text-right">{fmtPrice(r.last)}</span>
              <span className={`num w-16 text-right ${(r.change_pct ?? 0) >= 0 ? "text-buy" : "text-sell"}`}>{fmtPct(r.change_pct)}</span>
            </li>
          ))}
          {!rows.length && <li className="px-3 py-3 text-fg-mute">No matches</li>}
        </ul>
      </div>
    </div>
  );
}
