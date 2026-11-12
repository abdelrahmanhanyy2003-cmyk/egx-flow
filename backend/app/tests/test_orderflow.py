"""CVD, volume profile, POC / value area, imbalance, classification."""

from __future__ import annotations

import pytest

from app.analytics.cvd import CVDCalculator, compute_cvd, detect_divergence
from app.analytics.imbalance import book_imbalance
from app.analytics.volume_profile import VolumeProfile, profile_from_trades
from app.domain.models import ClassificationMethod, Side
from app.market_data.trade_classifier import TradeClassifier
from app.tests.conftest import mk_trade

DAY = 86_400_000


# ------------------------------------------------------------------ CVD
def test_cvd_accumulates_buy_minus_sell():
    c = CVDCalculator(reset="none")
    c.add(mk_trade(1, 10, 100, Side.BUY))
    c.add(mk_trade(2, 10, 30, Side.SELL))
    c.add(mk_trade(3, 10, 50, Side.BUY))
    assert c.cvd == 120
    assert c.buy_volume == 150 and c.sell_volume == 30


def test_cvd_unknown_side_contributes_zero_and_is_counted():
    c = CVDCalculator(reset="none")
    c.add(mk_trade(1, 10, 100, Side.UNKNOWN, method=ClassificationMethod.UNKNOWN))
    c.add(mk_trade(2, 10, 40, Side.SELL))
    assert c.cvd == -40
    assert c.unknown_volume == 100


def test_cvd_estimated_share():
    c = CVDCalculator(reset="none")
    c.add(mk_trade(1, 10, 100, Side.BUY, method=ClassificationMethod.PROVIDER))
    c.add(mk_trade(2, 10, 100, Side.SELL, method=ClassificationMethod.QUOTE_RULE))
    assert c.estimated_share == pytest.approx(0.5)


def test_cvd_session_reset_on_new_cairo_day():
    c = CVDCalculator(reset="session")
    base = 1_700_000_000_000
    c.add(mk_trade(1, 10, 100, Side.BUY, ts=base))
    c.add(mk_trade(2, 10, 100, Side.BUY, ts=base + DAY))
    assert c.cvd == 100  # reset at the new session
    assert c.session_delta == 100


def test_cvd_interval_reset():
    c = CVDCalculator(reset="interval", interval_minutes=1)
    t0 = 1_700_000_040_000 - (1_700_000_040_000 % 60_000)
    c.add(mk_trade(1, 10, 10, Side.BUY, ts=t0))
    c.add(mk_trade(2, 10, 10, Side.BUY, ts=t0 + 30_000))
    assert c.cvd == 20
    c.add(mk_trade(3, 10, 5, Side.SELL, ts=t0 + 61_000))
    assert c.cvd == -5


def test_cvd_points_are_bucketed():
    c = CVDCalculator(reset="none", bucket_ms=1000)
    t = 1_700_000_000_000
    c.add(mk_trade(1, 10, 1, Side.BUY, ts=t))
    c.add(mk_trade(2, 10, 1, Side.BUY, ts=t + 400))
    c.add(mk_trade(3, 10, 1, Side.BUY, ts=t + 1200))
    assert [p.cvd for p in c.points] == [2, 3]


def test_compute_cvd_pure():
    trades = [mk_trade(1, 1, 5, Side.BUY), mk_trade(2, 1, 2, Side.SELL), mk_trade(3, 1, 1, Side.UNKNOWN)]
    assert compute_cvd(trades) == [5, 3, 3]


def test_divergence_bearish_and_bullish():
    closes = [10.0] * 20 + [11.0]
    cvds = [float(i) for i in range(20)] + [5.0]
    d = detect_divergence(closes, cvds, lookback=20)
    assert d and d["kind"] == "bearish"
    closes = [10.0] * 20 + [9.0]
    cvds = [float(-i) for i in range(20)] + [-5.0]
    d = detect_divergence(closes, cvds, lookback=20)
    assert d and d["kind"] == "bullish"
    assert detect_divergence([1.0] * 5, [1.0] * 5, lookback=20) is None


