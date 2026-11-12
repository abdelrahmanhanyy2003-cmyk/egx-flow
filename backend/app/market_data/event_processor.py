"""Thread-safe event intake: buffering, backpressure, dedup, gap detection.

Providers push events from arbitrary threads (e.g. Lightstreamer callbacks).
:class:`EventBuffer` hands them to the asyncio loop through a bounded,
order-preserving buffer:

* Trades and book deltas are never coalesced. If the buffer overflows the
  oldest ordered event is dropped, counted, and the symbol is flagged as having
  a gap (surfaced in the UI as a data-integrity warning).
* Quotes, book snapshots and market/index stats are *coalesced* per key: when a
  newer one arrives the older pending one is tombstoned and the newer one is
  appended at the end, so arrival order relative to trades is preserved.

:class:`EventValidator` performs dedup, timestamp sanity and sequence-gap checks.
"""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from app.core.timeutil import now_ms
from app.domain.models import (
    BookDelta,
    BookSnapshot,
    DataQuality,
    IndexValue,
    MarketEvent,
    MarketStats,
    ProviderStatusEvent,
    Quote,
    Trade,
)


def _coalesce_key(ev: MarketEvent) -> tuple[str, str] | None:
    if isinstance(ev, Quote):
        return ("q", ev.symbol)
    if isinstance(ev, BookSnapshot):
        return ("b", ev.symbol)
    if isinstance(ev, MarketStats):
        return ("m", str(ev.market_id))
    if isinstance(ev, IndexValue):
        return ("i", str(ev.index_id))
    return None


@dataclass
class BufferMetrics:
    received: int = 0
    coalesced: int = 0
    overflow: int = 0
    max_depth: int = 0


class EventBuffer:
    def __init__(self, maxsize: int = 50000) -> None:
        self.maxsize = maxsize
        self._lock = threading.Lock()
        self._items: deque[tuple[int, MarketEvent]] = deque()
        self._pending_key: dict[tuple[str, str], int] = {}
        self._tomb: set[int] = set()
        self._next = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self.metrics = BufferMetrics()
        self.gap_symbols: set[str] = set()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._wake = asyncio.Event()

    def put(self, ev: MarketEvent) -> None:
        """Thread-safe producer entry point."""
        if hasattr(ev, "received_ts") and not ev.received_ts:  # type: ignore[union-attr]
            ev.received_ts = now_ms()  # type: ignore[union-attr]
        with self._lock:
            self.metrics.received += 1
            key = _coalesce_key(ev)
            if key is not None:
                old = self._pending_key.get(key)
                if old is not None:
                    self._tomb.add(old)
                    self.metrics.coalesced += 1
                self._pending_key[key] = self._next
            live = len(self._items) - len(self._tomb)
            if live >= self.maxsize:
                # drop oldest live event
                while self._items:
                    i, dropped = self._items.popleft()
                    if i in self._tomb:
                        self._tomb.discard(i)
                        continue
                    self.metrics.overflow += 1
                    sym = getattr(dropped, "symbol", None)
                    if sym and isinstance(dropped, (Trade, BookDelta)):
                        self.gap_symbols.add(sym)
                    dk = _coalesce_key(dropped)
                    if dk is not None and self._pending_key.get(dk) == i:
                        del self._pending_key[dk]
                    break
            self._items.append((self._next, ev))
            self._next += 1
            depth = len(self._items) - len(self._tomb)
            if depth > self.metrics.max_depth:
                self.metrics.max_depth = depth
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass

    def drain(self, limit: int = 10000) -> list[MarketEvent]:
        out: list[MarketEvent] = []
        with self._lock:
            while self._items and len(out) < limit:
                i, ev = self._items.popleft()
                if i in self._tomb:
                    self._tomb.discard(i)
                    continue
                k = _coalesce_key(ev)
                if k is not None and self._pending_key.get(k) == i:
                    del self._pending_key[k]
                out.append(ev)
        return out

    async def wait(self, timeout: float = 0.25) -> None:
        if self._wake is None:
            await asyncio.sleep(timeout)
            return
        try:
            await asyncio.wait_for(self._wake.wait(), timeout)
        except (TimeoutError, asyncio.TimeoutError):
            pass
        self._wake.clear()

    def depth(self) -> int:
        with self._lock:
            return len(self._items) - len(self._tomb)


@dataclass
class StreamHealth:
    last_seq: int | None = None
    gaps: int = 0
    duplicates: int = 0
    late: int = 0
    last_ts: int = 0
    last_received: int = 0


@dataclass
class EventValidator:
    dedup_capacity: int = 200_000
    late_tolerance_ms: int = 2_000
    _seen: OrderedDict[tuple[str, str], None] = field(default_factory=OrderedDict)
    health: dict[str, StreamHealth] = field(default_factory=dict)

    def _h(self, key: str) -> StreamHealth:
        h = self.health.get(key)
        if h is None:
            h = self.health[key] = StreamHealth()
        return h

    def accept(self, ev: MarketEvent) -> bool:
        """Return False for events that must be discarded (duplicates)."""
        if isinstance(ev, ProviderStatusEvent):
            return True
        sym = getattr(ev, "symbol", None) or "_market"
        h = self._h(sym)
        if isinstance(ev, Trade):
            key = (ev.symbol, ev.trade_id)
            if key in self._seen:
                h.duplicates += 1
                return False
            self._seen[key] = None
            if len(self._seen) > self.dedup_capacity:
                self._seen.popitem(last=False)
        seq = getattr(ev, "seq", None)
        if isinstance(ev, (Trade, BookDelta)) and seq is not None:
            if h.last_seq is not None:
                if seq <= h.last_seq:
                    h.duplicates += 1
                    return False
                if seq > h.last_seq + 1:
                    h.gaps += seq - h.last_seq - 1
            h.last_seq = seq
        ts = getattr(ev, "ts", 0)
        if isinstance(ev, Trade) and ts and h.last_ts and ts < h.last_ts - self.late_tolerance_ms:
            h.late += 1  # out-of-order but valid; counted, kept, downgraded
            if ev.quality == DataQuality.LIVE:
                ev.quality = DataQuality.DELAYED
        if ts > h.last_ts:
            h.last_ts = ts
        h.last_received = now_ms()
        return True

    def report(self) -> dict[str, dict[str, int | None]]:
        return {
            k: {
                "gaps": v.gaps,
                "duplicates": v.duplicates,
                "late": v.late,
                "last_ts": v.last_ts,
                "last_received": v.last_received,
            }
            for k, v in self.health.items()
        }
