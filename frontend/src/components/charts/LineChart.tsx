"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type IChartApi,
  LineSeries,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

const cairo = new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit", hour12: false });
const cairoDay = new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", day: "2-digit", month: "short" });
const cairoFull = new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", day: "2-digit", month: "short", year: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });

function baseChart(el: HTMLDivElement, daily: boolean): IChartApi {
  return createChart(el, {
    autoSize: true,
    layout: { background: { type: ColorType.Solid, color: "#050b16" }, textColor: "#8aa0b8", fontSize: 10, fontFamily: "ui-monospace, monospace" },
    grid: { vertLines: { color: "#0c1828" }, horzLines: { color: "#0c1828" } },
    rightPriceScale: { borderColor: "#1a2b42" },
    timeScale: {
      borderColor: "#1a2b42",
      timeVisible: !daily,
      tickMarkFormatter: (t: Time) => (daily ? cairoDay : cairo).format((t as number) * 1000),
    },
    localization: { timeFormatter: (t: Time) => cairoFull.format((t as number) * 1000) },
    crosshair: { mode: 0 },
  });
}

function dedupe<T extends { time: UTCTimestamp }>(rows: T[]): T[] {
  const out: T[] = [];
  for (const r of rows) {
    if (out.length && out[out.length - 1].time >= r.time) out[out.length - 1] = r;
    else out.push(r);
  }
  return out;
}

export interface LineSpec {
  data: [number, number][];
  color: string;
  title?: string;
  histogram?: boolean;
}

export function LineChart({ series, daily = false, priceLines = [] }: { series: LineSpec[]; daily?: boolean; priceLines?: { price: number; color: string; title: string }[] }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  useEffect(() => {
    if (!el.current) return;
    chart.current = baseChart(el.current, daily);
    return () => {
      chart.current?.remove();
      chart.current = null;
    };
  }, [daily]);
  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    const created = series.map((s) => {
      const ser = s.histogram
        ? c.addSeries(HistogramSeries, { color: s.color, priceScaleId: "left", title: s.title })
        : c.addSeries(LineSeries, { color: s.color, lineWidth: 1, title: s.title, priceLineVisible: false });
      ser.setData(dedupe(s.data.map(([t, v]) => ({ time: Math.floor(t / 1000) as UTCTimestamp, value: v }))));
      return ser;
    });
    if (created[0]) for (const pl of priceLines) created[0].createPriceLine({ price: pl.price, color: pl.color, title: pl.title, lineWidth: 1, lineStyle: 2 });
    return () => {
      if (chart.current !== c) return; // chart already disposed (unmount)
      for (const s of created) c.removeSeries(s);
    };
  }, [series, priceLines]);
  return <div ref={el} className="h-full min-h-[120px] w-full" />;
}

export interface Candle {
  t: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export function CandleChart({ candles, daily = false, priceLines = [] }: { candles: Candle[]; daily?: boolean; priceLines?: { price: number; color: string; title: string }[] }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  useEffect(() => {
    if (!el.current) return;
    chart.current = baseChart(el.current, daily);
    return () => {
      chart.current?.remove();
      chart.current = null;
    };
  }, [daily]);
  useEffect(() => {
    const c = chart.current;
    if (!c) return;
    const cs = c.addSeries(CandlestickSeries, {
      upColor: "#19c37d", downColor: "#ff4d5e", borderVisible: false, wickUpColor: "#19c37d", wickDownColor: "#ff4d5e",
    });
    cs.setData(dedupe(candles.map((k) => ({ time: Math.floor(k.t / 1000) as UTCTimestamp, open: k.open, high: k.high, low: k.low, close: k.close }))));
    const vs = c.addSeries(HistogramSeries, { color: "#233a57", priceScaleId: "vol", priceFormat: { type: "volume" } });
    c.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    vs.setData(dedupe(candles.map((k) => ({ time: Math.floor(k.t / 1000) as UTCTimestamp, value: k.volume ?? 0, color: k.close >= k.open ? "rgba(25,195,125,0.35)" : "rgba(255,77,94,0.35)" }))));
    for (const pl of priceLines) cs.createPriceLine({ price: pl.price, color: pl.color, title: pl.title, lineWidth: 1, lineStyle: 2 });
    c.timeScale().fitContent();
    return () => {
      if (chart.current !== c) return; // chart already disposed (unmount)
      c.removeSeries(cs);
      c.removeSeries(vs);
    };
  }, [candles, priceLines]);
  return <div ref={el} className="h-full min-h-[160px] w-full" />;
}
