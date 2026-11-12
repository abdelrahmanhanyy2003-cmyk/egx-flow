"""Convert Younit SDK objects into EGX Flow's normalized models.

Field names used here are exactly those defined in the SDK's models
(``younit.models.*`` / ``younit.models.streaming``). Access is duck-typed via
``getattr`` so unit tests can use lightweight fakes.

Important data-semantics notes (see docs/EFG_API_CAPABILITIES.md):

* ``SymbolUpdate`` arrives in Lightstreamer MERGE mode: after the initial
  snapshot only changed fields are sent, others are ``None``. :class:`QuoteMerger`
  keeps the last known value per field.
* ``TradeUpdate.transaction_type`` is documented only as a "Buy/sell side
  indicator". It is not documented as the aggressor side, so it is used for
  classification ONLY when the operator configures an explicit value map.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.timeutil import CAIRO, dt_to_ms, now_ms, parse_provider_time
from app.domain.models import (
    BrokerOrder,
    ClassificationMethod,
    DataQuality,
    IndexValue,
    Instrument,
    MarketStats,
    PortfolioPosition,
    PortfolioSummaryData,
    Quote,
    Side,
    Trade,
)
from app.providers.base import Candle

SRC = "efg_younit"


def _g(o: Any, name: str, default: Any = None) -> Any:
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)


class QuoteMerger:
    FIELDS = (
        "bid", "ask", "last", "bid_volume", "ask_volume", "open", "high", "low", "close",
        "volume", "value", "trades_count", "change_pct", "status", "symbol",
    )

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}

    def merge(self, symbol: str, update: Any) -> dict[str, Any]:
        st = self._state.setdefault(symbol, {})
        for f in self.FIELDS:
            v = _g(update, f)
            if v is not None:
                st[f] = v
        st["last_updated"] = _g(update, "last_updated") or st.get("last_updated")
        return st


def symbol_update_to_quote(symbol: str, merged: dict[str, Any], received: int) -> Quote:
    ts = parse_provider_time(merged.get("last_updated")) or received
    return Quote(
        symbol=symbol,
        bid=merged.get("bid"),
        ask=merged.get("ask"),
        last=merged.get("last"),
        bid_qty=merged.get("bid_volume"),
        ask_qty=merged.get("ask_volume"),
        ts=ts,
        source=SRC,
        quality=DataQuality.LIVE,
        received_ts=received,
        open=merged.get("open"),
        high=merged.get("high"),
        low=merged.get("low"),
        prev_close=merged.get("close"),
        volume=merged.get("volume"),
        value=merged.get("value"),
        trades_count=merged.get("trades_count"),
        change_pct=merged.get("change_pct"),
        status=merged.get("status"),
    )


def map_provider_side(raw: str | None, side_map: dict[str, str]) -> Side | None:
    if raw is None or not side_map:
        return None
    v = side_map.get(str(raw).strip().lower())
    return Side.BUY if v == "buy" else Side.SELL if v == "sell" else None


def trade_update_to_trade(
    symbol: str, u: Any, received: int, side_map: dict[str, str]
) -> Trade | None:
    command = (_g(u, "command") or "ADD").upper()
    if command == "DELETE":
        return None
    price, qty = _g(u, "price"), _g(u, "volume")
    if not price or not qty or price <= 0 or qty <= 0:
        return None
    tid = _g(u, "ticket_number") or _g(u, "key")
    if not tid:
        return None
    ts = parse_provider_time(_g(u, "last_updated")) or received
    raw_side = _g(u, "transaction_type")
    pside = map_provider_side(raw_side, side_map)
    return Trade(
        trade_id=str(tid),
        symbol=symbol,
        price=float(price),
        quantity=float(qty),
        ts=ts,
        source=SRC,
        quality=DataQuality.LIVE,
        side=pside or Side.UNKNOWN,
        method=ClassificationMethod.PROVIDER if pside else ClassificationMethod.UNKNOWN,
        confidence=1.0 if pside else 0.0,
        received_ts=received,
        provider_side_raw=raw_side,
    )


def market_update_to_stats(u: Any, received: int) -> MarketStats:
    return MarketStats(
        market_id=_g(u, "market_id"),
        status=_g(u, "status"),
        traded_value=_g(u, "traded_value"),
        traded_volume=_g(u, "traded_volume"),
        trades_count=_g(u, "trades_count"),
        advances=_g(u, "advances"),
        declines=_g(u, "declines"),
        unchanged=_g(u, "unchanged"),
        ts=parse_provider_time(_g(u, "market_time")) or received,
        source=SRC,
        quality=DataQuality.LIVE,
    )


def index_update_to_value(u: Any, received: int) -> IndexValue:
    return IndexValue(
        index_id=_g(u, "index_id"),
        name=_g(u, "name"),
        value=_g(u, "value"),
        change_pct=_g(u, "change_pct"),
        net_change=_g(u, "net_change"),
        ts=received,
        source=SRC,
        quality=DataQuality.LIVE,
    )


def stock_info_to_instrument(s: Any) -> Instrument | None:
    sym = _g(s, "symbol")
    if not sym:
        return None
    return Instrument(
        symbol=str(sym).upper(),
        name=_g(s, "name") or _g(s, "short_name") or str(sym),
        currency=_g(s, "currency") or "EGP",
        # The SDK exposes no tick size; it is inferred from observed prices and labelled.
        tick_size=None,
        tick_size_source="unknown",
        trading_status="listed",
        sector=_g(s, "security_class_name"),
        provider_id=str(_g(s, "stock_id")) if _g(s, "stock_id") is not None else None,
        reference_price=_g(s, "last") or None,
    )


def quote_rest_to_instrument_limits(inst: Instrument, q: Any) -> Instrument:
    lo, hi = _g(q, "min_price"), _g(q, "max_price")
    inst.lower_limit = lo or None
    inst.upper_limit = hi or None
    return inst


def candle_to_candle(c: Any) -> Candle | None:
    ts = _g(c, "timestamp")
    if ts is None:
        return None
    return Candle(dt_to_ms(ts), _g(c, "open"), _g(c, "high"), _g(c, "low"), _g(c, "close"), _g(c, "volume"))


def position_to_position(p: Any) -> PortfolioPosition:
    return PortfolioPosition(
        symbol=_g(p, "symbol") or "?",
        quantity=float(_g(p, "quantity") or 0),
        avg_price=float(_g(p, "average_price") or 0),
        current_price=_g(p, "market_price"),
        market_value=_g(p, "market_value"),
        unrealized_pnl=_g(p, "unrealized_pnl"),
        realized_pnl=_g(p, "realized_pnl"),
        allocation_pct=None,  # computed locally
        name=_g(p, "name"),
        unrealized_pnl_pct=_g(p, "unrealized_pnl_pct"),
        source=SRC,
        quality=DataQuality.LIVE,
        broker_fields=[
            "quantity", "avg_price", "current_price", "market_value",
            "unrealized_pnl", "unrealized_pnl_pct", "realized_pnl",
        ],
    )


def summary_to_summary(s: Any) -> PortfolioSummaryData:
    return PortfolioSummaryData(
        total_value=_g(s, "total_balance"),
        cash=_g(s, "total_cash"),
        stocks_value=_g(s, "total_stocks"),
        realized_pnl=_g(s, "realized_profit"),
        unrealized_pnl=_g(s, "unrealized_profit"),
        unrealized_pnl_pct=_g(s, "unrealized_profit_pct"),
        currency=_g(s, "currency") or "EGP",
        ts=now_ms(),
        source=SRC,
        quality=DataQuality.LIVE,
        broker_fields=["total_value", "cash", "stocks_value", "realized_pnl", "unrealized_pnl", "unrealized_pnl_pct"],
    )


def _any_time_to_ms(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return dt_to_ms(v if v.tzinfo else v.replace(tzinfo=CAIRO))
    return parse_provider_time(str(v))


def history_entry_to_order(h: Any) -> BrokerOrder:
    """``OrderHistoryEntry`` (GET /api/stocks/order-history/{MarketId}/{ProfileId})."""
    sym = _g(h, "reuter_id") or _g(h, "short_name")
    if isinstance(sym, str):
        sym = sym.split(".")[0]
    return BrokerOrder(
        order_id=str(_g(h, "order_id")),
        symbol=sym,
        side=_g(h, "transaction_type"),
        quantity=_g(h, "quantity"),
        filled_quantity=None,
        price=_g(h, "price"),
        avg_price=_g(h, "average"),
        status=_g(h, "status"),
        ts=_any_time_to_ms(_g(h, "order_date")),
        raw_status=_g(h, "status"),
        source=SRC,
    )


def raw_order_row_to_order(r: dict[str, Any], symbol_for_id: dict[str, str]) -> BrokerOrder:
    """``list_orders`` returns raw rows keyed OrderId/StockId/ProfileId/Quantity/Price/Status."""
    sid = r.get("StockId")
    return BrokerOrder(
        order_id=str(r.get("OrderId")),
        symbol=symbol_for_id.get(str(sid)) if sid is not None else None,
        side=None,
        quantity=r.get("Quantity"),
        filled_quantity=None,
        price=r.get("Price"),
        avg_price=None,
        status=str(r.get("Status")) if r.get("Status") is not None else None,
        ts=None,
        source=SRC,
    )
