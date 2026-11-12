from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import container
from app.services.container import Container

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/overview")
async def overview(c: Container = Depends(container)) -> dict[str, Any]:
    return c.hub.overview()


@router.get("/status")
async def status(c: Container = Depends(container)) -> dict[str, Any]:
    return c.hub.status()


@router.get("/session")
async def session(c: Container = Depends(container)) -> dict[str, Any]:
    from app.core.timeutil import now_ms

    return c.hub.sessions.session_for(now_ms()).to_dict()
