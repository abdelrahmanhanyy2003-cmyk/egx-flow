"""Absorption detection.

Absorption = heavy aggressive volume into a price level while that level holds.

* Aggressive SELLING at/near the bid that fails to push price lower ->
  passive buyers absorbing supply (``bullish`` absorption).
* Aggressive BUYING at/near the ask that fails to lift price ->
  passive sellers absorbing demand (``bearish`` absorption).

Trades with UNKNOWN side are ignored (no guessing).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from app.domain.models import Side, Trade


@dataclass
class AbsorptionConfig:
    window_ms: int = 60_000
    min_share: float = 0.35  # share of window aggressive volume at the level
    min_value_egp: float = 300_000.0
    min_trades: int = 4
    max_break_ticks: int = 1
    min_vs_typical: float = 3.0  # absorbed volume vs typical displayed level size


@dataclass
class AbsorptionSignal:
    symbol: str
    kind: str  # bullish | bearish
    price: float
    aggressive_volume: float
    aggressive_value: float
    trades: int
    share: float
    held: bool
    ts: int
    window_start: int
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["label"] = (
            "Potential absorption: sellers hitting bid, level holding"
            if self.kind == "bullish"
            else "Potential absorption: buyers lifting offer, level holding"
        )
        return d


class AbsorptionDetector:
    def __init__(self, symbol: str, config: AbsorptionConfig | None = None) -> None:
        self.symbol = symbol
        self.cfg = config or AbsorptionConfig()
        self.trades: deque[Trade] = deque()
        self._last_emit: dict[tuple[str, float], int] = {}

    def on_trade(self, t: Trade) -> None:
        if t.side == Side.UNKNOWN:
            return
        self.trades.append(t)

    def evaluate(
        self, ts: int, best_bid: float | None, best_ask: float | None, tick: float | None,
        typical_level: float | None = None,
    ) -> list[AbsorptionSignal]:
        cutoff = ts - self.cfg.window_ms
        while self.trades and self.trades[0].ts < cutoff:
            self.trades.popleft()
        if not self.trades or tick is None:
            return []
        totals = {Side.BUY: 0.0, Side.SELL: 0.0}
        by_level: dict[tuple[Side, float], list[float]] = {}
        for t in self.trades:
            totals[t.side] += t.quantity
            agg = by_level.setdefault((t.side, t.price), [0.0, 0.0, 0.0])
            agg[0] += t.quantity
            agg[1] += t.value
            agg[2] += 1
        out: list[AbsorptionSignal] = []
        for (side, price), (vol, val, n) in by_level.items():
            tot = totals[side]
            share = vol / tot if tot else 0.0
            if share < self.cfg.min_share or val < self.cfg.min_value_egp or n < self.cfg.min_trades:
                continue
            # more volume absorbed than is typically displayed at a level
            if typical_level and vol < self.cfg.min_vs_typical * typical_level:
                continue
            brk = self.cfg.max_break_ticks * tick
            if side == Side.SELL:
                held = best_bid is not None and best_bid >= price - brk
                kind = "bullish"
            else:
                held = best_ask is not None and best_ask <= price + brk
                kind = "bearish"
            if not held:
                continue
            key = (kind, price)
            last = self._last_emit.get(key)
            if last is not None and ts - last < self.cfg.window_ms:
                continue
            self._last_emit[key] = ts
            conf = round(min(0.9, 0.35 + 0.5 * share + 0.02 * min(n, 10)), 3)
            out.append(
                AbsorptionSignal(
                    self.symbol, kind, price, vol, val, int(n), round(share, 3), held, ts, cutoff, conf
                )
            )
        return out
