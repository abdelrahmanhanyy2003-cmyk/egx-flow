export const TZ = "Africa/Cairo";

const egp0 = new Intl.NumberFormat("en-EG", { maximumFractionDigits: 0 });
const egp2 = new Intl.NumberFormat("en-EG", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function fmtEGP(v: number | null | undefined, digits = 0): string {
  if (v == null || !isFinite(v)) return "—";
  return `EGP ${(digits ? egp2 : egp0).format(v)}`;
}

export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v == null || !isFinite(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtCompact(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return v.toFixed(0);
}

export function fmtPrice(v: number | null | undefined, tick?: number | null): string {
  if (v == null || !isFinite(v)) return "—";
  const d = tick && tick < 0.01 ? 3 : 2;
  return v.toFixed(d);
}

export function fmtPct(v: number | null | undefined, digits = 2, signed = true): string {
  if (v == null || !isFinite(v)) return "—";
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

const timeFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const hmFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
const dtFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
const dFmt = new Intl.DateTimeFormat("en-GB", { timeZone: TZ, year: "numeric", month: "short", day: "2-digit" });

export const fmtTime = (ms: number | null | undefined) => (ms ? timeFmt.format(ms) : "—");
export const fmtHM = (ms: number) => hmFmt.format(ms);
export const fmtDateTime = (ms: number | null | undefined) => (ms ? dtFmt.format(ms) : "—");
export const fmtDate = (ms: number | null | undefined) => (ms ? dFmt.format(ms) : "—");

export function fmtDuration(ms: number): string {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export const signClass = (v: number | null | undefined) =>
  v == null ? "text-fg-dim" : v > 0 ? "text-buy" : v < 0 ? "text-sell" : "text-fg-dim";
