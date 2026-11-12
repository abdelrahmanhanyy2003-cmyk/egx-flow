"""Read-only facade over ``younit.Client``.

The SDK exposes order placement (``buy``, ``sell``, ``place_order``,
``amend_order``, ``cancel_order`` and fund equivalents). EGX Flow is READ-ONLY,
so the SDK client is wrapped and only an explicit whitelist of read methods is
reachable. Attribute access to anything else raises ``PermissionError``.

All calls are synchronous in the SDK; :meth:`call` runs them through the local
rate limiter with 429 back-off. Callers execute it in a worker thread.
"""

from __future__ import annotations

from typing import Any

from app.core.security import FORBIDDEN_TRADING_METHODS
from app.integrations.efg_hermes.rate_limit import TokenBucket, call_with_backoff

READ_METHODS = frozenset(
    {
        "account_info",
        "portfolio",
        "positions",
        "position",
        "positions_split",
        "fund_positions",
        "quote",
        "stock_info",
        "list_stocks",
        "search_stocks",
        "historical_prices",
        "market_status",
        "top_gainers",
        "top_losers",
        "trending_stocks",
        "list_orders",
        "order_history",
        "fund_order_history",
        "refresh_symbols",
        "close",
    }
)
STREAM_METHODS = frozenset(
    {
        "connect",
        "disconnect",
        "is_connected",
        "subscribe_quote",
        "subscribe_index",
        "subscribe_market",
        "subscribe_trades",
        "subscribe_orders",
        "unsubscribe",
    }
)
assert not (READ_METHODS & FORBIDDEN_TRADING_METHODS)


class ReadOnlyStreaming:
    def __init__(self, streaming: Any) -> None:
        object.__setattr__(self, "_s", streaming)

    def __getattr__(self, name: str) -> Any:
        if name not in STREAM_METHODS:
            raise PermissionError(f"streaming method '{name}' is not exposed (read-only)")
        return getattr(object.__getattribute__(self, "_s"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise PermissionError("read-only wrapper")


class ReadOnlyYounitClient:
    def __init__(self, sdk_client: Any, max_requests_per_minute: int = 60) -> None:
        object.__setattr__(self, "_c", sdk_client)
        object.__setattr__(self, "_bucket", TokenBucket(max_requests_per_minute))
        object.__setattr__(self, "rate_limited_count", 0)
        object.__setattr__(self, "streaming", ReadOnlyStreaming(sdk_client.streaming))

    def __getattr__(self, name: str) -> Any:
        if name in FORBIDDEN_TRADING_METHODS or name not in READ_METHODS:
            raise PermissionError(f"'{name}' is not available: EGX Flow is read-only")
        return getattr(object.__getattribute__(self, "_c"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "rate_limited_count":
            object.__setattr__(self, name, value)
            return
        raise PermissionError("read-only wrapper")

    @property
    def profile_id(self) -> int | None:
        return object.__getattribute__(self, "_c").profile_id

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        fn = self.__getattr__(method)

        def _inc() -> None:
            object.__setattr__(self, "rate_limited_count", self.rate_limited_count + 1)

        return call_with_backoff(
            lambda: fn(*args, **kwargs), object.__getattribute__(self, "_bucket"), on_rate_limited=_inc
        )
