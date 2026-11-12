from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.api.deps import container
from app.database.repositories import user_repo
from app.services.container import Container

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/summary")
async def summary(c: Container = Depends(container)) -> dict[str, Any]:
    return c.portfolio.view()


@router.post("/refresh")
async def refresh(c: Container = Depends(container)) -> dict[str, Any]:
    await c.portfolio.refresh()
    return c.portfolio.view()


@router.get("/risk")
async def risk(c: Container = Depends(container)) -> dict[str, Any]:
    return c.portfolio.risk_view()


@router.get("/history")
async def history(since: int = 0, c: Container = Depends(container)) -> dict[str, Any]:
    rows = await asyncio.to_thread(user_repo.portfolio_history, since, c.portfolio.provider.name)
    return {"rows": rows, "label": "Recorded portfolio snapshots (local)."}


@router.get("/orders/open")
async def open_orders(c: Container = Depends(container)) -> dict[str, Any]:
    return {"rows": await c.portfolio.open_orders(), "source": c.portfolio.provider.name}


@router.get("/orders/history")
async def order_history(c: Container = Depends(container)) -> dict[str, Any]:
    return {"rows": [o.to_dict() for o in await c.portfolio.order_history()], "source": c.portfolio.provider.name}


# ------------------------------------------------------------------ journal
class JournalIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)
    side: Literal["buy", "sell"]
    trade_date: str = Field(min_length=8, max_length=32)
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    fees: float = Field(default=0.0, ge=0)
    notes: str | None = Field(default=None, max_length=5000)
    thesis: str | None = Field(default=None, max_length=5000)
    tags: str | None = Field(default=None, max_length=256)

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalnum():
            raise ValueError("symbol must be alphanumeric")
        return v


@router.get("/journal")
async def journal(symbol: str | None = None, c: Container = Depends(container)) -> dict[str, Any]:
    rows = await asyncio.to_thread(user_repo.list_journal, symbol.upper() if symbol else None)
    return {"rows": rows, "stats": c.portfolio.journal_stats(rows)}


@router.post("/journal")
async def add_journal(body: JournalIn) -> dict[str, Any]:
    data = body.model_dump() | {"broker_order_id": None, "origin": "manual"}
    return await asyncio.to_thread(user_repo.add_journal, data)


@router.put("/journal/{jid}")
async def update_journal(jid: int, body: JournalIn) -> dict[str, Any]:
    r = await asyncio.to_thread(user_repo.update_journal, jid, body.model_dump())
    if r is None:
        raise HTTPException(404, "not found")
    return r


@router.delete("/journal/{jid}")
async def delete_journal(jid: int) -> dict[str, Any]:
    if not await asyncio.to_thread(user_repo.delete_journal, jid):
        raise HTTPException(404, "not found")
    return {"ok": True}


@router.get("/reconciliation")
async def reconciliation(c: Container = Depends(container)) -> dict[str, Any]:
    return await c.portfolio.reconciliation()


@router.post("/reconciliation/import")
async def import_fills(c: Container = Depends(container)) -> dict[str, Any]:
    return await c.portfolio.import_broker_fills()
