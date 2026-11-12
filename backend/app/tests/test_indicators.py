"""Technical indicators and VWAP."""

from __future__ import annotations

import pytest

from app.analytics.indicators import atr, breadth, ema, macd, relative_volume, rsi, sma, true_range, volume_imbalance
from app.analytics.vwap import VWAP, anchored_vwap_series, vwap


def test_sma():
    assert sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_ema_seeded_with_sma():
    out = ema([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)  # 4*0.5 + 2*0.5
    assert out[4] == pytest.approx(4.0)


def test_rsi_extremes_and_known_value():
    up = [float(i) for i in range(20)]
    assert rsi(up, 14)[-1] == 100.0
    down = [float(20 - i) for i in range(20)]
    assert rsi(down, 14)[-1] == pytest.approx(0.0)
    # Classic Wilder example (first RSI value ~70.53)
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
              46.28, 46.28]
    assert rsi(closes, 14)[14] == pytest.approx(70.46, abs=0.2)


def test_macd_alignment():
    closes = [float(i) for i in range(60)]
    line, sig, hist = macd(closes, 12, 26, 9)
    assert line[24] is None and line[25] is not None
    assert sig[25 + 7] is None and sig[25 + 8] is not None
    # linear series: MACD line converges to constant (26-12)/2 = 7
    assert line[-1] == pytest.approx(7.0, rel=1e-3)
    assert hist[-1] == pytest.approx(0.0, abs=1e-2)


def test_true_range_and_atr():
    h = [10, 11, 12, 11]
    l_ = [9, 10, 10, 9]
    c = [9.5, 10.5, 11.5, 9.5]
    assert true_range(h, l_, c) == [1, 1.5, 2, 2.5]
    a = atr(h, l_, c, 2)
    assert a[1] == pytest.approx(1.25)
    assert a[2] == pytest.approx((1.25 * 1 + 2) / 2)
    assert a[3] == pytest.approx((a[2] * 1 + 2.5) / 2)


def test_relative_volume():
    v = [100] * 5 + [300]
    r = relative_volume(v, 5)
    assert r[5] == pytest.approx(3.0) and r[4] is None


def test_breadth_and_volume_imbalance():
    b = breadth(30, 10, 5)
    assert b["ad_ratio"] == 3 and b["ad_line"] == 20
    assert b["pct_advancing"] == pytest.approx(30 / 45 * 100)
    assert volume_imbalance(75, 25) == 0.5
    assert volume_imbalance(0, 0) == 0.0


def test_vwap_and_bands():
    v = VWAP()
    v.add(10, 100)
    v.add(12, 100)
    assert v.value == 11
    assert v.stdev == pytest.approx(1.0)
    assert v.bands(2) == (9.0, 13.0)
    assert vwap([10, 20], [3, 1]) == 12.5


def test_anchored_vwap_ignores_points_before_anchor():
    pts = [(1, 100.0, 10.0), (2, 10.0, 1.0), (3, 20.0, 1.0)]
    out = anchored_vwap_series(pts, 2)
    assert out == [(2, 10.0), (3, 15.0)]
    v = VWAP(anchor_ts=2)
    v.add(100, 10, ts=1)
    v.add(10, 1, ts=2)
    assert v.value == 10
