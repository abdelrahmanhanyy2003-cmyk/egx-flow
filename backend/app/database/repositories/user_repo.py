"""Preferences, layouts, watchlists, journal, portfolio snapshots, alerts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.timeutil import now_ms
from app.database.base import session_scope
from app.database.models import (
    AlertRow,
    AlertRuleRow,
    JournalEntryRow,
    PortfolioPositionRow,
    PortfolioSnapshotRow,
    UserPreferenceRow,
    WatchlistRow,
)

# ----------------------------------------------------------------- prefs
def get_pref(key: str, default: Any = None) -> Any:
    with session_scope() as s:
        r = s.get(UserPreferenceRow, key)
        return r.value if r else default


def set_pref(key: str, value: Any) -> None:
    with session_scope() as s:
        r = s.get(UserPreferenceRow, key)
        if r is None:
            s.add(UserPreferenceRow(key=key, value=value, updated_ms=now_ms()))
        else:
            r.value = value
            r.updated_ms = now_ms()


# ------------------------------------------------------------- watchlists
def list_watchlists() -> list[dict[str, Any]]:
    with session_scope() as s:
        return [{"id": r.id, "name": r.name, "symbols": r.symbols}
                for r in s.execute(select(WatchlistRow).order_by(WatchlistRow.id)).scalars()]


def save_watchlist(name: str, symbols: list[str]) -> dict[str, Any]:
    with session_scope() as s:
        r = s.execute(select(WatchlistRow).where(WatchlistRow.name == name)).scalar_one_or_none()
        if r is None:
            r = WatchlistRow(name=name, symbols=symbols, updated_ms=now_ms())
            s.add(r)
            s.flush()
        else:
            r.symbols = symbols
            r.updated_ms = now_ms()
        return {"id": r.id, "name": r.name, "symbols": r.symbols}


def delete_watchlist(wid: int) -> bool:
    with session_scope() as s:
        r = s.get(WatchlistRow, wid)
        if r is None:
            return False
        s.delete(r)
        return True


# ---------------------------------------------------------------- journal
def _j(r: JournalEntryRow) -> dict[str, Any]:
    return {
        "id": r.id, "symbol": r.symbol, "side": r.side, "trade_date": r.trade_date, "quantity": r.quantity,
        "price": r.price, "fees": r.fees, "notes": r.notes, "thesis": r.thesis, "tags": r.tags,
        "broker_order_id": r.broker_order_id, "origin": r.origin, "created_ms": r.created_ms,
        "updated_ms": r.updated_ms,
    }


def list_journal(symbol: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(JournalEntryRow).order_by(JournalEntryRow.trade_date, JournalEntryRow.id)
        if symbol:
            q = q.where(JournalEntryRow.symbol == symbol)
        return [_j(r) for r in s.execute(q).scalars()]


def add_journal(data: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as s:
        if data.get("broker_order_id"):
            dup = s.execute(select(JournalEntryRow).where(
                JournalEntryRow.broker_order_id == data["broker_order_id"])).scalar_one_or_none()
            if dup is not None:
                raise ValueError(f"broker order {data['broker_order_id']} already journaled (id {dup.id})")
        r = JournalEntryRow(**data, created_ms=now_ms(), updated_ms=now_ms())
        s.add(r)
        s.flush()
        return _j(r)


def update_journal(jid: int, data: dict[str, Any]) -> dict[str, Any] | None:
    with session_scope() as s:
        r = s.get(JournalEntryRow, jid)
        if r is None:
            return None
        for k, v in data.items():
            if k in ("symbol", "side", "trade_date", "quantity", "price", "fees", "notes", "thesis", "tags"):
                setattr(r, k, v)
        r.updated_ms = now_ms()
        return _j(r)


def delete_journal(jid: int) -> bool:
    with session_scope() as s:
        r = s.get(JournalEntryRow, jid)
        if r is None:
            return False
        s.delete(r)
        return True


# ------------------------------------------------------ portfolio history
def save_portfolio_snapshot(summary: dict[str, Any], positions: list[dict[str, Any]]) -> None:
    with session_scope() as s:
        snap = PortfolioSnapshotRow(
            ts=summary["ts"], total_value=summary.get("total_value"), cash=summary.get("cash"),
            stocks_value=summary.get("stocks_value"), unrealized_pnl=summary.get("unrealized_pnl"),
            realized_pnl=summary.get("realized_pnl"), source=summary["source"], quality=summary["quality"],
        )
        s.add(snap)
        s.flush()
        for p in positions:
            s.add(PortfolioPositionRow(
                snapshot_id=snap.id, symbol=p["symbol"], quantity=p["quantity"], avg_price=p["avg_price"],
                price=p.get("current_price"), market_value=p.get("market_value"),
                unrealized_pnl=p.get("unrealized_pnl"), realized_pnl=p.get("realized_pnl"),
            ))


def portfolio_history(since_ms: int = 0, source: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(PortfolioSnapshotRow).where(PortfolioSnapshotRow.ts >= since_ms)
        if source:
            q = q.where(PortfolioSnapshotRow.source == source)
        return [
            {"ts": r.ts, "total_value": r.total_value, "cash": r.cash, "stocks_value": r.stocks_value,
             "unrealized_pnl": r.unrealized_pnl, "realized_pnl": r.realized_pnl, "source": r.source,
             "quality": r.quality}
            for r in s.execute(q.order_by(PortfolioSnapshotRow.ts)).scalars()
        ]


# ----------------------------------------------------------------- alerts
def insert_alert(a: dict[str, Any]) -> dict[str, Any] | None:
    """Insert unless an alert with the same dedup key exists. Returns row or None."""
    with session_scope() as s:
        if s.execute(select(AlertRow.id).where(AlertRow.dedup_key == a["dedup_key"])).first():
            return None
        r = AlertRow(**a)
        s.add(r)
        s.flush()
        return {**a, "id": r.id, "acknowledged": False}


def list_alerts(limit: int = 200, symbol: str | None = None, rule: str | None = None) -> list[dict[str, Any]]:
    with session_scope() as s:
        q = select(AlertRow)
        if symbol:
            q = q.where(AlertRow.symbol == symbol)
        if rule:
            q = q.where(AlertRow.rule == rule)
        return [
            {"id": r.id, "ts": r.ts, "symbol": r.symbol, "rule": r.rule, "severity": r.severity,
             "message": r.message, "payload": r.payload, "acknowledged": r.acknowledged, "quality": r.quality}
            for r in s.execute(q.order_by(AlertRow.ts.desc()).limit(limit)).scalars()
        ]


def ack_alerts(ids: list[int] | None) -> int:
    with session_scope() as s:
        q = select(AlertRow).where(AlertRow.acknowledged.is_(False))
        if ids:
            q = q.where(AlertRow.id.in_(ids))
        n = 0
        for r in s.execute(q).scalars():
            r.acknowledged = True
            n += 1
        return n


def list_rules() -> list[dict[str, Any]]:
    with session_scope() as s:
        return [{"id": r.id, "rule": r.rule, "symbol": r.symbol, "enabled": r.enabled, "sound": r.sound,
                 "params": r.params} for r in s.execute(select(AlertRuleRow)).scalars()]


def upsert_rule(rule: str, symbol: str | None, enabled: bool, sound: bool, params: dict[str, Any]) -> dict[str, Any]:
    with session_scope() as s:
        q = select(AlertRuleRow).where(AlertRuleRow.rule == rule)
        q = q.where(AlertRuleRow.symbol.is_(None)) if symbol is None else q.where(AlertRuleRow.symbol == symbol)
        r = s.execute(q).scalar_one_or_none()
        if r is None:
            r = AlertRuleRow(rule=rule, symbol=symbol, enabled=enabled, sound=sound, params=params)
            s.add(r)
            s.flush()
        else:
            r.enabled, r.sound, r.params = enabled, sound, params
        return {"id": r.id, "rule": r.rule, "symbol": r.symbol, "enabled": r.enabled, "sound": r.sound,
                "params": r.params}


def delete_rule(rid: int) -> bool:
    with session_scope() as s:
        r = s.get(AlertRuleRow, rid)
        if r is None:
            return False
        s.delete(r)
        return True
