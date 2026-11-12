from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.alerts.rules import RULES
from app.api.deps import container, norm_symbol
from app.database.repositories import user_repo
from app.services.container import Container

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
async def history(limit: int = Query(200, le=2000), symbol: str | None = None, rule: str | None = None) -> dict[str, Any]:
    rows = await asyncio.to_thread(user_repo.list_alerts, limit, norm_symbol(symbol) if symbol else None, rule)
    return {"rows": rows}


class AckIn(BaseModel):
    ids: list[int] | None = None


@router.post("/ack")
async def ack(body: AckIn) -> dict[str, Any]:
    return {"acknowledged": await asyncio.to_thread(user_repo.ack_alerts, body.ids)}


@router.get("/rules")
async def rules(c: Container = Depends(container)) -> dict[str, Any]:
    overrides = await asyncio.to_thread(user_repo.list_rules)
    return {"catalogue": RULES, "overrides": overrides}


class RuleIn(BaseModel):
    rule: str
    symbol: str | None = Field(default=None, max_length=16)
    enabled: bool = True
    sound: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


@router.put("/rules")
async def upsert_rule(body: RuleIn, c: Container = Depends(container)) -> dict[str, Any]:
    if body.rule not in RULES:
        raise HTTPException(400, "unknown rule")
    allowed = set(RULES[body.rule]["params"])
    params: dict[str, Any] = {}
    for k, v in body.params.items():
        if k not in allowed:
            raise HTTPException(400, f"unknown param {k}")
        if v is not None and not isinstance(v, (int, float)):
            raise HTTPException(400, f"param {k} must be numeric")
        params[k] = v
    sym = norm_symbol(body.symbol) if body.symbol else None
    row = await asyncio.to_thread(user_repo.upsert_rule, body.rule, sym, body.enabled, body.sound, params)
    c.alerts.load_rules(await asyncio.to_thread(user_repo.list_rules))
    return row


@router.delete("/rules/{rid}")
async def delete_rule(rid: int, c: Container = Depends(container)) -> dict[str, Any]:
    if not await asyncio.to_thread(user_repo.delete_rule, rid):
        raise HTTPException(404, "not found")
    c.alerts.load_rules(await asyncio.to_thread(user_repo.list_rules))
    return {"ok": True}
