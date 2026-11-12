"""Market-data persistence (batched, idempotent inserts)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database.base import get_engine, session_scope
from app.database.models import (
    AlertRow,
    IndicatorValueRow,
    InstrumentRow,
    LiquidityEventRow,
    MarketSessionRow,
    OrderBookSnapshotRow,
    OrderBookUpdateRow,
    QuoteRow,
    TradeRow,
    VolumeProfileRow,
    WhaleEventRow,
)


def _insert_ignore(table: Any) -> Any:
    dialect = get_engine().dialect.name
    if dialect == "sqlite":
        return sqlite_insert(table).on_conflict_do_nothing()
    if dialect == "postgresql":
        return pg_insert(table).on_conflict_do_nothing()
    return insert(table)


def bulk_insert_ignore(model: Any, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with get_engine().begin() as conn:
        for i in range(0, len(rows), 2000):
            conn.execute(_insert_ignore(model.__table__), rows[i : i + 2000])


def upsert_instruments(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    dialect = get_engine().dialect.name
    table = InstrumentRow.__table__
    stmt: Any
    if dialect == "sqlite":
        stmt = sqlite_insert(table)
    else:
        stmt = pg_insert(table)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol"],
        set_={c: getattr(stmt.excluded, c) for c in ("name", "sector", "tick_size", "tick_size_source",
                                                      "trading_status", "provider_id", "source", "updated_ms")},
    )
    with get_engine().begin() as conn:
        conn.execute(stmt, rows)


def upsert_session(date: str, symbol: str, source: str, quality: str, resolution: str,
                   interval_ms: int, first_ts: int, last_ts: int, n_trades: int, n_books: int) -> None:
    with session_scope() as s:
        row = s.execute(
            select(MarketSessionRow).where(
                MarketSessionRow.session_date == date,
                MarketSessionRow.symbol == symbol,
                MarketSessionRow.source == source,
            )
        ).scalar_one_or_none()
        if row is None:
            s.add(MarketSessionRow(
                session_date=date, symbol=symbol, source=source, quality=quality, book_resolution=resolution,
                book_record_interval_ms=interval_ms, first_ts=first_ts, last_ts=last_ts,
                trades=n_trades, book_snapshots=n_books,
            ))
        else:
            row.first_ts = min(row.first_ts, first_ts)
            row.last_ts = max(row.last_ts, last_ts)
            row.trades += n_trades
            row.book_snapshots += n_books
            row.book_resolution = resolution


def list_sessions(symbol: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(MarketSessionRow).order_by(MarketSessionRow.session_date.desc(), MarketSessionRow.symbol)
        if symbol:
            q = q.where(MarketSessionRow.symbol == symbol)
        rows = s.execute(q.limit(limit)).scalars().all()
        return [
            {
                "id": r.id, "date": r.session_date, "symbol": r.symbol, "source": r.source,
                "quality": r.quality, "book_resolution": r.book_resolution,
                "book_record_interval_ms": r.book_record_interval_ms, "first_ts": r.first_ts,
                "last_ts": r.last_ts, "trades": r.trades, "book_snapshots": r.book_snapshots,
            }
            for r in rows
        ]


def get_session(session_id: int) -> dict[str, Any] | None:
    with session_scope() as s:
        r = s.get(MarketSessionRow, session_id)
        if r is None:
            return None
        return {"id": r.id, "date": r.session_date, "symbol": r.symbol, "source": r.source,
                "quality": r.quality, "book_resolution": r.book_resolution,
                "book_record_interval_ms": r.book_record_interval_ms,
                "first_ts": r.first_ts, "last_ts": r.last_ts}


def load_trades(symbol: str, t0: int, t1: int, source: str | None = None) -> list[TradeRow]:
    with session_scope() as s:
        q = select(TradeRow).where(TradeRow.symbol == symbol, TradeRow.ts >= t0, TradeRow.ts <= t1)
        if source:
            q = q.where(TradeRow.source == source)
        return list(s.execute(q.order_by(TradeRow.ts, TradeRow.trade_id)).scalars().all())


def load_book_snapshots(symbol: str, t0: int, t1: int, source: str | None = None) -> list[OrderBookSnapshotRow]:
    with session_scope() as s:
        q = select(OrderBookSnapshotRow).where(
            OrderBookSnapshotRow.symbol == symbol, OrderBookSnapshotRow.ts >= t0, OrderBookSnapshotRow.ts <= t1
        )
        if source:
            q = q.where(OrderBookSnapshotRow.source == source)
        return list(s.execute(q.order_by(OrderBookSnapshotRow.ts)).scalars().all())


def query_trades(symbol: str | None, min_value: float, t0: int | None, side: str | None, limit: int) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(TradeRow).where(TradeRow.value >= min_value)
        if symbol:
            q = q.where(TradeRow.symbol == symbol)
        if t0:
            q = q.where(TradeRow.ts >= t0)
        if side:
            q = q.where(TradeRow.side == side)
        rows = s.execute(q.order_by(TradeRow.ts.desc()).limit(limit)).scalars().all()
        return [
            {"trade_id": r.trade_id, "symbol": r.symbol, "ts": r.ts, "price": r.price, "quantity": r.quantity,
             "value": r.value, "side": r.side, "method": r.method, "confidence": r.confidence,
             "estimated": r.method in ("quote_rule", "tick_rule"), "source": r.source, "quality": r.quality}
            for r in rows
        ]


def save_volume_profile(symbol: str, date: str, prof: dict[str, Any], source: str, ts: int) -> None:
    with session_scope() as s:
        row = s.execute(select(VolumeProfileRow).where(
            VolumeProfileRow.symbol == symbol, VolumeProfileRow.session_date == date, VolumeProfileRow.source == source
        )).scalar_one_or_none()
        if row is None:
            s.add(VolumeProfileRow(symbol=symbol, session_date=date, levels=prof["levels"], poc=prof["poc"],
                                   vah=prof["vah"], val=prof["val"], source=source, updated_ms=ts))
        else:
            row.levels, row.poc, row.vah, row.val, row.updated_ms = prof["levels"], prof["poc"], prof["vah"], prof["val"], ts


def save_whale_events(rows: list[dict[str, Any]]) -> None:
    if rows:
        bulk_insert_ignore(WhaleEventRow, rows)


def save_liquidity_events(rows: list[dict[str, Any]]) -> None:
    if rows:
        bulk_insert_ignore(LiquidityEventRow, rows)


def recent_whale_events(kind: str | None, symbol: str | None, limit: int) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(WhaleEventRow)
        if kind:
            q = q.where(WhaleEventRow.kind == kind)
        if symbol:
            q = q.where(WhaleEventRow.symbol == symbol)
        rows = s.execute(q.order_by(WhaleEventRow.ts.desc()).limit(limit)).scalars().all()
        return [{"id": r.id, "symbol": r.symbol, "ts": r.ts, "kind": r.kind, "value": r.value,
                 "payload": r.payload, "source": r.source} for r in rows]


def prune_before(cutoff_ms: int, step_ms: int = 3_600_000) -> dict[str, int]:
    """Delete recorded market data and derived events older than ``cutoff_ms``.

    Works in one-hour slices, each in its own short transaction, so the live
    recorder is never blocked for long. The trading journal, portfolio
    snapshots, watchlists and preferences are never touched.
    """
    out: dict[str, int] = {}
    eng = get_engine()
    for model in (TradeRow, QuoteRow, OrderBookSnapshotRow, OrderBookUpdateRow, WhaleEventRow,
                  LiquidityEventRow, IndicatorValueRow, AlertRow):
        t = model.__table__
        with eng.begin() as conn:
            lo = conn.execute(select(func.min(t.c.ts))).scalar()
        n = 0
        while lo is not None and lo < cutoff_ms:
            lo = min(cutoff_ms, lo + step_ms)
            with eng.begin() as conn:
                n += conn.execute(delete(t).where(t.c.ts < lo)).rowcount or 0
        if n:
            out[t.name] = n
    s = MarketSessionRow.__table__
    with eng.begin() as conn:
        gone = conn.execute(delete(s).where(s.c.last_ts < cutoff_ms)).rowcount or 0
        conn.execute(update(s).where(s.c.first_ts < cutoff_ms).values(first_ts=cutoff_ms))
    if gone:
        out[s.name] = gone
    return out


def table_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    with session_scope() as s:
        for m in (TradeRow, OrderBookSnapshotRow, QuoteRow, MarketSessionRow, WhaleEventRow, LiquidityEventRow):
            out[m.__tablename__] = int(s.execute(select(func.count()).select_from(m)).scalar_one())
    return out
