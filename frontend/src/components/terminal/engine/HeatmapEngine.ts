/**
 * High-performance liquidity heatmap renderer (Canvas2D, no React in the hot path).
 *
 * Heatmap: an offscreen texture with ONE pixel column per book sample and ONE
 * pixel row per price tick. New samples are painted incrementally into an
 * ImageData buffer and flushed with a dirty-rect putImageData; drawing a frame
 * is a single scaled drawImage of the visible texture window plus vector
 * overlays (BBO, VWAP, bubbles, profile, axes). The texture is rebuilt only on
 * settings changes, price-range overflow or capacity overflow.
 */

import type { Series } from "@/lib/series";
import type { BubbleSettings, Drawing, HeatmapSettings } from "@/store/ui";
import { BG_PIXEL, buildLut } from "./palette";
import { niceStep, priceStep, timeStep } from "./scales";

const AXIS_W = 62;
const TIME_AXIS_H = 18;
const TEX_COLS = 7200;
const TEX_ROWS = 900;
const MAX_HOLD_COLS = 30;

const tzFmt = new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

export interface EngineOptions {
  heat: HeatmapSettings;
  bubbles: BubbleSettings;
  drawings: Drawing[];
  entryPrice?: number | null;
  drawTool: "none" | "hline";
  onAddDrawing?: (price: number) => void;
  onRemoveDrawing?: (id: string) => void;
  onFollowChange?: (follow: boolean) => void;
}

interface Hover {
  x: number;
  y: number;
}

export class HeatmapEngine {
  private main: HTMLCanvasElement;
  private vol: HTMLCanvasElement | null;
  private cvd: HTMLCanvasElement | null;
  private ctx: CanvasRenderingContext2D;
  private series: Series | null = null;
  private opts: EngineOptions;
  private dpr = 1;
  private W = 0;
  private H = 0;
  private raf = 0;
  private dirty = true;
  private lastVersion = -1;
  private lastStructure = -1;

  // viewport
  follow = true;
  private tRight = Date.now();
  private msPerPx = 1000 / 3;
  private pCenter: number | null = null;
  private pxPerTick = 9;
  private tick = 0.01;
  private res = 1000;

  // texture
  private tex: HTMLCanvasElement;
  private texCtx: CanvasRenderingContext2D;
  private img: ImageData;
  private pix: Uint32Array;
  private texT0 = 0;
  private texPTop = 0;
  private texReady = false;
  private lastPaintedIdxT = -Infinity;
  private prevPaintedX = -1;
  private prevCol: number = -1; // index of last painted column
  private dirtyX0 = Infinity;
  private dirtyX1 = -1;
  private lut: Uint32Array;
  private scaleQty = 1;
  private medQty = 1;
  private logK = Math.log1p(8);
  private settingsKey = "";

  // caches
  private vwapPts: number[] = []; // flat t,v pairs
  private vwapN = 0;
  private vwapPV = 0;
  private vwapV = 0;
  private vwapStruct = -1;

  // interaction
  private hover: Hover | null = null;
  private drag: { x: number; y: number; tR: number; pC: number; mode: "pan" | "pzoom"; ppt: number } | null = null;
  private resizeObs: ResizeObserver;
  private cleanup: (() => void)[] = [];

  constructor(main: HTMLCanvasElement, vol: HTMLCanvasElement | null, cvd: HTMLCanvasElement | null, opts: EngineOptions) {
    this.main = main;
    this.vol = vol;
    this.cvd = cvd;
    this.opts = opts;
    this.ctx = main.getContext("2d", { alpha: false })!;
    this.tex = document.createElement("canvas");
    this.tex.width = TEX_COLS;
    this.tex.height = TEX_ROWS;
    this.texCtx = this.tex.getContext("2d", { willReadFrequently: false })!;
    this.img = this.texCtx.createImageData(TEX_COLS, TEX_ROWS);
    this.pix = new Uint32Array(this.img.data.buffer);
    this.lut = buildLut(opts.heat.palette);
    this.resizeObs = new ResizeObserver(() => this.resize());
    this.resizeObs.observe(main);
    if (vol) this.resizeObs.observe(vol);
    if (cvd) this.resizeObs.observe(cvd);
    this.bindEvents();
    this.resize();
    this.loop = this.loop.bind(this);
    this.raf = requestAnimationFrame(this.loop);
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    this.resizeObs.disconnect();
    for (const c of this.cleanup) c();
  }

  setSeries(s: Series | null) {
    if (s === this.series) return;
    this.series = s;
    this.texReady = false;
    this.pCenter = null;
    this.follow = true;
    this.lastStructure = -1;
    this.vwapStruct = -1;
    this.dirty = true;
  }

  setOptions(o: EngineOptions) {
    const key = `${o.heat.palette}|${o.heat.sensitivity}|${o.heat.gamma}`;
    if (key !== this.settingsKey) {
      this.settingsKey = key;
      this.lut = buildLut(o.heat.palette);
      this.texReady = false;
    }
    this.opts = o;
    this.dirty = true;
  }

  // ---------------------------------------------------------------- public controls
  zoomTime(f: number) {
    this.msPerPx = Math.min(60_000, Math.max(5, this.msPerPx * f));
    this.dirty = true;
  }
  zoomPrice(f: number) {
    this.pxPerTick = Math.min(60, Math.max(0.15, this.pxPerTick * f));
    this.dirty = true;
  }
  goLive() {
    this.follow = true;
    this.pCenter = null;
    this.opts.onFollowChange?.(true);
    this.dirty = true;
  }

  // ---------------------------------------------------------------- geometry
  private plotW() {
    return Math.max(10, this.W - AXIS_W - this.profileW());
  }
  private plotH() {
    return Math.max(10, this.H - TIME_AXIS_H);
  }
  private profileW() {
    return this.opts.heat.showProfile ? Math.min(110, Math.max(60, this.W * 0.09)) : 0;
  }
  private tLeft() {
    return this.tRight - this.plotW() * this.msPerPx;
  }
  private xOf(t: number) {
    return (t - this.tLeft()) / this.msPerPx;
  }
  private tOf(x: number) {
    return this.tLeft() + x * this.msPerPx;
  }
  private pTop() {
    return (this.pCenter ?? 0) + (this.plotH() / 2 / this.pxPerTick) * this.tick;
  }
  private yOf(p: number) {
    return ((this.pTop() - p) / this.tick) * this.pxPerTick;
  }
  private pOf(y: number) {
    return this.pTop() - (y / this.pxPerTick) * this.tick;
  }

