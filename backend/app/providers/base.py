"""Provider abstraction.

Any EGX data source - EFG Hermes Younit, a licensed Level 2 vendor, or the demo
simulator - implements :class:`MarketDataProvider` (and optionally
:class:`PortfolioProvider`). The rest of the application only talks to these
interfaces, so a provider can be added or swapped without touching analytics,
storage or UI code.

Providers declare what they can actually deliver through
:class:`ProviderCapabilities`. The UI renders these flags so the user always
knows e.g. whether the heatmap is built from full depth or from L1 only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.domain.models import (
    BookResolution,
    BrokerOrder,
    DataQuality,
    Instrument,
    MarketEvent,
    PortfolioPosition,
    PortfolioSummaryData,
)

EventSink = Callable[[MarketEvent], None]


@dataclass
class ProviderCapabilities:
    level1_quotes: bool = False
    depth_levels: int = 0  # 0 = no depth beyond L1
    book_resolution: BookResolution = BookResolution.NONE
    book_update_interval_ms: int | None = None  # for snapshot-based books
    trades: bool = False
    trade_side: str = "none"  # "provided" | "unverified" | "none"
    historical_candles: bool = False
    historical_trades: bool = False
    historical_book: bool = False
    streaming: bool = False
    market_stats: bool = False
    index_values: bool = False
    portfolio: bool = False
    open_orders: bool = False
    order_history: bool = False
    investor_type_stats: bool = False
    quality: DataQuality = DataQuality.LIVE
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["book_resolution"] = self.book_resolution.value
        d["quality"] = self.quality.value
        return d


@dataclass
class ProviderStatus:
    name: str
    state: str = "disconnected"  # connecting|connected|disconnected|error|degraded
    detail: str = ""
    connected_since_ms: int | None = None
    last_event_ms: int | None = None
    reconnects: int = 0
    errors: int = 0
    rate_limited: int = 0
    subscriptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketDataProvider(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    def status(self) -> ProviderStatus: ...

    @abstractmethod
    async def start(self, sink: EventSink) -> None:
        """Connect and begin pushing normalized events into ``sink``.

        ``sink`` is thread-safe; providers may call it from any thread.
        """

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def list_instruments(self) -> list[Instrument]: ...

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None: ...

    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> None: ...

    async def historical_candles(
        self, symbol: str, period: str = "Month", date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[Candle]:
        return []


class PortfolioProvider(ABC):
    """Read-only access to the authenticated account owner's data."""

    name: str = "base"
    quality: DataQuality = DataQuality.LIVE

    @abstractmethod
    async def summary(self) -> PortfolioSummaryData | None: ...

    @abstractmethod
    async def positions(self) -> list[PortfolioPosition]: ...

    async def open_orders(self) -> list[BrokerOrder]:
        return []

    async def order_history(self) -> list[BrokerOrder]:
        return []
