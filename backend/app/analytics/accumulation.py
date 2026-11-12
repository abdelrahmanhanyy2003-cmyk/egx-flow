"""Potential accumulation / distribution signals from observable evidence.

The output is an *indicator*, never proof of institutional activity. Each
signal lists the evidence components and their contribution so the user can
judge it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analytics.bars import Bar


@dataclass
class FlowEvidence:
    bars: list[Bar]
    large_buy_value: float = 0.0
    large_sell_value: float = 0.0
    bullish_absorptions: int = 0
    bearish_absorptions: int = 0
    bid_icebergs: int = 0
    ask_icebergs: int = 0
    bid_wall_persistence_ms: int = 0
    ask_wall_persistence_ms: int = 0


@dataclass
class FlowSignal:
    kind: str  # accumulation | distribution | neutral
    confidence: float
    accumulation_score: float
    distribution_score: float
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": {
                "accumulation": "Potential accumulation",
                "distribution": "Potential distribution",
                "neutral": "No clear accumulation/distribution",
            }[self.kind],
            "confidence": self.confidence,
            "accumulation_score": self.accumulation_score,
            "distribution_score": self.distribution_score,
            "evidence": self.evidence,
            "disclaimer": "Indicator from observable order flow; not proof of institutional activity.",
        }


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def evaluate_flow(ev: FlowEvidence) -> FlowSignal:
    bars = ev.bars
    if len(bars) < 5:
        return FlowSignal("neutral", 0.0, 0.0, 0.0, [{"factor": "insufficient data", "value": len(bars)}])
    first, last = bars[0], bars[-1]
    price_chg = (last.close - first.open) / first.open if first.open else 0.0
    vol = sum(b.volume for b in bars) or 1.0
    delta = sum(b.delta for b in bars)
    delta_ratio = delta / vol  # -1..1
    rng = (max(b.high for b in bars) - min(b.low for b in bars)) / (first.open or 1)

    comps: list[tuple[str, float, float, str]] = []  # name, signed value (+acc / -dist), weight, note

    # 1. CVD vs price: buying pressure without price rise (or the reverse)
    if delta_ratio > 0 and price_chg <= rng * 0.25:
        comps.append(("cvd_vs_price", _clip(delta_ratio * 3), 0.30, "net aggressive buying while price contained"))
    elif delta_ratio < 0 and price_chg >= -rng * 0.25:
        comps.append(("cvd_vs_price", _clip(delta_ratio * 3), 0.30, "net aggressive selling while price holds"))
    else:
        comps.append(("cvd_vs_price", _clip(delta_ratio), 0.15, "delta aligned with price move"))

    # 2. Large transaction balance
    lt = ev.large_buy_value + ev.large_sell_value
    if lt > 0:
        comps.append(
            ("large_trade_balance", (ev.large_buy_value - ev.large_sell_value) / lt, 0.25,
             f"large buys {ev.large_buy_value:,.0f} vs large sells {ev.large_sell_value:,.0f} EGP")
        )
    # 3. Absorption
    ab = ev.bullish_absorptions + ev.bearish_absorptions
    if ab:
        comps.append(
            ("absorption", (ev.bullish_absorptions - ev.bearish_absorptions) / ab, 0.2,
             f"{ev.bullish_absorptions} bid-side / {ev.bearish_absorptions} offer-side absorption events")
        )
    # 4. Replenishing liquidity (potential icebergs)
    ic = ev.bid_icebergs + ev.ask_icebergs
    if ic:
        comps.append(
            ("replenishment", (ev.bid_icebergs - ev.ask_icebergs) / ic, 0.15,
             f"{ev.bid_icebergs} bid / {ev.ask_icebergs} offer potential iceberg levels")
        )
    # 5. Persistent walls
    wp = ev.bid_wall_persistence_ms + ev.ask_wall_persistence_ms
    if wp:
        comps.append(
            ("wall_persistence", (ev.bid_wall_persistence_ms - ev.ask_wall_persistence_ms) / wp, 0.10,
             "relative persistence of bid vs offer walls")
        )

    wsum = sum(w for _, _, w, _ in comps) or 1.0
    acc = sum(max(0.0, v) * w for _, v, w, _ in comps) / wsum
    dist = sum(max(0.0, -v) * w for _, v, w, _ in comps) / wsum
    evidence = [
        {"factor": n, "value": round(v, 3), "weight": w, "note": note,
         "direction": "accumulation" if v > 0 else "distribution" if v < 0 else "neutral"}
        for n, v, w, note in comps
    ]
    evidence.append({"factor": "price_change_pct", "value": round(price_chg * 100, 3), "weight": 0, "note": "context"})
    if acc >= 0.3 and acc > dist * 1.5:
        return FlowSignal("accumulation", round(acc, 3), round(acc, 3), round(dist, 3), evidence)
    if dist >= 0.3 and dist > acc * 1.5:
        return FlowSignal("distribution", round(dist, 3), round(acc, 3), round(dist, 3), evidence)
    return FlowSignal("neutral", round(max(acc, dist), 3), round(acc, 3), round(dist, 3), evidence)
