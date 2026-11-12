"""API protection and read-only guarantees."""

from __future__ import annotations

import hmac
import time

from fastapi import Header, HTTPException, Query, WebSocket, status

from app.core.config import get_settings


def _token_ok(candidate: str | None) -> bool:
    expected = get_settings().app_access_token
    if expected is None or not expected.get_secret_value():
        return True  # protection disabled (local development default)
    if not candidate:
        return False
    return hmac.compare_digest(candidate.encode(), expected.get_secret_value().encode())


async def require_access(
    x_egxflow_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    if not _token_ok(x_egxflow_token or token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid access token")


async def ws_access_ok(ws: WebSocket) -> bool:
    return _token_ok(ws.query_params.get("token") or ws.headers.get("x-egxflow-token"))


def origin_allowed(origin: str | None, allowed: list[str]) -> bool:
    """WebSockets are not covered by CORS, so the Origin header is checked by hand.

    Without this any website open in the user's browser could connect to the local
    WebSocket and read market/portfolio data (cross-site WebSocket hijacking).
    Non-browser clients send no Origin header and are allowed.
    """
    if not origin:
        return True
    return origin.rstrip("/") in {a.rstrip("/") for a in allowed}


class RateLimiter:
    """Per-key token bucket: ``per_minute`` requests, refilled continuously."""

    def __init__(self, per_minute: int, max_keys: int = 20_000) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.max_keys = max_keys
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        if self.capacity <= 0:
            return True
        now = time.monotonic() if now is None else now
        tokens, last = self._buckets.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        if len(self._buckets) > self.max_keys:  # forget the least recently seen half
            for k, _ in sorted(self._buckets.items(), key=lambda kv: kv[1][1])[: self.max_keys // 2]:
                del self._buckets[k]
        return True


# Methods on the Younit SDK client that place, modify or cancel orders. The
# integration layer exposes a whitelist of read methods only; this list exists so
# tests can prove none of these are reachable.
FORBIDDEN_TRADING_METHODS = frozenset(
    {
        "buy",
        "sell",
        "buy_market",
        "buy_limit",
        "sell_market",
        "sell_limit",
        "place_order",
        "cancel_order",
        "amend_order",
        "buy_fund",
        "sell_fund",
        "place_fund_order",
        "amend_fund_order",
        "cancel_fund_order",
    }
)
