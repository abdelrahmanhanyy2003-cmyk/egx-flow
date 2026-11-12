"""Large resting liquidity ("walls") detection and lifecycle tracking.

A level is a wall when its displayed size is a multiple of the median resting
level size AND its EGP value exceeds a floor. Walls are reported only after
persisting for ``min_persistence_ms`` (suppresses flicker). When a wall
disappears we distinguish:

* ``consumed`` - traded volume at the level explains most of the drop;
* ``pulled``   - the liquidity was removed without matching executions.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import BookSide
from app.market_data.orderbook_engine import OrderBook


@dataclass
class WallConfig:
    size_multiple: float = 4.0
    min_value_egp: float = 500_000.0
    min_persistence_ms: int = 3_000
    resize_pct: float = 0.35
    removal_ratio: float = 0.4  # wall gone when qty < ratio * threshold


@dataclass
class Wall:
    id: str
    symbol: str
    side: str
    price: float
    qty: float
    max_qty: float
    first_seen: int
    last_seen: int
    reported_qty: float = 0.0
    reported: bool = False
    status: str = "candidate"  # candidate | active | pulled | consumed
    traded_at_level: float = 0.0
    distance_pct: float | None = None
    distance_ticks: int | None = None

    @property
    def persistence_ms(self) -> int:
        return self.last_seen - self.first_seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "price": self.price,
            "qty": self.qty,
            "max_qty": self.max_qty,
            "value": round(self.price * self.qty, 2),
            "max_value": round(self.price * self.max_qty, 2),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "persistence_ms": self.persistence_ms,
            "status": self.status,
            "distance_pct": self.distance_pct,
            "distance_ticks": self.distance_ticks,
            "traded_at_level": self.traded_at_level,
        }


@dataclass
class WallEvent:
    kind: str  # new | resized | pulled | consumed
    wall: dict[str, Any]
    ts: int
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "wall": self.wall, "ts": self.ts, "detail": self.detail}


class WallDetector:
    def __init__(self, symbol: str, config: WallConfig | None = None) -> None:
        self.symbol = symbol
        self.cfg = config or WallConfig()
        self.walls: dict[tuple[str, float], Wall] = {}
        self.history: list[WallEvent] = []

    def on_trade(self, price: float, qty: float) -> None:
        for (_, p), w in self.walls.items():
            if abs(p - price) < 1e-9:
                w.traded_at_level += qty

    def threshold_qty(self, typical_level: float, price: float) -> float:
        by_mult = typical_level * self.cfg.size_multiple
        by_value = self.cfg.min_value_egp / price if price > 0 else float("inf")
        return max(by_mult, by_value)

    def update(
        self, book: OrderBook, ts: int, typical_level: float | None, tick: float | None
    ) -> list[WallEvent]:
        """``typical_level`` = slow-moving median resting level size (0/None -> current median)."""
        events: list[WallEvent] = []
        mid = book.mid
        if mid is None:
            return events
        if not typical_level:
            sizes = [q for _, q, _ in book.all_levels()]
            typical_level = statistics.median(sizes) if sizes else 0.0
        thr = self.threshold_qty(typical_level, mid)
        seen: set[tuple[str, float]] = set()
        for price, qty, side in book.all_levels():
            if qty < thr:
                continue
            key = (side.value, price)
            seen.add(key)
            w = self.walls.get(key)
            if w is None:
                w = self.walls[key] = Wall(
                    id=f"{self.symbol}:{side.value}:{price}:{ts}",
                    symbol=self.symbol,
                    side=side.value,
                    price=price,
                    qty=qty,
                    max_qty=qty,
                    first_seen=ts,
                    last_seen=ts,
                )
            w.qty = qty
            w.max_qty = max(w.max_qty, qty)
            w.last_seen = ts
            w.distance_pct = round((price - mid) / mid * 100, 3)
            touch = book.best_bid if side == BookSide.BID else book.best_ask
            # ticks from the same-side touch (negative = below best bid)
            w.distance_ticks = int(round((price - touch) / tick)) if tick and touch is not None else None
            if not w.reported and w.persistence_ms >= self.cfg.min_persistence_ms:
                w.reported = True
                w.status = "active"
                w.reported_qty = qty
                events.append(WallEvent("new", w.to_dict(), ts))
            elif w.reported and w.reported_qty and (
                abs(qty - w.reported_qty) / w.reported_qty >= self.cfg.resize_pct
            ):
                events.append(
                    WallEvent("resized", w.to_dict(), ts, {"from": w.reported_qty, "to": qty})
                )
                w.reported_qty = qty

        for key in list(self.walls):
            if key in seen:
                continue
            w = self.walls[key]
            side = BookSide(w.side)
            cur = book.qty_at(side, w.price)
            if cur >= thr * self.cfg.removal_ratio and cur > 0:
                w.qty = cur  # shrank below threshold but still meaningful: keep tracking
                w.last_seen = ts
                continue
            del self.walls[key]
            if not w.reported:
                continue
            dropped = max(0.0, w.qty - cur)
            crossed = (side == BookSide.BID and book.best_ask is not None and w.price >= book.best_ask) or (
                side == BookSide.ASK and book.best_bid is not None and w.price <= book.best_bid
            )
            if crossed or (dropped > 0 and w.traded_at_level >= 0.5 * dropped):
                w.status = "consumed"
            else:
                w.status = "pulled"
            ev = WallEvent(
                w.status, w.to_dict(), ts, {"dropped": dropped, "traded": w.traded_at_level}
            )
            events.append(ev)
        self.history.extend(events)
        if len(self.history) > 1000:
            self.history = self.history[-1000:]
        return events

    def active(self) -> list[dict[str, Any]]:
        return [w.to_dict() for w in self.walls.values() if w.reported]