  private resize() {
    const r = this.main.getBoundingClientRect();
    this.dpr = window.devicePixelRatio || 1;
    this.W = Math.max(50, Math.floor(r.width));
    this.H = Math.max(50, Math.floor(r.height));
    this.main.width = this.W * this.dpr;
    this.main.height = this.H * this.dpr;
    for (const c of [this.vol, this.cvd]) {
      if (!c) continue;
      const rr = c.getBoundingClientRect();
      c.width = Math.max(1, Math.floor(rr.width * this.dpr));
      c.height = Math.max(1, Math.floor(rr.height * this.dpr));
    }
    this.dirty = true;
  }

  // ---------------------------------------------------------------- texture
  private detectResolution(s: Series) {
    const c = s.columns;
    if (c.length > 3) {
      const diffs: number[] = [];
      for (let i = Math.max(1, c.length - 50); i < c.length; i++) diffs.push(c[i].t - c[i - 1].t);
      diffs.sort((a, b) => a - b);
      const med = diffs[diffs.length >> 1];
      if (med > 0) this.res = med;
    }
    const tk = s.stats?.tick ?? s.instrument?.tick_size;
    if (tk && tk > 0) this.tick = tk;
  }

  private computeScale(s: Series) {
    const cols = s.columns;
    const vals: number[] = [];
    const start = Math.max(0, cols.length - 600);
    const stride = Math.max(1, Math.floor((cols.length - start) / 120));
    for (let i = start; i < cols.length; i += stride) {
      const q = cols[i].qtys;
      for (let k = 0; k < q.length; k++) vals.push(Math.abs(q[k]));
    }
    if (!vals.length) return;
    vals.sort((a, b) => a - b);
    // log intensity relative to the median resting size; the top ~0.5% saturates
    this.medQty = Math.max(1, vals[vals.length >> 1]);
    this.scaleQty = Math.max(this.medQty * 2, vals[Math.floor(vals.length * 0.995)]);
    this.logK = Math.log1p(this.scaleQty / this.medQty);
  }

  private rebuildTexture() {
    const s = this.series;
    this.pix.fill(BG_PIXEL);
    this.texReady = false;
    if (!s || !s.columns.length) return;
    this.detectResolution(s);
    this.computeScale(s);
    const cols = s.columns;
    // anchor: keep the most recent TEX_COLS*0.75 columns, leaving room to grow
    const keepMs = TEX_COLS * 0.75 * this.res;
    const lastT = cols[cols.length - 1].t;
    this.texT0 = Math.max(cols[0].t, lastT - keepMs);
    this.texT0 -= this.texT0 % this.res;
    const ref = s.stats?.last ?? cols[cols.length - 1].last ?? cols[cols.length - 1].bb ?? 0;
    this.texPTop = Math.round(ref / this.tick) * this.tick + (TEX_ROWS / 2) * this.tick;
    this.prevCol = -1;
    this.prevPaintedX = -1;
    this.lastPaintedIdxT = -Infinity;
    this.texReady = true;
    this.paintNewColumns(true);
    this.flushTexture(true);
  }

  private colX(t: number) {
    return Math.round((t - this.texT0) / this.res);
  }

  private paintColumnAt(ci: number, x0: number, x1: number) {
    const s = this.series!;
    const col = s.columns[ci];
    const sens = this.opts.heat.sensitivity;
    const gamma = this.opts.heat.gamma;
    const invMed = sens / this.medQty;
    const invK = 1 / this.logK;
    for (let x = Math.max(0, x0); x <= Math.min(TEX_COLS - 1, x1); x++) {
      for (let y = 0; y < TEX_ROWS; y++) this.pix[y * TEX_COLS + x] = BG_PIXEL;
      const pr = col.prices;
      const q = col.qtys;
      for (let k = 0; k < pr.length; k++) {
        const row = Math.round((this.texPTop - pr[k]) / this.tick);
        if (row < 0 || row >= TEX_ROWS) continue;
        let v = Math.log1p(Math.abs(q[k]) * invMed) * invK;
        v = v >= 1 ? 1 : Math.pow(v, gamma);
        this.pix[row * TEX_COLS + x] = this.lut[Math.max(8, (v * 255) | 0)];
      }
    }
    if (x0 < this.dirtyX0) this.dirtyX0 = Math.max(0, x0);
    if (x1 > this.dirtyX1) this.dirtyX1 = Math.min(TEX_COLS - 1, x1);
  }

  /** Paint columns not yet in the texture. Returns false if a rebuild is required. */
  private paintNewColumns(initial = false): boolean {
    const s = this.series!;
    const cols = s.columns;
    if (!cols.length) return true;
    let i = initial ? s.columnIndexAt(this.texT0) : s.columnIndexAt(this.lastPaintedIdxT + 1);
    for (; i < cols.length; i++) {
      const c = cols[i];
      const x = this.colX(c.t);
      if (x >= TEX_COLS) return false; // capacity overflow
      // price range check: rebuild if the touch leaves the inner 90% of texture rows
      const ref = c.last ?? c.bb ?? c.ba;
      if (ref != null) {
        const row = (this.texPTop - ref) / this.tick;
        if (row < TEX_ROWS * 0.05 || row > TEX_ROWS * 0.95) return false;
      }
      // hold the previous column until this one (bounded)
      if (this.prevCol >= 0 && this.prevPaintedX >= 0 && x - this.prevPaintedX > 1) {
        const holdTo = Math.min(x - 1, this.prevPaintedX + MAX_HOLD_COLS);
        this.paintColumnAt(this.prevCol, this.prevPaintedX + 1, holdTo);
      }
      this.paintColumnAt(i, x, x);
      this.prevCol = i;
      this.prevPaintedX = x;
      this.lastPaintedIdxT = c.t;
    }
    return true;
  }

  private flushTexture(full = false) {
    if (full) {
      this.texCtx.putImageData(this.img, 0, 0);
    } else if (this.dirtyX1 >= this.dirtyX0) {
      this.texCtx.putImageData(this.img, 0, 0, this.dirtyX0, 0, this.dirtyX1 - this.dirtyX0 + 1, TEX_ROWS);
    }
    this.dirtyX0 = Infinity;
    this.dirtyX1 = -1;
  }

