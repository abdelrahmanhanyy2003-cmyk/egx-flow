"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Volume2, VolumeX } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useUi } from "@/store/ui";
import { DataTable } from "@/components/ui/DataTable";
import { Btn, ErrorNote, Panel, QualityBadge } from "@/components/ui/primitives";
import { playAlertSound } from "@/components/shell/AlertToaster";

export default function AlertsPage() {
  const qc = useQueryClient();
  const markRead = useUi((s) => s.markRead);
  const sound = useUi((s) => s.sound);
  const setSound = useUi((s) => s.setSound);
  const live = useUi((s) => s.alerts);
  const [filter, setFilter] = useState({ symbol: "", rule: "" });
  const hist = useQuery({
    queryKey: ["alerts", filter, live.length],
    queryFn: () => api(`/api/alerts?limit=500${filter.symbol ? `&symbol=${filter.symbol}` : ""}${filter.rule ? `&rule=${filter.rule}` : ""}`),
  });
  const rules = useQuery({ queryKey: ["rules"], queryFn: () => api("/api/alerts/rules") });
  const ack = useMutation({ mutationFn: (ids?: number[]) => api("/api/alerts/ack", { method: "POST", json: { ids: ids ?? null } }), onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }) });
  useEffect(() => markRead(), [markRead, live.length]);
  const catalogue = (rules.data?.catalogue ?? {}) as Record<string, { label: string; severity: string; params: Record<string, number | null> }>;
  const overrides = (rules.data?.overrides ?? []) as any[];
  return (
    <div className="grid h-full grid-cols-12 grid-rows-[auto_1fr] gap-2 p-2">
      <div className="col-span-12 flex items-center gap-3 text-[11px]">
        <h1 className="text-[13px] font-semibold">Alerts Center</h1>
        <Btn size="xs" active={sound} onClick={() => setSound(!sound)}>{sound ? <Volume2 size={12} /> : <VolumeX size={12} />} Sound {sound ? "on" : "off"}</Btn>
        <Btn size="xs" onClick={() => playAlertSound("warning")}>Test sound</Btn>
        <span className="text-fg-mute">Every alert has a unique dedup key (rule + symbol + event identity / cooldown bucket) enforced in the database — the same event never notifies twice.</span>
      </div>
      <Panel title="Alert history" className="col-span-7" right={
        <div className="flex items-center gap-1">
          <input placeholder="Symbol" value={filter.symbol} onChange={(e) => setFilter({ ...filter, symbol: e.target.value.toUpperCase() })} className="h-5 w-16 py-0 text-[10px]" />
          <select value={filter.rule} onChange={(e) => setFilter({ ...filter, rule: e.target.value })} className="h-5 py-0 text-[10px]">
            <option value="">All rules</option>
            {Object.entries(catalogue).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <Btn size="xs" onClick={() => ack.mutate(undefined)}>Acknowledge all</Btn>
        </div>
      }>
        <DataTable rows={hist.data?.rows ?? []} rowKey={(r: any) => String(r.id)} initialSort={{ key: "ts", dir: "desc" }} search searchKeys={[(r: any) => r.message, (r: any) => r.symbol ?? ""]}
          cols={[
            { key: "ts", label: "Time (Cairo)", render: (r: any) => <span className={r.acknowledged ? "text-fg-mute" : "text-fg"}>{fmtDateTime(r.ts)}</span> },
            { key: "severity", label: "Sev", render: (r: any) => <span className={r.severity === "critical" ? "text-sell" : r.severity === "warning" ? "text-warn" : "text-accent"}>{r.severity}</span> },
            { key: "symbol", label: "Sym" },
            { key: "rule", label: "Rule", render: (r: any) => catalogue[r.rule]?.label ?? r.rule },
            { key: "message", label: "Message", render: (r: any) => <span className="text-fg-dim">{r.message}</span> },
            { key: "quality", label: "Data", render: (r: any) => <QualityBadge q={r.quality} /> },
            { key: "ack", label: "", render: (r: any) => (!r.acknowledged ? <button className="text-accent" onClick={() => ack.mutate([r.id])}>ack</button> : null) },
          ]}
          empty="No alerts yet"
        />
      </Panel>
      <Panel title="Rules & thresholds" className="col-span-5" bodyClass="overflow-auto">
        <RuleEditor catalogue={catalogue} overrides={overrides} />
      </Panel>
    </div>
  );
}

