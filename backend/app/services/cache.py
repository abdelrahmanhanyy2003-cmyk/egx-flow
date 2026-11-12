"""Optional Redis cache for transient streaming state.

When ``REDIS_URL`` is set, the hub publishes the latest market overview and
per-symbol stats as JSON keys with a short TTL (and on a pub/sub channel), so
out-of-process consumers (additional API workers, notebooks, future
microservices) can read live state without touching the engine. Without Redis
this is a no-op - the modular monolith keeps all state in-process.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


class StateCache:
    def __init__(self, url: str) -> None:
        self.client: Any = None
        self.enabled = False
        if not url:
            return
        try:
            import redis.asyncio as aioredis

            self.client = aioredis.from_url(url, decode_responses=True)
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            log.warning("redis_unavailable", error=type(exc).__name__)

    async def publish(self, key: str, value: dict[str, Any], ttl_s: int = 10) -> None:
        if not self.enabled:
            return
        try:
            payload = json.dumps(value, default=str, separators=(",", ":"))
            await self.client.set(f"egxflow:{key}", payload, ex=ttl_s)
            await self.client.publish(f"egxflow:{key}", payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("redis_publish_failed", error=type(exc).__name__)
            self.enabled = False  # degrade gracefully; never break the engine

    async def close(self) -> None:
        if self.client is not None:
            try:
                await self.client.aclose()
            except Exception:  # noqa: BLE001
                pass
