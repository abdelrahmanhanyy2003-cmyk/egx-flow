"""EFG Hermes Younit portfolio / positions / order-history adapters (read-only).

SDK methods used: ``portfolio()``, ``positions()``, ``list_orders()``,
``order_history()``. Only the authenticated account owner's data is fetched.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.domain.models import BrokerOrder, DataQuality, PortfolioPosition, PortfolioSummaryData
from app.integrations.efg_hermes import normalization as N
from app.integrations.efg_hermes.market_data import EFGHermesMarketDataProvider, EFGHermesSession
from app.providers.base import PortfolioProvider

log = get_logger(__name__)


class EFGHermesPortfolioProvider(PortfolioProvider):
    name = "efg_younit"
    quality = DataQuality.LIVE

    def __init__(self, session: EFGHermesSession, market: EFGHermesMarketDataProvider) -> None:
        self.session = session
        self.market = market
        self.last_error: str | None = None

    async def summary(self) -> PortfolioSummaryData | None:
        try:
            s = await self.session.call("portfolio", self.session.settings.efg_market_id)
            self.last_error = None
            return N.summary_to_summary(s)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"portfolio: {type(exc).__name__}"
            log.warning("efg_portfolio_failed", error=type(exc).__name__)
            return None

    async def positions(self) -> list[PortfolioPosition]:
        try:
            rows = await self.session.call("positions", self.session.settings.efg_market_id)
            self.last_error = None
            return [N.position_to_position(p) for p in rows if not getattr(p, "is_fund", False)]
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"positions: {type(exc).__name__}"
            log.warning("efg_positions_failed", error=type(exc).__name__)
            return []

    async def open_orders(self) -> list[BrokerOrder]:
        try:
            rows = await self.session.call("list_orders")
            return [N.raw_order_row_to_order(r, self.market.symbol_by_id) for r in rows]
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"list_orders: {type(exc).__name__}"
            return []

    async def order_history(self) -> list[BrokerOrder]:
        try:
            rows = await self.session.call("order_history")
            return [N.history_entry_to_order(h) for h in rows]
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"order_history: {type(exc).__name__}"
            return []
