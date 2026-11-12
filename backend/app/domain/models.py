"""Normalized internal market/portfolio models.

Every provider (EFG Hermes Younit, a future licensed L2 vendor, the demo
simulator) converts its payloads into these structures. Hot-path types are
slotted dataclasses; timestamps are UTC epoch milliseconds.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class BookSide(str, Enum):
    BID = "bid"
    ASK = "ask"


class DataQuality(str, Enum):
    """How the data reached us. Always shown to the user."""

    LIVE = "live"
    DELAYED = "delayed"
    HISTORICAL = "historical"
    SIMULATED = "simulated"  # DEMO data - never real market activity


class ClassificationMethod(str, Enum):
    PROVIDER = "provider"  # exchange/provider supplied aggressor side
    QUOTE_RULE = "quote_rule"  # estimated: trade price vs prevailing bid/ask
    TICK_RULE = "tick_rule"  # estimated: trade price vs previous trade price
    UNKNOWN = "unknown"

    @property
    def estimated(self) -> bool:
        return self in (ClassificationMethod.QUOTE_RULE, ClassificationMethod.TICK_RULE)


class BookResolution(str, Enum):
    """Resolution of order-book information available from a provider."""

    ORDER_EVENTS = "order_events"  # per-order add/modify/delete (true MBO)
    DEPTH_UPDATES = "depth_updates"  # price-level incremental updates (MBP)
    DEPTH_SNAPSHOTS = "depth_snapshots"  # periodic full depth snapshots
    L1_ONLY = "l1_only"  # best bid / best ask only
    NONE = "none"


@dataclass(slots=True)
class Instrument:
    symbol: str
    name: str
    exchange: str = "EGX"
    currency: str = "EGP"
    tick_size: float | None = None  # None = unknown; resolver infers & labels it
    tick_size_source: str = "unknown"  # "provider" | "config" | "inferred" | "unknown"
    trading_status: str = "unknown"
    sector: str | None = None
    provider_id: str | None = None  # e.g. Younit stockId
    lower_limit: float | None = None
    upper_limit: float | None = None
    reference_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Quote:
    symbol: str
    bid: float | None
    ask: float | None
    last: float | None
    bid_qty: float | None
    ask_qty: float | None
    ts: int
    source: str
    quality: DataQuality
    received_ts: int = 0
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None  # cumulative session volume, if provided
    value: float | None = None  # cumulative session traded value (EGP)
    trades_count: int | None = None
    change_pct: float | None = None
    status: str | None = None

    @property
    def freshness_ms(self) -> int:
        return max(0, self.received_ts - self.ts) if self.received_ts else 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["quality"] = self.quality.value
        return d


@dataclass(slots=True)
class Trade:
    trade_id: str
    symbol: str
    price: float
    quantity: float
    ts: int
    source: str
    quality: DataQuality
    side: Side = Side.UNKNOWN
    method: ClassificationMethod = ClassificationMethod.UNKNOWN
    confidence: float = 0.0
    received_ts: int = 0
    provider_side_raw: str | None = None
    seq: int | None = None

    @property
    def value(self) -> float:
        return self.price * self.quantity

    @property
    def estimated(self) -> bool:
        return self.method.estimated

    def to_wire(self) -> list[Any]:
        """Compact representation for WebSocket transport."""
        return [
            self.trade_id,
            self.ts,
            self.price,
            self.quantity,
            self.side.value[0] if self.side != Side.UNKNOWN else "u",
            self.method.value,
            round(self.confidence, 2),
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "price": self.price,
            "quantity": self.quantity,
            "value": round(self.value, 2),
            "ts": self.ts,
            "side": self.side.value,
            "method": self.method.value,
            "estimated": self.estimated,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "quality": self.quality.value,
        }


@dataclass(slots=True)
class OrderBookLevel:
    symbol: str
    price: float
    side: BookSide
    quantity: float
    ts: int
    orders: int | None = None


@dataclass(slots=True)
class BookSnapshot:
    """Full (or L1-only) book state from a provider at a point in time."""

    symbol: str
    bids: list[tuple[float, float]]  # (price, qty) best first
    asks: list[tuple[float, float]]
    ts: int
    source: str
    quality: DataQuality
    resolution: BookResolution
    received_ts: int = 0
    seq: int | None = None


@dataclass(slots=True)
class BookDelta:
    symbol: str
    side: BookSide
    price: float
    quantity: float  # new total qty at level; 0 removes the level
    ts: int
    source: str
    quality: DataQuality
    received_ts: int = 0
    seq: int | None = None


@dataclass(slots=True)
class MarketStats:
    market_id: int | None
    status: str | None
    traded_value: float | None
    traded_volume: float | None
    trades_count: int | None
    advances: int | None
    declines: int | None
    unchanged: int | None
    ts: int
    source: str
    quality: DataQuality


@dataclass(slots=True)
class IndexValue:
    index_id: int | None
    name: str | None
    value: float | None
    change_pct: float | None
    net_change: float | None
    ts: int
    source: str
    quality: DataQuality


@dataclass(slots=True)
class ProviderStatusEvent:
    provider: str
    state: str  # connecting | connected | disconnected | error | stale
    detail: str = ""
    ts: int = 0


MarketEvent = Quote | Trade | BookSnapshot | BookDelta | MarketStats | IndexValue | ProviderStatusEvent


@dataclass(slots=True)
class PortfolioPosition:
    symbol: str
    quantity: float
    avg_price: float
    current_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    realized_pnl: float | None
    allocation_pct: float | None
    name: str | None = None
    unrealized_pnl_pct: float | None = None
    source: str = ""
    quality: DataQuality = DataQuality.LIVE
    # Which fields are broker-reported vs locally calculated.
    broker_fields: list[str] = field(default_factory=list)

    @property
    def invested(self) -> float:
        return self.quantity * self.avg_price

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["quality"] = self.quality.value
        d["invested"] = round(self.invested, 2)
        return d


@dataclass(slots=True)
class PortfolioSummaryData:
    total_value: float | None
    cash: float | None
    stocks_value: float | None
    realized_pnl: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    currency: str
    ts: int
    source: str
    quality: DataQuality
    broker_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["quality"] = self.quality.value
        return d


@dataclass(slots=True)
class BrokerOrder:
    order_id: str
    symbol: str | None
    side: str | None  # as reported by broker (transaction type)
    quantity: float | None
    filled_quantity: float | None
    price: float | None
    avg_price: float | None
    status: str | None
    ts: int | None
    raw_status: str | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
