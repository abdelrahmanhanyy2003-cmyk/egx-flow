"""MarketHub - the runtime core of the modular monolith.

Pipeline::

    provider thread(s) --put--> EventBuffer --drain--> EventValidator
        --> SymbolState (book / trades / analytics) --> Recorder (DB)
        --> AlertEngine --> WebSocketManager (batched every BROADCAST_INTERVAL_MS)

All SymbolState mutation happens on the asyncio loop thread; API handlers are
``async`` so they read state on the same thread without locks.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.alerts.engine import AlertEngine
from app.analytics.indicators import breadth
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.timeutil import cairo_iso, now_ms
from app.database.models import IndicatorValueRow
from app.database.repositories import market_repo, user_repo
from app.domain.models import (
    BookDelta,
    BookSnapshot,
    DataQuality,
    IndexValue,
    Instrument,
    MarketEvent,
    MarketStats,
    ProviderStatusEvent,
    Quote,
    Trade,
)
from app.market_data.event_processor import EventBuffer, EventValidator
from app.market_data.session_manager import SessionManager
from app.market_data.symbol_state import SymbolState
from app.providers.base import MarketDataProvider
from app.replay.recorder import Recorder
from app.services.cache import StateCache
from app.services.websocket_manager import WebSocketManager

log = get_logger(__name__)


class MarketHub:
    def __init__(self, settings: Settings, provider: MarketDataProvider, ws: WebSocketManager,
                 alerts: AlertEngine, recorder: Recorder) -> None:
        self.settings = settings
        self.provider = provider
        self.ws = ws
        self.alerts = alerts
        self.recorder = recorder
        self.buffer = EventBuffer(settings.event_queue_size)
        self.validator = EventValidator()
        self.sessions = SessionManager(settings.session_open, settings.session_close, settings.trading_weekdays)
        self.instruments: dict[str, Instrument] = {}
        self.states: dict[str, SymbolState] = {}
        self.market: MarketStats | None = None
        self.index: IndexValue | None = None
        self.provider_events: list[dict[str, Any]] = []
        self.quality = provider.capabilities.quality
        self.alerts.quality = self.quality.value
        self._tasks: list[asyncio.Task[None]] = []
        self.started_ms = now_ms()
        self.loop_lag_ms = 0.0
        self.events_processed = 0
        self.ready = False
        self.cache = StateCache(settings.redis_url)
        ws.snapshot_provider = self.snapshot_for_topic

    # ---------------------------------------------------------------- setup
    def _new_state(self, inst: Instrument, adv: float | None = None) -> SymbolState:
        st = SymbolState(
            inst,
            heatmap_columns=self.settings.heatmap_history_columns,
            depth_levels=self.settings.heatmap_depth_levels,
            trade_limit=self.settings.trade_history_limit,
            quality=self.quality,
            adv=adv,
        )
        self.states[inst.symbol] = st
        return st

    async def start(self) -> None:
        insts = await self.provider.list_instruments()
        self.instruments = {i.symbol: i for i in insts}
        await asyncio.to_thread(market_repo.upsert_instruments, [
            {"symbol": i.symbol, "name": i.name, "exchange": i.exchange, "currency": i.currency,
             "sector": i.sector, "tick_size": i.tick_size, "tick_size_source": i.tick_size_source,
             "trading_status": i.trading_status, "provider_id": i.provider_id, "source": self.provider.name,
             "updated_ms": now_ms()} for i in insts
        ])
        demo = self.quality == DataQuality.SIMULATED
        targets = list(self.instruments) if demo else [s for s in self.settings.watch_symbols if s in self.instruments]
        for sym in targets:
            adv = getattr(self.provider, "adv", lambda _s: None)(sym)
            self._new_state(self.instruments[sym], adv)

        loop = asyncio.get_running_loop()
        self.buffer.bind_loop(loop)
        if hasattr(self.provider, "prewarm") and self.settings.demo_prewarm_minutes > 0:
            await asyncio.to_thread(self.provider.prewarm, self._dispatch_prewarm, self._sample_all)  # type: ignore[attr-defined]
            for st in self.states.values():
                st.analytics_tick(st.last_event_ms or now_ms())
                st.discard_updates()
                st.pop_alert_events()
            await self.recorder.flush()
        await self.provider.start(self.buffer.put)
        # provider may downgrade quality after checking entitlements (e.g. delayed feed)
        self.quality = self.provider.capabilities.quality
        self.alerts.quality = self.quality.value
        for st in self.states.values():
            st.quality = self.quality
        await self.provider.subscribe(targets)
        if not demo:
            self._tasks.append(asyncio.create_task(self._load_adv(targets)))
        for coro in (self._consume(), self._sampler(), self._broadcaster(), self._analytics(),
                     self._flusher(), self._market_broadcast(), self._lag_probe(), self._retention()):
            self._tasks.append(asyncio.create_task(coro))
        self.ready = True

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self.provider.stop()
        await self.recorder.flush()
        await self.cache.close()

    async def _load_adv(self, symbols: list[str]) -> None:
        """ADV from provider daily candles (live mode)."""
        for s in symbols:
            try:
                candles = await self.provider.historical_candles(s, "Month")
                vols = [c.volume for c in candles[-20:] if c.volume]
                if vols and s in self.states:
                    self.states[s].adv = sum(vols) / len(vols)
                    self.states[s].llt.adv = self.states[s].adv
            except Exception as exc:  # noqa: BLE001
                log.warning("adv_load_failed", symbol=s, error=type(exc).__name__)

    async def ensure_symbol(self, symbol: str) -> SymbolState | None:
        st = self.states.get(symbol)
        if st is not None:
            return st
        inst = self.instruments.get(symbol)
        if inst is None:
            return None
        st = self._new_state(inst)
        await self.provider.subscribe([symbol])
        self._tasks.append(asyncio.create_task(self._load_adv([symbol])))
        return st

    # ----------------------------------------------------------- dispatch
    def _dispatch_prewarm(self, ev: MarketEvent) -> None:
        if self.validator.accept(ev):
            self._dispatch(ev)

    def _sample_all(self, ts: int) -> None:
        for st in self.states.values():
            st.sample(ts)
            self.recorder.maybe_record_book(st.book, ts, self.provider.name, self.quality.value)
            if ts % 5000 < 1000:
                st.analytics_tick(ts)
                for ev in st.pop_alert_events():
                    self.recorder.record_event(ev, self.provider.name)

    def _dispatch(self, ev: MarketEvent) -> None:
        self.events_processed += 1
        if isinstance(ev, Trade):
            st = self.states.get(ev.symbol)
            if st is not None:
                st.on_trade(ev)
                self.recorder.record_trade(ev)
        elif isinstance(ev, BookDelta):
            st = self.states.get(ev.symbol)
            if st is not None:
                st.on_book_delta(ev)
        elif isinstance(ev, Quote):
            st = self.states.get(ev.symbol)
            if st is not None:
                st.on_quote(ev)
                self.recorder.record_quote(ev)
        elif isinstance(ev, BookSnapshot):
            st = self.states.get(ev.symbol)
            if st is not None:
                st.on_book_snapshot(ev)
        elif isinstance(ev, MarketStats):
            self.market = ev
            if ev.status and ev.quality != DataQuality.SIMULATED:
                self.sessions.provider_status = str(ev.status)
        elif isinstance(ev, IndexValue):
            self.index = ev
        elif isinstance(ev, ProviderStatusEvent):
            self.provider_events.append({"provider": ev.provider, "state": ev.state, "detail": ev.detail, "ts": ev.ts})
            self.provider_events = self.provider_events[-100:]
            self.ws.broadcast({"type": "status", "data": self.status()})

    # -------------------------------------------------------------- loops
    async def _consume(self) -> None:
        while True:
            await self.buffer.wait(0.2)
            try:
                for ev in self.buffer.drain():
                    if self.validator.accept(ev):
                        self._dispatch(ev)
            except Exception as exc:  # noqa: BLE001
                log.error("dispatch_error", error=repr(exc)[:300])

    async def _sampler(self) -> None:
        res = self.settings.heatmap_resolution_ms / 1000
        while True:
            await asyncio.sleep(res - (time.time() % res))
            ts = now_ms()
            ts -= ts % self.settings.heatmap_resolution_ms
            for st in self.states.values():
                try:
                    st.sample(ts)
                    self.recorder.maybe_record_book(st.book, ts, self.provider.name, self.quality.value)
                except Exception as exc:  # noqa: BLE001
                    log.error("sample_error", symbol=st.symbol, error=repr(exc)[:300])

    async def _broadcaster(self) -> None:
        interval = self.settings.broadcast_interval_ms / 1000
        n = 0
        while True:
            await asyncio.sleep(interval)
            n += 1
            active = self.ws.active_topics()
            for sym, st in self.states.items():
                topic = f"symbol:{sym}"
                if topic in active:
                    upd = st.drain_updates(include_profile=(n % 4 == 0))
                    if upd:
                        self.ws.publish(topic, {"type": "update", "data": upd})
                else:
                    st.discard_updates()

    async def _analytics(self) -> None:
        while True:
            await asyncio.sleep(2.0)
            ts = now_ms()
            alerts: list[dict[str, Any]] = []
            for st in self.states.values():
                try:
                    st.analytics_tick(ts)
                    for ev in st.pop_alert_events():
                        self.recorder.record_event(ev, self.provider.name)
                        alerts.extend(await asyncio.to_thread(self.alerts.on_event, ev))
                    alerts.extend(await asyncio.to_thread(self.alerts.on_stats, st.symbol, st.stats(), ts))
                except Exception as exc:  # noqa: BLE001
                    log.error("analytics_error", symbol=st.symbol, error=repr(exc)[:300])
            for a in alerts:
                self.ws.broadcast({"type": "alert", "data": a})
            if "whales" in self.ws.active_topics():
                self.ws.publish("whales", {"type": "whales", "data": self.whale_dashboard()})

    async def _flusher(self) -> None:
        n = 0
        while True:
            await asyncio.sleep(2.0)
            n += 1
            await self.recorder.flush()
            if n % 30 == 0:  # every minute: persist session volume profiles & whale scores
                await self._persist_profiles()

    async def _persist_profiles(self) -> None:
        ts = now_ms()
        rows: list[dict[str, Any]] = []
        for st in self.states.values():
            if st.profile.total and st.session_key:
                prof = st.profile.to_dict()
                await asyncio.to_thread(market_repo.save_volume_profile, st.symbol, str(st.session_key), prof,
                                        self.provider.name, ts)
            if st.whale:
                rows.append({"symbol": st.symbol, "ts": ts, "name": "whale_score", "value": st.whale["score"],
                             "payload": st.whale, "source": self.provider.name})
            if st.vwap.value is not None:
                rows.append({"symbol": st.symbol, "ts": ts, "name": "vwap", "value": st.vwap.value,
                             "payload": None, "source": self.provider.name})
        if rows:
            await asyncio.to_thread(market_repo.bulk_insert_ignore, IndicatorValueRow, rows)

    async def _market_broadcast(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            need_ws = "market" in self.ws.active_topics()
            if not (need_ws or self.cache.enabled):
                continue
            ov = self.overview()
            if need_ws:
                self.ws.publish("market", {"type": "market", "data": ov})
            if self.cache.enabled:
                await self.cache.publish("market:overview", ov)
                for sym, st in self.states.items():
                    await self.cache.publish(f"symbol:{sym}:stats", st.stats())

    async def _retention(self) -> None:
        """Hourly housekeeping: drop recorded data older than RECORD_RETENTION_DAYS."""
        days = self.settings.record_retention_days
        if days <= 0:
            return
        await asyncio.sleep(30.0)
        while True:
            try:
                cutoff = now_ms() - int(days * 86_400_000)
                removed = await asyncio.to_thread(market_repo.prune_before, cutoff)
                if removed:
                    log.info("retention_pruned", **removed)
            except Exception as exc:  # noqa: BLE001
                log.warning("retention_failed", error=repr(exc)[:200])
            await asyncio.sleep(3600.0)

    async def _lag_probe(self) -> None:
        while True:
            t0 = time.perf_counter()
            await asyncio.sleep(0.5)
            self.loop_lag_ms = max(0.0, (time.perf_counter() - t0 - 0.5) * 1000)

    # ------------------------------------------------------------- views
    def snapshot_for_topic(self, topic: str) -> dict[str, Any] | None:
        if topic.startswith("symbol:"):
            st = self.states.get(topic.split(":", 1)[1])
            return st.snapshot() if st else None
        if topic == "market":
            return self.overview()
        if topic == "whales":
            return self.whale_dashboard()
        return None

    def liquidity_score(self, st: SymbolState) -> float | None:
        """Local heuristic 0-100 combining near-touch depth value and spread tightness."""
        if not st.book.bids or not st.book.asks or st.book.mid is None:
            return None
        bids, asks = st.book.top(5)
        depth_val = sum(p * q for p, q in bids) + sum(p * q for p, q in asks)
        spread_bps = (st.book.spread or 0) / st.book.mid * 10_000
        return round(50 * min(1.0, depth_val / 5_000_000) + 50 * (1 - min(1.0, spread_bps / 100)), 1)

    def explorer(self) -> list[dict[str, Any]]:
        out = []
        for sym, inst in self.instruments.items():
            st = self.states.get(sym)
            row: dict[str, Any] = {"symbol": sym, "name": inst.name, "sector": inst.sector, "streaming": st is not None}
            if st is not None:
                s = st.stats()
                row.update(
                    last=s["last"], change_pct=s["change_pct"], volume=s["volume"], value=s["value"],
                    rvol=s["rvol"], spread=s["spread"],
                    spread_bps=(s["spread"] / st.book.mid * 10_000) if s["spread"] and st.book.mid else None,
                    liquidity_score=self.liquidity_score(st), whale_score=s["whale_score"], flow=s["flow"],
                    trades=s["trades"], quality=s["quality"], book_resolution=s["book_resolution"],
                    last_event_ms=s["last_event_ms"],
                )
            out.append(row)
        return out

    def overview(self) -> dict[str, Any]:
        ts = now_ms()
        sess = self.sessions.session_for(ts)
        m = self.market
        movers = [r for r in self.explorer() if r.get("change_pct") is not None]
        movers.sort(key=lambda r: r["change_pct"])
        active = sorted([r for r in movers if r.get("value")], key=lambda r: -r["value"])
        demo = self.quality == DataQuality.SIMULATED
        return {
            "ts": ts,
            "cairo_time": cairo_iso(ts),
            "quality": self.quality.value,
            "session": sess.to_dict() | ({"state": "open", "source": "demo"} if demo else {}),
            "market": None if m is None else {
                "status": m.status, "traded_value": m.traded_value, "traded_volume": m.traded_volume,
                "trades_count": m.trades_count, "advances": m.advances, "declines": m.declines,
                "unchanged": m.unchanged, "ts": m.ts, "quality": m.quality.value,
                "breadth": breadth(m.advances or 0, m.declines or 0, m.unchanged or 0),
            },
            "index": None if self.index is None else {
                "name": self.index.name, "value": self.index.value, "change_pct": self.index.change_pct,
                "net_change": self.index.net_change, "ts": self.index.ts, "quality": self.index.quality.value,
            },
            "gainers": movers[::-1][:5],
            "losers": movers[:5],
            "most_active": active[:8],
            "provider": self.provider.status().to_dict(),
        }

    def whale_dashboard(self) -> dict[str, Any]:
        ts = now_ms()
        hour = ts - 3_600_000
        large: list[dict[str, Any]] = []
        walls: list[dict[str, Any]] = []
        new_walls: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        icebergs: list[dict[str, Any]] = []
        absorptions: list[dict[str, Any]] = []
        ranking: list[dict[str, Any]] = []
        activity: list[dict[str, Any]] = []
        acc: list[dict[str, Any]] = []
        dist: list[dict[str, Any]] = []
        for sym, st in self.states.items():
            lts = [x.to_dict() for x in st.large_trades]
            large.extend(lts)
            recent = [x for x in lts if x["ts"] >= hour]
            if recent:
                activity.append({
                    "symbol": sym, "count": len(recent),
                    "value": sum(x["value"] for x in recent),
                    "buy_value": sum(x["value"] for x in recent if x["side"] == "buy"),
                    "sell_value": sum(x["value"] for x in recent if x["side"] == "sell"),
                })
            for w in st.walls.active():
                walls.append(w)
            for e in list(st.wall_events)[-30:]:
                d = e.to_dict()
                (new_walls if e.kind == "new" else removed if e.kind in ("pulled", "consumed") else []).append(d)
            icebergs.extend(s.to_dict() for s in st.iceberg_signals)
            absorptions.extend(a.to_dict() for a in list(st.absorptions)[-10:])
            if st.whale:
                ranking.append({"symbol": sym, "name": st.instrument.name, "score": st.whale["score"],
                                "band": st.whale["band"], "factors": st.whale["factors"],
                                "flow": st.flow.kind if st.flow else None,
                                "last": st.last_price, "change_pct": st.stats()["change_pct"]})
            if st.flow and st.flow.kind == "accumulation":
                acc.append({"symbol": sym, **st.flow.to_dict()})
            elif st.flow and st.flow.kind == "distribution":
                dist.append({"symbol": sym, **st.flow.to_dict()})
        buys = sorted([x for x in large if x["side"] == "buy"], key=lambda x: -x["value"])[:25]
        sells = sorted([x for x in large if x["side"] == "sell"], key=lambda x: -x["value"])[:25]
        walls.sort(key=lambda w: -w["value"])
        new_walls.sort(key=lambda e: -e["ts"])
        removed.sort(key=lambda e: -e["ts"])
        ranking.sort(key=lambda r: -r["score"])
        activity.sort(key=lambda a: -a["value"])
        return {
            "ts": ts, "quality": self.quality.value,
            "feed": sorted(large, key=lambda x: -x["ts"])[:150],
            "most_active": activity, "largest_buys": buys, "largest_sells": sells,
            "largest_resting": walls[:30], "new_walls": new_walls[:40], "removed_walls": removed[:40],
            "icebergs": sorted(icebergs, key=lambda s: -s["confidence"])[:40],
            "absorptions": sorted(absorptions, key=lambda a: -a["ts"])[:40],
            "accumulation": sorted(acc, key=lambda a: -a["confidence"]),
            "distribution": sorted(dist, key=lambda a: -a["confidence"]),
            "ranking": ranking,
            "disclaimer": ("Signals are derived from observable public order flow. They do not identify "
                           "participants and are not proof of institutional activity."),
        }

    def status(self) -> dict[str, Any]:
        ps = self.provider.status().to_dict()
        now = now_ms()
        stale = []
        for sym, st in self.states.items():
            if st.last_event_ms and now - st.last_event_ms > self.settings.stale_after_seconds * 1000:
                stale.append(sym)
        return {
            "ready": self.ready,
            "mode": self.settings.data_mode,
            "quality": self.quality.value,
            "provider": ps,
            "capabilities": self.provider.capabilities.to_dict(),
            "buffer": {"depth": self.buffer.depth(), **self.buffer.metrics.__dict__,
                       "gap_symbols": sorted(self.buffer.gap_symbols)},
            "integrity": self.validator.report(),
            "stale_symbols": stale,
            "events_processed": self.events_processed,
            "loop_lag_ms": round(self.loop_lag_ms, 2),
            "symbols": len(self.states),
            "ws_clients": len(self.ws.clients),
            "uptime_s": int((now - self.started_ms) / 1000),
            "recorder": dict(self.recorder.written),
            "provider_events": self.provider_events[-20:],
            "session": self.sessions.session_for(now).to_dict(),
            "cairo_time": cairo_iso(now),
        }


async def load_alert_rules(alerts: AlertEngine) -> None:
    alerts.load_rules(await asyncio.to_thread(user_repo.list_rules))
