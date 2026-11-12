"""Authentication management for the Younit SDK.

We deliberately do NOT implement our own auth flow. The official SDK:

* exchanges ``TRADING_ID`` + ``API_KEY`` for a bearer token
  (``POST /api/public-keys/token``),
* refreshes it five minutes before expiry and re-authenticates once on 401,
* pushes refreshed tokens into the Lightstreamer connection.

This module only (a) checks whether the SDK is installed, (b) checks whether
credentials are configured server-side, and (c) constructs the SDK client with
credentials read from settings. Tokens are never read, stored or logged here.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from app.core.config import Settings


def sdk_available() -> bool:
    return importlib.util.find_spec("younit") is not None


def sdk_version() -> str | None:
    if not sdk_available():
        return None
    try:
        import younit

        return getattr(younit, "__version__", "unknown")
    except Exception:  # noqa: BLE001
        return None


def streaming_lib_available() -> bool:
    return importlib.util.find_spec("lightstreamer") is not None


def credentials_configured(settings: Settings) -> bool:
    return settings.has_broker_credentials


def create_sdk_client(settings: Settings) -> Any:
    """Construct ``younit.Client`` (authenticates immediately).

    Raises ``RuntimeError`` if the SDK is missing or credentials are absent.
    SDK exceptions (``InvalidCredentials``, ``AuthError``, ``ConfigError``)
    propagate to the caller, which reports them without echoing secrets.
    """
    if not sdk_available():
        raise RuntimeError(
            "younit SDK not installed. See docs/EFG_API_CAPABILITIES.md#installation"
        )
    if not credentials_configured(settings):
        raise RuntimeError("TRADING_ID / API_KEY are not configured in the backend .env")
    from younit import Client  # type: ignore[import-not-found]

    assert settings.trading_id is not None and settings.api_key is not None
    return Client(
        trading_id=settings.trading_id.get_secret_value(),
        api_key=settings.api_key.get_secret_value(),
        lazy_auth=False,
        lazy_symbols=False,
    )
