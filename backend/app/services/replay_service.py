"""Replay controller: loads recorded sessions and streams playback over WS."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.database.repositories import market_repo
from app.domain.models import Instrument
from app.replay.playback import ReplaySession, build_events
from app.services.market_service import MarketHub
from app.services.websocket_manager import WebSocketManager


class ReplayService:
    def __init__(self, hub: MarketHub, ws: WebSocketManager) -> None:
        self.hub = hub
        self.ws = ws
        self.sessions: dict[str, ReplaySession] = {}
        self._task: asyncio.Task[None] | None = None
        prev = ws.snapshot_provider

        def provider(topic: str) -> dict[str, Any] | None:
            if topic.startswith("replay:"):
                r = self.sessions.get(topic.split(":", 1)[1])
                return self.snapshot(r) if r else None
            return prev(topic) if prev else None

        ws.snapshot_provider = provider

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def open(self, session_id: int, t0: int | None = None, t1: int | None = None) -> ReplaySession:
        sess = await asyncio.to_thread(market_repo.get_session, session_id)
        if sess is None:
            raise KeyError("session not found")
        a = t0 if t0 is not None else sess["first_ts"]
        b = t1 if t1 is not None else sess["last_ts"]
        # Bound memory: load at most the most recent REPLAY_MAX_WINDOW_HOURS of the range.
        max_ms = int(self.hub.settings.replay_max_window_hours * 3_600_000)
        if max_ms > 0 and b - a > max_ms:
            a = b - max_ms
            sess = sess | {"window_clamped_hours": self.hub.settings.replay_max_window_hours}
        trades = await asyncio.to_thread(market_repo.load_trades, sess["symbol"], a, b, sess["source"])
        books = await asyncio.to_thread(market_repo.load_book_snapshots, sess["symbol"], a, b, sess["source"])
        inst = self.hub.instruments.get(sess["symbol"]) or Instrument(sess["symbol"], sess["symbol"])
        r = ReplaySession(sess, inst, build_events(trades, books))
        # keep at most a few concurrent replays in memory
        if len(self.sessions) >= 4:
            oldest = next(iter(self.sessions))
            del self.sessions[oldest]
        self.sessions[r.id] = r
        return r

    def snapshot(self, r: ReplaySession) -> dict[str, Any]:
        assert r.state is not None
        snap = r.state.snapshot(columns=20000, trades=20000)
        snap["replay"] = r.info()
        return snap

    def control(self, rid: str, action: str, value: float | None = None) -> ReplaySession:
        r = self.sessions[rid]
        if action == "play":
            r.playing = True
        elif action == "pause":
            r.playing = False
        elif action == "speed" and value:
            r.speed = max(0.1, min(600.0, float(value)))
        elif action == "seek" and value is not None:
            r.seek(int(value))
            self.ws.publish(f"replay:{rid}", {"type": "snapshot", "data": self.snapshot(r)})
        elif action == "restart":
            r.reset()
            self.ws.publish(f"replay:{rid}", {"type": "snapshot", "data": self.snapshot(r)})
        return r

    async def _loop(self) -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.1)
            now = time.perf_counter()
            dt = (now - last) * 1000
            last = now
            for rid, r in list(self.sessions.items()):
                if not r.playing:
                    continue
                r.advance(dt)
                assert r.state is not None
                upd = r.state.drain_updates(include_profile=True)
                msg: dict[str, Any] = {"type": "update", "data": upd or {"symbol": r.instrument.symbol}}
                msg["data"]["replay"] = r.info()
                self.ws.publish(f"replay:{rid}", msg)
