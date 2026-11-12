"""Historical replay of RECORDED sessions.

Replay feeds stored trades and stored order-book snapshots, in timestamp
order, through a fresh :class:`SymbolState` - the exact same code path as live
processing - so CVD, profiles, walls and large-trade detection reproduce what
was computed live. Nothing is reconstructed from OHLCV candles; if a session
has no recorded book snapshots the heatmap stays empty and the UI says so.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import (
    BookResolution,
    BookSnapshot,
    ClassificationMethod,
    DataQuality,
    Instrument,
    Side,
    Trade,
)
from app.market_data.symbol_state import SymbolState

ReplayEvent = tuple[int, int, Any]  # (ts, order, payload) ; order: 0 trade, 1 book


def build_events(trade_rows: list[Any], book_rows: list[Any]) -> list[ReplayEvent]:
    evs: list[ReplayEvent] = []
    for r in trade_rows:
        evs.append((r.ts, 0, r))
    for r in book_rows:
        evs.append((r.ts, 1, r))
    evs.sort(key=lambda e: (e[0], e[1]))
    return evs


def row_to_trade(r: Any) -> Trade:
    return Trade(
        trade_id=r.trade_id, symbol=r.symbol, price=r.price, quantity=r.quantity, ts=r.ts, source=r.source,
        quality=DataQuality(r.quality), side=Side(r.side), method=ClassificationMethod(r.method),
        confidence=r.confidence, received_ts=r.received_ts, provider_side_raw=r.provider_side_raw,
    )


def row_to_book(r: Any) -> BookSnapshot:
    return BookSnapshot(
        symbol=r.symbol, bids=[(p, q) for p, q in r.bids], asks=[(p, q) for p, q in r.asks], ts=r.ts,
        source=r.source, quality=DataQuality(r.quality), resolution=BookResolution(r.resolution),
    )


@dataclass
class ReplaySession:
    session: dict[str, Any]
    instrument: Instrument
    events: list[ReplayEvent]
    speed: float = 1.0
    playing: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    idx: int = 0
    cursor: int = 0
    state: SymbolState | None = None
    _last_analytics: int = 0

    def __post_init__(self) -> None:
        self.reset()

    @property
    def start_ts(self) -> int:
        return self.events[0][0] if self.events else self.session["first_ts"]

    @property
    def end_ts(self) -> int:
        return self.events[-1][0] if self.events else self.session["last_ts"]

    def reset(self) -> None:
        self.state = SymbolState(self.instrument, heatmap_columns=20000, depth_levels=30,
                                 quality=DataQuality(self.session["quality"]) if self.session.get("quality") else DataQuality.HISTORICAL)
        self.idx = 0
        self.cursor = self.start_ts
        self._last_analytics = 0

    def _apply_until(self, target: int) -> int:
        assert self.state is not None
        n = 0
        while self.idx < len(self.events) and self.events[self.idx][0] <= target:
            ts, kind, row = self.events[self.idx]
            if kind == 0:
                self.state.on_trade(row_to_trade(row))
            else:
                self.state.on_book_snapshot(row_to_book(row))
                self.state.sample(ts)
            if ts - self._last_analytics >= 2000:
                self.state.analytics_tick(ts)
                self._last_analytics = ts
            self.idx += 1
            n += 1
        self.cursor = target
        return n

    def advance(self, wall_ms: float) -> int:
        if not self.playing:
            return 0
        target = min(self.end_ts, int(self.cursor + wall_ms * self.speed))
        n = self._apply_until(target)
        if target >= self.end_ts:
            self.playing = False
        return n

    def seek(self, ts: int) -> None:
        ts = max(self.start_ts, min(self.end_ts, ts))
        if ts < self.cursor:
            self.reset()
        self._apply_until(ts)
        assert self.state is not None
        self.state.discard_updates()

    def info(self) -> dict[str, Any]:
        return {
            "id": self.id, "session": self.session, "symbol": self.instrument.symbol, "speed": self.speed,
            "playing": self.playing, "cursor": self.cursor, "start_ts": self.start_ts, "end_ts": self.end_ts,
            "events": len(self.events), "position": self.idx,
            "quality": self.session.get("quality"),
            "book_resolution": self.session.get("book_resolution"),
            "book_record_interval_ms": self.session.get("book_record_interval_ms"),
        }
