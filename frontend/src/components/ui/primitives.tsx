"use client";

import { clsx } from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Quality } from "@/lib/types";

export function cn(...a: (string | false | null | undefined)[]) {
  return clsx(a);
}

export function Btn({ className, active, size = "sm", ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean; size?: "xs" | "sm" }) {
  return (
    <button
      {...p}
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border transition-colors disabled:opacity-40",
        size === "xs" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-[11px]",
        active ? "border-accent/60 bg-accent/15 text-accent" : "border-line bg-bg-2 text-fg-dim hover:border-line-2 hover:text-fg",
        className,
      )}
    />
  );
}

export function Panel({ title, right, children, className, bodyClass }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; bodyClass?: string }) {
  return (
    <section className={cn("flex min-h-0 flex-col border border-line bg-bg-1", className)}>
      {title !== undefined && (
        <header className="flex h-7 shrink-0 items-center justify-between border-b border-line px-2">
          <span className="panel-title">{title}</span>
          <div className="flex items-center gap-1">{right}</div>
        </header>
      )}
      <div className={cn("min-h-0 flex-1", bodyClass)}>{children}</div>
    </section>
  );
}

const QUALITY_STYLE: Record<string, string> = {
  live: "border-buy/50 text-buy",
  delayed: "border-warn/60 text-warn",
  historical: "border-accent/50 text-accent",
  simulated: "border-demo/60 text-demo",
};

export function QualityBadge({ q, className }: { q: Quality | string | null | undefined; className?: string }) {
  if (!q) return null;
  const label = q === "simulated" ? "DEMO" : q.toUpperCase();
  return <span className={cn("rounded-sm border px-1 py-px text-[9px] font-bold tracking-wider", QUALITY_STYLE[q] ?? "border-line text-fg-dim", className)}>{label}</span>;
}

export function EstBadge({ title = "Estimated (heuristic / inferred)" }: { title?: string }) {
  return (
    <span title={title} className="rounded-sm border border-warn/50 px-1 text-[9px] font-semibold text-warn">
      EST
    </span>
  );
}

export function Stat({ label, value, sub, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex min-w-0 flex-col", className)}>
      <span className="truncate text-[9px] uppercase tracking-wider text-fg-mute">{label}</span>
      <span className="num truncate text-[13px] text-fg">{value}</span>
      {sub && <span className="num truncate text-[10px] text-fg-dim">{sub}</span>}
    </div>
  );
}

export function Slider({ label, value, min, max, step, onChange, fmt }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; fmt?: (v: number) => string }) {
  return (
    <label className="flex items-center gap-2 text-[10px] text-fg-dim">
      <span className="w-24 shrink-0">{label}</span>
      <input type="range" className="flex-1 accent-[#2fb4ff]" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      <span className="num w-14 text-right text-fg">{fmt ? fmt(value) : value}</span>
    </label>
  );
}

export function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (b: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-[11px] text-fg-dim hover:text-fg">
      <input type="checkbox" className="accent-[#2fb4ff]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="flex h-full min-h-16 items-center justify-center p-3 text-center text-[11px] text-fg-mute">{children}</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="m-2 rounded-sm border border-sell/40 bg-sell/10 p-2 text-[11px] text-sell">{String((error as Error).message ?? error)}</div>;
}