  private syncTexture() {
    const s = this.series;
    if (!s) return;
    if (s.structureVersion !== this.lastStructure) {
      this.lastStructure = s.structureVersion;
      this.texReady = false;
    }
    if (!this.texReady) {
      this.rebuildTexture();
      return;
    }
    if (s.columns.length && s.columns[s.columns.length - 1].t > this.lastPaintedIdxT) {
      // remap prevCol index (series may have trimmed its head)
      this.prevCol = this.prevCol >= 0 ? s.columnIndexAt(this.lastPaintedIdxT) : -1;
      if (!this.paintNewColumns()) this.rebuildTexture();
      else this.flushTexture();
    }
  }

  // ---------------------------------------------------------------- loop
  private loop() {
    this.raf = requestAnimationFrame(this.loop);
    const s = this.series;
    const v = s ? s.version : -1;
    if (v !== this.lastVersion) {
      this.lastVersion = v;
      this.dirty = true;
    }
    if (!this.dirty) return;
    this.dirty = false;
    try {
      this.syncTexture();
      this.updateFollow();
      this.drawMain();
      this.drawVolume();
      this.drawCvd();
    } catch (e) {
      // never let a render error kill the loop
      console.error("heatmap render error", e);
    }
  }

  private dataEndT(): number {
    const s = this.series;
    if (!s) return Date.now();
    const lc = s.columns.length ? s.columns[s.columns.length - 1].t : 0;
    const lt = s.tT.length ? s.tT[s.tT.length - 1] : 0;
    return Math.max(lc, lt) || Date.now();
  }

  private updateFollow() {
    const s = this.series;
    if (!s) return;
    const last = s.stats?.last ?? s.book?.best_bid ?? null;
    if (this.pCenter == null && last != null) this.pCenter = last;
    if (this.follow) {
      this.tRight = this.dataEndT() + this.plotW() * this.msPerPx * 0.06;
      if (last != null && this.pCenter != null) {
        const y = this.yOf(last);
        const h = this.plotH();
        if (y < h * 0.2 || y > h * 0.8) this.pCenter = last;
      }
    }
  }

  // ---------------------------------------------------------------- drawing
  private drawMain() {
    const ctx = this.ctx;
    const s = this.series;
    const { W, H, dpr } = this;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#050b16";
    ctx.fillRect(0, 0, W, H);
    if (!s || this.pCenter == null) {
      ctx.fillStyle = "#5b6f86";
      ctx.font = "12px ui-monospace, monospace";
      ctx.fillText("Waiting for market data…", 16, 24);
      return;
    }
    const pw = this.plotW();
    const ph = this.plotH();
    const heat = this.opts.heat;

    // ---- heatmap texture window
    if (heat.showHeatmap && this.texReady) {
      const tL = this.tLeft();
      let sx = (tL - this.texT0) / this.res;
      let sw = (pw * this.msPerPx) / this.res;
      let sy = (this.texPTop - this.pTop()) / this.tick;
      let sh = ph / this.pxPerTick;
      let dx = 0,
        dy = 0,
        dw = pw,
        dh = ph;
      // manual clipping of the source rect to texture bounds
      if (sx < 0) {
        const cut = -sx;
        dx += (cut / sw) * dw;
        dw -= (cut / sw) * dw;
        sw -= cut;
        sx = 0;
      }
      if (sx + sw > TEX_COLS) {
        const cut = sx + sw - TEX_COLS;
        dw -= (cut / sw) * dw;
        sw -= cut;
      }
      if (sy < 0) {
        const cut = -sy;
        dy += (cut / sh) * dh;
        dh -= (cut / sh) * dh;
        sh -= cut;
        sy = 0;
      }
      if (sy + sh > TEX_ROWS) {
        const cut = sy + sh - TEX_ROWS;
        dh -= (cut / sh) * dh;
        sh -= cut;
      }
      if (sw > 0 && sh > 0 && dw > 0 && dh > 0) {
        ctx.imageSmoothingEnabled = dw / sw < 1;
        // offset by half a column so a sample is centred on its timestamp
        ctx.drawImage(this.tex, sx, sy, sw, sh, dx - this.res / this.msPerPx / 2, dy - this.pxPerTick / 2, dw, dh);
      }
      // nothing to the right of the latest sample
      const xEnd = this.xOf(this.dataEndT()) + this.res / this.msPerPx / 2;
      if (xEnd < pw) {
        ctx.fillStyle = "#050b16";
        ctx.fillRect(Math.max(0, xEnd), 0, pw - xEnd, ph);
      }
    }

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, pw, ph);
    ctx.clip();

    if (s.stats?.quality === "simulated") {
      ctx.fillStyle = "rgba(180,140,255,0.06)";
      ctx.font = "bold 72px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("DEMO", pw / 2, ph / 2 + 24);
      ctx.textAlign = "left";
    }

    this.drawValueArea(pw);
    if (heat.showBBO) this.drawBBO();
    if (heat.showVwap) this.drawVwap();
    if (this.opts.bubbles.show) this.drawBubbles();
    this.drawLevels(pw);
    ctx.restore();

