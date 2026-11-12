"""Price-level order book maintained from snapshots and/or deltas.

Also computes liquidity changes between successive states, which feed the
liquidity-wall tracker and the iceberg detector.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import BookResolution, BookSide
from app.market_data.normalizer import rp


@dataclass(slots=True)
class LevelChange:
    side: BookSide
    price: float
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before


class OrderBook:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.ts: int = 0
        self.resolution: BookResolution = BookResolution.NONE
        self.updates: int = 0

    # ----- mutation -----
    def apply_snapshot(
        self,
        bids: list[tuple[float, float]],
        asks: list[tuple[float, float]],
        ts: int,
        resolution: BookResolution,
    ) -> list[LevelChange]:
        new_bids = {rp(p): float(q) for p, q in bids if q > 0}
        new_asks = {rp(p): float(q) for p, q in asks if q > 0}
        changes = self._diff(BookSide.BID, self.bids, new_bids) + self._diff(
            BookSide.ASK, self.asks, new_asks
        )
        self.bids, self.asks = new_bids, new_asks
        self.ts = ts
        self.resolution = resolution
        self.updates += 1
        return changes

    def apply_delta(self, side: BookSide, price: float, qty: float, ts: int) -> LevelChange | None:
        book = self.bids if side == BookSide.BID else self.asks
        p = rp(price)
        before = book.get(p, 0.0)
        if qty <= 0:
            book.pop(p, None)
        else:
            book[p] = float(qty)
        self.ts = ts
        self.updates += 1
        if self.resolution == BookResolution.NONE:
            self.resolution = BookResolution.DEPTH_UPDATES
        # remove crossed levels (stale levels left after aggressive executions)
        self._uncross(side)
        if before == qty:
            return None
        return LevelChange(side, p, before, max(qty, 0.0))

    def _uncross(self, updated_side: BookSide) -> None:
        if not self.bids or not self.asks:
            return
        bb, ba = max(self.bids), min(self.asks)
        if bb < ba:
            return
        if updated_side == BookSide.BID:
            for p in [p for p in self.asks if p <= bb]:
                del self.asks[p]
        else:
            for p in [p for p in self.bids if p >= ba]:
                del self.bids[p]

    @staticmethod
    def _diff(side: BookSide, old: dict[float, float], new: dict[float, float]) -> list[LevelChange]:
        out: list[LevelChange] = []
        for p in old.keys() | new.keys():
            b, a = old.get(p, 0.0), new.get(p, 0.0)
            if b != a:
                out.append(LevelChange(side, p, b, a))
        return out

    # ----- queries -----
    @property
    def best_bid(self) -> float | None:
        return max(self.bids) if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return min(self.asks) if self.asks else None

    @property
    def mid(self) -> float | None:
        bb, ba = self.best_bid, self.best_ask
        if bb is None or ba is None:
            return bb if ba is None else ba
        return (bb + ba) / 2

    @property
    def spread(self) -> float | None:
        bb, ba = self.best_bid, self.best_ask
        if bb is None or ba is None:
            return None
        return rp(ba - bb)

    def top(self, n: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        bids = sorted(self.bids.items(), key=lambda x: -x[0])[:n]
        asks = sorted(self.asks.items(), key=lambda x: x[0])[:n]
        return bids, asks

    def qty_at(self, side: BookSide, price: float) -> float:
        return (self.bids if side == BookSide.BID else self.asks).get(rp(price), 0.0)

    def all_levels(self) -> list[tuple[float, float, BookSide]]:
        return [(p, q, BookSide.BID) for p, q in self.bids.items()] + [
            (p, q, BookSide.ASK) for p, q in self.asks.items()
        ]

    def to_dict(self, n: int = 25) -> dict[str, object]:
        bids, asks = self.top(n)
        return {
            "symbol": self.symbol,
            "ts": self.ts,
            "bids": bids,
            "asks": asks,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "spread": self.spread,
            "resolution": self.resolution.value,
        }
