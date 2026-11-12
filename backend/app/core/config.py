"""Application configuration.

All settings come from environment variables / a local ``.env`` file.
Secrets are held as ``SecretStr`` so they never appear in ``repr`` or logs.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Broker credentials (EFG Hermes Younit). Read server-side only. ---
    trading_id: SecretStr | None = Field(default=None, alias="TRADING_ID")
    api_key: SecretStr | None = Field(default=None, alias="API_KEY")

    # --- Infrastructure ---
    database_url: str = Field(default="", alias="DATABASE_URL")
    redis_url: str = Field(default="", alias="REDIS_URL")

    app_env: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    data_mode: Literal["demo", "live"] = Field(default="demo", alias="DATA_MODE")

    # Optional shared secret protecting the local API/WS. When set, clients must
    # send it as ``X-EGXFlow-Token`` header (or ``token`` query param for WS).
    app_access_token: SecretStr | None = Field(default=None, alias="APP_ACCESS_TOKEN")
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100",
        alias="CORS_ORIGINS",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Network hardening ---
    # Host header allow-list (protects a localhost app against DNS rebinding). "*" disables.
    allowed_hosts: str = Field(default="localhost,127.0.0.1", alias="ALLOWED_HOSTS")
    # Per-client-IP REST budget (token bucket). 0 disables.
    api_rate_limit_per_minute: int = Field(default=600, alias="API_RATE_LIMIT_PER_MINUTE")
    ws_max_clients: int = Field(default=64, alias="WS_MAX_CLIENTS")
    ws_max_per_ip: int = Field(default=12, alias="WS_MAX_PER_IP")
    ws_max_topics: int = Field(default=32, alias="WS_MAX_TOPICS")
    # Hosted showcase: simulated data only, every write endpoint disabled, API docs hidden.
    public_demo: bool = Field(default=False, alias="PUBLIC_DEMO")

    # --- Storage housekeeping ---
    # Recorded market data older than this is deleted (0 = keep forever).
    record_retention_days: float = Field(default=3.0, alias="RECORD_RETENTION_DAYS")
    # Longest stretch of a recorded session loaded into memory for one replay.
    replay_max_window_hours: float = Field(default=6.0, alias="REPLAY_MAX_WINDOW_HOURS")

    # --- Market conventions (configurable, never hardcoded in logic) ---
    timezone: str = Field(default="Africa/Cairo", alias="MARKET_TIMEZONE")
    currency: str = Field(default="EGP", alias="MARKET_CURRENCY")
    # Default EGX continuous session; overridden by live MarketStatistics status.
    session_open: str = Field(default="10:00", alias="EGX_SESSION_OPEN")
    session_close: str = Field(default="14:30", alias="EGX_SESSION_CLOSE")
    # Python weekday numbers (Mon=0 .. Sun=6). EGX trades Sunday-Thursday.
    trading_days: str = Field(default="6,0,1,2,3", alias="EGX_TRADING_DAYS")

    # --- Engine tuning ---
    heatmap_resolution_ms: int = Field(default=1000, alias="HEATMAP_RESOLUTION_MS")
    heatmap_history_columns: int = Field(default=3600, alias="HEATMAP_HISTORY_COLUMNS")
    heatmap_depth_levels: int = Field(default=60, alias="HEATMAP_DEPTH_LEVELS")
    trade_history_limit: int = Field(default=20000, alias="TRADE_HISTORY_LIMIT")
    broadcast_interval_ms: int = Field(default=250, alias="BROADCAST_INTERVAL_MS")
    event_queue_size: int = Field(default=50000, alias="EVENT_QUEUE_SIZE")
    stale_after_seconds: float = Field(default=30.0, alias="STALE_AFTER_SECONDS")
    record_market_data: bool = Field(default=True, alias="RECORD_MARKET_DATA")
    book_snapshot_record_interval_s: float = Field(default=1.0, alias="BOOK_SNAPSHOT_RECORD_S")

    # --- Demo simulator ---
    demo_prewarm_minutes: int = Field(default=20, alias="DEMO_PREWARM_MINUTES")
    demo_seed: int = Field(default=7, alias="DEMO_SEED")

    # --- EFG Hermes Younit integration ---
    efg_market_id: int = Field(default=1, alias="EFG_MARKET_ID")
    # SDK docstring example: ``index_id`` 1 = EGX30. Verify against your entitlement.
    efg_egx30_index_id: int = Field(default=1, alias="EFG_EGX30_INDEX_ID")
    efg_watch_symbols: str = Field(
        default="COMI,ETEL,FWRY,EGAL,HRHO,TMGH,SWDY,EAST,ABUK,ORAS", alias="EFG_WATCH_SYMBOLS"
    )
    # The SDK documents ``TradeUpdate.transaction_type`` only as "Buy/sell side
    # indicator"; whether it is the AGGRESSOR side is not documented. It is
    # ignored for classification unless you map its values explicitly, e.g.
    # ``EFG_TRANSACTION_TYPE_MAP=B:buy,S:sell``.
    efg_transaction_type_map: str = Field(default="", alias="EFG_TRANSACTION_TYPE_MAP")
    efg_portfolio_poll_s: float = Field(default=30.0, alias="EFG_PORTFOLIO_POLL_S")
    efg_max_requests_per_minute: int = Field(default=60, alias="EFG_MAX_REQUESTS_PER_MINUTE")

    @field_validator("data_mode", mode="before")
    @classmethod
    def _lower(cls, v: object) -> object:
        return v.lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _public_demo_is_demo_only(self) -> "Settings":
        # A public showcase must never be able to expose a real brokerage account.
        if self.public_demo and self.data_mode != "demo":
            raise ValueError("PUBLIC_DEMO=true requires DATA_MODE=demo (live account data is never served publicly)")
        return self

    @property
    def allowed_host_list(self) -> list[str]:
        hosts = [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]
        if self.app_env == "test":
            hosts.append("testserver")
        return hosts or ["localhost", "127.0.0.1"]

    # ----- derived helpers -----
    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        data_dir = BACKEND_DIR / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(data_dir / 'egxflow.db').as_posix()}"

    @property
    def has_broker_credentials(self) -> bool:
        return bool(
            self.trading_id
            and self.api_key
            and self.trading_id.get_secret_value()
            and self.api_key.get_secret_value()
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trading_weekdays(self) -> set[int]:
        return {int(x) for x in self.trading_days.split(",") if x.strip()}

    @property
    def watch_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.efg_watch_symbols.split(",") if s.strip()]

    @property
    def transaction_type_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in self.efg_transaction_type_map.split(","):
            if ":" in pair:
                k, v = pair.split(":", 1)
                v = v.strip().lower()
                if v in ("buy", "sell"):
                    out[k.strip().lower()] = v
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
