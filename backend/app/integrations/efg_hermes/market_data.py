"""EFG Hermes Younit market-data provider (read-only).

Capabilities reflect what the SDK actually exposes (see
docs/EFG_API_CAPABILITIES.md): Level 1 quotes, the trade tape, market/index
statistics and OHLCV candles. There is NO Level 2 depth stream, so the
heatmap is built from L1 (best bid/ask sizes) and labelled ``l1_only``.
For full depth plug a licensed L2 vendor into :class:`MarketDataProvider`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.timeutil import now_ms
from app.domain.models import BookResolution, DataQuality, Instrument, ProviderStatusEvent
from app.integrations.efg_hermes import normalization as N
from app.integrations.efg_hermes.authentication import create_sdk_client
from app.integrations.efg_hermes.client import ReadOnlyYounitClient
from app.integrations.efg_hermes.streaming import ConnectionMonitor, StreamingAdapter
from app.providers.base import (
    Candle,
    EventSink,
    MarketDataProvider,
    ProviderCapabilities,
    ProviderStatus,
)

log = get_logger(__name__)


class EFGHermesSession:
    """Owns the single read-only SDK client shared by market & portfolio adapters."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: ReadOnlyYounitClient | None = None
        self.error: str | None = None

    def ensure(self) -> ReadOnlyYounitClient:
        if self.client is None:
            raw = create_sdk_client(self.settings)
            self.client = ReadOnlyYounitClient(raw, self.settings.efg_max_requests_per_minute)
        return self.client

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        client = await asyncio.to_thread(self.ensure)
        return await asyncio.to_thread(client.call, method, *args, **kwargs)


