"""Portfolio risk analytics (locally calculated estimates)."""

from __future__ import annotations

from typing import Any


def concentration(positions: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [(p["symbol"], p.get("market_value") or 0.0) for p in positions]
    tot = sum(v for _, v in vals)
    weights = sorted(((s, v / tot) for s, v in vals), key=lambda x: -x[1]) if tot else []
    hhi = sum(w * w for _, w in weights)
    return {
        "weights": [{"symbol": s, "weight_pct": round(w * 100, 3)} for s, w in weights],
        "hhi": round(hhi, 4),
        "effective_positions": round(1 / hhi, 2) if hhi else None,
        "largest": weights[0][0] if weights else None,
        "largest_weight_pct": round(weights[0][1] * 100, 3) if weights else None,
        "top3_weight_pct": round(sum(w for _, w in weights[:3]) * 100, 3) if weights else None,
    }


def sector_concentration(positions: list[dict[str, Any]], sector_of: dict[str, str | None]) -> list[dict[str, Any]]:
    tot = sum(p.get("market_value") or 0.0 for p in positions)
    agg: dict[str, float] = {}
    for p in positions:
        sec = sector_of.get(p["symbol"]) or "Unclassified"
        agg[sec] = agg.get(sec, 0.0) + (p.get("market_value") or 0.0)
    return sorted(
        ({"sector": k, "value": v, "weight_pct": round(v / tot * 100, 3) if tot else 0.0} for k, v in agg.items()),
        key=lambda x: -x["value"],
    )


def drawdown(equity: list[tuple[int, float]]) -> dict[str, Any]:
    peak = None
    max_dd = 0.0
    series = []
    peak_ts = trough_ts = None
    cur_peak_ts = None
    for ts, v in equity:
        if peak is None or v > peak:
            peak, cur_peak_ts = v, ts
        dd = (v - peak) / peak * 100 if peak else 0.0
        series.append([ts, round(dd, 4)])
        if dd < max_dd:
            max_dd, peak_ts, trough_ts = dd, cur_peak_ts, ts
    current = series[-1][1] if series else 0.0
    return {"max_drawdown_pct": round(max_dd, 4), "current_drawdown_pct": current,
            "peak_ts": peak_ts, "trough_ts": trough_ts, "series": series}


def exposure_change(history: list[dict[str, Any]], now_value: float | None, day_ms: int = 86_400_000) -> dict[str, Any]:
    if not history or now_value is None:
        return {"change": None, "change_pct": None, "reference_ts": None}
    ref_ts = history[-1]["ts"] - day_ms
    ref = None
    for h in history:
        if h["ts"] <= ref_ts:
            ref = h
    if ref is None:
        ref = history[0]
    rv = ref.get("stocks_value")
    if not rv:
        return {"change": None, "change_pct": None, "reference_ts": ref["ts"]}
    return {"change": now_value - rv, "change_pct": (now_value / rv - 1) * 100, "reference_ts": ref["ts"]}
