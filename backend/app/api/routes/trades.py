from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.analytics.volume_profile import profile_from_trades
from app.api.deps import container, norm_symbol
from app.database.repositories import market_repo
from app.services.container import Container

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("/large")
async def large(symbol: str | None = None, min_value: float = Query(500_000, ge=0), since: int | None = None,
                side: str | None = Query(None, pattern="^(buy|sell|unknown)$"), limit: int = Query(200, le=2000),
                c: Container = Depends(container)) -> dict[str, Any]:
    sym = norm_symbol(symbol) if symbol else None
    rows = await asyncio.to_thread(market_repo.query_trades, sym, min_value, since, side, limit)
    return {"rows": rows, "quality": c.hub.quality.value}


@router.get("/{symbol}")
async def trades(symbol: str, limit: int = Query(500, le=20000), c: Container = Depends(container)) -> dict[str, Any]:
    st = c.hub.states.get(norm_symbol(symbol))
    if st is None:
        raise HTTPException(404, "symbol not streaming")
    return {"symbol": st.symbol, "trades": [t.to_dict() for t in list(st.trades)[-limit:]]}


@router.get("/{symbol}/profile")
async def profile(symbol: str, t0: int | None = None, t1: int | None = None, value_area: float = Query(0.7, gt=0, lt=1),
                  c: Container = Depends(container)) -> dict[str, Any]:
    st = c.hub.states.get(norm_symbol(symbol))
    if st is None:
        raise HTTPException(404, "symbol not streaming")
    if t0 is None and t1 is None:
        return {"scope": "session", **st.profile.to_dict(value_area)}
    return {"scope": "range", "t0": t0, "t1": t1, **profile_from_trades(st.trades, t0, t1).to_dict(value_area)}


@router.get("/{symbol}/cvd")
async def cvd(symbol: str, since: int = 0, c: Container = Depends(container)) -> dict[str, Any]:
    st = c.hub.states.get(norm_symbol(symbol))
    if st is None:
        raise HTTPException(404, "symbol not streaming")
    return {"summary": st.cvd.summary(), "series": st.cvd.series_since(since), "divergence": st.divergence}
