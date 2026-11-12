"use client";

export function ScoreBar({ v, hot }: { v: number | null | undefined; hot?: boolean }) {
  if (v == null) return <span className="text-fg-mute">—</span>;
  const c = hot ? (v >= 55 ? "bg-sell" : v >= 35 ? "bg-warn" : "bg-accent/60") : v >= 60 ? "bg-buy" : v >= 30 ? "bg-warn" : "bg-sell/70";
  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block h-1.5 w-12 overflow-hidden rounded-sm bg-bg-3">
        <span className={`block h-full ${c}`} style={{ width: `${Math.min(100, v)}%` }} />
      </span>
      <span className="w-6 text-right">{v.toFixed(0)}</span>
    </span>
  );
}
