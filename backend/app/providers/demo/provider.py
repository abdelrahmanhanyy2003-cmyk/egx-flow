"""DEMO providers: simulated market data and a simulated portfolio.

Everything produced here is labelled ``SIMULATED`` / "DEMO" and must never be
presented as real market or account information.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from app.core.logging import get_logger
from app.core.timeutil import now_ms
from app.domain.models import (
    BookResolution,
    BrokerOrder,
    DataQuality,
    Instrument,
    MarketEvent,
    PortfolioPosition,
    PortfolioSummaryData,
)
from app.providers.base import (
    Candle,
    EventSink,
    MarketDataProvider,
    PortfolioProvider,
    ProviderCapabilities,
    ProviderStatus,
)
from app.providers.demo.simulator import MarketSim
from app.providers.demo.universe import DEMO_INDEX_BASE, DEMO_UNIVERSE

log = get_logger(__name__)
STEP_MS = 250


class DemoMarketDataProvider(MarketDataProvider):
    name = "demo"

    def __init__(self, seed: int = 7, prewarm_minutes: int = 20) -> None:
        self.sim = MarketSim(DEMO_UNIVERSE, seed, DEMO_INDEX_BASE)
        self.prewarm_minutes = prewarm_minutes
        self._status = ProviderStatus(name=self.name)
        self._task: asyncio.Task[None] | None = None
        self._sink: EventSink | None = None
        self._subs: set[str] = set()
        self._sim_clock = now_ms()
        self._snapshotted = False

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            level1_quotes=True,
            depth_levels=40,
            book_resolution=BookResolution.DEPTH_UPDATES,
            trades=True,
            trade_side="provided",
            historical_candles=True,
            historical_trades=False,
            historical_book=False,
            streaming=True,
            market_stats=True,
            index_values=True,
            portfolio=True,
            open_orders=True,
            order_history=True,
            investor_type_stats=False,
            quality=DataQuality.SIMULATED,
            notes=["DEMO: all data is simulated and is not real EGX market activity."],
        )

    def status(self) -> ProviderStatus:
        return self._status

    def prewarm(self, dispatch: Callable[[MarketEvent], None], on_tick: Callable[[int], None]) -> None:
        """Synchronously simulate history so charts are populated at startup."""
        start = now_ms() - self.prewarm_minutes * 60_000
        t = start
        t0 = time.perf_counter()
        next_sample = start
        for ev in self.sim.snapshots(start):
            dispatch(ev)
        self._snapshotted = True
        while t < now_ms() - STEP_MS:
            self.sim.step(t, STEP_MS / 1000, dispatch, with_quotes=False)
            if t >= next_sample:
                for ev in self.sim.market_events(t):
                    dispatch(ev)
                on_tick(t)
                next_sample += 1000
            t += STEP_MS
        self._sim_clock = t
        log.info("demo_prewarm_done", minutes=self.prewarm_minutes, seconds=round(time.perf_counter() - t0, 2))

    async def start(self, sink: EventSink) -> None:
        self._sink = sink
        self._status.state = "connected"
        self._status.connected_since_ms = now_ms()
        self._status.detail = "DEMO simulator running"
        if not self._snapshotted:
            for ev in self.sim.snapshots(now_ms()):
                sink(ev)
            self._snapshotted = True
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        assert self._sink is not None
        last_market = 0
        while True:
            t = now_ms()
            self.sim.step(t, STEP_MS / 1000, self._sink, with_quotes=True)
            if t - last_market >= 1000:
                for ev in self.sim.market_events(t):
                    self._sink(ev)
                last_market = t
            self._status.last_event_ms = t
            await asyncio.sleep(STEP_MS / 1000)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        self._status.state = "disconnected"

    async def list_instruments(self) -> list[Instrument]:
        return [
            Instrument(
                symbol=s, name=n, sector=sec, tick_size=tick, tick_size_source="demo-config",
                trading_status="DEMO", reference_price=px, provider_id=f"demo-{s}",
            )
            for s, n, sec, px, tick, _adv in DEMO_UNIVERSE
        ]

    def adv(self, symbol: str) -> float | None:
        for s, *_rest, adv in DEMO_UNIVERSE:
            if s == symbol:
                return adv
        return None

    async def subscribe(self, symbols: list[str]) -> None:
        self._subs.update(symbols)
        self._status.subscriptions = sorted(self._subs)

    async def unsubscribe(self, symbols: list[str]) -> None:
        self._subs.difference_update(symbols)
        self._status.subscriptions = sorted(self._subs)

    async def historical_candles(
        self, symbol: str, period: str = "Month", date_from: str | None = None, date_to: str | None = None
    ) -> list[Candle]:
        """Simulated daily candles ending at the simulator's reference price (DEMO)."""
        import random

        s = self.sim.syms.get(symbol)
        if s is None:
            return []
        n = {"Day": 1, "Week": 5, "Month": 22, "Year": 250}.get(period, 120)
        n = max(n, 120)
        rng = random.Random(hash(symbol) & 0xFFFF)
        px = s.prev_close
        out: list[Candle] = []
        day = 86_400_000
        end = now_ms() - now_ms() % day - day
        closes = [px]
        for _ in range(n - 1):
            closes.append(closes[-1] / (1 + rng.gauss(0.0004, 0.018)))
        closes.reverse()
        for i, c in enumerate(closes):
            o = c * (1 + rng.gauss(0, 0.006))
            h = max(o, c) * (1 + abs(rng.gauss(0, 0.008)))
            low = min(o, c) * (1 - abs(rng.gauss(0, 0.008)))
            v = s.adv * rng.lognormvariate(0, 0.35)
            out.append(Candle(end - (n - 1 - i) * day, round(o, 3), round(h, 3), round(low, 3), round(c, 3), round(v)))
        return out


