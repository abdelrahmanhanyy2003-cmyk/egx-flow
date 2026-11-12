"""ORM table definitions.

Time-series tables (quotes, trades, orderbook_snapshots, orderbook_updates)
use composite natural primary keys that include ``ts`` so they can become
TimescaleDB hypertables partitioned on ``ts`` (epoch milliseconds). All of
them are indexed on (symbol, ts). Every row keeps its original event
timestamp, receive timestamp, source and quality.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONType


class InstrumentRow(Base):
    __tablename__ = "instruments"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    exchange: Mapped[str] = mapped_column(String(16), default="EGX")
    currency: Mapped[str] = mapped_column(String(8), default="EGP")
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tick_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    tick_size_source: Mapped[str] = mapped_column(String(32), default="unknown")
    trading_status: Mapped[str] = mapped_column(String(32), default="unknown")
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    updated_ms: Mapped[int] = mapped_column(BigInteger)


class MarketSessionRow(Base):
    """One recorded session per (date, symbol, source) - used by replay."""

    __tablename__ = "market_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_date: Mapped[str] = mapped_column(String(10), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(32))
    quality: Mapped[str] = mapped_column(String(16))
    book_resolution: Mapped[str] = mapped_column(String(32))
    book_record_interval_ms: Mapped[int] = mapped_column(Integer)
    first_ts: Mapped[int] = mapped_column(BigInteger)
    last_ts: Mapped[int] = mapped_column(BigInteger)
    trades: Mapped[int] = mapped_column(Integer, default=0)
    book_snapshots: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (UniqueConstraint("session_date", "symbol", "source", name="uq_session"),)


class QuoteRow(Base):
    __tablename__ = "quotes"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    received_ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    quality: Mapped[str] = mapped_column(String(16))
    __table_args__ = (Index("ix_quotes_symbol_ts", "symbol", "ts"),)


class TradeRow(Base):
    __tablename__ = "trades"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    value: Mapped[float] = mapped_column(Float)
    side: Mapped[str] = mapped_column(String(8))
    method: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    provider_side_raw: Mapped[str | None] = mapped_column(String(32), nullable=True)
    received_ts: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(32))
    quality: Mapped[str] = mapped_column(String(16))
    __table_args__ = (Index("ix_trades_symbol_ts", "symbol", "ts"), Index("ix_trades_value", "value"))


class OrderBookSnapshotRow(Base):
    __tablename__ = "orderbook_snapshots"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bids: Mapped[list] = mapped_column(JSONType)  # [[price, qty], ...] best first
    asks: Mapped[list] = mapped_column(JSONType)
    resolution: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32))
    quality: Mapped[str] = mapped_column(String(16))
    __table_args__ = (Index("ix_obs_symbol_ts", "symbol", "ts"),)


class OrderBookUpdateRow(Base):
    """Incremental price-level updates (only recorded when a provider supplies them
    and RECORD_BOOK_UPDATES is enabled)."""

    __tablename__ = "orderbook_updates"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    n: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    side: Mapped[str] = mapped_column(String(4))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    quality: Mapped[str] = mapped_column(String(16))


class VolumeProfileRow(Base):
    __tablename__ = "volume_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    session_date: Mapped[str] = mapped_column(String(10), index=True)
    levels: Mapped[list] = mapped_column(JSONType)
    poc: Mapped[float | None] = mapped_column(Float, nullable=True)
    vah: Mapped[float | None] = mapped_column(Float, nullable=True)
    val: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    updated_ms: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("symbol", "session_date", "source", name="uq_vp"),)


class IndicatorValueRow(Base):
    __tablename__ = "indicator_values"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32))
    ts: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    __table_args__ = (Index("ix_ind_symbol_name_ts", "symbol", "name", "ts"),)


class PortfolioSnapshotRow(Base):
    __tablename__ = "portfolio_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    total_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    stocks_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    quality: Mapped[str] = mapped_column(String(16))


class PortfolioPositionRow(Base):
    __tablename__ = "portfolio_positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)


class JournalEntryRow(Base):
    __tablename__ = "journal_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(8))  # buy | sell
    trade_date: Mapped[str] = mapped_column(String(32))  # ISO date/time (Cairo)
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str | None] = mapped_column(String(256), nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    origin: Mapped[str] = mapped_column(String(16), default="manual")  # manual | broker
    created_ms: Mapped[int] = mapped_column(BigInteger)
    updated_ms: Mapped[int] = mapped_column(BigInteger)


class WhaleEventRow(Base):
    __tablename__ = "whale_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32))
    ts: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(32))  # large_trade | iceberg | absorption | flow | cvd_divergence
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONType)
    source: Mapped[str] = mapped_column(String(32))
    __table_args__ = (Index("ix_whale_symbol_ts", "symbol", "ts"), Index("ix_whale_kind_ts", "kind", "ts"))


class LiquidityEventRow(Base):
    __tablename__ = "liquidity_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32))
    ts: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16))  # new | resized | pulled | consumed
    side: Mapped[str] = mapped_column(String(4))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSONType)
    source: Mapped[str] = mapped_column(String(32))
    __table_args__ = (Index("ix_liq_symbol_ts", "symbol", "ts"),)


class AlertRow(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    rule: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(12))
    message: Mapped[str] = mapped_column(String(512))
    payload: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(256), unique=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[str] = mapped_column(String(16))


class AlertRuleRow(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule: Mapped[str] = mapped_column(String(48))
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None = global default
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sound: Mapped[bool] = mapped_column(Boolean, default=True)
    params: Mapped[dict] = mapped_column(JSONType)
    __table_args__ = (UniqueConstraint("rule", "symbol", name="uq_rule_symbol"),)


class WatchlistRow(Base):
    __tablename__ = "watchlists"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    symbols: Mapped[list] = mapped_column(JSONType)
    updated_ms: Mapped[int] = mapped_column(BigInteger)


class UserPreferenceRow(Base):
    __tablename__ = "user_preferences"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONType)
    updated_ms: Mapped[int] = mapped_column(BigInteger)


TIMESERIES_TABLES = ("quotes", "trades", "orderbook_snapshots", "orderbook_updates")
