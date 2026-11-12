"""Portfolio valuation, P&L (FIFO + fees), reconciliation (no double counting), risk."""

from __future__ import annotations

import pytest

from app.domain.models import BrokerOrder, DataQuality, PortfolioPosition
from app.portfolio.pnl import Fill, fifo, return_pct, unrealized
from app.portfolio.positions import enrich_positions
from app.portfolio.reconciliation import importable, reconcile
from app.portfolio.risk import concentration, drawdown, exposure_change, sector_concentration


def test_fifo_realized_with_fees():
    fills = [
        Fill("COMI", "buy", 100, 10.0, fees=10.0, ts="1"),  # unit cost 10.10
        Fill("COMI", "buy", 100, 12.0, fees=0.0, ts="2"),  # unit cost 12.00
        Fill("COMI", "sell", 150, 13.0, fees=15.0, ts="3"),  # 0.10/share fee
    ]
    r = fifo(fills)["COMI"]
    # lot1: 100*(12.9-10.1)=280 ; lot2: 50*(12.9-12)=45
    assert r.realized == pytest.approx(325.0)
    assert r.open_qty == 50
    assert r.avg_cost == pytest.approx(12.0)
    assert r.fees == 25.0
    assert len(r.closed) == 2 and r.closed[0].quantity == 100


def test_fifo_rejects_oversell():
    with pytest.raises(ValueError):
        fifo([Fill("X", "buy", 10, 1.0), Fill("X", "sell", 11, 1.0)])


def test_unrealized_and_return():
    assert unrealized(100, 10.0, 12.5) == 250.0
    assert unrealized(100, 10.0, None) is None
    assert return_pct(10.0, 11.0) == pytest.approx(10.0)


def _pos(sym, qty, avg, price=None, mv=None, upnl=None):
    return PortfolioPosition(sym, qty, avg, price, mv, upnl, 0.0, None, quality=DataQuality.LIVE,
                             broker_fields=["quantity", "avg_price"])


def test_enrich_positions_labels_local_fields_and_never_overrides_broker():
    pos = [_pos("A", 100, 10.0, price=11.0, mv=1100.0, upnl=100.0), _pos("B", 50, 20.0)]
    out = enrich_positions(pos, {"A": 99.0, "B": 22.0}, total_value=None)
    a, b = out
    assert a["current_price"] == 11.0 and a["market_value"] == 1100.0  # broker values kept
    assert "current_price" not in a["local_fields"]
    assert b["current_price"] == 22.0 and "current_price" in b["local_fields"]
    assert b["market_value"] == 1100.0 and b["unrealized_pnl"] == 100.0
    assert a["allocation_pct"] == pytest.approx(50.0) and b["allocation_pct"] == pytest.approx(50.0)


def _order(oid, side, qty, px, status="Filled", sym="COMI"):
    return BrokerOrder(oid, sym, side, qty, qty, px, px, status, 1_700_000_000_000)


def test_reconciliation_statuses():
    broker = [_order("1", "Buy", 100, 10.0), _order("2", "Sell", 50, 11.0), _order("3", "Buy", 5, 1.0, "Cancelled")]
    journal = [
        {"id": 1, "symbol": "COMI", "side": "buy", "quantity": 100, "price": 10.0, "broker_order_id": "1"},
        {"id": 2, "symbol": "COMI", "side": "sell", "quantity": 40, "price": 11.0, "broker_order_id": "2"},
        {"id": 3, "symbol": "COMI", "side": "buy", "quantity": 1, "price": 1.0, "broker_order_id": "999"},
        {"id": 4, "symbol": "COMI", "side": "buy", "quantity": 1, "price": 1.0, "broker_order_id": None},
    ]
    rows = reconcile(broker, journal)
    st = sorted(r["status"] for r in rows)
    assert st == ["journal_only", "manual", "matched", "mismatch"]
    mm = next(r for r in rows if r["status"] == "mismatch")
    assert "quantity" in mm["note"]


def test_import_never_double_counts():
    broker = [_order("1", "Buy", 100, 10.0), _order("2", "Sell", 50, 11.0), _order("3", "Buy", 5, 1.0, "Rejected")]
    journal = [{"id": 1, "symbol": "COMI", "side": "buy", "quantity": 100, "price": 10.0, "broker_order_id": "1"}]
    rows = importable(broker, journal)
    assert [r["broker_order_id"] for r in rows] == ["2"]
    assert rows[0]["side"] == "sell" and rows[0]["origin"] == "broker"
    journal.append({**rows[0], "id": 2})
    assert importable(broker, journal) == []


def test_concentration_and_sectors():
    pos = [{"symbol": "A", "market_value": 600.0}, {"symbol": "B", "market_value": 300.0},
           {"symbol": "C", "market_value": 100.0}]
    c = concentration(pos)
    assert c["largest"] == "A" and c["largest_weight_pct"] == 60.0
    assert c["hhi"] == pytest.approx(0.36 + 0.09 + 0.01)
    secs = sector_concentration(pos, {"A": "Banks", "B": "Banks", "C": None})
    assert secs[0] == {"sector": "Banks", "value": 900.0, "weight_pct": 90.0}
    assert secs[1]["sector"] == "Unclassified"


def test_drawdown():
    eq = [(1, 100.0), (2, 120.0), (3, 90.0), (4, 130.0), (5, 117.0)]
    d = drawdown(eq)
    assert d["max_drawdown_pct"] == pytest.approx(-25.0)
    assert d["peak_ts"] == 2 and d["trough_ts"] == 3
    assert d["current_drawdown_pct"] == pytest.approx(-10.0)


def test_exposure_change():
    hist = [{"ts": 0, "stocks_value": 1000.0}, {"ts": 86_400_000, "stocks_value": 1100.0}]
    e = exposure_change(hist, 1210.0)
    assert e["change"] == pytest.approx(210.0) and e["change_pct"] == pytest.approx(21.0)
