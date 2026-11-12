"use client";

import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { fmtTime } from "@/lib/format";
import type { AlertItem } from "@/lib/types";
import { useUi } from "@/store/ui";
import { QualityBadge } from "@/components/ui/primitives";

let audioCtx: AudioContext | null = null;

export function playAlertSound(sev: string) {
  try {
    audioCtx ??= new AudioContext();
    const ctx = audioCtx;
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = "sine";
    o.frequency.value = sev === "critical" ? 980 : sev === "warning" ? 740 : 560;
    g.gain.setValueAtTime(0.0001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.27);
  } catch {
    /* audio unavailable */
  }
}

export function AlertToaster() {
  const alerts = useUi((s) => s.alerts);
  const [visible, setVisible] = useState<AlertItem[]>([]);
  const [seen, setSeen] = useState(0);
  useEffect(() => {
    if (!alerts.length) return;
    const top = alerts[0];
    const key = `${top.id ?? top.ts}`;
    if (Number(key) === seen) return;
    setSeen(Number(key));
    setVisible((v) => [top, ...v].slice(0, 4));
    const t = setTimeout(() => setVisible((v) => v.filter((x) => x !== top)), 7000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alerts]);
  return (
    <div className="pointer-events-none fixed bottom-3 right-3 z-50 flex w-96 flex-col gap-2">
      {visible.map((a, i) => (
        <div key={`${a.id ?? a.ts}-${i}`} className={`pointer-events-auto border-l-2 bg-bg-2/95 p-2 shadow-lg backdrop-blur ${a.severity === "critical" ? "border-sell" : a.severity === "warning" ? "border-warn" : "border-accent"}`}>
          <div className="flex items-center gap-2 text-[10px] text-fg-mute">
            <span className="font-semibold uppercase">{a.label ?? a.rule}</span>
            {a.symbol && <span className="text-fg">{a.symbol}</span>}
            <QualityBadge q={a.quality} />
            <span className="num ml-auto">{fmtTime(a.ts)}</span>
            <button onClick={() => setVisible((v) => v.filter((x) => x !== a))}><X size={11} /></button>
          </div>
          <div className="mt-0.5 text-[11px] text-fg">{a.message}</div>
        </div>
      ))}
    </div>
  );
}