function RuleEditor({ catalogue, overrides }: { catalogue: Record<string, any>; overrides: any[] }) {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: (b: any) => api("/api/alerts/rules", { method: "PUT", json: b }),
    onSuccess: () => {
      setErr(null);
      qc.invalidateQueries({ queryKey: ["rules"] });
    },
    onError: setErr,
  });
  const del = useMutation({ mutationFn: (id: number) => api(`/api/alerts/rules/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }) });
  const sym = symbol.trim().toUpperCase() || null;
  const find = (rule: string, s: string | null) => overrides.find((o) => o.rule === rule && o.symbol === s);
  return (
    <div className="space-y-2 p-2 text-[11px]">
      <div className="flex items-center gap-2">
        <span className="text-fg-dim">Scope:</span>
        <input placeholder="Global (blank) or symbol e.g. COMI" value={symbol} onChange={(e) => setSymbol(e.target.value)} className="h-6 flex-1" />
      </div>
      <ErrorNote error={err} />
      {Object.entries(catalogue).map(([rule, def]) => {
        const glob = find(rule, null);
        const own = find(rule, sym);
        const eff = { enabled: true, sound: true, ...(glob ?? {}), ...(own ?? {}) };
        const params = { ...def.params, ...(glob?.params ?? {}), ...(own?.params ?? {}) };
        return (
          <RuleRow key={rule + (sym ?? "")} rule={rule} label={def.label} severity={def.severity} params={params} enabled={eff.enabled} sound={eff.sound} own={own}
            onSave={(p, enabled, sound) => save.mutate({ rule, symbol: sym, enabled, sound, params: p })}
            onReset={own ? () => del.mutate(own.id) : undefined}
          />
        );
      })}
    </div>
  );
}

function RuleRow({ rule, label, severity, params, enabled, sound, own, onSave, onReset }: {
  rule: string; label: string; severity: string; params: Record<string, number | null>; enabled: boolean; sound: boolean; own?: any;
  onSave: (p: Record<string, number | null>, enabled: boolean, sound: boolean) => void; onReset?: () => void;
}) {
  const [p, setP] = useState(params);
  const [en, setEn] = useState(enabled);
  const [snd, setSnd] = useState(sound);
  return (
    <div className="border border-line p-1.5">
      <div className="flex items-center gap-2">
        <input type="checkbox" checked={en} onChange={(e) => setEn(e.target.checked)} />
        <span className="flex-1 font-semibold text-fg">{label}</span>
        <span className={severity === "critical" ? "text-sell" : severity === "warning" ? "text-warn" : "text-accent"}>{severity}</span>
        <label className="flex items-center gap-1 text-fg-dim"><input type="checkbox" checked={snd} onChange={(e) => setSnd(e.target.checked)} />sound</label>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        {Object.entries(p).map(([k, v]) => (
          <label key={k} className="flex items-center gap-1 text-fg-dim">
            {k.replace(/_/g, " ")}
            <input type="number" step="any" value={v ?? ""} onChange={(e) => setP({ ...p, [k]: e.target.value === "" ? null : Number(e.target.value) })} className="h-5 w-24 py-0" />
          </label>
        ))}
        <Btn size="xs" className="ml-auto" onClick={() => onSave(p, en, snd)}>Save</Btn>
        {onReset && <Btn size="xs" onClick={onReset} title="Remove this override">Reset</Btn>}
        {own && <span className="text-[9px] text-accent">override</span>}
      </div>
      <span className="hidden">{rule}</span>
    </div>
  );
}