    if (heat.showProfile) this.drawProfile(pw, ph);
    this.drawPriceAxis(pw, ph);
    this.drawTimeAxis(pw, ph);
    this.drawHeader();
    this.drawCrosshair(pw, ph);
  }

  private drawBBO() {
    const s = this.series!;
    const ctx = this.ctx;
    const cols = s.columns;
    const i0 = Math.max(0, s.columnIndexAt(this.tLeft()) - 1);
    const xEndPad = this.res / this.msPerPx;
    for (const [key, color] of [["bb", "#19c37d"], ["ba", "#ff4d5e"]] as const) {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      let started = false;
      let prevY = 0;
      for (let i = i0; i < cols.length; i++) {
        const p = cols[i][key];
        if (p == null) continue;
        const x = this.xOf(cols[i].t);
        const y = this.yOf(p);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, prevY);
          ctx.lineTo(x, y);
        }
        prevY = y;
        if (x > this.plotW()) break;
      }
      if (started) ctx.lineTo(this.xOf(this.dataEndT()) + xEndPad / 2, prevY);
      ctx.stroke();
    }
  }

  private drawVwap() {
    const s = this.series!;
    if (this.vwapStruct !== s.structureVersion || s.tT.length < this.vwapN) {
      this.vwapStruct = s.structureVersion;
      this.vwapN = 0;
      this.vwapPV = 0;
      this.vwapV = 0;
      this.vwapPts = [];
    }
    for (let i = this.vwapN; i < s.tT.length; i++) {
      this.vwapPV += s.tP[i] * s.tQ[i];
      this.vwapV += s.tQ[i];
      const t = s.tT[i];
      const n = this.vwapPts.length;
      const bucket = t - (t % 5000);
      if (n && this.vwapPts[n - 2] === bucket) this.vwapPts[n - 1] = this.vwapPV / this.vwapV;
      else this.vwapPts.push(bucket, this.vwapPV / this.vwapV);
    }
    this.vwapN = s.tT.length;
    const ctx = this.ctx;
    ctx.strokeStyle = "rgba(245,185,66,0.9)";
    ctx.setLineDash([4, 3]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    let started = false;
    const tL = this.tLeft();
    for (let i = 0; i < this.vwapPts.length; i += 2) {
      if (this.vwapPts[i] < tL - 10000) continue;
      const x = this.xOf(this.vwapPts[i]);
      const y = this.yOf(this.vwapPts[i + 1]);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }

  private bubbleCache: { key: string; items: { x: number; y: number; r: number; side: number; est: boolean; t: number; p: number; q: number; n: number }[] } = { key: "", items: [] };

  private computeBubbles() {
    const s = this.series!;
    const b = this.opts.bubbles;
    const tL = this.tLeft();
    const tR = this.tRight;
    const i0 = s.tradeIndexAt(tL);
    const i1 = s.tradeIndexAt(tR + 1);
    const agg = Math.max(1, b.aggregationMs);
    const groups = new Map<string, { t: number; pv: number; q: number; side: number; est: boolean; n: number }>();
    for (let i = i0; i < i1; i++) {
      const t = s.tT[i];
      const bucket = t - (t % agg);
      const side = s.tS[i];
      const key = b.cluster ? `${bucket}|${side}` : `${bucket}|${side}|${s.tP[i]}`;
      let g = groups.get(key);
      if (!g) {
        g = { t: bucket + agg / 2, pv: 0, q: 0, side, est: false, n: 0 };
        groups.set(key, g);
      }
      g.pv += s.tP[i] * s.tQ[i];
      g.q += s.tQ[i];
      g.n++;
      if (s.tE[i]) g.est = true;
    }
    const arr = [...groups.values()].filter((g) => g.pv >= b.minValue);
    if (!arr.length) return [];
    const qs = arr.map((g) => g.q).sort((a, c) => a - c);
    const qRef = Math.max(1, qs[Math.floor(qs.length * 0.995)] ?? qs[qs.length - 1]);
    const items = arr.map((g) => {
      const p = g.pv / g.q;
      const r = b.minSize + (b.maxSize - b.minSize) * Math.min(1, Math.sqrt(g.q / qRef));
      return { x: this.xOf(g.t), y: this.yOf(p), r, side: g.side, est: g.est, t: g.t, p, q: g.q, n: g.n };
    });
    items.sort((a, c) => a.r - c.r);
    return items.length > 8000 ? items.slice(items.length - 8000) : items;
  }

  private drawBubbles() {
    const ctx = this.ctx;
    const b = this.opts.bubbles;
    const s = this.series!;
    const key = `${s.version}|${this.tRight}|${this.msPerPx}|${this.pCenter}|${this.pxPerTick}|${JSON.stringify(b)}|${this.W}|${this.H}`;
    if (this.bubbleCache.key !== key) this.bubbleCache = { key, items: this.computeBubbles() };
    ctx.globalAlpha = b.alpha;
    for (const it of this.bubbleCache.items) {
      if (it.x < -it.r || it.x > this.plotW() + it.r) continue;
      const fill = it.side === 1 ? "#19c37d" : it.side === 2 ? "#ff4d5e" : "#7f8ea3";
      ctx.beginPath();
      ctx.arc(it.x, it.y, it.r, 0, Math.PI * 2);
      if (it.est) {
        // estimated aggressor side: hollow ring
        ctx.lineWidth = Math.max(1, it.r * 0.28);
        ctx.strokeStyle = fill;
        ctx.stroke();
      } else {
        ctx.fillStyle = fill;
        ctx.fill();
        if (it.r > 8) {
          ctx.lineWidth = 1;
          ctx.strokeStyle = "rgba(255,255,255,0.35)";
          ctx.stroke();
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  private drawValueArea(pw: number) {
    const prof = this.series?.profile;
    if (!prof || !this.opts.heat.showProfile || this.opts.heat.profileMode !== "session") return;
    const ctx = this.ctx;
    if (prof.vah != null && prof.val != null) {
      ctx.fillStyle = "rgba(47,180,255,0.04)";
      const y0 = this.yOf(prof.vah) - this.pxPerTick / 2;
      const y1 = this.yOf(prof.val) + this.pxPerTick / 2;
      ctx.fillRect(0, y0, pw, y1 - y0);
    }
  }

  private drawLevels(pw: number) {
    const s = this.series!;
    const ctx = this.ctx;
    ctx.font = "10px ui-monospace, monospace";
    // drawings (horizontal lines)
    for (const d of this.opts.drawings) {
      const y = this.yOf(d.price);
      ctx.strokeStyle = d.color;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(pw, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = d.color;
      ctx.fillText(d.label ?? d.price.toFixed(this.tick < 0.01 ? 3 : 2), 6, y - 3);
    }
    // position entry reference
    if (this.opts.entryPrice) {
      const y = this.yOf(this.opts.entryPrice);
      ctx.strokeStyle = "#b48cff";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(pw, y);
      ctx.stroke();
      ctx.lineWidth = 1;
      ctx.fillStyle = "#b48cff";
      ctx.fillText(`ENTRY ${this.opts.entryPrice.toFixed(2)}`, 6, y - 3);
    }
    // active walls: bracket at right edge
    if (this.opts.heat.showWalls) {
      for (const w of s.walls) {
        const y = this.yOf(w.price);
        if (y < 0 || y > this.plotH()) continue;
        ctx.fillStyle = w.side === "bid" ? "rgba(25,195,125,0.9)" : "rgba(255,77,94,0.9)";
        ctx.fillRect(pw - 4, y - this.pxPerTick / 2, 4, Math.max(2, this.pxPerTick));
        const label = `${w.side === "bid" ? "BID" : "ASK"} WALL ${compact(w.qty)}`;
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(5,11,22,0.75)";
        ctx.fillRect(pw - tw - 12, y - 6, tw + 6, 12);
        ctx.fillStyle = w.side === "bid" ? "#19c37d" : "#ff4d5e";
        ctx.fillText(label, pw - tw - 9, y + 3);
      }
    }
    if (this.opts.heat.showIcebergs) {
      for (const ic of s.icebergs) {
        const y = this.yOf(ic.price);
        const x = this.xOf(ic.last_ts);
        ctx.fillStyle = "#f5b942";
        ctx.beginPath();
        ctx.moveTo(x, y - 6);
        ctx.lineTo(x + 6, y);
        ctx.lineTo(x, y + 6);
        ctx.lineTo(x - 6, y);
        ctx.closePath();
        ctx.fill();
        ctx.fillText(`ICE? ${Math.round(ic.confidence * 100)}%`, x + 8, y + 3);
      }
    }
    // last price line
    const last = s.stats?.last;
    if (last != null) {
      const y = this.yOf(last);
      ctx.strokeStyle = "rgba(255,255,255,0.45)";
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(pw, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  private visibleProfile(): { levels: Map<number, [number, number, number]>; poc: number | null; vah: number | null; val: number | null } {
    const s = this.series!;
    if (this.opts.heat.profileMode === "session" && s.profile) {
      const m = new Map<number, [number, number, number]>();
      for (const [p, b, se, u] of s.profile.levels) m.set(p, [b, se, u]);
      return { levels: m, poc: s.profile.poc, vah: s.profile.vah, val: s.profile.val };
    }
    const m = new Map<number, [number, number, number]>();
    const i0 = s.tradeIndexAt(this.tLeft());
    const i1 = s.tradeIndexAt(this.tRight + 1);
    let tot = 0;
    for (let i = i0; i < i1; i++) {
      const p = s.tP[i];
      let lv = m.get(p);
      if (!lv) {
        lv = [0, 0, 0];
        m.set(p, lv);
      }
      lv[s.tS[i] === 1 ? 0 : s.tS[i] === 2 ? 1 : 2] += s.tQ[i];
      tot += s.tQ[i];
    }
    // POC / value area (70%) for the visible range
    const prices = [...m.keys()].sort((a, b) => a - b);
    if (!prices.length) return { levels: m, poc: null, vah: null, val: null };
    const vols = prices.map((p) => m.get(p)!.reduce((a, b) => a + b, 0));
    let pi = 0;
    for (let k = 1; k < vols.length; k++) if (vols[k] > vols[pi]) pi = k;
    let i = pi,
      j = pi,
      acc = vols[pi];
    while (acc < tot * 0.7 && (i > 0 || j < prices.length - 1)) {
      const up = j < prices.length - 1 ? vols[j + 1] : -1;
      const dn = i > 0 ? vols[i - 1] : -1;
      if (up >= dn) acc += vols[++j];
      else acc += vols[--i];
    }
    return { levels: m, poc: prices[pi], vah: prices[j], val: prices[i] };
  }

  private drawProfile(pw: number, ph: number) {
    const ctx = this.ctx;
    const w = this.profileW();
    const x0 = pw;
    ctx.fillStyle = "#07101d";
    ctx.fillRect(x0, 0, w, ph);
    ctx.strokeStyle = "#1a2b42";
    ctx.beginPath();
    ctx.moveTo(x0 + 0.5, 0);
    ctx.lineTo(x0 + 0.5, ph);
    ctx.stroke();
    const vp = this.visibleProfile();
    let max = 0;
    for (const v of vp.levels.values()) max = Math.max(max, v[0] + v[1] + v[2]);
    if (!max) return;
    const h = Math.max(1, this.pxPerTick - (this.pxPerTick > 3 ? 1 : 0));
    for (const [p, [b, s, u]] of vp.levels) {
      const y = this.yOf(p) - h / 2;
      if (y < -h || y > ph) continue;
      const tot = b + s + u;
      const len = (tot / max) * (w - 6);
      const inVA = vp.val != null && vp.vah != null && p >= vp.val && p <= vp.vah;
      const a = inVA ? 0.85 : 0.45;
      let x = x0 + 2;
      const bw = (b / tot) * len;
      const sw = (s / tot) * len;
      ctx.fillStyle = `rgba(25,195,125,${a})`;
      ctx.fillRect(x, y, bw, h);
      x += bw;
      ctx.fillStyle = `rgba(255,77,94,${a})`;
      ctx.fillRect(x, y, sw, h);
      x += sw;
      ctx.fillStyle = `rgba(127,142,163,${a})`;
      ctx.fillRect(x, y, len - bw - sw, h);
    }
    ctx.font = "9px ui-monospace, monospace";
    for (const [p, label, color] of [
      [vp.poc, "POC", "#f5b942"],
      [vp.vah, "VAH", "#2fb4ff"],
      [vp.val, "VAL", "#2fb4ff"],
    ] as const) {
      if (p == null) continue;
      const y = this.yOf(p);
      ctx.strokeStyle = color;
      ctx.lineWidth = label === "POC" ? 1.5 : 1;
      ctx.beginPath();
      ctx.moveTo(x0, y);
      ctx.lineTo(x0 + w, y);
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.fillText(label, x0 + w - 22, y - 2);
    }
    ctx.lineWidth = 1;
    ctx.fillStyle = "#5b6f86";
    ctx.fillText(this.opts.heat.profileMode === "session" ? "SESSION VP" : "VISIBLE VP", x0 + 4, 10);
  }

  private drawPriceAxis(pw: number, ph: number) {
    const ctx = this.ctx;
    const x0 = pw + this.profileW();
    ctx.fillStyle = "#08111f";
    ctx.fillRect(x0, 0, AXIS_W, this.H);
    ctx.strokeStyle = "#1a2b42";
    ctx.beginPath();
    ctx.moveTo(x0 + 0.5, 0);
    ctx.lineTo(x0 + 0.5, this.H);
    ctx.stroke();
    const step = priceStep(this.tick, this.pxPerTick, 22);
    const pBot = this.pOf(ph);
    const pTop = this.pTop();
    const start = Math.ceil(pBot / step) * step;
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = "#8aa0b8";
    const dec = this.tick < 0.01 ? 3 : 2;
    for (let p = start; p <= pTop; p += step) {
      const y = this.yOf(p);
      ctx.fillText(p.toFixed(dec), x0 + 6, y + 3);
      ctx.strokeStyle = "rgba(26,43,66,0.55)";
      ctx.beginPath();
      ctx.moveTo(0, Math.round(y) + 0.5);
      ctx.lineTo(4, Math.round(y) + 0.5);
      ctx.stroke();
    }
    const s = this.series!;
    const tag = (p: number | null | undefined, bg: string, fg = "#050b16") => {
      if (p == null) return;
      const y = this.yOf(p);
      if (y < 0 || y > ph) return;
      ctx.fillStyle = bg;
      ctx.fillRect(x0 + 1, y - 7, AXIS_W - 2, 14);
      ctx.fillStyle = fg;
      ctx.fillText(p.toFixed(dec), x0 + 6, y + 3);
    };
    tag(s.stats?.best_bid, "#19c37d");
    tag(s.stats?.best_ask, "#ff4d5e");
    tag(s.stats?.last, "#d6e2f0");
  }

  private drawTimeAxis(pw: number, ph: number) {
    const ctx = this.ctx;
    ctx.fillStyle = "#08111f";
    ctx.fillRect(0, ph, this.W, TIME_AXIS_H);
    ctx.strokeStyle = "#1a2b42";
    ctx.beginPath();
    ctx.moveTo(0, ph + 0.5);
    ctx.lineTo(this.W, ph + 0.5);
    ctx.stroke();
    const step = timeStep(this.msPerPx, 80);
    const tL = this.tLeft();
    // align to Cairo wall clock: offset is handled by formatting; steps are UTC-aligned (whole seconds/minutes)
    const start = Math.ceil(tL / step) * step;
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = "#8aa0b8";
    for (let t = start; t <= this.tRight; t += step) {
      const x = this.xOf(t);
      if (x > pw - 20) break;
      const label = tzFmt.format(t);
      ctx.fillText(step >= 60_000 ? label.slice(0, 5) : label, x - 22, ph + 13);
      ctx.strokeStyle = "rgba(26,43,66,0.5)";
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, ph);
      ctx.lineTo(Math.round(x) + 0.5, ph + 4);
      ctx.stroke();
    }
  }

  private drawHeader() {
    const s = this.series!;
    const ctx = this.ctx;
    const res = s.stats?.book_resolution ?? "";
    ctx.font = "10px ui-monospace, monospace";
    let x = 8;
    const chip = (txt: string, color: string) => {
      const w = ctx.measureText(txt).width + 10;
      ctx.fillStyle = "rgba(5,11,22,0.8)";
      ctx.fillRect(x, 6, w, 15);
      ctx.strokeStyle = color;
      ctx.strokeRect(x + 0.5, 6.5, w - 1, 14);
      ctx.fillStyle = color;
      ctx.fillText(txt, x + 5, 17);
      x += w + 4;
    };
    if (s.replay) chip(`REPLAY ${s.replay.speed}x`, "#2fb4ff");
    if (s.stats?.quality === "simulated") chip("DEMO · SIMULATED", "#b48cff");
    else if (s.stats?.quality === "delayed") chip("DELAYED", "#f5b942");
    if (res === "l1_only") chip("L1 ONLY · best bid/ask, no depth", "#f5b942");
    else if (res === "depth_snapshots") chip("DEPTH SNAPSHOTS", "#8aa0b8");
    if (!this.follow) chip("PAUSED SCROLL · dbl-click to follow", "#8aa0b8");
  }

  private nearestBubble(x: number, y: number) {
    let best: (typeof this.bubbleCache.items)[number] | null = null;
    let bd = Infinity;
    for (const it of this.bubbleCache.items) {
      const d = Math.hypot(it.x - x, it.y - y);
      if (d <= Math.max(4, it.r) && d < bd) {
        bd = d;
        best = it;
      }
    }
    return best;
  }

  private drawCrosshair(pw: number, ph: number) {
    const h = this.hover;
    if (!h || h.x > pw || h.y > ph) return;
    const ctx = this.ctx;
    const s = this.series!;
    ctx.strokeStyle = "rgba(214,226,240,0.35)";
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(h.x, 0);
    ctx.lineTo(h.x, ph);
    ctx.moveTo(0, h.y);
    ctx.lineTo(pw, h.y);
    ctx.stroke();
    ctx.setLineDash([]);
    const p = Math.round(this.pOf(h.y) / this.tick) * this.tick;
    const t = this.tOf(h.x);
    // resting size at that price from the nearest column
    const ci = Math.min(s.columns.length - 1, Math.max(0, s.columnIndexAt(t) - 1));
    let rest = 0;
    let side = "";
    const col = s.columns[ci];
    if (col) {
      for (let k = 0; k < col.prices.length; k++) {
        if (Math.abs(col.prices[k] - p) < this.tick / 2) {
          rest = Math.abs(col.qtys[k]);
          side = col.qtys[k] > 0 ? "bid" : "ask";
        }
      }
    }
    const lines = [`${tzFmt.format(t)}  ${p.toFixed(this.tick < 0.01 ? 3 : 2)}`];
    lines.push(rest ? `resting ${side} ${rest.toLocaleString()} sh  (EGP ${compact(rest * p)})` : "no resting liquidity");
    const b = this.nearestBubble(h.x, h.y);
    if (b) {
      const sideTxt = b.side === 1 ? "BUY" : b.side === 2 ? "SELL" : "UNKNOWN";
      lines.push(`${sideTxt}${b.est ? " (side estimated)" : ""} ${b.q.toLocaleString()} @ ${b.p.toFixed(3)}`);
      lines.push(`value EGP ${Math.round(b.q * b.p).toLocaleString()} · ${b.n} print${b.n > 1 ? "s" : ""}`);
    }
    ctx.font = "10px ui-monospace, monospace";
    const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 12;
    const bh = lines.length * 13 + 6;
    let bx = h.x + 14;
    let by = h.y + 14;
    if (bx + w > pw) bx = h.x - w - 14;
    if (by + bh > ph) by = h.y - bh - 14;
    ctx.fillStyle = "rgba(8,17,31,0.92)";
    ctx.fillRect(bx, by, w, bh);
    ctx.strokeStyle = "#233a57";
    ctx.strokeRect(bx + 0.5, by + 0.5, w - 1, bh - 1);
    ctx.fillStyle = "#d6e2f0";
    lines.forEach((l, i) => ctx.fillText(l, bx + 6, by + 15 + i * 13));
  }

  // ---------------------------------------------------------------- sub panes
  private subCtx(c: HTMLCanvasElement) {
    const ctx = c.getContext("2d", { alpha: false })!;
    const w = c.width / this.dpr;
    const h = c.height / this.dpr;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = "#050b16";
    ctx.fillRect(0, 0, w, h);
    return { ctx, w, h };
  }

  private drawVolume() {
    if (!this.vol || !this.series) return;
    const { ctx, w, h } = this.subCtx(this.vol);
    const s = this.series;
    const pw = this.plotW();
    const tf = this.opts.heat.volumeTfMs;
    const tL = this.tLeft();
    const i0 = s.tradeIndexAt(tL - tf);
    const i1 = s.tradeIndexAt(this.tRight + 1);
    const buckets = new Map<number, [number, number, number]>();
    for (let i = i0; i < i1; i++) {
      const b = s.tT[i] - (s.tT[i] % tf);
      let v = buckets.get(b);
      if (!v) {
        v = [0, 0, 0];
        buckets.set(b, v);
      }
      v[s.tS[i] === 1 ? 0 : s.tS[i] === 2 ? 1 : 2] += s.tQ[i];
    }
    let max = 0,
      sum = 0;
    for (const v of buckets.values()) {
      const t = v[0] + v[1] + v[2];
      max = Math.max(max, t);
      sum += t;
    }
    const avg = buckets.size ? sum / buckets.size : 0;
    const bw = Math.max(1, tf / this.msPerPx - 1);
    const H = h - 12;
    for (const [t, v] of buckets) {
      const x = this.xOf(t);
      if (x + bw < 0 || x > pw) continue;
      const tot = v[0] + v[1] + v[2];
      const bh = (tot / (max || 1)) * H;
      let y = h;
      const seg = (q: number, col: string) => {
        const sh = (q / (tot || 1)) * bh;
        ctx.fillStyle = col;
        ctx.fillRect(x, y - sh, bw, sh);
        y -= sh;
      };
      seg(v[0], "#19c37d");
      seg(v[1], "#ff4d5e");
      seg(v[2], "#7f8ea3");
      if (avg && tot > avg * 3) {
        ctx.strokeStyle = "#f5b942";
        ctx.strokeRect(x - 0.5, h - bh - 0.5, bw + 1, bh + 1);
      }
    }
    this.drawSubAxis(ctx, w, h, pw, `VOL ${tf / 1000}s  max ${compact(max)}`);
  }

  private drawCvd() {
    if (!this.cvd || !this.series) return;
    const { ctx, w, h } = this.subCtx(this.cvd);
    const s = this.series;
    const pw = this.plotW();
    const pts = s.cvd;
    const tL = this.tLeft();
    let lo = 0;
    while (lo < pts.length && pts[lo][0] < tL) lo++;
    lo = Math.max(0, lo - 1);
    let mn = Infinity,
      mx = -Infinity;
    for (let i = lo; i < pts.length; i++) {
      mn = Math.min(mn, pts[i][1]);
      mx = Math.max(mx, pts[i][1]);
    }
    if (!isFinite(mn)) {
      this.drawSubAxis(ctx, w, h, pw, "CVD");
      return;
    }
    if (mn === mx) {
      mn -= 1;
      mx += 1;
    }
    const pad = (mx - mn) * 0.1;
    mn -= pad;
    mx += pad;
    const yOf = (v: number) => h - ((v - mn) / (mx - mn)) * h;
    const zeroY = yOf(0);
    if (zeroY > 0 && zeroY < h) {
      ctx.strokeStyle = "rgba(138,160,184,0.35)";
      ctx.beginPath();
      ctx.moveTo(0, zeroY);
      ctx.lineTo(pw, zeroY);
      ctx.stroke();
    }
    // area + line
    ctx.beginPath();
    let first = true;
    for (let i = lo; i < pts.length; i++) {
      const x = this.xOf(pts[i][0]);
      const y = yOf(pts[i][1]);
      if (first) {
        ctx.moveTo(x, y);
        first = false;
      } else ctx.lineTo(x, y);
    }
    const last = pts[pts.length - 1][1];
    ctx.strokeStyle = last >= 0 ? "#19c37d" : "#ff4d5e";
    ctx.lineWidth = 1.4;
    ctx.stroke();
    ctx.lineWidth = 1;
    // moving average of CVD
    const n = Math.max(2, this.opts.heat.cvdMa);
    ctx.strokeStyle = "rgba(245,185,66,0.85)";
    ctx.beginPath();
    let sum = 0;
    first = true;
    const start = Math.max(0, lo - n);
    for (let i = start; i < pts.length; i++) {
      sum += pts[i][1];
      if (i - start >= n) sum -= pts[i - n][1];
      if (i - start >= n - 1 && i >= lo) {
        const x = this.xOf(pts[i][0]);
        const y = yOf(sum / n);
        if (first) {
          ctx.moveTo(x, y);
          first = false;
        } else ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
    const est = s.stats?.cvd?.estimated_share ?? 0;
    this.drawSubAxis(ctx, w, h, pw, `CVD ${compact(last)}  MA${n}${est > 0.01 ? `  · ${(est * 100).toFixed(0)}% side-estimated` : ""}`);
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = "#8aa0b8";
    ctx.fillText(compact(mx), pw + 6, 10);
    ctx.fillText(compact(mn), pw + 6, h - 3);
  }

  private drawSubAxis(ctx: CanvasRenderingContext2D, w: number, h: number, pw: number, label: string) {
    ctx.fillStyle = "#08111f";
    ctx.fillRect(pw, 0, w - pw, h);
    ctx.strokeStyle = "#1a2b42";
    ctx.beginPath();
    ctx.moveTo(pw + 0.5, 0);
    ctx.lineTo(pw + 0.5, h);
    ctx.moveTo(0, 0.5);
    ctx.lineTo(w, 0.5);
    ctx.stroke();
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = "#5b6f86";
    ctx.fillText(label, 6, 11);
    if (this.hover && this.hover.x < pw) {
      ctx.strokeStyle = "rgba(214,226,240,0.3)";
      ctx.beginPath();
      ctx.moveTo(this.hover.x, 0);
      ctx.lineTo(this.hover.x, h);
      ctx.stroke();
    }
  }

  // ---------------------------------------------------------------- events
  private bindEvents() {
    const el = this.main;
    const on = <K extends keyof HTMLElementEventMap>(t: K, fn: (e: HTMLElementEventMap[K]) => void, o?: AddEventListenerOptions) => {
      el.addEventListener(t, fn as EventListener, o);
      this.cleanup.push(() => el.removeEventListener(t, fn as EventListener));
    };
    on(
      "wheel",
      (e) => {
        e.preventDefault();
        const f = e.deltaY > 0 ? 1.12 : 1 / 1.12;
        const overAxis = e.offsetX > this.plotW();
        if (overAxis || e.shiftKey || e.ctrlKey) this.zoomPrice(1 / f);
        else {
          // zoom time around the cursor
          const tAt = this.tOf(e.offsetX);
          this.zoomTime(f);
          if (!this.follow) this.tRight = tAt + (this.plotW() - e.offsetX) * this.msPerPx;
        }
      },
      { passive: false },
    );
    on("mousedown", (e) => {
      if (e.button !== 0) return;
      if (this.opts.drawTool === "hline" && e.offsetX < this.plotW()) {
        const p = Math.round(this.pOf(e.offsetY) / this.tick) * this.tick;
        this.opts.onAddDrawing?.(Number(p.toFixed(4)));
        return;
      }
      const mode = e.offsetX > this.plotW() ? "pzoom" : "pan";
      this.drag = { x: e.clientX, y: e.clientY, tR: this.tRight, pC: this.pCenter ?? 0, mode, ppt: this.pxPerTick };
    });
    const move = (e: MouseEvent) => {
      const r = el.getBoundingClientRect();
      this.hover = { x: e.clientX - r.left, y: e.clientY - r.top };
      if (this.drag) {
        const dx = e.clientX - this.drag.x;
        const dy = e.clientY - this.drag.y;
        if (this.drag.mode === "pzoom") {
          this.pxPerTick = Math.min(60, Math.max(0.15, this.drag.ppt * Math.exp(-dy / 150)));
        } else {
          if (Math.abs(dx) > 2 && this.follow) {
            this.follow = false;
            this.opts.onFollowChange?.(false);
          }
          if (!this.follow) this.tRight = this.drag.tR - dx * this.msPerPx;
          this.pCenter = this.drag.pC + (dy / this.pxPerTick) * this.tick;
        }
      }
      this.dirty = true;
    };
    on("mousemove", move);
    const up = () => {
      this.drag = null;
    };
    window.addEventListener("mouseup", up);
    this.cleanup.push(() => window.removeEventListener("mouseup", up));
    on("mouseleave", () => {
      this.hover = null;
      this.dirty = true;
    });
    on("dblclick", () => this.goLive());
    on("contextmenu", (e) => {
      const p = this.pOf(e.offsetY);
      const near = this.opts.drawings.find((d) => Math.abs(this.yOf(d.price) - this.yOf(p)) < 6);
      if (near) {
        e.preventDefault();
        this.opts.onRemoveDrawing?.(near.id);
      }
    });
    for (const c of [this.vol, this.cvd]) {
      if (!c) continue;
      const mv = (e: MouseEvent) => {
        const r = c.getBoundingClientRect();
        this.hover = { x: e.clientX - r.left, y: -1000 };
        this.dirty = true;
      };
      c.addEventListener("mousemove", mv);
      this.cleanup.push(() => c.removeEventListener("mousemove", mv));
    }
  }

  /** Synchronous render benchmark (dev tool): pans/zooms and renders `frames` frames. */
  benchmark(frames = 200, width = 1400, height = 700): { frames: number; avgMs: number; p95Ms: number; maxMs: number; rebuildMs: number } {
    // render at an explicit size so the result does not depend on the current layout
    this.W = width;
    this.H = height;
    this.main.width = width * this.dpr;
    this.main.height = height * this.dpr;
    for (const c of [this.vol, this.cvd]) {
      if (c) {
        c.width = width * this.dpr;
        c.height = 80 * this.dpr;
      }
    }
    const t0 = performance.now();
    this.texReady = false;
    this.syncTexture();
    const rebuildMs = performance.now() - t0;
    const times: number[] = [];
    const follow = this.follow;
    this.follow = false;
    const tR = this.tRight;
    for (let i = 0; i < frames; i++) {
      const a = performance.now();
      this.tRight = tR - Math.abs(Math.sin(i / 20)) * this.plotW() * this.msPerPx * 0.5;
      if (i % 25 === 0) this.zoomTime(i % 50 ? 1.15 : 1 / 1.15);
      this.hover = { x: (i * 7) % this.plotW(), y: (i * 5) % this.plotH() };
      this.syncTexture();
      this.drawMain();
      this.drawVolume();
      this.drawCvd();
      times.push(performance.now() - a);
    }
    this.tRight = tR;
    this.follow = follow;
    this.hover = null;
    this.resize();
    times.sort((x, y) => x - y);
    const avg = times.reduce((s, v) => s + v, 0) / times.length;
    const r = (v: number) => Math.round(v * 100) / 100;
    return { frames, avgMs: r(avg), p95Ms: r(times[Math.floor(times.length * 0.95)]), maxMs: r(times[times.length - 1]), rebuildMs: r(rebuildMs) };
  }

  // for perf telemetry
  stats() {
    return { texCols: TEX_COLS, texRows: TEX_ROWS, res: this.res, tick: this.tick, scale: this.scaleQty, msPerPx: this.msPerPx };
  }
}

function compact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return v.toFixed(0);
}

export { niceStep };
