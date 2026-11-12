"""EFG Hermes Younit integration with mocks (no credentials, no network).

Live connectivity checks are separate: see test_live_efg.py (skipped unless
EGXFLOW_LIVE_TESTS=1 and credentials are configured).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.security import FORBIDDEN_TRADING_METHODS
from app.domain.models import ClassificationMethod, Side
from app.integrations.efg_hermes import normalization as N
from app.integrations.efg_hermes.client import ReadOnlyYounitClient
from app.integrations.efg_hermes.rate_limit import TokenBucket, call_with_backoff
from app.integrations.efg_hermes.streaming import ConnectionMonitor, StreamingAdapter


class FakeStreaming:
    def __init__(self) -> None:
        self.connected = False
        self.subs: list[tuple[str, Any]] = []
        self.connect_calls = 0
        self.fail_connects = 0

    def connect(self) -> None:
        self.connect_calls += 1
        if self.fail_connects > 0:
            self.fail_connects -= 1
            raise ConnectionError("boom")
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False
        self.subs.clear()

    def is_connected(self) -> bool:
        return self.connected

    def _sub(self, kind: str, key: Any, cb: Any) -> SimpleNamespace:
        h = SimpleNamespace(kind=kind, key=key, cb=cb)
        self.subs.append((kind, h))
        return h

    def subscribe_quote(self, symbol, on_update, on_error=None):
        return self._sub("quote", symbol, on_update)

    def subscribe_trades(self, symbol, on_update, on_error=None):
        return self._sub("trades", symbol, on_update)

    def subscribe_market(self, market_id=1, on_update=None, on_error=None):
        return self._sub("market", market_id, on_update)

    def subscribe_index(self, index_id, on_update, on_error=None):
        return self._sub("index", index_id, on_update)

    def subscribe_orders(self, on_update, on_error=None, client_account_id=None):
        return self._sub("orders", None, on_update)

    def unsubscribe(self, h):
        self.subs = [s for s in self.subs if s[1] is not h]


class FakeSDK:
    def __init__(self) -> None:
        self.streaming = FakeStreaming()
        self.calls: list[str] = []

    def positions(self, market_id=None):
        self.calls.append("positions")
        return []

    def buy(self, *a, **k):  # must be unreachable
        raise AssertionError("trading method reached!")

    sell = place_order = cancel_order = amend_order = buy


def test_read_only_wrapper_blocks_every_trading_method():
    c = ReadOnlyYounitClient(FakeSDK())
    for m in FORBIDDEN_TRADING_METHODS:
        with pytest.raises(PermissionError):
            getattr(c, m)
    with pytest.raises(PermissionError):
        c.call("buy", "COMI", 1)
    with pytest.raises(PermissionError):
        c.some_unknown_method  # noqa: B018
    with pytest.raises(PermissionError):
        c.streaming.subscribe_raw  # noqa: B018
    assert c.call("positions") == []


def test_quote_merger_keeps_last_values_in_merge_mode():
    m = N.QuoteMerger()
    m.merge("COMI", SimpleNamespace(bid=80.0, ask=80.1, last=80.05, bid_volume=100, ask_volume=200,
                                    last_updated=None))
    merged = m.merge("COMI", SimpleNamespace(bid=None, ask=80.2, last=None, bid_volume=None, ask_volume=50,
                                             last_updated=None))
    q = N.symbol_update_to_quote("COMI", merged, 123)
    assert (q.bid, q.ask, q.last, q.bid_qty, q.ask_qty) == (80.0, 80.2, 80.05, 100, 50)
    assert q.ts == 123 and q.source == "efg_younit"


def test_trade_update_side_ignored_unless_mapped():
    u = SimpleNamespace(command="ADD", key="k1", ticket_number="T1", price=10.5, volume=300,
                        last_updated="2026-11-09T11:00:00", transaction_type="B")
    t = N.trade_update_to_trade("COMI", u, 999, {})
    assert t and t.side == Side.UNKNOWN and t.method == ClassificationMethod.UNKNOWN
    assert t.provider_side_raw == "B"
    assert t.ts == 1_794_214_800_000  # Cairo local -> UTC
    t2 = N.trade_update_to_trade("COMI", u, 999, {"b": "buy"})
    assert t2 and t2.side == Side.BUY and t2.method == ClassificationMethod.PROVIDER


def test_trade_update_rejects_deletes_and_invalid():
    base = dict(key="k", ticket_number="T", price=10.0, volume=1, last_updated=None, transaction_type=None)
    assert N.trade_update_to_trade("X", SimpleNamespace(command="DELETE", **base), 1, {}) is None
    assert N.trade_update_to_trade("X", SimpleNamespace(command="ADD", **{**base, "volume": 0}), 1, {}) is None


def test_position_and_summary_normalization_mark_broker_fields():
    p = SimpleNamespace(symbol="FWRY", quantity=100, average_price=7.0, market_price=8.0, market_value=800.0,
                        unrealized_pnl=100.0, realized_pnl=5.0, name="Fawry", unrealized_pnl_pct=14.28)
    pos = N.position_to_position(p)
    assert pos.quantity == 100 and pos.avg_price == 7.0 and "market_value" in pos.broker_fields
    s = SimpleNamespace(total_balance=1000.0, total_cash=200.0, total_stocks=800.0, realized_profit=5.0,
                        unrealized_profit=100.0, unrealized_profit_pct=14.0, currency="EGP")
    assert N.summary_to_summary(s).cash == 200.0


def test_order_history_normalization_uses_sdk_field_names():
    h = SimpleNamespace(order_id=42, reuter_id="COMI.CA", short_name="CIB", transaction_type="Buy", quantity=10,
                        price=80.0, average=79.9, status="Filled", order_date=datetime(2026, 11, 1, 11, 0))
    o = N.history_entry_to_order(h)
    assert o.order_id == "42" and o.symbol == "COMI" and o.avg_price == 79.9 and o.ts is not None


def test_streaming_adapter_normalizes_and_resubscribes():
    sdk = FakeSDK()
    client = ReadOnlyYounitClient(sdk)
    events: list[Any] = []
    ad = StreamingAdapter(client, events.append, {}, 1, 1)
    ad.connect()
    ad.subscribe("COMI")
    kinds = sorted(k for k, _ in sdk.streaming.subs)
    assert kinds == ["index", "market", "quote", "trades"]
    quote_cb = next(h.cb for k, h in sdk.streaming.subs if k == "quote")
    quote_cb(SimpleNamespace(bid=1.0, ask=1.1, last=1.05, bid_volume=1, ask_volume=1, last_updated=None))
    assert events and events[-1].symbol == "COMI"
    # simulate a reconnect
    sdk.streaming.disconnect()
    ad.resubscribe_all()
    assert sorted(k for k, _ in sdk.streaming.subs) == ["index", "market", "quote", "trades"]


def test_delayed_entitlement_labels_events_delayed():
    from app.domain.models import DataQuality

    sdk = FakeSDK()
    events: list[Any] = []
    ad = StreamingAdapter(ReadOnlyYounitClient(sdk), events.append, {}, 1, None, DataQuality.DELAYED)
    ad.connect()
    ad.subscribe("COMI")
    cb = next(h.cb for k, h in sdk.streaming.subs if k == "trades")
    cb(SimpleNamespace(command="ADD", key="1", ticket_number="1", price=1.0, volume=5, last_updated=None,
                       transaction_type=None))
    assert events[-1].quality == DataQuality.DELAYED


def test_connection_monitor_reconnects_with_backoff():
    sdk = FakeSDK()
    ad = StreamingAdapter(ReadOnlyYounitClient(sdk), lambda e: None, {}, 1, None)
    ad.connect()
    ad.subscribe("ETEL")
    states: list[str] = []
    sleeps: list[float] = []
    mon = ConnectionMonitor(ad, lambda s, d: states.append(s), sleep=sleeps.append)
    sdk.streaming.connected = False
    sdk.streaming.fail_connects = 2
    assert mon.check_once() == "connected"
    assert mon.reconnects == 1
    assert sleeps == [1.0, 2.0]  # exponential back-off
    assert ("quote", ) == tuple({k for k, _ in sdk.streaming.subs if k == "quote"})


def test_connection_monitor_flags_stale_stream():
    sdk = FakeSDK()
    ad = StreamingAdapter(ReadOnlyYounitClient(sdk), lambda e: None, {}, 1, None)
    ad.connect()
    ad.last_event_ms = 1  # ancient
    states: list[str] = []
    mon = ConnectionMonitor(ad, lambda s, d: states.append(s), stale_after_s=5)
    assert mon.check_once() == "degraded"


class RateLimited(Exception):
    status_code = 429


def test_rate_limit_backoff_then_success():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimited()
        return "ok"

    slept: list[float] = []
    assert call_with_backoff(fn, TokenBucket(600), sleep=slept.append) == "ok"
    assert slept == [2.0, 4.0]


def test_rate_limit_gives_up_and_non_429_propagates():
    def always():
        raise RateLimited()

    with pytest.raises(RateLimited):
        call_with_backoff(always, TokenBucket(600), retries=1, sleep=lambda s: None)

    def boom():
        raise ValueError("x")

    with pytest.raises(ValueError):
        call_with_backoff(boom, TokenBucket(600), sleep=lambda s: None)
