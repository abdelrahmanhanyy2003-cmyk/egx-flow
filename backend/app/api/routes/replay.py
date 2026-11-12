from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import container, norm_symbol
from app.database.repositories import market_repo
from app.services.container import Container

router = APIRouter(prefix="/api/replay", tags=["replay"])


@router.get("/sessions")
async def sessions(symbol: str | None = None) -> dict[str, Any]:
    rows = await asyncio.to_thread(market_repo.list_sessions, norm_symbol(symbol) if symbol else None)
    return {"rows": rows, "note": "Only locally recorded sessions can be replayed. Nothing is reconstructed from candles."}


class OpenIn(BaseModel):
    session_id: int
    t0: int | None = None
    t1: int | None = None


@router.post("/open")
async def open_session(body: OpenIn, c: Container = Depends(container)) -> dict[str, Any]:
    try:
        r = await c.replay.open(body.session_id, body.t0, body.t1)
    except KeyError:
        raise HTTPException(404, "session not found") from None
    return r.info()


class ControlIn(BaseModel):
    action: Literal["play", "pause", "speed", "seek", "restart"]
    value: float | None = None


@router.post("/{rid}/control")
async def control(rid: str, body: ControlIn, c: Container = Depends(container)) -> dict[str, Any]:
    if rid not in c.replay.sessions:
        raise HTTPException(404, "replay not found")
    return c.replay.control(rid, body.action, body.value).info()
