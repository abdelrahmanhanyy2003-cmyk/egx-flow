"use client";

import { Crosshair, Minus, Radio, Settings2, Trash2, ZoomIn, ZoomOut } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Series } from "@/lib/series";
import { useUi } from "@/store/ui";
import { Btn, Slider, Toggle } from "@/components/ui/primitives";
import { HeatmapEngine } from "./engine/HeatmapEngine";

export interface HeatmapHandle {
  zoomTime: (f: number) => void;
  zoomPrice: (f: number) => void;
  goLive: () => void;
}

interface Props {
  series: Series | null;
  symbol: string;
  entryPrice?: number | null;
  compact?: boolean;
}

export const HeatmapChart = forwardRef<HeatmapHandle, Props>(function HeatmapChart({ series, symbol, entryPrice, compact }, ref) {
  const mainRef = useRef<HTMLCanvasElement>(null);
  const volRef = useRef<HTMLCanvasElement>(null);
  const cvdRef = useRef<HTMLCanvasElement>(null);
  const engine = useRef<HeatmapEngine | null>(null);
  const heat = useUi((s) => s.heat);
  const bubbles = useUi((s) => s.bubbles);
  const drawings = useUi((s) => s.drawings[symbol]);
  const drawTool = useUi((s) => s.drawTool);
  const addDrawing = useUi((s) => s.addDrawing);
  const removeDrawing = useUi((s) => s.removeDrawing);
  const clearDrawings = useUi((s) => s.clearDrawings);
  const setDrawTool = useUi((s) => s.setDrawTool);
  const setHeat = useUi((s) => s.setHeat);
  const setBubbles = useUi((s) => s.setBubbles);
  const [follow, setFollow] = useState(true);
  const [showCfg, setShowCfg] = useState(false);

  const opts = {
    heat,
    bubbles,
    drawings: drawings ?? [],
    entryPrice,
    drawTool,
    onAddDrawing: (price: number) => {
      addDrawing(symbol, { id: `${Date.now()}`, price, color: "#2fb4ff" });
      setDrawTool("none");
    },
    onRemoveDrawing: (id: string) => removeDrawing(symbol, id),
    onFollowChange: setFollow,
  };

  useEffect(() => {
    if (!mainRef.current) return;
    const e = new HeatmapEngine(mainRef.current, volRef.current, cvdRef.current, opts);
    engine.current = e;
    // dev-only handle for profiling: window.__egxEngine.benchmark(300)
    if (process.env.NODE_ENV !== "production") (window as unknown as { __egxEngine?: HeatmapEngine }).__egxEngine = e;
    return () => e.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    engine.current?.setSeries(series);
    setFollow(true);
  }, [series]);

  useEffect(() => {
    engine.current?.setOptions(opts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heat, bubbles, drawings, entryPrice, drawTool, symbol]);

  useImperativeHandle(ref, () => ({
    zoomTime: (f) => engine.current?.zoomTime(f),
    zoomPrice: (f) => engine.current?.zoomPrice(f),
    goLive: () => engine.current?.goLive(),
  }));

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div className="flex h-7 shrink-0 items-center gap-1 border-b border-line bg-bg-1 px-1.5">
        <Btn size="xs" active={heat.showHeatmap} onClick={() => setHeat({ showHeatmap: !heat.showHeatmap })} title="Toggle heatmap (H)">Heatmap</Btn>
        <Btn size="xs" active={bubbles.show} onClick={() => setBubbles({ show: !bubbles.show })} title="Toggle volume bubbles (B)">Bubbles</Btn>
        <Btn size="xs" active={heat.showProfile} onClick={() => setHeat({ showProfile: !heat.showProfile })} title="Toggle volume profile (P)">Profile</Btn>
        {heat.showProfile && (
          <Btn size="xs" onClick={() => setHeat({ profileMode: heat.profileMode === "session" ? "visible" : "session" })} title="Session vs visible-range profile">
            {heat.profileMode === "session" ? "Session" : "Visible"}
          </Btn>
        )}
        <Btn size="xs" active={heat.showBBO} onClick={() => setHeat({ showBBO: !heat.showBBO })}>BBO</Btn>
        <Btn size="xs" active={heat.showVwap} onClick={() => setHeat({ showVwap: !heat.showVwap })}>VWAP</Btn>
        {!compact && (
          <>
            <Btn size="xs" active={heat.showVolume} onClick={() => setHeat({ showVolume: !heat.showVolume })}>Volume</Btn>
            <Btn size="xs" active={heat.showCvd} onClick={() => setHeat({ showCvd: !heat.showCvd })}>CVD</Btn>
          </>
        )}
        <span className="mx-1 h-4 w-px bg-line" />
        <Btn size="xs" active={drawTool === "hline"} onClick={() => setDrawTool(drawTool === "hline" ? "none" : "hline")} title="Horizontal line tool: click on chart. Right-click a line to delete.">
          <Minus size={12} /> Line
        </Btn>
        <Btn size="xs" onClick={() => clearDrawings(symbol)} title="Clear drawings"><Trash2 size={12} /></Btn>
        <span className="mx-1 h-4 w-px bg-line" />
        <Btn size="xs" onClick={() => engine.current?.zoomTime(1 / 1.3)} title="Zoom in (+)"><ZoomIn size={12} /></Btn>
        <Btn size="xs" onClick={() => engine.current?.zoomTime(1.3)} title="Zoom out (-)"><ZoomOut size={12} /></Btn>
        <Btn size="xs" active={follow} onClick={() => engine.current?.goLive()} title="Follow live (F / double-click)">
          {follow ? <Radio size={12} /> : <Crosshair size={12} />} {follow ? "Live" : "Follow"}
        </Btn>
        <div className="ml-auto" />
        <Btn size="xs" active={showCfg} onClick={() => setShowCfg(!showCfg)} title="Heatmap & bubble settings"><Settings2 size={12} /> Settings</Btn>
      </div>
      {showCfg && (
        <div className="absolute right-1 top-8 z-30 w-80 space-y-2 border border-line-2 bg-bg-2 p-3 shadow-xl">
          <div className="panel-title">Heatmap</div>
          <Slider label="Sensitivity" value={heat.sensitivity} min={0.2} max={4} step={0.05} onChange={(v) => setHeat({ sensitivity: v })} fmt={(v) => v.toFixed(2) + "x"} />
          <Slider label="Contrast (gamma)" value={heat.gamma} min={0.3} max={1.5} step={0.05} onChange={(v) => setHeat({ gamma: v })} fmt={(v) => v.toFixed(2)} />
          <label className="flex items-center gap-2 text-[10px] text-fg-dim">
            <span className="w-24">Palette</span>
            <select value={heat.palette} onChange={(e) => setHeat({ palette: e.target.value as "classic" })}>
              <option value="classic">Classic (navy-cyan-yellow-red)</option>
              <option value="thermal">Thermal</option>
              <option value="mono">Mono blue</option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-1">
            <Toggle label="Walls" checked={heat.showWalls} onChange={(b) => setHeat({ showWalls: b })} />
            <Toggle label="Iceberg marks" checked={heat.showIcebergs} onChange={(b) => setHeat({ showIcebergs: b })} />
          </div>
          <Slider label="Volume bars TF" value={heat.volumeTfMs / 1000} min={1} max={300} step={1} onChange={(v) => setHeat({ volumeTfMs: v * 1000 })} fmt={(v) => v + "s"} />
          <Slider label="CVD MA period" value={heat.cvdMa} min={2} max={200} step={1} onChange={(v) => setHeat({ cvdMa: v })} />
          <div className="panel-title pt-1">Volume bubbles</div>
          <Slider label="Min size" value={bubbles.minSize} min={1} max={10} step={0.5} onChange={(v) => setBubbles({ minSize: v })} fmt={(v) => v + "px"} />
          <Slider label="Max size" value={bubbles.maxSize} min={6} max={60} step={1} onChange={(v) => setBubbles({ maxSize: v })} fmt={(v) => v + "px"} />
          <Slider label="Min value" value={bubbles.minValue} min={0} max={2_000_000} step={10_000} onChange={(v) => setBubbles({ minValue: v })} fmt={(v) => (v / 1000).toFixed(0) + "K EGP"} />
          <Slider label="Transparency" value={bubbles.alpha} min={0.1} max={1} step={0.05} onChange={(v) => setBubbles({ alpha: v })} fmt={(v) => Math.round(v * 100) + "%"} />
          <Slider label="Time aggregation" value={bubbles.aggregationMs / 1000} min={0.25} max={60} step={0.25} onChange={(v) => setBubbles({ aggregationMs: v * 1000 })} fmt={(v) => v + "s"} />
          <Toggle label="Cluster across prices within a bucket" checked={bubbles.cluster} onChange={(b) => setBubbles({ cluster: b })} />
          <p className="pt-1 text-[10px] leading-snug text-fg-mute">
            Filled bubbles = provider/exchange aggressor side. Hollow rings = side estimated (quote/tick rule). Grey = side unknown.
          </p>
        </div>
      )}
      <div className="relative min-h-0 flex-1">
        <canvas ref={mainRef} className={`absolute inset-0 h-full w-full ${drawTool === "hline" ? "cursor-crosshair" : "cursor-default"}`} />
      </div>
      <div className={heat.showVolume && !compact ? "h-[70px] shrink-0 border-t border-line" : "hidden"}>
        <canvas ref={volRef} className="h-full w-full" />
      </div>
      <div className={heat.showCvd && !compact ? "h-[90px] shrink-0 border-t border-line" : "hidden"}>
        <canvas ref={cvdRef} className="h-full w-full" />
      </div>
    </div>
  );
});
