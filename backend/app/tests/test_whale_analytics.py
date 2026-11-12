"""Large lots, walls (persistence, pulled vs consumed), icebergs, absorption, whale score."""

from __future__ import annotations

import pytest

from app.analytics.absorption import AbsorptionDetector
from app.analytics.accumulation import FlowEvidence, evaluate_flow
from app.analytics.bars import Bar
from app.analytics.iceberg import IcebergDetector
from app.analytics.large_lot import LargeLotConfig, LargeLotTracker, RollingDistribution
from app.analytics.liquidity_walls import WallConfig, WallDetector
from app.analytics.whale_score import WEIGHTS, WhaleInputs, whale_score
from app.domain.models import BookResolution, BookSide, Side
from app.market_data.orderbook_engine import LevelChange, OrderBook
from app.tests.conftest import mk_trade


# ------------------------------------------------------------ large lots
def test_rolling_distribution_percentile_and_rank():
    d = RollingDistribution(100)
    for v in range(1, 101):
        d.add(float(v))
    assert d.percentile(50) == pytest.approx(50.5)
    assert d.percentile(99) == pytest.approx(99.01)
    assert d.rank(100) == 100.0
    assert d.mean == 50.5


def test_large_lot_warmup_uses_floor():
    t = LargeLotTracker(LargeLotConfig(min_value_egp=1000, warmup=10))
    thr, method = t.threshold()
    assert thr == 1000 and "warming" in method
    assert t.on_trade(mk_trade(1, 10, 50)) is None  # 500 EGP
    assert t.on_trade(mk_trade(2, 10, 150)) is not None  # 1500 EGP >= floor


def test_large_lot_dynamic_percentile_threshold():
    cfg = LargeLotConfig(min_value_egp=100, percentile=95, warmup=50, size_multiple=1e9)
    t = LargeLotTracker(cfg)
    for i in range(200):
        t.on_trade(mk_trade(i, 10, 10 + (i % 20)))  # values 100..290
    thr, method = t.threshold()
    assert 270 < thr <= 290 and method.startswith("p95")
    assert t.on_trade(mk_trade(999, 10, 25)) is None
    big = t.on_trade(mk_trade(1000, 10, 500))
    assert big is not None and big.percentile_rank == 100.0
    assert big.multiple_of_avg > 20


def test_large_lot_does_not_set_its_own_threshold():
    cfg = LargeLotConfig(min_value_egp=1, percentile=100, warmup=5, size_multiple=1e9)
    t = LargeLotTracker(cfg)
    for i in range(10):
        t.on_trade(mk_trade(i, 1, 10))
    # p100 of history = 10; a 10_000 trade must be flagged (evaluated before being added)
    assert t.on_trade(mk_trade(50, 1, 10_000)) is not None


def test_large_lot_clusters_same_side_in_window():
    cfg = LargeLotConfig(min_value_egp=100, warmup=10_000, cluster_window_ms=10_000, cluster_min_trades=3)
    t = LargeLotTracker(cfg)
    base = 1_000_000
    for i in range(3):
        t.on_trade(mk_trade(i, 10, 20, Side.BUY, ts=base + i * 5000))
    t.on_trade(mk_trade(9, 10, 20, Side.SELL, ts=base + 16_000))
    cl = t.clusters()
    assert len(cl) == 1 and cl[0].count == 3 and cl[0].side == "buy" and cl[0].value == 600


# ----------------------------------------------------------------- walls
def _book(bids, asks, ts=0):
    b = OrderBook("TEST")
    b.apply_snapshot(bids, asks, ts, BookResolution.DEPTH_SNAPSHOTS)
    return b


def _levels(big_bid=None):
    bids = [(10.0 - i * 0.01, 100.0) for i in range(10)]
    if big_bid:
        bids[5] = (bids[5][0], big_bid)
    asks = [(10.01 + i * 0.01, 100.0) for i in range(10)]
    return bids, asks


def test_wall_reported_only_after_persistence():
    det = WallDetector("TEST", WallConfig(size_multiple=4, min_value_egp=0, min_persistence_ms=3000))
    bids, asks = _levels(big_bid=1000)
    assert det.update(_book(bids, asks), 0, 100, 0.01) == []
    assert det.update(_book(bids, asks), 2000, 100, 0.01) == []
    ev = det.update(_book(bids, asks), 3000, 100, 0.01)
    assert len(ev) == 1 and ev[0].kind == "new"
    w = ev[0].wall
    assert w["side"] == "bid" and w["price"] == 9.95 and w["persistence_ms"] == 3000
    assert w["distance_ticks"] == -5  # five ticks below the best bid


