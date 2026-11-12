"""Liquidity heatmap history.

At a fixed resolution the current book is sampled into a compact column. The
column records exactly what the book held at that moment - nothing is
interpolated. If the provider only supplies L1, columns contain only the best
bid/ask levels and are labelled ``l1_only``.
"""

from __future__ import annotations

from array import array
from collections import deque
from dataclasses import dataclass
from typing import Any

from app.domain.models import BookResolution
from app.market_data.orderbook_engine import OrderBook


@dataclass(slots=True)
class HeatColumn:
    t: int
    best_bid: float | None
    best_ask: float | None
    last: float | None
    prices: array  # 'd'
    qtys: array  # 'd' - positive = bid, negative = ask (compact side encoding)
    resolution: BookResolution

    def to_wire(self) -> list[Any]:
        return [
            self.t,
            self.best_bid,
            self.best_ask,
            self.last,
            [round(p, 4) for p in self.prices],
            [round(q) for q in self.qtys],
        ]


class HeatmapHistory:
    def __init__(self, max_columns: int, depth_levels: int) -> None:
        self.columns: deque[HeatColumn] = deque(maxlen=max_columns)
        self.depth_levels = depth_levels
        self.max_qty_seen: float = 0.0
        self.typical_level: float = 0.0

    def capture(self, book: OrderBook, t: int, last: float | None) -> HeatColumn | None:
        if not book.bids and not book.asks:
            return None
        bids, asks = book.top(self.depth_levels)
        prices = array("d")
        qtys = array("d")
        for p, q in bids:
            prices.append(p)
            qtys.append(q)
        for p, q in asks:
            prices.append(p)
            qtys.append(-q)
            if q > self.max_qty_seen:
                self.max_qty_seen = q
        for _, q in bids:
            if q > self.max_qty_seen:
                self.max_qty_seen = q
        col = HeatColumn(t, book.best_bid, book.best_ask, last, prices, qtys, book.resolution)
        self.columns.append(col)
        self.update_typical(col)
        return col

    def since(self, t: int, limit: int | None = None) -> list[HeatColumn]:
        out = [c for c in self.columns if c.t > t] if t else list(self.columns)
        if limit is not None and len(out) > limit:
            out = out[-limit:]
        return out

    def update_typical(self, col: HeatColumn) -> None:
        """Slow EMA of the median resting level size (dynamic wall threshold base)."""
        n = len(col.qtys)
        if not n:
            return
        med = sorted(abs(q) for q in col.qtys)[n // 2]
        self.typical_level = med if self.typical_level <= 0 else self.typical_level * 0.98 + med * 0.02
