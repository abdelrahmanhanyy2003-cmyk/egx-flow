"""WebSocket fan-out with per-client backpressure.

Each client has a bounded outbound queue. If a slow client's queue fills, its
pending incremental updates are dropped and it is flagged for resync: the next
cycle sends it a fresh full snapshot instead of an unbounded backlog.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(eq=False)
class Client:
    ws: WebSocket
    topics: set[str] = field(default_factory=set)
    queue: asyncio.Queue[str] = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    resync: set[str] = field(default_factory=set)
    dropped: int = 0
    ip: str = ""


class WebSocketManager:
    def __init__(self) -> None:
        self.clients: set[Client] = set()
        self.snapshot_provider: Callable[[str], dict[str, Any] | None] | None = None

    def topic_subscribers(self, topic: str) -> int:
        return sum(1 for c in self.clients if topic in c.topics)

    def active_topics(self) -> set[str]:
        out: set[str] = set()
        for c in self.clients:
            out |= c.topics
        return out

    async def connect(self, ws: WebSocket, ip: str = "") -> Client:
        await ws.accept()
        c = Client(ws, ip=ip)
        self.clients.add(c)
        return c

    def disconnect(self, c: Client) -> None:
        self.clients.discard(c)

    @staticmethod
    def _encode(msg: dict[str, Any]) -> str:
        return json.dumps(msg, separators=(",", ":"), default=str)

    def _enqueue(self, c: Client, text: str, topic: str | None) -> None:
        try:
            c.queue.put_nowait(text)
        except asyncio.QueueFull:
            c.dropped += 1
            # drain backlog and request a resync for this topic
            while not c.queue.empty():
                try:
                    c.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            if topic:
                c.resync.add(topic)

    def send_to(self, c: Client, msg: dict[str, Any]) -> None:
        self._enqueue(c, self._encode(msg), msg.get("topic"))

    def publish(self, topic: str, msg: dict[str, Any]) -> None:
        targets = [c for c in self.clients if topic in c.topics]
        if not targets:
            return
        msg["topic"] = topic
        text = self._encode(msg)
        for c in targets:
            if topic in c.resync and self.snapshot_provider is not None:
                c.resync.discard(topic)
                snap = self.snapshot_provider(topic)
                if snap is not None:
                    self._enqueue(c, self._encode({"type": "snapshot", "topic": topic, "data": snap}), topic)
                continue
            self._enqueue(c, text, topic)

    def broadcast(self, msg: dict[str, Any]) -> None:
        text = self._encode(msg)
        for c in list(self.clients):
            self._enqueue(c, text, None)

    async def writer(self, c: Client) -> None:
        try:
            while True:
                text = await c.queue.get()
                await c.ws.send_text(text)
        except Exception:  # noqa: BLE001 - connection closed
            return
