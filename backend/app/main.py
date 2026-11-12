"""EGX Flow backend entrypoint (FastAPI)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.routes import alerts, auth, market, orderbook, portfolio, positions, prefs, replay, stocks, trades, whales
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.security import RateLimiter, origin_allowed, require_access, ws_access_ok
from app.database.base import init_engine
from app.database.migrate import upgrade_head
from app.services.container import build
from app.services.market_service import load_alert_rules

log = get_logger("egxflow")
VERSION = "0.2.0"

# In PUBLIC_DEMO mode every write is refused except replay controls, which only
# touch short-lived in-memory playback state.
PUBLIC_DEMO_WRITE_PREFIXES = ("/api/replay/",)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    limiter = RateLimiter(settings.api_rate_limit_per_minute)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        init_engine(settings.resolved_database_url)
        await asyncio.to_thread(upgrade_head)
        c = build(settings)
        await load_alert_rules(c.alerts)
        log.info("starting", mode=settings.data_mode, provider=c.market_provider.name,
                 public_demo=settings.public_demo)
        await c.hub.start()
        await c.portfolio.start()
        c.replay.start()
        app.state.container = c
        log.info("ready", symbols=len(c.hub.states))
        try:
            yield
        finally:
            await c.replay.stop()
            await c.portfolio.stop()
            await c.hub.stop()

    docs = not settings.public_demo
    app = FastAPI(
        title="EGX Flow", version=VERSION, lifespan=lifespan,
        description="Read-only EGX order-flow & market-intelligence terminal API",
        docs_url="/docs" if docs else None, redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next: Any) -> Response:
        path = request.url.path
        if path != "/api/health":
            ip = request.client.host if request.client else "unknown"
            if not limiter.allow(ip):
                return JSONResponse({"detail": "Too many requests - slow down."}, status_code=429,
                                    headers={"Retry-After": "5"})
            if (settings.public_demo and request.method not in ("GET", "HEAD", "OPTIONS")
                    and not path.startswith(PUBLIC_DEMO_WRITE_PREFIXES)):
                return JSONResponse({"detail": "This is a read-only public demo."}, status_code=403)
        resp: Response = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Cross-Origin-Resource-Policy"] = "same-site"
        return resp

    # Added last = outermost: CORS wraps the guard so 403/429 replies stay readable by
    # the UI; the Host check wraps everything.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-EGXFlow-Token"],
    )
    if "*" not in settings.allowed_host_list:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

    for r in (auth, market, stocks, orderbook, trades, portfolio, positions, whales, alerts, replay, prefs):
        app.include_router(r.router, dependencies=[Depends(require_access)])

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        c = getattr(app.state, "container", None)
        return {"ok": c is not None and c.hub.ready, "mode": settings.data_mode,
                "public_demo": settings.public_demo, "version": VERSION}

    @app.get("/api/system/status", dependencies=[Depends(require_access)])
    async def system_status() -> dict[str, Any]:
        c = app.state.container
        from app.database.repositories import market_repo

        counts = await asyncio.to_thread(market_repo.table_counts)
        return c.hub.status() | {"integration": c.integration_status(), "db": counts,
                                 "public_demo": settings.public_demo,
                                 "portfolio": {"last_refresh": c.portfolio.last_refresh, "error": c.portfolio.error}}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        c = getattr(app.state, "container", None)
        ip = ws.client.host if ws.client else "unknown"
        # Rejecting before accept() fails the handshake (HTTP 403) - nothing is sent.
        if c is None or not origin_allowed(ws.headers.get("origin"), settings.cors_origin_list):
            await ws.close(code=4403)
            return
        if not await ws_access_ok(ws):
            await ws.close(code=4401)
            return
        if (len(c.ws.clients) >= settings.ws_max_clients
                or sum(1 for x in c.ws.clients if x.ip == ip) >= settings.ws_max_per_ip):
            await ws.close(code=4429)
            return
        client = await c.ws.connect(ws, ip)
        writer = asyncio.create_task(c.ws.writer(client))
        c.ws.send_to(client, {"type": "status", "data": c.hub.status()})
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > 4096:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                op, topic = msg.get("op"), str(msg.get("topic", ""))[:64]
                if op == "sub" and topic:
                    if topic.startswith("symbol:"):
                        sym = topic.split(":", 1)[1].upper()
                        if not sym.isalnum() or len(sym) > 16:
                            continue
                        topic = f"symbol:{sym}"
                    if topic not in client.topics and len(client.topics) >= settings.ws_max_topics:
                        continue
                    if topic.startswith("symbol:"):
                        await c.hub.ensure_symbol(topic.split(":", 1)[1])
                    client.topics.add(topic)
                    snap = c.ws.snapshot_provider(topic) if c.ws.snapshot_provider else None
                    if snap is not None:
                        c.ws.send_to(client, {"type": "snapshot", "topic": topic, "data": snap})
                elif op == "unsub" and topic:
                    client.topics.discard(topic)
                elif op == "ping":
                    c.ws.send_to(client, {"type": "pong", "ts": msg.get("ts")})
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            log.warning("ws_error", error=type(exc).__name__)
        finally:
            c.ws.disconnect(client)
            writer.cancel()

    return app


app = create_app()
