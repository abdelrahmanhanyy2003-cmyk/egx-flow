"""Alert dedup, replay accuracy against live computation, and API smoke tests (demo mode)."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any

from app.alerts.engine import AlertEngine
from app.domain.models import BookResolution, BookSnapshot, DataQuality, Instrument, Side
from app.market_data.symbol_state import SymbolState
from app.tests.conftest import mk_trade


# ------------------------------------------------------------------ alerts
def test_alert_engine_never_duplicates_same_event():
    stored: dict[str, dict[str, Any]] = {}

    def persist(a: dict[str, Any]) -> dict[str, Any] | None:
        if a["dedup_key"] in stored:
            return None
        stored[a["dedup_key"]] = a
        return a

    eng = AlertEngine(persist)
    ev = {"type": "large_trade", "symbol": "COMI", "trade_id": "T1", "value": 5e6, "quantity": 60000,
          "price": 83.0, "side": "buy", "ts": 1, "estimated": False}
    first = eng.on_event(ev)
    assert {a["rule"] for a in first} == {"large_trade", "large_buy"}
    assert eng.on_event(ev) == []
    eng2 = AlertEngine(persist)  # simulates a restart: DB uniqueness still blocks it
    assert eng2.on_event(ev) == []


def test_alert_rules_symbol_override_and_disable():
    eng = AlertEngine()
    eng.load_rules([
        {"rule": "large_trade", "symbol": None, "enabled": True, "sound": True, "params": {"min_value": 10e6}},
        {"rule": "large_trade", "symbol": "FWRY", "enabled": True, "sound": False, "params": {"min_value": 1e5}},
        {"rule": "large_buy", "symbol": None, "enabled": False, "sound": True, "params": {}},
    ])
    ev = {"type": "large_trade", "symbol": "FWRY", "trade_id": "x", "value": 2e5, "quantity": 1, "price": 1,
          "side": "buy", "ts": 1}
    out = eng.on_event(ev)
    assert [a["rule"] for a in out] == ["large_trade"] and out[0]["sound"] is False
    assert eng.on_event({**ev, "symbol": "COMI", "trade_id": "y"}) == []


def test_continuous_alerts_respect_cooldown_buckets():
    eng = AlertEngine()
    stats = {"imbalance": {"imbalance": 0.8, "levels": 10}, "rvol": None, "change_pct": None, "last": None}
    assert len(eng.on_stats("COMI", stats, 0)) == 1
    assert eng.on_stats("COMI", stats, 60_000) == []  # same 10-minute bucket
    assert len(eng.on_stats("COMI", stats, 11 * 60_000)) == 1


def test_price_alert_and_position_pnl():
    eng = AlertEngine()
    eng.load_rules([{"rule": "price_alert", "symbol": "ETEL", "enabled": True, "sound": True,
                     "params": {"above": 42.0, "below": None}}])
    assert eng.on_stats("ETEL", {"last": 41.9}, 0) == []
    assert len(eng.on_stats("ETEL", {"last": 42.0}, 1)) == 1
    assert len(eng.on_position({"symbol": "FWRY", "unrealized_pnl_pct": -7.5}, 0)) == 1
    assert eng.on_position({"symbol": "FWRY", "unrealized_pnl_pct": 1.0}, 0) == []


# ------------------------------------------------------------------ replay
def _live_run() -> tuple[SymbolState, list[Any], list[BookSnapshot]]:
    inst = Instrument("RPL", "Replay Test", tick_size=0.01, tick_size_source="config")
    st = SymbolState(inst, quality=DataQuality.SIMULATED)
    trades, books = [], []
    base = 1_794_214_800_000
    px = 10.0
    for i in range(400):
        ts = base + i * 1000
        if i % 3 == 0:
            b = BookSnapshot("RPL", [(round(px - 0.01 * k, 2), 100 + k * 10 + i % 7) for k in range(10)],
                             [(round(px + 0.01 * (k + 1), 2), 120 + k * 10) for k in range(10)], ts, "test",
                             DataQuality.SIMULATED, BookResolution.DEPTH_SNAPSHOTS)
            books.append(b)
            st.on_book_snapshot(b)
            st.sample(ts)
        side = Side.BUY if (i * 7) % 5 < 3 else Side.SELL
        t = mk_trade(i, px + (0.01 if side == Side.BUY else 0.0), 50 + (i * 13) % 400, side, ts=ts + 500,
                     symbol="RPL")
        trades.append(t)
        st.on_trade(t)
        if i % 50 == 0:
            px = round(px + (0.02 if i % 100 == 0 else -0.01), 2)
    return st, trades, books


def test_replay_reproduces_live_analytics(tmp_path):
    from app.database.base import create_all, init_engine
    from app.database.repositories import market_repo
    from app.replay.playback import ReplaySession, build_events
    from app.replay.recorder import Recorder

    init_engine(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    create_all()
    live, trades, books = _live_run()
    rec = Recorder(True, book_interval_ms=1)
    for t in trades:
        rec.record_trade(t)
    for b in books:
        ob = SymbolState(Instrument("RPL", "x")).book
        ob.apply_snapshot(b.bids, b.asks, b.ts, b.resolution)
        rec.maybe_record_book(ob, b.ts, "test", "simulated")
    asyncio.run(rec.flush())

    sessions = market_repo.list_sessions("RPL")
    assert len(sessions) == 1 and sessions[0]["trades"] == len(trades)
    s = market_repo.get_session(sessions[0]["id"])
    assert s is not None
    evs = build_events(market_repo.load_trades("RPL", s["first_ts"], s["last_ts"]),
                       market_repo.load_book_snapshots("RPL", s["first_ts"], s["last_ts"]))
    r = ReplaySession(s, Instrument("RPL", "Replay Test", tick_size=0.01), evs, speed=1000.0, playing=True)
    while r.playing:
        r.advance(1000)
    assert r.state is not None
    rs = r.state
    assert rs.cvd.cvd == live.cvd.cvd
    assert rs.volume == live.volume and rs.trade_count == live.trade_count
    assert rs.profile.to_dict() == live.profile.to_dict()
    assert rs.vwap.value == live.vwap.value
    assert len(rs.heatmap.columns) == len(books)

    # seek backwards rebuilds state deterministically
    mid = (s["first_ts"] + s["last_ts"]) // 2
    r.seek(mid)
    expect = sum(t.quantity for t in trades if t.ts <= mid)
    assert r.state.volume == expect


# --------------------------------------------------------------------- API
def test_api_demo_mode_end_to_end():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        h = c.get("/api/health").json()
        assert h["ok"] is True and h["mode"] == "demo"
        ov = c.get("/api/market/overview").json()
        assert ov["quality"] == "simulated"
        rows = c.get("/api/stocks").json()["rows"]
        assert any(r["symbol"] == "COMI" and r["streaming"] for r in rows)
        ob = c.get("/api/orderbook/COMI").json()
        assert ob["best_bid"] < ob["best_ask"]
        assert c.get("/api/orderbook/BAD!").status_code in (400, 404)
        st = c.get("/api/auth/status").json()
        assert st["read_only"] is True and "API_KEY" not in json.dumps(st)
        pf = c.get("/api/portfolio/summary").json()
        assert pf["quality"] == "simulated" and pf["positions"]
        j = c.post("/api/portfolio/journal", json={"symbol": "comi", "side": "buy", "trade_date": "2026-11-01",
                                                   "quantity": 10, "price": 80, "fees": 1}).json()
        assert j["symbol"] == "COMI"
        assert c.post("/api/portfolio/journal", json={"symbol": "COMI", "side": "hold", "trade_date": "2026-11-01",
                                                      "quantity": 1, "price": 1}).status_code == 422
        imp1 = c.post("/api/portfolio/reconciliation/import").json()
        imp2 = c.post("/api/portfolio/reconciliation/import").json()
        assert imp1["created"] > 0 and imp2["created"] == 0  # never double counted
        assert c.put("/api/alerts/rules", json={"rule": "large_trade", "params": {"min_value": 1}}).status_code == 200
        assert c.put("/api/alerts/rules", json={"rule": "nope"}).status_code == 400
        with c.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"op": "sub", "topic": "symbol:COMI"}))
            got = set()
            for _ in range(6):
                m = json.loads(ws.receive_text())
                got.add(m["type"])
                if m["type"] == "snapshot":
                    d = m["data"]
                    assert d["columns"] and d["trades"] and d["stats"]["quality"] == "simulated"
            assert "snapshot" in got
        sess = c.get("/api/replay/sessions").json()["rows"]
        assert sess, "demo prewarm should have recorded sessions"
        info = c.post("/api/replay/open", json={"session_id": sess[0]["id"]}).json()
        assert info["events"] > 0
        assert c.post(f"/api/replay/{info['id']}/control", json={"action": "speed", "value": 30}).json()["speed"] == 30


def test_access_token_protects_api(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core import config

    monkeypatch.setenv("APP_ACCESS_TOKEN", "s3cret")
    config.get_settings.cache_clear()
    try:
        from app.main import app

        with TestClient(app) as c:
            assert c.get("/api/market/status").status_code == 401
            assert c.get("/api/market/status", headers={"X-EGXFlow-Token": "s3cret"}).status_code == 200
            assert c.get("/api/health").status_code == 200
    finally:
        monkeypatch.delenv("APP_ACCESS_TOKEN")
        config.get_settings.cache_clear()


_ = (os, tempfile)