def test_flickering_level_never_reported():
    det = WallDetector("TEST", WallConfig(size_multiple=4, min_value_egp=0, min_persistence_ms=3000))
    with_wall, without = _levels(1000), _levels()
    assert det.update(_book(*with_wall), 0, 100, 0.01) == []
    assert det.update(_book(*without), 1000, 100, 0.01) == []  # removed before persistence: silent


def test_wall_pulled_vs_consumed():
    cfg = WallConfig(size_multiple=4, min_value_egp=0, min_persistence_ms=1000)
    # pulled: disappears with no trades at level
    det = WallDetector("TEST", cfg)
    det.update(_book(*_levels(1000)), 0, 100, 0.01)
    det.update(_book(*_levels(1000)), 1000, 100, 0.01)
    ev = det.update(_book(*_levels()), 2000, 100, 0.01)
    assert [e.kind for e in ev] == ["pulled"]
    # consumed: trades at the level explain the drop
    det = WallDetector("TEST", cfg)
    det.update(_book(*_levels(1000)), 0, 100, 0.01)
    det.update(_book(*_levels(1000)), 1000, 100, 0.01)
    det.on_trade(9.95, 900)
    ev = det.update(_book(*_levels()), 2000, 100, 0.01)
    assert [e.kind for e in ev] == ["consumed"]


def test_wall_resize_event():
    det = WallDetector("TEST", WallConfig(size_multiple=4, min_value_egp=0, min_persistence_ms=0, resize_pct=0.3))
    det.update(_book(*_levels(1000)), 0, 100, 0.01)
    ev = det.update(_book(*_levels(2000)), 1000, 100, 0.01)
    assert [e.kind for e in ev] == ["resized"]


# --------------------------------------------------------------- iceberg
def _feed_iceberg(det: IcebergDetector, refills: int, clip: float = 100, price: float = 10.0, t0: int = 0):
    det.resolution = BookResolution.DEPTH_UPDATES
    det.on_level_change(LevelChange(BookSide.BID, price, 0, clip), t0)
    t = t0
    for _ in range(refills):
        t += 500
        det.on_trade(price, clip, Side.SELL, t, clip, 0, price, price + 0.01)
        det.on_level_change(LevelChange(BookSide.BID, price, clip, 0), t + 10)
        det.on_level_change(LevelChange(BookSide.BID, price, 0, clip), t + 200)
    return t


def test_iceberg_detected_on_repeated_replenishment():
    det = IcebergDetector("TEST")
    t = _feed_iceberg(det, 5)
    sigs = det.evaluate(t + 1000, best_bid=10.0, best_ask=10.01)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.side == "bid" and s.price == 10.0 and s.replenishments >= 4
    assert s.executed == 500 and s.max_displayed == 100 and s.estimated_hidden == 400
    assert 0 < s.confidence <= 0.95
    assert s.to_dict()["estimated"] is True and "not a confirmed" in s.to_dict()["label"]


def test_no_iceberg_without_replenishment():
    det = IcebergDetector("TEST")
    det.resolution = BookResolution.DEPTH_UPDATES
    det.on_level_change(LevelChange(BookSide.BID, 10.0, 0, 1000), 0)
    for i in range(5):
        det.on_trade(10.0, 100, Side.SELL, 100 * i, 1000, 0, 10.0, 10.01)
    assert det.evaluate(1000, 10.0, 10.01) == []


def test_iceberg_void_when_level_broken():
    det = IcebergDetector("TEST")
    t = _feed_iceberg(det, 5)
    assert det.evaluate(t + 1000, best_bid=9.99, best_ask=10.0) == []


def test_iceberg_confidence_lower_with_coarser_book():
    a, b = IcebergDetector("A"), IcebergDetector("B")
    ta = _feed_iceberg(a, 5)
    tb = _feed_iceberg(b, 5)
    b.resolution = BookResolution.L1_ONLY
    ca = a.evaluate(ta + 1000, 10.0, 10.01)[0].confidence
    cb = b.evaluate(tb + 1000, 10.0, 10.01)[0].confidence
    assert cb < ca