# --------------------------------------------------------------------------
DEMO_POSITIONS = [
    # symbol, qty, avg cost, realized pnl
    ("COMI", 1_500, 76.40, 4_820.0),
    ("FWRY", 20_000, 7.21, -1_350.0),
    ("ETEL", 2_500, 38.90, 0.0),
    ("EGAL", 300, 141.00, 2_100.0),
    ("TMGH", 1_200, 64.30, 0.0),
]
DEMO_CASH = 85_000.0


class DemoPortfolioProvider(PortfolioProvider):
    name = "demo"
    quality = DataQuality.SIMULATED

    def __init__(self, price_lookup: Callable[[str], float | None], name_lookup: Callable[[str], str | None]) -> None:
        self._price = price_lookup
        self._name = name_lookup

    async def positions(self) -> list[PortfolioPosition]:
        out: list[PortfolioPosition] = []
        for sym, qty, avg, realized in DEMO_POSITIONS:
            px = self._price(sym)
            mv = qty * px if px is not None else None
            out.append(
                PortfolioPosition(
                    symbol=sym, quantity=qty, avg_price=avg, current_price=px, market_value=mv,
                    unrealized_pnl=(px - avg) * qty if px is not None else None,
                    realized_pnl=realized, allocation_pct=None, name=self._name(sym),
                    unrealized_pnl_pct=(px / avg - 1) * 100 if px is not None else None,
                    source="demo", quality=DataQuality.SIMULATED,
                    broker_fields=["quantity", "avg_price", "realized_pnl"],
                )
            )
        return out

    async def summary(self) -> PortfolioSummaryData | None:
        pos = await self.positions()
        stocks = sum(p.market_value or 0 for p in pos)
        unreal = sum(p.unrealized_pnl or 0 for p in pos)
        invested = sum(p.invested for p in pos)
        return PortfolioSummaryData(
            total_value=stocks + DEMO_CASH, cash=DEMO_CASH, stocks_value=stocks,
            realized_pnl=sum(p.realized_pnl or 0 for p in pos), unrealized_pnl=unreal,
            unrealized_pnl_pct=unreal / invested * 100 if invested else None, currency="EGP",
            ts=now_ms(), source="demo", quality=DataQuality.SIMULATED, broker_fields=["cash"],
        )

    async def open_orders(self) -> list[BrokerOrder]:
        return [
            BrokerOrder("DEMO-90017", "COMI", "Buy", 500, 0, 79.00, None, "Open (DEMO)", now_ms() - 3_600_000, source="demo"),
        ]

    async def order_history(self) -> list[BrokerOrder]:
        day = 86_400_000
        n = now_ms()
        return [
            BrokerOrder("DEMO-88101", "COMI", "Buy", 1_500, 1_500, 76.40, 76.40, "Filled (DEMO)", n - 30 * day, source="demo"),
            BrokerOrder("DEMO-88233", "FWRY", "Buy", 20_000, 20_000, 7.21, 7.21, "Filled (DEMO)", n - 21 * day, source="demo"),
            BrokerOrder("DEMO-88412", "ETEL", "Buy", 2_500, 2_500, 38.90, 38.90, "Filled (DEMO)", n - 14 * day, source="demo"),
            BrokerOrder("DEMO-88550", "EGAL", "Buy", 450, 450, 141.00, 141.00, "Filled (DEMO)", n - 10 * day, source="demo"),
            BrokerOrder("DEMO-88771", "EGAL", "Sell", 150, 150, 155.00, 155.00, "Filled (DEMO)", n - 4 * day, source="demo"),
            BrokerOrder("DEMO-88902", "TMGH", "Buy", 1_200, 1_200, 64.30, 64.30, "Filled (DEMO)", n - 2 * day, source="demo"),
        ]
