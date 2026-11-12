"""Price normalization and tick-size resolution.

Tick sizes are never hardcoded: they come from instrument metadata (provider or
explicit configuration). When neither is available the resolver infers the
smallest observed price increment and labels the result ``inferred``.
"""

from __future__ import annotations

import math

PRICE_DECIMALS = 4


def rp(price: float) -> float:
    """Round a price to a stable key representation."""
    return round(price, PRICE_DECIMALS)


class TickSizeResolver:
    def __init__(self, tick_size: float | None = None, source: str = "unknown") -> None:
        self._tick = tick_size
        self.source = source if tick_size else "unknown"
        self._observed: set[float] = set()
        self._inferred: float | None = None

    @property
    def tick(self) -> float | None:
        return self._tick or self._inferred

    def observe(self, price: float) -> None:
        if self._tick is not None or price <= 0:
            return
        p = rp(price)
        if p in self._observed or len(self._observed) > 2000:
            return
        self._observed.add(p)
        if len(self._observed) >= 3:
            prices = sorted(self._observed)
            diffs = [round(b - a, PRICE_DECIMALS) for a, b in zip(prices, prices[1:]) if b - a > 1e-9]
            if diffs:
                # GCD of diffs on a 1e-3 grid gives the finest consistent increment.
                g = 0
                for d in diffs:
                    g = math.gcd(g, int(round(d * 1000)))
                if g > 0:
                    self._inferred = g / 1000
                    self.source = "inferred"

    def snap(self, price: float) -> float:
        t = self.tick
        if not t:
            return rp(price)
        return rp(round(price / t) * t)