# ------------------------------------------------------------ profile
def test_volume_profile_poc_and_sides():
    vp = VolumeProfile()
    vp.add(10.00, 100, Side.BUY)
    vp.add(10.01, 300, Side.SELL)
    vp.add(10.01, 50, Side.BUY)
    vp.add(10.02, 80, Side.UNKNOWN)
    assert vp.poc == 10.01
    assert vp.total == 530
    lv = dict((p, (b, s, u)) for p, b, s, u in vp.to_dict()["levels"])
    assert lv[10.01] == (50, 300, 0)
    assert lv[10.02] == (0, 0, 80)


def test_value_area_contains_70pct_and_grows_from_poc():
    vp = VolumeProfile()
    vols = {1.0: 5, 1.1: 10, 1.2: 20, 1.3: 40, 1.4: 15, 1.5: 7, 1.6: 3}
    for p, v in vols.items():
        vp.add(p, v, Side.BUY)
    val, vah = vp.value_area(0.70)
    assert vp.poc == 1.3
    inside = sum(v for p, v in vols.items() if val <= p <= vah)
    assert inside >= 0.70 * sum(vols.values())
    # expansion: POC 40 -> add 1.2 (20) vs 1.4 (15): 1.2 first -> 60; then 1.4 (15) vs 1.1 (10): 1.4 -> 75 >= 70
    assert (val, vah) == (1.2, 1.4)


def test_value_area_single_level_and_empty():
    vp = VolumeProfile()
    assert vp.value_area() == (None, None)
    vp.add(5.0, 10, Side.SELL)
    assert vp.value_area() == (5.0, 5.0)


def test_poc_tie_is_deterministic_lowest_price():
    vp = VolumeProfile()
    vp.add(2.0, 10, Side.BUY)
    vp.add(1.0, 10, Side.BUY)
    assert vp.poc == 1.0


def test_range_profile_filters_by_time():
    trades = [mk_trade(i, 10 + i * 0.01, 10, ts=1000 * i) for i in range(10)]
    vp = profile_from_trades(trades, 3000, 5000)
    assert vp.total == 30
    assert set(vp.levels) == {10.03, 10.04, 10.05}


# ----------------------------------------------------------- imbalance
def test_book_imbalance_basic():
    bids = [(10.0, 300), (9.99, 100)]
    asks = [(10.01, 100), (10.02, 100)]
    im = book_imbalance(bids, asks, levels=2)
    assert im.bid_volume == 400 and im.ask_volume == 200
    assert im.imbalance == pytest.approx(200 / 600)
    assert im.imbalance_pct == pytest.approx(400 / 600 * 100)
    assert im.largest_bid_share == pytest.approx(0.75)
    assert im.ask_concentration == pytest.approx(0.5)


def test_book_imbalance_respects_depth_levels_and_empty():
    bids = [(10.0, 100), (9.99, 1000)]
    asks = [(10.01, 100)]
    assert book_imbalance(bids, asks, levels=1).imbalance == 0
    e = book_imbalance([], [], 5)
    assert e.imbalance == 0 and e.imbalance_pct == 50.0


# ------------------------------------------------------- classification
def test_classifier_prefers_provider_side():
    c = TradeClassifier()
    r = c.classify(10.0, 1, provider_side=Side.SELL, bid=9.9, ask=10.0, quote_ts=0)
    assert r.side == Side.SELL and r.method == ClassificationMethod.PROVIDER


def test_classifier_quote_rule():
    c = TradeClassifier()
    assert c.classify(10.01, 10, bid=10.0, ask=10.01, quote_ts=5).side == Side.BUY
    r = c.classify(10.0, 10, bid=10.0, ask=10.01, quote_ts=5)
    assert r.side == Side.SELL and r.method == ClassificationMethod.QUOTE_RULE and r.confidence == 0.9
    inside = c.classify(10.04, 10, bid=10.0, ask=10.05, quote_ts=5)
    assert inside.side == Side.BUY and inside.confidence < 0.9


def test_classifier_tick_rule_when_quote_stale_or_missing():
    c = TradeClassifier(max_quote_age_ms=1000)
    first = c.classify(10.0, 0)
    assert first.side == Side.UNKNOWN  # nothing to go on: never invent a side
    up = c.classify(10.1, 10_000, bid=9.0, ask=9.5, quote_ts=0)  # stale quote ignored
    assert up.side == Side.BUY and up.method == ClassificationMethod.TICK_RULE
    zero = c.classify(10.1, 10_001)
    assert zero.side == Side.BUY and zero.confidence == 0.5  # zero tick -> last direction
    down = c.classify(10.0, 10_002)
    assert down.side == Side.SELL
