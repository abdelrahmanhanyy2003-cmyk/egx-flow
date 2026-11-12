"""Cumulative Volume Delta.

CVD = cumulative aggressive buy volume - aggressive sell volume. Trades with an
UNKNOWN side contribute zero (never guessed). The share of volume whose side
was *estimated* (quote/tick rule) is tracked so the UI can flag it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

from app.core.timeutil import cairo_date
from app.domain.models import Side, Trade

ResetMode = Literal["session", "none", "interval"]


@dataclass(slots=True)
class CVDPoint:
    t: int
    cvd: float


class CVDCalculator:
    def __init__(
        self,
        reset: ResetMode = "session",
        interval_minutes: int = 60,
        bucket_ms: int = 1000,
        max_points: int = 20000,
    ) -> None:
        self.reset = reset
        self.interval_ms = interval_minutes * 60_000
        self.bucket_ms = bucket_ms
        self.cvd = 0.0
        self.session_delta = 0.0
        self.buy_volume = 0.0
        self.sell_volume = 0.0
        self.unknown_volume = 0.0
        self.estimated_volume = 0.0
        self.points: deque[CVDPoint] = deque(maxlen=max_points)
        self._period_key: object = None
        self._session_key: object = None

    def _period(self, ts: int) -> object:
        if self.reset == "session":
            return cairo_date(ts)
        if self.reset == "interval":
            return ts // self.interval_ms
        return 0

    def add(self, trade: Trade) -> float:
        pk = self._period(trade.ts)
        if self._period_key is None:
            self._period_key = pk
        elif pk != self._period_key and self.reset != "none":
            self.cvd = 0.0
            self._period_key = pk
        sk = cairo_date(trade.ts)
        if sk != self._session_key:
            self._session_key = sk
            self.session_delta = 0.0
            self.buy_volume = self.sell_volume = self.unknown_volume = self.estimated_volume = 0.0

        d = 0.0
        if trade.side == Side.BUY:
            d = trade.quantity
            self.buy_volume += trade.quantity
        elif trade.side == Side.SELL:
            d = -trade.quantity
            self.sell_volume += trade.quantity
        else:
            self.unknown_volume += trade.quantity
        if trade.estimated:
            self.estimated_volume += trade.quantity
        self.cvd += d
        self.session_delta += d

        bt = trade.ts - trade.ts % self.bucket_ms
        if self.points and self.points[-1].t == bt:
            self.points[-1].cvd = self.cvd
        elif not self.points or bt > self.points[-1].t:
            self.points.append(CVDPoint(bt, self.cvd))
        return self.cvd

    @property
    def estimated_share(self) -> float:
        total = self.buy_volume + self.sell_volume + self.unknown_volume
        return self.estimated_volume / total if total else 0.0

    def summary(self) -> dict[str, Any]:
        total = self.buy_volume + self.sell_volume + self.unknown_volume
        return {
            "cvd": self.cvd,
            "session_delta": self.session_delta,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "unknown_volume": self.unknown_volume,
            "buy_pct": self.buy_volume / total * 100 if total else None,
            "estimated_share": round(self.estimated_share, 4),
            "reset": self.reset,
        }

    def series_since(self, t: int) -> list[list[float]]:
        return [[p.t, p.cvd] for p in self.points if p.t > t]


def compute_cvd(trades: list[Trade]) -> list[float]:
    """Pure helper: running CVD for a list of trades (no resets)."""
    out: list[float] = []
    c = 0.0
    for t in trades:
        if t.side == Side.BUY:
            c += t.quantity
        elif t.side == Side.SELL:
            c -= t.quantity
        out.append(c)
    return out


def detect_divergence(
    closes: list[float], cvds: list[float], lookback: int = 20
) -> dict[str, Any] | None:
    """Detect price/CVD divergence on the most recent bar.

    Bearish: price prints a new high over ``lookback`` bars while CVD does not.
    Bullish: price prints a new low while CVD does not.
    """
    n = min(len(closes), len(cvds))
    if n < lookback + 1:
        return None
    pc, cc = closes[-1], cvds[-1]
    prev_p = closes[-lookback - 1 : -1]
    prev_c = cvds[-lookback - 1 : -1]
    if pc > max(prev_p) and cc < max(prev_c):
        strength = (max(prev_c) - cc) / (abs(max(prev_c)) + 1e-9)
        return {"kind": "bearish", "price": pc, "cvd": cc, "strength": round(min(1.0, strength), 3)}
    if pc < min(prev_p) and cc > min(prev_c):
        strength = (cc - min(prev_c)) / (abs(min(prev_c)) + 1e-9)
        return {"kind": "bullish", "price": pc, "cvd": cc, "strength": round(min(1.0, strength), 3)}
    return None
