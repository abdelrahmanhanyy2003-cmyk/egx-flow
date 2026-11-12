"""Heuristic detector for POTENTIAL iceberg-like activity.

This never confirms hidden orders. Confirmation requires order-level (MBO)
data with explicit hidden/reserve flags, which no current EGX provider in this
application exposes. Signals are always labelled ``estimated``.

Evidence considered at a single price level on the passive side:

* repeated executions at the same price;
* displayed size being replenished after executions;
* executed volume exceeding the maximum displayed size;
* the level holding (price not trading through it).

Confidence is scaled down when the book resolution is coarse (L1-only or
periodic snapshots), because replenishment may be hidden between samples or
confused with new visible orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.models import BookResolution, BookSide, Side
from app.market_data.orderbook_engine import LevelChange

RESOLUTION_FACTOR = {
    BookResolution.ORDER_EVENTS: 1.0,
    BookResolution.DEPTH_UPDATES: 0.9,
    BookResolution.DEPTH_SNAPSHOTS: 0.75,
    BookResolution.L1_ONLY: 0.55,
    BookResolution.NONE: 0.0,
}


@dataclass
class IcebergConfig:
    min_exec_ratio: float = 2.0  # executed / max displayed
    min_replenishments: int = 3
    min_executions: int = 4
    replenish_window_ms: int = 3_000  # size must reappear soon after executions
    refill_tolerance: float = 0.35  # refill must be within +/-35% of the initial clip size
    expire_ms: int = 300_000


@dataclass
class _LevelState:
    side: BookSide
    price: float
    first_ts: int
    first_displayed: float
    max_displayed: float
    displayed: float
    executed: float = 0.0
    executions: int = 0
    replenishments: int = 0
    exec_since_change: float = 0.0
    last_ts: int = 0
    last_exec_ts: int = 0
    reported_conf: float = 0.0


@dataclass
class IcebergSignal:
    symbol: str
    side: str  # passive side holding the level
    price: float
    displayed: float
    max_displayed: float
    executed: float
    estimated_hidden: float
    replenishments: int
    executions: int
    confidence: float
    first_ts: int
    last_ts: int
    resolution: str

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["estimated"] = True
        d["label"] = "Potential iceberg (heuristic estimate - not a confirmed hidden order)"
        return d


class IcebergDetector:
    def __init__(self, symbol: str, config: IcebergConfig | None = None) -> None:
        self.symbol = symbol
        self.cfg = config or IcebergConfig()
        self.levels: dict[tuple[BookSide, float], _LevelState] = {}
        self.resolution = BookResolution.NONE

    def _state(self, side: BookSide, price: float, displayed: float, ts: int) -> _LevelState:
        key = (side, price)
        st = self.levels.get(key)
        if st is None:
            st = self.levels[key] = _LevelState(side, price, ts, displayed, displayed, displayed, last_ts=ts)
        return st

    def on_trade(
        self, price: float, qty: float, aggressor: Side, ts: int, displayed_bid: float,
        displayed_ask: float, best_bid: float | None, best_ask: float | None,
    ) -> None:
        if aggressor == Side.BUY:
            side, disp = BookSide.ASK, displayed_ask
        elif aggressor == Side.SELL:
            side, disp = BookSide.BID, displayed_bid
        else:
            # infer passive side purely from where the price sits in the book
            if best_ask is not None and price >= best_ask:
                side, disp = BookSide.ASK, displayed_ask
            elif best_bid is not None and price <= best_bid:
                side, disp = BookSide.BID, displayed_bid
            else:
                return
        st = self._state(side, price, disp, ts)
        st.executed += qty
        st.executions += 1
        st.exec_since_change += qty
        st.last_ts = ts
        st.last_exec_ts = ts

    def on_level_change(self, ch: LevelChange, ts: int) -> None:
        st = self.levels.get((ch.side, ch.price))
        if st is None:
            if ch.after > 0:
                self.levels[(ch.side, ch.price)] = _LevelState(
                    ch.side, ch.price, ts, ch.after, ch.after, ch.after, last_ts=ts
                )
            return
        # A size increase shortly after executions, back to roughly the same displayed
        # size (iceberg peaks refresh to a constant clip) = replenishment.
        if ch.after > ch.before and st.exec_since_change > 0:
            ref = st.first_displayed or st.max_displayed
            similar = ref > 0 and abs(ch.after - ref) / ref <= self.cfg.refill_tolerance
            if ts - st.last_exec_ts <= self.cfg.replenish_window_ms and similar:
                st.replenishments += 1
            st.exec_since_change = 0.0
        st.displayed = ch.after
        st.max_displayed = max(st.max_displayed, ch.after)
        st.last_ts = ts

    def evaluate(
        self, ts: int, best_bid: float | None = None, best_ask: float | None = None
    ) -> list[IcebergSignal]:
        out: list[IcebergSignal] = []
        rf = RESOLUTION_FACTOR.get(self.resolution, 0.5)
        for key in list(self.levels):
            st = self.levels[key]
            if ts - st.last_ts > self.cfg.expire_ms:
                del self.levels[key]
                continue
            # The level must hold: if price traded through it, the hypothesis is void.
            broken = (st.side == BookSide.BID and best_bid is not None and best_bid < st.price - 1e-9) or (
                st.side == BookSide.ASK and best_ask is not None and best_ask > st.price + 1e-9
            )
            if broken:
                del self.levels[key]
                continue
            if st.max_displayed <= 0:
                continue
            ratio = st.executed / st.max_displayed
            if (
                ratio >= self.cfg.min_exec_ratio
                and st.replenishments >= self.cfg.min_replenishments
                and st.executions >= self.cfg.min_executions
            ):
                base = 0.3 + 0.08 * min(st.replenishments, 6) + 0.12 * min(ratio - 1.0, 2.5)
                conf = round(min(0.95, base) * rf, 3)
                out.append(
                    IcebergSignal(
                        symbol=self.symbol,
                        side=st.side.value,
                        price=st.price,
                        displayed=st.displayed,
                        max_displayed=st.max_displayed,
                        executed=st.executed,
                        estimated_hidden=max(0.0, st.executed - st.max_displayed),
                        replenishments=st.replenishments,
                        executions=st.executions,
                        confidence=conf,
                        first_ts=st.first_ts,
                        last_ts=st.last_ts,
                        resolution=self.resolution.value,
                    )
                )
        return out
