"""Client-side rate limiting and retry for Younit REST calls.

The SDK already retries idempotent GETs on 5xx/connection errors and re-auths
once on 401. On top of that we (1) cap our own request rate with a token
bucket and (2) back off when the SDK raises ``RateLimited`` (HTTP 429).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class TokenBucket:
    def __init__(self, per_minute: int) -> None:
        self.capacity = max(1, per_minute)
        self.tokens = float(self.capacity)
        self.rate = self.capacity / 60.0
        self.updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
                wait = (1 - self.tokens) / self.rate
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 1.0))


def is_rate_limited(exc: BaseException) -> bool:
    return type(exc).__name__ == "RateLimited" or getattr(exc, "status_code", None) == 429


def call_with_backoff(
    fn: Callable[[], T],
    bucket: TokenBucket,
    *,
    retries: int = 3,
    base_delay: float = 2.0,
    on_rate_limited: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    attempt = 0
    while True:
        if not bucket.acquire():
            raise TimeoutError("local rate limiter: request budget exhausted")
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below unless 429
            if not is_rate_limited(exc) or attempt >= retries:
                raise
            if on_rate_limited:
                on_rate_limited()
            sleep(base_delay * (2**attempt))
            attempt += 1
