"""Composition root: builds providers/services according to DATA_MODE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.alerts.engine import AlertEngine
from app.core.config import Settings
from app.database.repositories import user_repo
from app.integrations.efg_hermes.authentication import (
    credentials_configured,
    sdk_available,
    sdk_version,
    streaming_lib_available,
)
from app.providers.base import MarketDataProvider, PortfolioProvider
from app.replay.recorder import Recorder
from app.services.market_service import MarketHub
from app.services.portfolio_service import PortfolioService
from app.services.replay_service import ReplayService
from app.services.websocket_manager import WebSocketManager


@dataclass
class Container:
    settings: Settings
    ws: WebSocketManager
    hub: MarketHub
    portfolio: PortfolioService
    replay: ReplayService
    alerts: AlertEngine
    market_provider: MarketDataProvider
    portfolio_provider: PortfolioProvider
    efg_session: Any = None

    def integration_status(self) -> dict[str, Any]:
        s = self.settings
        return {
            "data_mode": s.data_mode,
            "sdk_installed": sdk_available(),
            "sdk_version": sdk_version(),
            "lightstreamer_installed": streaming_lib_available(),
            "credentials_configured": credentials_configured(s),
            "read_only": True,
            "provider": self.market_provider.status().to_dict(),
            "capabilities": self.market_provider.capabilities.to_dict(),
            "portfolio_error": getattr(self.portfolio_provider, "last_error", None),
            "init_error": getattr(self.efg_session, "error", None) if self.efg_session else None,
        }


def build(settings: Settings) -> Container:
    ws = WebSocketManager()
    alerts = AlertEngine(persist=user_repo.insert_alert)
    recorder = Recorder(settings.record_market_data, int(settings.book_snapshot_record_interval_s * 1000))
    efg_session = None
    if settings.data_mode == "live":
        from app.integrations.efg_hermes.market_data import EFGHermesMarketDataProvider, EFGHermesSession
        from app.integrations.efg_hermes.portfolio import EFGHermesPortfolioProvider

        efg_session = EFGHermesSession(settings)
        mprov: MarketDataProvider = EFGHermesMarketDataProvider(settings, efg_session)
        hub = MarketHub(settings, mprov, ws, alerts, recorder)
        pprov: PortfolioProvider = EFGHermesPortfolioProvider(efg_session, mprov)  # type: ignore[arg-type]
        poll = settings.efg_portfolio_poll_s
    else:
        from app.providers.demo.provider import DemoMarketDataProvider, DemoPortfolioProvider

        mprov = DemoMarketDataProvider(settings.demo_seed, settings.demo_prewarm_minutes)
        hub = MarketHub(settings, mprov, ws, alerts, recorder)
        pprov = DemoPortfolioProvider(
            lambda s: hub.states[s].last_price if s in hub.states else None,
            lambda s: hub.instruments[s].name if s in hub.instruments else None,
        )
        poll = 5.0
    portfolio = PortfolioService(pprov, hub, ws, alerts, poll)
    replay = ReplayService(hub, ws)
    return Container(settings, ws, hub, portfolio, replay, alerts, mprov, pprov, efg_session)