def test_iceberg_refill_to_different_size_is_not_replenishment():
    det = IcebergDetector("TEST")
    det.resolution = BookResolution.DEPTH_UPDATES
    det.on_level_change(LevelChange(BookSide.BID, 10.0, 0, 100), 0)
    t = 0
    for i in range(5):
        t += 500
        det.on_trade(10.0, 100, Side.SELL, t, 100, 0, 10.0, 10.01)
        det.on_level_change(LevelChange(BookSide.BID, 10.0, 100, 0), t + 10)
        det.on_level_change(LevelChange(BookSide.BID, 10.0, 0, 400 + i * 300), t + 200)  # random new orders
    assert det.evaluate(t + 1000, 10.0, 10.01) == []


# ------------------------------------------------------------ absorption
def test_bullish_absorption_when_bid_holds():
    det = AbsorptionDetector("TEST")
    for i in range(6):
        det.on_trade(mk_trade(i, 10.0, 10_000, Side.SELL, ts=1000 + i))
    sigs = det.evaluate(2000, best_bid=10.0, best_ask=10.01, tick=0.01, typical_level=1000)
    assert len(sigs) == 1 and sigs[0].kind == "bullish" and sigs[0].held
    # dedup within the window
    assert det.evaluate(3000, 10.0, 10.01, 0.01, 1000) == []


def test_no_absorption_when_level_breaks():
    det = AbsorptionDetector("TEST")
    for i in range(6):
        det.on_trade(mk_trade(i, 10.0, 10_000, Side.SELL, ts=1000 + i))
    assert det.evaluate(2000, best_bid=9.97, best_ask=9.98, tick=0.01, typical_level=1000) == []


def test_absorption_ignores_unknown_side():
    det = AbsorptionDetector("TEST")
    for i in range(6):
        det.on_trade(mk_trade(i, 10.0, 10_000, Side.UNKNOWN, ts=1000 + i))
    assert det.evaluate(2000, 10.0, 10.01, 0.01) == []


# ---------------------------------------------------- accumulation / score
def _bars(n, delta_sign, drift=0.0):
    out = []
    p = 10.0
    for i in range(n):
        b = Bar(i * 60_000, p, p + 0.02, p - 0.02, p + drift, volume=1000)
        if delta_sign > 0:
            b.buy_volume, b.sell_volume = 700, 300
        else:
            b.buy_volume, b.sell_volume = 300, 700
        p += drift
        out.append(b)
    return out


def test_flow_accumulation_from_buying_without_price_rise():
    sig = evaluate_flow(FlowEvidence(bars=_bars(10, +1), large_buy_value=5e6, large_sell_value=1e6,
                                     bullish_absorptions=3))
    assert sig.kind == "accumulation" and sig.confidence > 0.3
    assert any(e["factor"] == "cvd_vs_price" for e in sig.evidence)
    assert "not proof" in sig.to_dict()["disclaimer"]


def test_flow_distribution_and_insufficient_data():
    sig = evaluate_flow(FlowEvidence(bars=_bars(10, -1), large_sell_value=5e6, bearish_absorptions=2))
    assert sig.kind == "distribution"
    assert evaluate_flow(FlowEvidence(bars=_bars(2, 1))).kind == "neutral"


def test_whale_score_bounds_and_explainability():
    low = whale_score(WhaleInputs())
    assert low["score"] == 0 and low["band"] == "normal"
    assert {f["factor"] for f in low["factors"]} == set(WEIGHTS)
    high = whale_score(WhaleInputs(largest_trade_pctile=100, large_value_share=0.6, large_trades_recent=10,
                                   large_trades_baseline=1, rvol=4, liquidity_concentration=0.8,
                                   persistent_walls=5, absorption_events=5, cvd_divergence=1.0,
                                   depth_change_pct=80))
    assert high["score"] == 100 and high["band"] == "extreme"
    assert sum(f["contribution"] for f in high["factors"]) == high["score"]


def test_whale_score_monotonic_in_each_factor():
    base = whale_score(WhaleInputs(largest_trade_pctile=95))["score"]
    more = whale_score(WhaleInputs(largest_trade_pctile=99))["score"]
    assert more > base
