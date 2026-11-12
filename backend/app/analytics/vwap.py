"""Session VWAP and anchored VWAP with standard-deviation bands."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class VWAP:
    anchor_ts: int | None = None
    pv: float = 0.0
    v: float = 0.0
    p2v: float = 0.0

    def add(self, price: float, qty: float, ts: int | None = None) -> None:
        if self.anchor_ts is not None and ts is not None and ts < self.anchor_ts:
            return
        self.pv += price * qty
        self.v += qty
        self.p2v += price * price * qty

    @property
    def value(self) -> float | None:
        return self.pv / self.v if self.v else None

    @property
    def stdev(self) -> float | None:
        if not self.v:
            return None
        m = self.pv / self.v
        var = max(0.0, self.p2v / self.v - m * m)
        return math.sqrt(var)

    def bands(self, k: float = 1.0) -> tuple[float | None, float | None]:
        m, s = self.value, self.stdev
        if m is None or s is None:
            return None, None
        return m - k * s, m + k * s


def vwap(prices: Iterable[float], qtys: Iterable[float]) -> float | None:
    pv = v = 0.0
    for p, q in zip(prices, qtys):
        pv += p * q
        v += q
    return pv / v if v else None


def anchored_vwap_series(
    points: list[tuple[int, float, float]], anchor_ts: int
) -> list[tuple[int, float]]:
    """``points`` = (ts, price, qty) sorted by ts. Returns (ts, avwap) from anchor."""
    out: list[tuple[int, float]] = []
    pv = v = 0.0
    for ts, p, q in points:
        if ts < anchor_ts:
            continue
        pv += p * q
        v += q
        if v:
            out.append((ts, pv / v))
    return out
