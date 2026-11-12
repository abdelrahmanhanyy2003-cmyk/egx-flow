"""Portfolio intelligence: broker data + local analytics, clearly separated."""

from __future__ import annotations

import asyncio
from typing import Any

from app.alerts.engine import AlertEngine
from app.core.logging import get_logger
from app.core.timeutil import now_ms
from app.database.repositories import user_repo
from app.domain.models import BrokerOrder, PortfolioPosition, PortfolioSummaryData
from app.portfolio import reconciliation, risk
from app.portfolio.pnl import Fill, fifo
from app.portfolio.positions import enrich_positions
from app.providers.base import PortfolioProvider
from app.services.market_service import MarketHub
from app.services.websocket_manager import WebSocketManager

log = get_logger(__name__)


class PortfolioService:
    def __init__(self, provider: PortfolioProvider, hub: MarketHub, ws: WebSocketManager, alerts: AlertEngine,
                 poll_s: float) -> None:
        self.provider = provider
        self.hub = hub
        self.ws = ws
        self.alerts = alerts
        self.poll_s = poll_s
        self.summary_data: PortfolioSummaryData | None = None
        self.positions_data: list[PortfolioPosition] = []
        self.last_refresh: int | None = None
        self.error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._last_snapshot = 0
        self.session_open_value: float | None = None

    async def start(self) -> None:
        await self.refresh()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.poll_s)
            try:
                await self.refresh()
            except Exception as exc:  # noqa: BLE001
                self.error = type(exc).__name__
                log.warning("portfolio_refresh_failed", error=type(exc).__name__)

    async def refresh(self) -> None:
        summ = await self.provider.summary()
        pos = await self.provider.positions()
        if summ is not None:
            self.summary_data = summ
        self.positions_data = pos
        self.last_refresh = now_ms()
        self.error = getattr(self.provider, "last_error", None)
        for sym in {p.symbol for p in pos}:
            await self.hub.ensure_symbol(sym)
        view = self.view()
        ts = now_ms()
        alerts = []
        for p in view["positions"]:
            alerts.extend(await asyncio.to_thread(self.alerts.on_position, p, ts))
        for a in alerts:
            self.ws.broadcast({"type": "alert", "data": a})
        if ts - self._last_snapshot >= 60_000 and view["summary"]:
            self._last_snapshot = ts
            await asyncio.to_thread(user_repo.save_portfolio_snapshot, view["summary"], view["positions"])
        if self.session_open_value is None and view["summary"]:
            self.session_open_value = view["summary"].get("total_value")

    # ----------------------------------------------------------------- views
    def live_prices(self) -> dict[str, float | None]:
        return {s: st.last_price for s, st in self.hub.states.items()}

    def view(self) -> dict[str, Any]:
        summ = self.summary_data.to_dict() if self.summary_data else None
        positions = enrich_positions(self.positions_data, self.live_prices(),
                                     summ.get("stocks_value") if summ else None)
        invested = sum(p["invested"] for p in positions)
        if summ is not None:
            local = []
            mv = sum(p["market_value"] or 0 for p in positions)
            summ["invested_capital"] = invested
            local.append("invested_capital")
            if summ.get("total_value") is not None and invested:
                summ["overall_return_pct"] = ((mv + sum(p["realized_pnl"] or 0 for p in positions)) / invested - 1) * 100
                local.append("overall_return_pct")
            # Daily P&L: change of position value vs prior close (local estimate from live data)
            daily = 0.0
            have = False
            for p in positions:
                st = self.hub.states.get(p["symbol"])
                if st and st.prev_close and st.last_price is not None:
                    daily += (st.last_price - st.prev_close) * p["quantity"]
                    have = True
            summ["daily_pnl"] = daily if have else None
            local.append("daily_pnl")
            summ["local_fields"] = local
        alloc = [{"symbol": p["symbol"], "value": p["market_value"], "weight_pct": p["allocation_pct"]} for p in positions]
        if summ and summ.get("cash") is not None:
            alloc.append({"symbol": "CASH", "value": summ["cash"], "weight_pct": None})
            tot = sum(a["value"] or 0 for a in alloc)
            for a in alloc:
                a["weight_pct"] = (a["value"] or 0) / tot * 100 if tot else None
        return {
            "summary": summ,
            "positions": positions,
            "allocation": alloc,
            "source": self.provider.name,
            "quality": self.provider.quality.value,
            "last_refresh": self.last_refresh,
            "error": self.error,
            "notes": [
                "Fields listed in broker_fields are reported by the broker; local_fields are calculated by EGX Flow.",
            ],
        }

    def risk_view(self) -> dict[str, Any]:
        v = self.view()
        sectors = {s: (i.sector if i else None) for s, i in ((p["symbol"], self.hub.instruments.get(p["symbol"])) for p in v["positions"])}
        hist = user_repo.portfolio_history(0, self.provider.name)
        equity = [(h["ts"], h["total_value"]) for h in hist if h["total_value"] is not None]
        if v["summary"] and v["summary"].get("total_value") is not None:
            equity.append((now_ms(), v["summary"]["total_value"]))
        largest = sorted(v["positions"], key=lambda p: -(p["market_value"] or 0))[:5]
        return {
            "concentration": risk.concentration(v["positions"]),
            "sectors": risk.sector_concentration(v["positions"], sectors),
            "largest_holdings": [{"symbol": p["symbol"], "market_value": p["market_value"],
                                  "weight_pct": p["allocation_pct"]} for p in largest],
            "drawdown": risk.drawdown(equity),
            "equity_curve": [[t, v_] for t, v_ in equity],
            "exposure_change": risk.exposure_change(hist, v["summary"].get("stocks_value") if v["summary"] else None),
            "label": "Locally calculated estimates from recorded portfolio snapshots.",
            "quality": v["quality"],
        }

    async def open_orders(self) -> list[dict[str, Any]]:
        return [o.to_dict() for o in await self.provider.open_orders()]

    async def order_history(self) -> list[BrokerOrder]:
        return await self.provider.order_history()

    async def reconciliation(self) -> dict[str, Any]:
        broker = await self.provider.order_history()
        journal = await asyncio.to_thread(user_repo.list_journal)
        return {"rows": reconciliation.reconcile(broker, journal),
                "importable": len(reconciliation.importable(broker, journal))}

    async def import_broker_fills(self) -> dict[str, Any]:
        broker = await self.provider.order_history()
        journal = await asyncio.to_thread(user_repo.list_journal)
        created = 0
        skipped = 0
        for row in reconciliation.importable(broker, journal):
            try:
                await asyncio.to_thread(user_repo.add_journal, row)
                created += 1
            except ValueError:
                skipped += 1  # already journaled (unique broker_order_id) - never double counted
        return {"created": created, "skipped": skipped}

    def journal_stats(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        fills = [Fill(e["symbol"], e["side"], e["quantity"], e["price"], e["fees"] or 0.0, e["trade_date"], e["id"])
                 for e in sorted(entries, key=lambda e: (e["trade_date"], e["id"]))]
        try:
            res = fifo(fills)
        except ValueError as exc:
            return {"error": str(exc)}
        prices = self.live_prices()
        out = []
        for sym, r in res.items():
            px = prices.get(sym)
            out.append({
                "symbol": sym, "open_qty": r.open_qty, "avg_cost": r.avg_cost, "realized_pnl": r.realized,
                "fees": r.fees, "unrealized_pnl": (px - r.avg_cost) * r.open_qty if px is not None and r.open_qty else None,
                "closed": [c.__dict__ for c in r.closed],
            })
        return {"symbols": out, "realized_total": sum(r.realized for r in res.values()),
                "fees_total": sum(r.fees for r in res.values()),
                "label": "FIFO from journal entries (fees capitalised on buys, deducted on sells). Local calculation."}
