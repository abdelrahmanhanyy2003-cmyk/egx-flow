"""User preferences, saved layouts and watchlists."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database.repositories import user_repo

router = APIRouter(prefix="/api/prefs", tags=["preferences"])

ALLOWED_KEYS = {"layouts", "active_layout", "heatmap", "bubbles", "indicators", "ui", "watchlist_active"}


@router.get("")
async def all_prefs() -> dict[str, Any]:
    out = {}
    for k in ALLOWED_KEYS:
        out[k] = await asyncio.to_thread(user_repo.get_pref, k)
    return out


class PrefIn(BaseModel):
    value: Any


@router.put("/{key}")
async def set_pref(key: str, body: PrefIn) -> dict[str, Any]:
    if key not in ALLOWED_KEYS:
        raise HTTPException(400, "unknown preference key")
    if len(json.dumps(body.value, default=str)) > 200_000:
        raise HTTPException(413, "preference too large")
    await asyncio.to_thread(user_repo.set_pref, key, body.value)
    return {"ok": True}


@router.get("/watchlists")
async def watchlists() -> dict[str, Any]:
    return {"rows": await asyncio.to_thread(user_repo.list_watchlists)}


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    symbols: list[str] = Field(max_length=500)


@router.put("/watchlists")
async def save_watchlist(body: WatchlistIn) -> dict[str, Any]:
    syms = [s.strip().upper() for s in body.symbols if s.strip().isalnum()]
    return await asyncio.to_thread(user_repo.save_watchlist, body.name, syms)


@router.delete("/watchlists/{wid}")
async def delete_watchlist(wid: int) -> dict[str, Any]:
    if not await asyncio.to_thread(user_repo.delete_watchlist, wid):
        raise HTTPException(404, "not found")
    return {"ok": True}