class EFGHermesMarketDataProvider(MarketDataProvider):
    name = "efg_younit"

    def __init__(self, settings: Settings, session: EFGHermesSession) -> None:
        self.settings = settings
        self.session = session
        self._status = ProviderStatus(name=self.name)
        self.adapter: StreamingAdapter | None = None
        self.monitor: ConnectionMonitor | None = None
        self._sink: EventSink | None = None
        self._symbol_by_id: dict[str, str] = {}
        self.feed_quality = DataQuality.LIVE
        self.live_datafeed: bool | None = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        mapped = bool(self.settings.transaction_type_map)
        return ProviderCapabilities(
            level1_quotes=True,
            depth_levels=0,
            book_resolution=BookResolution.L1_ONLY,
            trades=True,
            trade_side="provided" if mapped else "unverified",
            historical_candles=True,
            historical_trades=False,
            historical_book=False,
            streaming=True,
            market_stats=True,
            index_values=True,
            portfolio=True,
            open_orders=True,
            order_history=True,
            investor_type_stats=False,
            quality=self.feed_quality,
            notes=[
                f"AccountInfo.is_live_datafeed = {self.live_datafeed} (False -> data labelled DELAYED).",
                "No Level 2 depth in the Younit SDK: heatmap shows best bid/ask (L1) only.",
                "Trade side: TradeUpdate.transaction_type semantics undocumented; quote/tick-rule "
                "estimates are used unless EFG_TRANSACTION_TYPE_MAP is configured.",
                "No historical trades or historical order book: replay uses locally recorded data only.",
                "Market status mapping (2=open, 3=closed) is empirically derived by the SDK authors.",
            ],
        )

    def status(self) -> ProviderStatus:
        if self.monitor:
            self._status.reconnects = self.monitor.reconnects
        if self.adapter:
            self._status.last_event_ms = self.adapter.last_event_ms
            self._status.errors = self.adapter.errors
            self._status.subscriptions = sorted(self.adapter.symbols)
        if self.session.client is not None:
            self._status.rate_limited = self.session.client.rate_limited_count
        return self._status

    def _set_status(self, state: str, detail: str) -> None:
        if state == "connected" and self._status.state != "connected":
            self._status.connected_since_ms = now_ms()
        self._status.state = state
        self._status.detail = detail
        if self._sink:
            self._sink(ProviderStatusEvent(self.name, state, detail, now_ms()))

    async def start(self, sink: EventSink) -> None:
        self._sink = sink
        self._set_status("connecting", "authenticating with EFG Hermes")
        try:
            client = await asyncio.to_thread(self.session.ensure)
        except Exception as exc:  # noqa: BLE001
            self.session.error = type(exc).__name__ + ": " + str(exc)[:200]
            self._set_status("error", f"authentication/initialisation failed: {type(exc).__name__}")
            log.error("efg_init_failed", error=type(exc).__name__)
            return
        # Entitlement: AccountInfo.is_live_datafeed tells whether the feed is real-time.
        try:
            info = await asyncio.to_thread(client.call, "account_info")
            live = getattr(info, "is_live_datafeed", None)
            self.feed_quality = DataQuality.LIVE if live is not False else DataQuality.DELAYED
            self.live_datafeed = live
        except Exception as exc:  # noqa: BLE001
            log.warning("efg_account_info_failed", error=type(exc).__name__)
        self.adapter = StreamingAdapter(
            client, sink, self.settings.transaction_type_map,
            self.settings.efg_market_id, self.settings.efg_egx30_index_id, self.feed_quality,
        )
        try:
            await asyncio.to_thread(self.adapter.connect)
            self._set_status("connected", "streaming")
        except Exception as exc:  # noqa: BLE001
            self._set_status("error", f"streaming connect failed: {type(exc).__name__}")
        self.monitor = ConnectionMonitor(self.adapter, self._set_status, self.settings.stale_after_seconds)
        self.monitor.start()

    async def stop(self) -> None:
        if self.monitor:
            self.monitor.stop()
        if self.adapter:
            await asyncio.to_thread(self.adapter.disconnect)
        self._set_status("disconnected", "stopped")

    async def list_instruments(self) -> list[Instrument]:
        try:
            stocks = await self.session.call("list_stocks", self.settings.efg_market_id)
        except Exception as exc:  # noqa: BLE001
            log.error("efg_list_stocks_failed", error=type(exc).__name__)
            return []
        out: list[Instrument] = []
        for s in stocks:
            inst = N.stock_info_to_instrument(s)
            if inst is None:
                continue
            # equities only (the SDK enriches class names from a snapshot - may be None)
            cls = inst.sector
            if cls is not None and cls not in ("LocalSecurity_IN", "LocalSecurity_OUT", "OTC"):
                continue
            if inst.provider_id:
                self._symbol_by_id[inst.provider_id] = inst.symbol
            out.append(inst)
        return out

    @property
    def symbol_by_id(self) -> dict[str, str]:
        return self._symbol_by_id

    async def subscribe(self, symbols: list[str]) -> None:
        if not self.adapter:
            return
        for s in symbols:
            try:
                await asyncio.to_thread(self.adapter.subscribe, s)
            except Exception as exc:  # noqa: BLE001
                log.warning("efg_subscribe_failed", symbol=s, error=type(exc).__name__)

    async def unsubscribe(self, symbols: list[str]) -> None:
        if not self.adapter:
            return
        for s in symbols:
            await asyncio.to_thread(self.adapter.unsubscribe, s)

    async def historical_candles(
        self, symbol: str, period: str = "Month", date_from: str | None = None, date_to: str | None = None
    ) -> list[Candle]:
        candles = await self.session.call("historical_prices", symbol, period, date_from, date_to)
        return [c for c in (N.candle_to_candle(x) for x in candles) if c is not None]

    async def instrument_limits(self, inst: Instrument) -> Instrument:
        """Price limits from ``quote()`` (GET stock-trading-info)."""
        try:
            q = await self.session.call("quote", inst.symbol)
            return N.quote_rest_to_instrument_limits(inst, q)
        except Exception:  # noqa: BLE001
            return inst
