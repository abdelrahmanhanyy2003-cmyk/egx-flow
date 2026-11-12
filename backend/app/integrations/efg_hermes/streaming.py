"""Lightstreamer streaming adapter (via the SDK's ``client.streaming``).

Streams used (all documented in the SDK):

* ``subscribe_quote(symbol)``   -> SymbolStatistics (MERGE)  -> :class:`Quote`
* ``subscribe_trades(symbol)``  -> SecurityTrades (COMMAND)  -> :class:`Trade`
* ``subscribe_market(market)``  -> MarketStatistics (MERGE)  -> :class:`MarketStats`
* ``subscribe_index(index_id)`` -> IndexStatistics (MERGE)   -> :class:`IndexValue`

Not used: ``subscribe_orders`` is only consumed by the portfolio adapter for
display; nothing here can place or modify orders.

Callbacks fire on the Lightstreamer thread; they only normalize and hand the
event to the thread-safe sink.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger
from app.core.timeutil import now_ms
from app.domain.models import DataQuality, MarketEvent, ProviderStatusEvent
from app.integrations.efg_hermes import normalization as N

log = get_logger(__name__)


class StreamingAdapter:
    def __init__(
        self,
        client: Any,  # ReadOnlyYounitClient
        sink: Callable[[MarketEvent], None],
        side_map: dict[str, str],
        market_id: int,
        index_id: int | None,
        quality: DataQuality = DataQuality.LIVE,
    ) -> None:
        self.quality = quality
        self.client = client
        self.sink = sink
        self.side_map = side_map
        self.market_id = market_id
        self.index_id = index_id
        self.merger = N.QuoteMerger()
        self.symbols: set[str] = set()
        self._subs: dict[str, list[Any]] = {}
        self._global_subs: list[Any] = []
        self._lock = threading.RLock()
        self.last_event_ms: int | None = None
        self.errors = 0
        self.trade_deletes = 0

    # ----------------------------------------------------------- callbacks
    def _on_error(self, exc: Exception) -> None:
        self.errors += 1
        log.warning("efg_stream_error", error=type(exc).__name__)
        self.sink(ProviderStatusEvent("efg_younit", "error", type(exc).__name__, now_ms()))

    def _quote_cb(self, symbol: str) -> Callable[[Any], None]:
        def cb(u: Any) -> None:
            r = now_ms()
            self.last_event_ms = r
            merged = self.merger.merge(symbol, u)
            q = N.symbol_update_to_quote(symbol, merged, r)
            q.quality = self.quality
            self.sink(q)

        return cb

    def _trade_cb(self, symbol: str) -> Callable[[Any], None]:
        def cb(u: Any) -> None:
            r = now_ms()
            self.last_event_ms = r
            if (getattr(u, "command", None) or "").upper() == "DELETE":
                self.trade_deletes += 1
                return
            t = N.trade_update_to_trade(symbol, u, r, self.side_map)
            if t is not None:
                t.quality = self.quality
                self.sink(t)

        return cb

    def _market_cb(self, u: Any) -> None:
        r = now_ms()
        self.last_event_ms = r
        self.sink(N.market_update_to_stats(u, r))

    def _index_cb(self, u: Any) -> None:
        r = now_ms()
        self.last_event_ms = r
        self.sink(N.index_update_to_value(u, r))

    # -------------------------------------------------------- subscriptions
    def connect(self) -> None:
        self.client.streaming.connect()
        with self._lock:
            if not self._global_subs:
                self._global_subs.append(
                    self.client.streaming.subscribe_market(
                        market_id=self.market_id, on_update=self._market_cb, on_error=self._on_error
                    )
                )
                if self.index_id is not None:
                    self._global_subs.append(
                        self.client.streaming.subscribe_index(
                            self.index_id, on_update=self._index_cb, on_error=self._on_error
                        )
                    )

    def subscribe(self, symbol: str) -> None:
        with self._lock:
            if symbol in self._subs:
                return
            subs = [
                self.client.streaming.subscribe_quote(symbol, on_update=self._quote_cb(symbol), on_error=self._on_error),
                self.client.streaming.subscribe_trades(symbol, on_update=self._trade_cb(symbol), on_error=self._on_error),
            ]
            self._subs[symbol] = subs
            self.symbols.add(symbol)

    def unsubscribe(self, symbol: str) -> None:
        with self._lock:
            for s in self._subs.pop(symbol, []):
                try:
                    self.client.streaming.unsubscribe(s)
                except Exception:  # noqa: BLE001
                    log.warning("efg_unsubscribe_failed", symbol=symbol)
            self.symbols.discard(symbol)

    def is_connected(self) -> bool:
        try:
            return bool(self.client.streaming.is_connected())
        except Exception:  # noqa: BLE001
            return False

    def resubscribe_all(self) -> None:
        """After a reconnect, rebuild every subscription from scratch.

        ``self.symbols`` is the *desired* set and survives failed attempts.
        """
        with self._lock:
            syms = sorted(self.symbols)
            self._subs.clear()
            self._global_subs.clear()
        self.connect()
        for s in syms:
            self.subscribe(s)

    def disconnect(self) -> None:
        try:
            self.client.streaming.disconnect()
        except Exception:  # noqa: BLE001
            pass


class ConnectionMonitor:
    """Heartbeat + automatic reconnection with exponential back-off.

    Runs in its own daemon thread (the SDK is synchronous).
    """

    def __init__(
        self,
        adapter: StreamingAdapter,
        on_status: Callable[[str, str], None],
        stale_after_s: float = 30.0,
        market_open: Callable[[], bool] = lambda: True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.adapter = adapter
        self.on_status = on_status
        self.stale_after_s = stale_after_s
        self.market_open = market_open
        self.sleep = sleep
        self.reconnects = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="efg-conn-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def check_once(self) -> str:
        """One heartbeat evaluation; returns the resulting state."""
        if not self.adapter.is_connected():
            self.on_status("connecting", "stream disconnected - reconnecting")
            if self.reconnect():
                return "connected"
            return "error"
        last = self.adapter.last_event_ms
        if last is not None and self.market_open() and (now_ms() - last) / 1000 > self.stale_after_s:
            self.on_status("degraded", f"no stream updates for {int((now_ms() - last) / 1000)}s")
            return "degraded"
        self.on_status("connected", "streaming")
        return "connected"

    def reconnect(self, max_attempts: int = 6) -> bool:
        delay = 1.0
        for attempt in range(1, max_attempts + 1):
            if self._stop.is_set():
                return False
            try:
                self.adapter.disconnect()
                self.adapter.resubscribe_all()
                self.reconnects += 1
                log.info("efg_reconnected", attempt=attempt)
                return True
            except Exception as exc:  # noqa: BLE001
                log.warning("efg_reconnect_failed", attempt=attempt, error=type(exc).__name__)
                self.sleep(delay)
                delay = min(delay * 2, 60.0)
        self.on_status("error", "reconnect attempts exhausted")
        return False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception as exc:  # noqa: BLE001
                log.warning("efg_monitor_error", error=type(exc).__name__)
            self._stop.wait(5.0)
