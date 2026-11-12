"""Network hardening, public-demo mode and storage housekeeping."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.core.security import RateLimiter, origin_allowed
from app.main import create_app

ALLOWED = ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_origin_allow_list():
    assert origin_allowed("http://localhost:3000", ALLOWED)
    assert origin_allowed("http://localhost:3000/", ALLOWED)
    assert origin_allowed(None, ALLOWED)  # non-browser client
    assert not origin_allowed("http://evil.example", ALLOWED)
    assert not origin_allowed("http://localhost:3000.evil.example", ALLOWED)
    assert not origin_allowed("null", ALLOWED)


def test_rate_limiter_bucket_refills():
    rl = RateLimiter(60)  # 1 token per second, burst 60
    assert all(rl.allow("a", now=0.0) for _ in range(60))
    assert not rl.allow("a", now=0.0)
    assert rl.allow("b", now=0.0)  # independent keys
    assert rl.allow("a", now=1.5) and not rl.allow("a", now=1.5)
    assert RateLimiter(0).allow("x")  # disabled


def test_public_demo_refuses_live_mode():
    with pytest.raises(ValidationError):
        Settings(PUBLIC_DEMO=True, DATA_MODE="live")
    assert Settings(PUBLIC_DEMO=True, DATA_MODE="demo").public_demo is True


def test_public_demo_blocks_writes_and_hides_docs():
    c = TestClient(create_app(Settings(PUBLIC_DEMO=True)))  # no lifespan: guards only
    assert c.get("/api/health").json()["public_demo"] is True
    for method, path in (("post", "/api/portfolio/journal"), ("put", "/api/alerts/rules"),
                         ("put", "/api/prefs/layouts"), ("delete", "/api/portfolio/journal/1"),
                         ("post", "/api/auth/live-check"), ("post", "/api/portfolio/refresh")):
        r = c.request(method.upper(), path)
        assert r.status_code == 403, path
        assert "read-only" in r.json()["detail"]
    # replay controls pass the guard (503 = reached the route; engine not started here)
    assert c.post("/api/replay/open", json={"session_id": 1}).status_code == 503
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    # normal mode keeps the docs and allows writes through the guard
    n = TestClient(create_app(Settings(PUBLIC_DEMO=False)))
    assert n.get("/docs").status_code == 200
    assert n.post("/api/portfolio/refresh").status_code == 503


def test_rate_limit_returns_429_but_never_for_health():
    c = TestClient(create_app(Settings(API_RATE_LIMIT_PER_MINUTE=3)))
    codes = [c.get("/api/market/status").status_code for _ in range(5)]
    assert codes[:3] == [503, 503, 503] and codes[3:] == [429, 429]
    assert c.get("/api/market/status").headers.get("retry-after") == "5"
    assert all(c.get("/api/health").status_code == 200 for _ in range(10))


def test_unknown_host_header_rejected():
    c = TestClient(create_app(Settings()))
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    assert c.get("/api/health", headers={"host": "localhost:8000"}).status_code == 200


def test_security_headers_present():
    r = TestClient(create_app(Settings())).get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def test_websocket_origin_check_and_connection_cap():
    app = create_app(Settings(WS_MAX_PER_IP=1, CORS_ORIGINS="http://localhost:3000"))
    with TestClient(app) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws", headers={"origin": "http://evil.example"}):
                pass
        with c.websocket_connect("/ws", headers={"origin": "http://localhost:3000"}) as ws:
            assert ws.receive_json()["type"] == "status"
            with pytest.raises(WebSocketDisconnect):  # second socket from the same IP
                with c.websocket_connect("/ws", headers={"origin": "http://localhost:3000"}):
                    pass


def test_retention_prunes_old_market_data_only(tmp_path):
    from app.database.base import create_all, init_engine
    from app.database.models import TradeRow
    from app.database.repositories import market_repo, user_repo

    init_engine(f"sqlite:///{(tmp_path / 'p.db').as_posix()}")
    create_all()
    hour = 3_600_000
    now = 100 * hour
    rows = [{"symbol": "X", "ts": now - h * hour, "trade_id": f"t{h}", "price": 1.0, "quantity": 1.0,
             "value": 1.0, "side": "buy", "method": "provider", "confidence": 1.0, "provider_side_raw": None,
             "received_ts": now, "source": "test", "quality": "simulated"} for h in range(10)]
    market_repo.bulk_insert_ignore(TradeRow, rows)
    market_repo.upsert_session("2026-01-01", "X", "test", "simulated", "depth_updates", 1000, now - 9 * hour, now, 10, 0)
    market_repo.upsert_session("2025-12-31", "X", "test", "simulated", "depth_updates", 1000, now - 50 * hour,
                               now - 40 * hour, 5, 0)
    j = user_repo.add_journal({"symbol": "X", "side": "buy", "trade_date": "2020-01-01", "quantity": 1, "price": 1,
                               "fees": 0, "notes": None, "thesis": None, "tags": None, "broker_order_id": None,
                               "origin": "manual"})
    removed = market_repo.prune_before(now - 4 * hour)
    assert removed["trades"] == 5 and removed["market_sessions"] == 1
    left = market_repo.load_trades("X", 0, now)
    assert [t.trade_id for t in left] == ["t4", "t3", "t2", "t1", "t0"]
    sess = market_repo.list_sessions("X")
    assert len(sess) == 1 and sess[0]["first_ts"] == now - 4 * hour
    assert user_repo.list_journal()[0]["id"] == j["id"]  # user data untouched
    assert market_repo.prune_before(now - 4 * hour) == {}  # idempotent
