"""Volume profile with Point of Control and Value Area."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.domain.models import Side, Trade
from app.market_data.normalizer import rp


class VolumeProfile:
    def __init__(self) -> None:
        # price -> [buy, sell, unknown]
        self.levels: dict[float, list[float]] = {}
        self.total = 0.0

    def add(self, price: float, qty: float, side: Side) -> None:
        p = rp(price)
        lv = self.levels.get(p)
        if lv is None:
            lv = self.levels[p] = [0.0, 0.0, 0.0]
        lv[0 if side == Side.BUY else 1 if side == Side.SELL else 2] += qty
        self.total += qty

    def add_trade(self, t: Trade) -> None:
        self.add(t.price, t.quantity, t.side)

    def volume_at(self, price: float) -> float:
        lv = self.levels.get(rp(price))
        return sum(lv) if lv else 0.0

    @property
    def poc(self) -> float | None:
        if not self.levels:
            return None
        # ties -> the lower price (deterministic)
        return max(sorted(self.levels), key=lambda p: sum(self.levels[p]))

    def value_area(self, pct: float = 0.70) -> tuple[float | None, float | None]:
        """Return (VAL, VAH) containing ``pct`` of volume, grown out from the POC.

        At each step the adjacent level (above or below) with more volume is
        added; ties prefer the level above.
        """
        if not self.levels:
            return None, None
        prices = sorted(self.levels)
        vols = [sum(self.levels[p]) for p in prices]
        poc = self.poc
        i = j = prices.index(poc)  # type: ignore[arg-type]
        acc = vols[i]
        target = self.total * pct
        while acc < target and (i > 0 or j < len(prices) - 1):
            up = vols[j + 1] if j < len(prices) - 1 else -1.0
            dn = vols[i - 1] if i > 0 else -1.0
            if up >= dn:
                j += 1
                acc += up
            else:
                i -= 1
                acc += dn
        return prices[i], prices[j]

    def to_dict(self, value_area_pct: float = 0.70) -> dict[str, Any]:
        val, vah = self.value_area(value_area_pct)
        return {
            "levels": [[p, *self.levels[p]] for p in sorted(self.levels)],
            "total": self.total,
            "poc": self.poc,
            "val": val,
            "vah": vah,
            "value_area_pct": value_area_pct,
        }


def profile_from_trades(
    trades: Iterable[Trade], t0: int | None = None, t1: int | None = None
) -> VolumeProfile:
    vp = VolumeProfile()
    for t in trades:
        if t0 is not None and t.ts < t0:
            continue
        if t1 is not None and t.ts > t1:
            continue
        vp.add_trade(t)
    return vp
