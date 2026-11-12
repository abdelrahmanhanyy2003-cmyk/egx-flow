"use client";

import { useState } from "react";
import { accessToken, API_BASE, setAccessToken } from "@/lib/api";
import { ws } from "@/lib/ws";
import { DEFAULT_LAYOUT, useUi } from "@/store/ui";
import { Btn, Panel, Slider, Toggle } from "@/components/ui/primitives";
import { SHORTCUTS } from "@/components/shell/ShortcutsDialog";

export default function SettingsPage() {
  const heat = useUi((s) => s.heat);
  const bubbles = useUi((s) => s.bubbles);
  const setHeat = useUi((s) => s.setHeat);
  const setBubbles = useUi((s) => s.setBubbles);
  const setLayout = useUi((s) => s.setLayout);
  const sound = useUi((s) => s.sound);
  const setSound = useUi((s) => s.setSound);
  const [tok, setTok] = useState(() => (typeof window !== "undefined" ? accessToken() ?? "" : ""));
  return (
    <div className="grid h-full grid-cols-3 gap-2 overflow-auto p-2">
      <Panel title="Heatmap" bodyClass="space-y-2 p-3">
        <Slider label="Sensitivity" value={heat.sensitivity} min={0.2} max={4} step={0.05} onChange={(v) => setHeat({ sensitivity: v })} fmt={(v) => v.toFixed(2) + "x"} />
        <Slider label="Contrast (gamma)" value={heat.gamma} min={0.3} max={1.5} step={0.05} onChange={(v) => setHeat({ gamma: v })} />
        <label className="flex items-center gap-2 text-[11px] text-fg-dim">Palette
          <select value={heat.palette} onChange={(e) => setHeat({ palette: e.target.value as "classic" })}>
            <option value="classic">Classic</option><option value="thermal">Thermal</option><option value="mono">Mono blue</option>
          </select>
        </label>
        <Toggle label="Best bid/ask lines" checked={heat.showBBO} onChange={(b) => setHeat({ showBBO: b })} />
        <Toggle label="Session VWAP" checked={heat.showVwap} onChange={(b) => setHeat({ showVwap: b })} />
        <Toggle label="Volume profile" checked={heat.showProfile} onChange={(b) => setHeat({ showProfile: b })} />
        <Toggle label="Wall markers" checked={heat.showWalls} onChange={(b) => setHeat({ showWalls: b })} />
        <Toggle label="Iceberg markers (estimated)" checked={heat.showIcebergs} onChange={(b) => setHeat({ showIcebergs: b })} />
        <Slider label="Volume bars TF" value={heat.volumeTfMs / 1000} min={1} max={300} step={1} onChange={(v) => setHeat({ volumeTfMs: v * 1000 })} fmt={(v) => v + "s"} />
        <Slider label="CVD MA period" value={heat.cvdMa} min={2} max={200} step={1} onChange={(v) => setHeat({ cvdMa: v })} />
        <p className="text-[10px] text-fg-mute">CVD resets each EGX session (Africa/Cairo date). Trades with unknown aggressor side are excluded from CVD and counted separately.</p>
      </Panel>
      <Panel title="Volume bubbles" bodyClass="space-y-2 p-3">
        <Toggle label="Show bubbles" checked={bubbles.show} onChange={(b) => setBubbles({ show: b })} />
        <Slider label="Min size" value={bubbles.minSize} min={1} max={10} step={0.5} onChange={(v) => setBubbles({ minSize: v })} />
        <Slider label="Max size" value={bubbles.maxSize} min={6} max={60} step={1} onChange={(v) => setBubbles({ maxSize: v })} />
        <Slider label="Min value (EGP)" value={bubbles.minValue} min={0} max={2_000_000} step={10_000} onChange={(v) => setBubbles({ minValue: v })} fmt={(v) => (v / 1000).toFixed(0) + "K"} />
        <Slider label="Transparency" value={bubbles.alpha} min={0.1} max={1} step={0.05} onChange={(v) => setBubbles({ alpha: v })} />
        <Slider label="Time aggregation" value={bubbles.aggregationMs / 1000} min={0.25} max={60} step={0.25} onChange={(v) => setBubbles({ aggregationMs: v * 1000 })} fmt={(v) => v + "s"} />
        <Toggle label="Cluster across prices" checked={bubbles.cluster} onChange={(b) => setBubbles({ cluster: b })} />
        <div className="panel-title pt-3">Notifications</div>
        <Toggle label="Sound notifications" checked={sound} onChange={setSound} />
        <div className="panel-title pt-3">Layout</div>
        <Btn onClick={() => setLayout(DEFAULT_LAYOUT)}>Reset terminal layout</Btn>
      </Panel>
      <Panel title="Connection & security" bodyClass="space-y-2 p-3 text-[11px]">
        <div><span className="text-fg-mute">Backend:</span> <span className="num">{API_BASE}</span></div>
        <p className="text-fg-dim">Broker credentials (TRADING_ID / API_KEY) are configured only in the backend <code>.env</code>. They are never sent to, stored in, or bundled into this frontend.</p>
        <label className="block text-fg-dim">Local API access token (optional, only if the backend sets APP_ACCESS_TOKEN). Kept in this browser tab&apos;s session storage only.</label>
        <div className="flex gap-1">
          <input type="password" value={tok} onChange={(e) => setTok(e.target.value)} className="flex-1" autoComplete="off" />
          <Btn onClick={() => { setAccessToken(tok || null); ws.reconnectNow(); }}>Apply</Btn>
        </div>
        <div className="panel-title pt-3">Keyboard shortcuts</div>
        <table className="w-full">
          <tbody>
            {SHORTCUTS.map(([k, d]) => (
              <tr key={k} className="border-t border-line"><td className="num py-0.5 pr-2 text-accent">{k}</td><td className="text-fg-dim">{d}</td></tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
