"""Whale Activity Score (0-100), fully explainable.

Each factor maps an observable metric to a 0..1 sub-score with a fixed weight.
The response always includes every factor, its raw input, sub-score, weight
and contribution - the score is never a black box. It measures *unusual
large-participant footprints in public market data*; it does not identify any
participant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

WEIGHTS = {
    "unusual_trade_size": 18,
    "large_trade_value_share": 15,
    "large_trade_frequency": 12,
    "unusual_volume": 12,
    "liquidity_concentration": 10,
    "persistent_walls": 10,
    "absorption": 9,
    "cvd_divergence": 7,
    "depth_change": 7,
}
assert sum(WEIGHTS.values()) == 100


@dataclass
class WhaleInputs:
    largest_trade_pctile: float = 0.0  # percentile rank of largest recent trade (0-100)
    large_value_share: float = 0.0  # share of traded value in large trades (0-1)
    large_trades_recent: int = 0  # count in lookback window
    large_trades_baseline: float = 1.0  # expected count per window
    rvol: float | None = None  # relative volume
    liquidity_concentration: float = 0.0  # HHI-like 0..1 of top book levels
    persistent_walls: int = 0
    absorption_events: int = 0
    cvd_divergence: float = 0.0  # 0..1 strength
    depth_change_pct: float = 0.0  # abs % change in visible depth over window


def _lin(x: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def whale_score(i: WhaleInputs) -> dict[str, Any]:
    freq_ratio = i.large_trades_recent / max(i.large_trades_baseline, 0.5)
    factors = [
        ("unusual_trade_size", i.largest_trade_pctile, _lin(i.largest_trade_pctile, 90, 100),
         "percentile rank of largest recent trade vs symbol history"),
        ("large_trade_value_share", i.large_value_share, _lin(i.large_value_share, 0.05, 0.5),
         "share of traded value executed in large lots"),
        ("large_trade_frequency", freq_ratio, _lin(freq_ratio, 1.0, 4.0),
         "large trades in window vs baseline"),
        ("unusual_volume", i.rvol, _lin(i.rvol or 0.0, 1.0, 3.0),
         "relative volume vs average (RVOL)"),
        ("liquidity_concentration", i.liquidity_concentration, _lin(i.liquidity_concentration, 0.15, 0.6),
         "concentration of resting liquidity in few levels"),
        ("persistent_walls", i.persistent_walls, _lin(i.persistent_walls, 0, 4),
         "count of persistent large resting orders"),
        ("absorption", i.absorption_events, _lin(i.absorption_events, 0, 4),
         "absorption events in window"),
        ("cvd_divergence", i.cvd_divergence, _lin(i.cvd_divergence, 0.0, 1.0),
         "price/CVD divergence strength"),
        ("depth_change", i.depth_change_pct, _lin(abs(i.depth_change_pct), 10, 60),
         "absolute % change of visible depth"),
    ]
    out = []
    total = 0.0
    for name, raw, sub, desc in factors:
        contrib = sub * WEIGHTS[name]
        total += contrib
        out.append(
            {
                "factor": name,
                "input": None if raw is None else round(float(raw), 4),
                "subscore": round(sub, 3),
                "weight": WEIGHTS[name],
                "contribution": round(contrib, 2),
                "description": desc,
            }
        )
    score = round(total, 1)
    band = "extreme" if score >= 75 else "high" if score >= 55 else "elevated" if score >= 35 else "normal"
    return {
        "score": score,
        "band": band,
        "factors": out,
        "disclaimer": "Measures unusual large-lot footprints in public data; does not identify participants.",
    }
