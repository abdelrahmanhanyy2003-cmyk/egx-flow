"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { AlertItem } from "@/lib/types";

export interface HeatmapSettings {
  showHeatmap: boolean;
  sensitivity: number; // multiplies the auto-scaled intensity
  gamma: number; // contrast curve
  palette: "classic" | "thermal" | "mono";
  showBBO: boolean;
  showVwap: boolean;
  showProfile: boolean;
  profileMode: "session" | "visible";
  showVolume: boolean;
  showCvd: boolean;
  cvdMa: number;
  volumeTfMs: number;
  showWalls: boolean;
  showIcebergs: boolean;
}

export interface BubbleSettings {
  show: boolean;
  minSize: number;
  maxSize: number;
  minValue: number; // EGP
  alpha: number;
  aggregationMs: number; // time aggregation of prints
  cluster: boolean; // merge across prices within an aggregation bucket
}

export interface Drawing {
  id: string;
  price: number;
  color: string;
  label?: string;
}

export interface LayoutState {
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  bottomCollapsed: boolean;
  swapSides: boolean;
  rightOrder: string[];
  bottomOrder: string[];
  bottomTab: string;
  sizesH?: number[];
  sizesV?: number[];
}

export const DEFAULT_LAYOUT: LayoutState = {
  leftCollapsed: false,
  rightCollapsed: false,
  bottomCollapsed: false,
  swapSides: false,
  rightOrder: ["book", "imbalance", "depth", "profile"],
  bottomOrder: ["tape", "llt", "volume", "cvd", "studies", "flow", "replay"],
  bottomTab: "tape",
};

interface UiState {
  tabs: string[];
  active: string;
  watchlist: string[];
  heat: HeatmapSettings;
  bubbles: BubbleSettings;
  imbalanceLevels: number;
  layout: LayoutState;
  drawings: Record<string, Drawing[]>;
  drawTool: "none" | "hline";
  sound: boolean;
  alerts: AlertItem[];
  unread: number;
  searchOpen: boolean;
  shortcutsOpen: boolean;
  openSymbol: (s: string) => void;
  closeTab: (s: string) => void;
  setActive: (s: string) => void;
  cycleTab: (d: 1 | -1) => void;
  setWatchlist: (w: string[]) => void;
  setHeat: (p: Partial<HeatmapSettings>) => void;
  setBubbles: (p: Partial<BubbleSettings>) => void;
  setImbalanceLevels: (n: number) => void;
  setLayout: (p: Partial<LayoutState>) => void;
  addDrawing: (sym: string, d: Drawing) => void;
  clearDrawings: (sym: string) => void;
  removeDrawing: (sym: string, id: string) => void;
  setDrawTool: (t: "none" | "hline") => void;
  setSound: (b: boolean) => void;
  pushAlert: (a: AlertItem) => void;
  markRead: () => void;
  setSearchOpen: (b: boolean) => void;
  setShortcutsOpen: (b: boolean) => void;
}

const safeStorage = createJSONStorage(() => {
  try {
    const k = "__egx_t";
    window.localStorage.setItem(k, "1");
    window.localStorage.removeItem(k);
    return window.localStorage;
  } catch {
    const mem = new Map<string, string>();
    return {
      getItem: (k: string) => mem.get(k) ?? null,
      setItem: (k: string, v: string) => void mem.set(k, v),
      removeItem: (k: string) => void mem.delete(k),
    };
  }
});

export const useUi = create<UiState>()(
  persist(
    (set, get) => ({
      tabs: ["COMI", "ETEL", "FWRY", "EGAL"],
      active: "COMI",
      watchlist: ["COMI", "ETEL", "FWRY", "EGAL", "HRHO", "TMGH", "SWDY", "EAST", "ABUK", "ORAS"],
      heat: {
        showHeatmap: true,
        sensitivity: 1,
        gamma: 1.1,
        palette: "classic",
        showBBO: true,
        showVwap: true,
        showProfile: true,
        profileMode: "session",
        showVolume: true,
        showCvd: true,
        cvdMa: 20,
        volumeTfMs: 15000,
        showWalls: true,
        showIcebergs: true,
      },
      bubbles: { show: true, minSize: 1.5, maxSize: 16, minValue: 0, alpha: 0.8, aggregationMs: 1000, cluster: false },
      imbalanceLevels: 10,
      layout: DEFAULT_LAYOUT,
      drawings: {},
      drawTool: "none",
      sound: true,
      alerts: [],
      unread: 0,
      searchOpen: false,
      shortcutsOpen: false,
      openSymbol: (s) => {
        const sym = s.toUpperCase();
        const tabs = get().tabs.includes(sym) ? get().tabs : [...get().tabs, sym].slice(-10);
        set({ tabs, active: sym });
      },
      closeTab: (s) => {
        const tabs = get().tabs.filter((t) => t !== s);
        const active = get().active === s ? tabs[tabs.length - 1] ?? "COMI" : get().active;
        set({ tabs: tabs.length ? tabs : ["COMI"], active });
      },
      setActive: (s) => set({ active: s }),
      cycleTab: (d) => {
        const { tabs, active } = get();
        const i = tabs.indexOf(active);
        set({ active: tabs[(i + d + tabs.length) % tabs.length] });
      },
      setWatchlist: (w) => set({ watchlist: w }),
      setHeat: (p) => set({ heat: { ...get().heat, ...p } }),
      setBubbles: (p) => set({ bubbles: { ...get().bubbles, ...p } }),
      setImbalanceLevels: (n) => set({ imbalanceLevels: n }),
      setLayout: (p) => set({ layout: { ...get().layout, ...p } }),
      addDrawing: (sym, d) => set({ drawings: { ...get().drawings, [sym]: [...(get().drawings[sym] ?? []), d] } }),
      clearDrawings: (sym) => set({ drawings: { ...get().drawings, [sym]: [] } }),
      removeDrawing: (sym, id) =>
        set({ drawings: { ...get().drawings, [sym]: (get().drawings[sym] ?? []).filter((d) => d.id !== id) } }),
      setDrawTool: (t) => set({ drawTool: t }),
      setSound: (b) => set({ sound: b }),
      pushAlert: (a) => {
        const key = a.id ?? `${a.rule}|${a.symbol}|${a.ts}|${a.message}`;
        if (get().alerts.some((x) => (x.id ?? `${x.rule}|${x.symbol}|${x.ts}|${x.message}`) === key)) return;
        set({ alerts: [a, ...get().alerts].slice(0, 200), unread: get().unread + 1 });
      },
      markRead: () => set({ unread: 0 }),
      setSearchOpen: (b) => set({ searchOpen: b }),
      setShortcutsOpen: (b) => set({ shortcutsOpen: b }),
    }),
    {
      name: "egxflow.ui",
      storage: safeStorage,
      partialize: (s) => ({
        tabs: s.tabs,
        active: s.active,
        watchlist: s.watchlist,
        heat: s.heat,
        bubbles: s.bubbles,
        imbalanceLevels: s.imbalanceLevels,
        layout: s.layout,
        drawings: s.drawings,
        sound: s.sound,
      }),
    },
  ),
);
