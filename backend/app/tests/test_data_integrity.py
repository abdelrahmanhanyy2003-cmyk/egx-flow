"""Dedup, buffering/backpressure, missing & delayed events, order book, session calendar."""

from __future__ import annotations

from app.domain.models import BookDelta, BookResolution, BookSide, DataQuality, Quote, Side
from app.market_data.event_processor import EventBuffer, EventValidator
from app.market_data.normalizer import TickSizeResolver
from app.market_data.orderbook_engine import OrderBook
from app.market_data.session_manager import SessionManager
from app.tests.conftest import mk_trade


def _q(sym, ts, bid=10.0):
    return Quote(sym, bid, bid + 0.01, bid, 100, 100, ts, "test", DataQuality.LIVE, received_ts=ts)


def test_validator_drops_duplicate_trades():
    v = EventValidator()
    t = mk_trade(1, 10, 10)
    assert v.accept(t) is True
    assert v.accept(mk_trade(1, 10, 10)) is False
    assert v.health["TEST"].duplicates == 1


def test_validator_detects_sequence_gaps_and_replays():
    v = EventValidator()
    for seq in (1, 2, 5):
        t = mk_trade(seq, 10, 1)
        t.seq = seq
        assert v.accept(t)
    assert v.health["TEST"].gaps == 2
    old = mk_trade(100, 10, 1)
    old.seq = 4  # stale sequence number -> rejected
    assert v.accept(old) is False


def test_validator_marks_late_trades_delayed_but_keeps_them():
    v = EventValidator(late_tolerance_ms=1000)
    v.accept(mk_trade(1, 10, 1, ts=100_000))
    late = mk_trade(2, 10, 1, ts=90_000)
    late.quality = DataQuality.LIVE
    assert v.accept(late) is True
    assert late.quality == DataQuality.DELAYED and v.health["TEST"].late == 1


def test_buffer_coalesces_quotes_but_preserves_order_vs_trades():
    b = EventBuffer(100)
    b.put(_q("A", 1))
    t = mk_trade(1, 10, 1, symbol="A")
    b.put(t)
    b.put(_q("A", 2))  # supersedes first quote; appended after the trade
    out = b.drain()
    assert len(out) == 2
    assert out[0] is t and isinstance(out[1], Quote) and out[1].ts == 2
    assert b.metrics.coalesced == 1


def test_buffer_never_coalesces_trades_and_flags_overflow_gaps():
    b = EventBuffer(maxsize=3)
    for i in range(5):
        b.put(mk_trade(i, 10, 1, symbol="X"))
    out = b.drain()
    assert [t.trade_id for t in out] == ["2", "3", "4"]
    assert b.metrics.overflow == 2 and "X" in b.gap_symbols


def test_orderbook_delta_snapshot_and_uncross():
    ob = OrderBook("T")
    ob.apply_snapshot([(10.0, 100), (9.99, 50)], [(10.01, 70)], 1, BookResolution.DEPTH_SNAPSHOTS)
    assert (ob.best_bid, ob.best_ask, ob.spread) == (10.0, 10.01, 0.01)
    ch = ob.apply_delta(BookSide.BID, 10.0, 0, 2)
    assert ch and ch.before == 100 and ch.after == 0 and ob.best_bid == 9.99
    ob.apply_delta(BookSide.BID, 10.02, 10, 3)  # crosses the ask -> stale ask removed
    assert ob.best_ask is None or ob.best_ask > 10.02
    changes = ob.apply_snapshot([(9.99, 60)], [(10.03, 5)], 4, BookResolution.DEPTH_SNAPSHOTS)
    assert any(c.price == 9.99 and c.after == 60 for c in changes)


def test_tick_size_inferred_and_labelled():
    t = TickSizeResolver()
    assert t.tick is None and t.source == "unknown"
    for p in (10.0, 10.05, 10.1, 10.15, 10.25):
        t.observe(p)
    assert t.tick == 0.05 and t.source == "inferred"
    assert TickSizeResolver(0.01, "provider").snap(10.004) == 10.0


def test_session_manager_calendar_and_provider_override():
    sm = SessionManager("10:00", "14:30", {6, 0, 1, 2, 3})
    # 2026-11-09 is a Monday; 11:00 Cairo (UTC+2) = 09:00 UTC
    ms = 1_794_214_800_000  # 2026-11-09T09:00:00Z
    s = sm.session_for(ms)
    assert s.state == "open" and s.source == "calendar"
    fri = ms + 4 * 86_400_000
    assert sm.session_for(fri).state == "holiday_or_weekend"
    sm.provider_status = "Closed"
    assert sm.session_for(ms).state == "closed" and sm.session_for(ms).source == "provider"


def test_symbol_state_l1_only_book_from_quotes():
    from app.domain.models import Instrument
    from app.market_data.symbol_state import SymbolState

    st = SymbolState(Instrument("T", "Test"))
    st.on_quote(_q("T", 1000))
    assert st.book.resolution == BookResolution.L1_ONLY
    assert st.book.best_bid == 10.0 and st.book.best_ask == 10.01
    # trades without provider side are classified with the quote rule and flagged estimated
    t = mk_trade(1, 10.01, 5, Side.UNKNOWN, ts=1500)
    from app.domain.models import ClassificationMethod

    t.method = ClassificationMethod.UNKNOWN
    st.on_trade(t)
    assert t.side == Side.BUY and t.estimated


def test_symbol_state_ignores_l1_quote_book_when_depth_feed_present():
    from app.domain.models import Instrument
    from app.market_data.symbol_state import SymbolState

    st = SymbolState(Instrument("T", "Test"))
    st.on_book_delta(BookDelta("T", BookSide.BID, 9.0, 100, 1, "t", DataQuality.LIVE))
    st.on_quote(_q("T", 2))
    assert st.book.best_bid == 9.0 and st.book.resolution == BookResolution.DEPTH_UPDATES
