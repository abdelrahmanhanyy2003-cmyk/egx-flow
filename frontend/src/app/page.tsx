"use client";

import { ArrowDown, ArrowLeftRight, ArrowUp, PanelBottomClose, PanelLeftClose, PanelRightClose, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { Panel as RPanel, PanelGroup, PanelResizeHandle, type ImperativePanelGroupHandle, type ImperativePanelHandle } from "react-resizable-panels";
import { useSeriesTick, useTopicSeries } from "@/lib/hooks";
import type { Series } from "@/lib/series";
import { fmtCompact, fmtPct, fmtPrice } from "@/lib/format";
import { useUi } from "@/store/ui";
import { Btn, cn, QualityBadge } from "@/components/ui/primitives";
import { HeatmapChart, type HeatmapHandle } from "@/components/terminal/HeatmapChart";
import { DepthPanel, ImbalancePanel, OrderBookPanel, ProfileStatsPanel } from "@/components/terminal/SidePanels";
import { CvdPanel, FlowPanel, LargeLotTracker, ReplayLauncher, StudiesPanel, TimeAndSales, VolumeAnalysis } from "@/components/terminal/BottomPanels";
import { applyLayout, TerminalSidebar, useSavedLayouts } from "@/components/terminal/TerminalSidebar";

const BOTTOM_LABELS: Record<string, string> = {
  tape: "Time & Sales",
  llt: "Large Lot Tracker",
  volume: "Volume analysis",
  cvd: "CVD",
  studies: "Studies",
  flow: "Whale score · flow",
  replay: "Replay",
};

const RIGHT_WIDGETS: Record<string, (s: Series | null) => React.ReactNode> = {
  book: (s) => <OrderBookPanel series={s} />,
  imbalance: (s) => <ImbalancePanel series={s} />,
  depth: (s) => <DepthPanel series={s} />,
  profile: (s) => <ProfileStatsPanel series={s} />,
};
const RIGHT_LABELS: Record<string, string> = { book: "Order book", imbalance: "Imbalance", depth: "Depth", profile: "Session/profile" };

function SymbolHeader({ series }: { series: Series | null }) {
  useSeriesTick(series, 300);
  const st = series?.stats;
  const inst = series?.instrument;
  return (
    <div className="flex min-w-0 items-center gap-4 whitespace-nowrap px-2 text-[11px]">
      <span className="hidden max-w-56 truncate text-fg-dim 2xl:inline">{inst?.name}</span>
      {st && (
        <>
          <span className="num text-[14px] text-fg">{fmtPrice(st.last, st.tick)}</span>
          <span className={cn("num", (st.change_pct ?? 0) >= 0 ? "text-buy" : "text-sell")}>{fmtPct(st.change_pct)}</span>
          <span className="num text-fg-mute">Bid <span className="text-buy">{fmtPrice(st.best_bid, st.tick)}</span> · Ask <span className="text-sell">{fmtPrice(st.best_ask, st.tick)}</span></span>
          <span className="num text-fg-mute">Vol {fmtCompact(st.volume)} · EGP {fmtCompact(st.value)}</span>
          <QualityBadge q={st.quality} />
        </>
      )}
    </div>
  );
}

export default function TerminalPage() {
  const tabs = useUi((s) => s.tabs);
  const active = useUi((s) => s.active);
  const setActive = useUi((s) => s.setActive);
  const closeTab = useUi((s) => s.closeTab);
  const layout = useUi((s) => s.layout);
  const setLayout = useUi((s) => s.setLayout);
  const series = useTopicSeries(`symbol:${active}`);
  const chart = useRef<HeatmapHandle>(null);
  const leftRef = useRef<ImperativePanelHandle>(null);
  const rightRef = useRef<ImperativePanelHandle>(null);
  const bottomRef = useRef<ImperativePanelHandle>(null);
  const hGroup = useRef<ImperativePanelGroupHandle>(null);
  const vGroup = useRef<ImperativePanelGroupHandle>(null);
  const { layouts } = useSavedLayouts();

  // apply stored panel sizes (e.g. after loading a saved layout)
  useEffect(() => {
    const same = (a?: number[], b?: number[]) => !!a && !!b && a.length === b.length && a.every((x, i) => Math.abs(x - b[i]) < 0.5);
    const h = hGroup.current;
    if (h && layout.sizesH && !same(h.getLayout(), layout.sizesH)) h.setLayout(layout.sizesH);
    const v = vGroup.current;
    if (v && layout.sizesV && !same(v.getLayout(), layout.sizesV)) v.setLayout(layout.sizesV);
  }, [layout.sizesH, layout.sizesV]);

  // sync collapse state <-> panels
  useEffect(() => {
    const sync = (r: ImperativePanelHandle | null, c: boolean) => {
      if (!r) return;
      if (c && !r.isCollapsed()) r.collapse();
      if (!c && r.isCollapsed()) r.expand();
    };
    sync(leftRef.current, layout.leftCollapsed);
    sync(rightRef.current, layout.rightCollapsed);
    sync(bottomRef.current, layout.bottomCollapsed);
  }, [layout.leftCollapsed, layout.rightCollapsed, layout.bottomCollapsed, layout.swapSides]);

  // terminal keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
      const ui = useUi.getState();
      const k = e.key;
      if (e.ctrlKey && /^[1-4]$/.test(k)) {
        const l = layouts[Number(k) - 1];
        if (l) {
          e.preventDefault();
          applyLayout(l);
        }
        return;
      }
      if (e.altKey && k === "ArrowRight") return ui.cycleTab(1);
      if (e.altKey && k === "ArrowLeft") return ui.cycleTab(-1);
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (/^[1-9]$/.test(k) && ui.tabs[Number(k) - 1]) ui.setActive(ui.tabs[Number(k) - 1]);
      else if (k === "+" || k === "=") chart.current?.zoomTime(1 / 1.25);
      else if (k === "-" || k === "_") e.shiftKey ? chart.current?.zoomPrice(1 / 1.25) : chart.current?.zoomTime(1.25);
      else if (k === "f" || k === "F") chart.current?.goLive();
      else if (k === "h" || k === "H") ui.setHeat({ showHeatmap: !ui.heat.showHeatmap });
      else if (k === "b" || k === "B") ui.setBubbles({ show: !ui.bubbles.show });
      else if (k === "p" || k === "P") ui.setHeat({ showProfile: !ui.heat.showProfile });
      else if (k === "v" || k === "V") ui.setHeat({ showVwap: !ui.heat.showVwap });
      else if (k === "l" || k === "L") ui.setDrawTool(ui.drawTool === "hline" ? "none" : "hline");
      else if (k === "[") ui.setLayout({ leftCollapsed: !ui.layout.leftCollapsed });
      else if (k === "]") ui.setLayout({ rightCollapsed: !ui.layout.rightCollapsed });
      else if (k === "\\") ui.setLayout({ bottomCollapsed: !ui.layout.bottomCollapsed });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [layouts]);

  const moveRight = (id: string, d: -1 | 1) => {
    const o = [...layout.rightOrder];
    const i = o.indexOf(id);
    const j = i + d;
    if (j < 0 || j >= o.length) return;
    [o[i], o[j]] = [o[j], o[i]];
    setLayout({ rightOrder: o });
  };
  const moveBottom = (id: string, d: -1 | 1) => {
    const o = [...layout.bottomOrder];
    const i = o.indexOf(id);
    const j = i + d;
    if (j < 0 || j >= o.length) return;
    [o[i], o[j]] = [o[j], o[i]];
    setLayout({ bottomOrder: o });
  };

  const left = (
    <RPanel key="left" id="left" order={layout.swapSides ? 3 : 1} ref={leftRef} defaultSize={14} minSize={10} maxSize={28} collapsible collapsedSize={0}
      onCollapse={() => setLayout({ leftCollapsed: true })} onExpand={() => setLayout({ leftCollapsed: false })}>
      <TerminalSidebar />
    </RPanel>
  );
  const right = (
    <RPanel key="right" id="right" order={layout.swapSides ? 1 : 3} ref={rightRef} defaultSize={20} minSize={14} maxSize={34} collapsible collapsedSize={0}
      onCollapse={() => setLayout({ rightCollapsed: true })} onExpand={() => setLayout({ rightCollapsed: false })}>
      <div className="flex h-full flex-col overflow-auto">
        {layout.rightOrder.map((id) => (
          <div key={id} className="group relative">
            <div className="absolute right-1 top-1 z-10 hidden gap-0.5 group-hover:flex">
              <button title={`Move ${RIGHT_LABELS[id]} up`} onClick={() => moveRight(id, -1)} className="text-fg-mute hover:text-fg"><ArrowUp size={11} /></button>
              <button title={`Move ${RIGHT_LABELS[id]} down`} onClick={() => moveRight(id, 1)} className="text-fg-mute hover:text-fg"><ArrowDown size={11} /></button>
            </div>
            {RIGHT_WIDGETS[id]?.(series)}
          </div>
        ))}
      </div>
    </RPanel>
  );

  return (
    <PanelGroup ref={hGroup} direction="horizontal" className="h-full" key={layout.swapSides ? "s" : "n"}
      onLayout={(sizes) => setLayout({ sizesH: sizes })}>
      {layout.swapSides ? right : left}
      <PanelResizeHandle className="resize-handle-v" />
      <RPanel id="center" order={2} minSize={35}>
        <PanelGroup ref={vGroup} direction="vertical" onLayout={(sizes) => setLayout({ sizesV: sizes })}>
          <RPanel id="chart" order={1} minSize={30}>
            <div className="flex h-full flex-col">
              <div className="flex h-8 shrink-0 items-center border-b border-line bg-bg-1">
                <div className="flex h-full items-stretch overflow-x-auto">
                  {tabs.map((t, i) => (
                    <div key={t} onClick={() => setActive(t)} className={cn("group flex cursor-pointer items-center gap-1.5 border-r border-line px-3 text-[12px]", t === active ? "bg-bg text-accent" : "text-fg-dim hover:text-fg")}>
                      <span className="num text-[9px] text-fg-mute">{i + 1}</span>
                      <span className="font-semibold">{t}</span>
                      <button className="opacity-0 group-hover:opacity-100" onClick={(e) => { e.stopPropagation(); closeTab(t); }}><X size={10} /></button>
                    </div>
                  ))}
                </div>
                <SymbolHeader series={series} />
                <div className="ml-auto flex items-center gap-1 pr-2">
                  <Btn size="xs" title="Collapse left sidebar ([)" onClick={() => setLayout({ leftCollapsed: !layout.leftCollapsed })}><PanelLeftClose size={12} /></Btn>
                  <Btn size="xs" title="Swap sidebars" onClick={() => setLayout({ swapSides: !layout.swapSides })}><ArrowLeftRight size={12} /></Btn>
                  <Btn size="xs" title="Collapse bottom panel (\)" onClick={() => setLayout({ bottomCollapsed: !layout.bottomCollapsed })}><PanelBottomClose size={12} /></Btn>
                  <Btn size="xs" title="Collapse right sidebar (])" onClick={() => setLayout({ rightCollapsed: !layout.rightCollapsed })}><PanelRightClose size={12} /></Btn>
                </div>
              </div>
              <div className="min-h-0 flex-1">
                <HeatmapChart ref={chart} series={series} symbol={active} />
              </div>
            </div>
          </RPanel>
          <PanelResizeHandle className="resize-handle-h" />
          <RPanel id="bottom" order={2} ref={bottomRef} defaultSize={30} minSize={12} collapsible collapsedSize={0}
            onCollapse={() => setLayout({ bottomCollapsed: true })} onExpand={() => setLayout({ bottomCollapsed: false })}>
            <div className="flex h-full flex-col bg-bg-1">
              <div className="flex h-7 shrink-0 items-stretch border-b border-line">
                {layout.bottomOrder.map((id) => (
                  <div key={id} className={cn("group flex items-center gap-1 border-r border-line px-2 text-[11px]", layout.bottomTab === id ? "bg-bg text-accent" : "text-fg-dim")}>
                    <button onClick={() => setLayout({ bottomTab: id })}>{BOTTOM_LABELS[id]}</button>
                    <span className="hidden gap-0.5 group-hover:flex">
                      <button onClick={() => moveBottom(id, -1)} title="Move left" className="text-fg-mute hover:text-fg">‹</button>
                      <button onClick={() => moveBottom(id, 1)} title="Move right" className="text-fg-mute hover:text-fg">›</button>
                    </span>
                  </div>
                ))}
              </div>
              <div className="min-h-0 flex-1">
                {layout.bottomTab === "tape" && <TimeAndSales series={series} />}
                {layout.bottomTab === "llt" && <LargeLotTracker series={series} />}
                {layout.bottomTab === "volume" && <VolumeAnalysis series={series} />}
                {layout.bottomTab === "cvd" && <CvdPanel series={series} />}
                {layout.bottomTab === "studies" && <StudiesPanel symbol={active} />}
                {layout.bottomTab === "flow" && <FlowPanel series={series} />}
                {layout.bottomTab === "replay" && <ReplayLauncher symbol={active} />}
              </div>
            </div>
          </RPanel>
        </PanelGroup>
      </RPanel>
      <PanelResizeHandle className="resize-handle-v" />
      {layout.swapSides ? left : right}
    </PanelGroup>
  );
}
