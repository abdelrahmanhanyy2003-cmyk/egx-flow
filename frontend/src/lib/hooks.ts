"use client";

import { useEffect, useRef, useState } from "react";
import { getSeries, type Series } from "./series";
import { ws, type WsStatus } from "./ws";
import type { SymbolSnapshot, SymbolUpdate } from "./types";

/** Subscribe a topic ("symbol:COMI" / "replay:<id>") into its Series store. */
export function useTopicSeries(topic: string | null): Series | null {
  const [series, setSeries] = useState<Series | null>(null);
  useEffect(() => {
    if (!topic) {
      setSeries(null);
      return;
    }
    const s = getSeries(topic);
    setSeries(s);
    const off = ws.subscribe(topic, (msg) => {
      if (msg.type === "snapshot") s.applySnapshot(msg.data as SymbolSnapshot);
      else if (msg.type === "update") s.applyUpdate(msg.data as SymbolUpdate);
    });
    return off;
  }, [topic]);
  return series;
}

/** Re-render at most every `ms` when a series changes. */
export function useSeriesTick(series: Series | null, ms = 250): number {
  const [v, setV] = useState(0);
  const pending = useRef(false);
  useEffect(() => {
    if (!series) return;
    setV(series.version);
    let timer: ReturnType<typeof setTimeout> | null = null;
    const off = series.listen(() => {
      if (pending.current) return;
      pending.current = true;
      timer = setTimeout(() => {
        pending.current = false;
        setV(series.version);
      }, ms);
    });
    return () => {
      off();
      if (timer) clearTimeout(timer);
      pending.current = false;
    };
  }, [series, ms]);
  return v;
}

export function useWsStatus(): WsStatus {
  const [s, setS] = useState<WsStatus>(ws.status);
  useEffect(() => ws.onStatus(setS), []);
  return s;
}

/** Subscribe to a JSON topic (market / whales) and keep the latest payload. */
export function useTopicData<T>(topic: string, type: string): T | null {
  const [d, setD] = useState<T | null>(null);
  useEffect(
    () =>
      ws.subscribe(topic, (msg) => {
        if (msg.type === type || msg.type === "snapshot") setD(msg.data as T);
      }),
    [topic, type],
  );
  return d;
}

export function useNow(ms = 1000): number {
  const [n, setN] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setN(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return n;
}
