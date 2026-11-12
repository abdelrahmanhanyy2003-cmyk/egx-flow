"""Broker connection status. Credentials are never accepted or returned by the API:
they live only in the backend ``.env``."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import container
from app.services.container import Container

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
async def status(c: Container = Depends(container)) -> dict[str, Any]:
    return c.integration_status()


@router.post("/live-check")
async def live_check(c: Container = Depends(container)) -> dict[str, Any]:
    """Authorized live connectivity check (read-only calls only).

    Requires DATA_MODE=live with credentials configured. Performs
    ``account_info`` and ``market_status`` and reports success/failure without
    exposing account identifiers.
    """
    if c.efg_session is None:
        raise HTTPException(400, "live checks require DATA_MODE=live")
    out: dict[str, Any] = {}
    try:
        info = await c.efg_session.call("account_info")
        out["account_info"] = {"ok": True, "is_live_datafeed": getattr(info, "is_live_datafeed", None),
                               "profiles": len(getattr(info, "profiles", []) or [])}
    except Exception as exc:  # noqa: BLE001
        out["account_info"] = {"ok": False, "error": type(exc).__name__}
    try:
        st = await asyncio.wait_for(c.efg_session.call("market_status"), 15)
        out["market_status"] = {"ok": True, "status": st}
    except Exception as exc:  # noqa: BLE001
        out["market_status"] = {"ok": False, "error": type(exc).__name__}
    return out
