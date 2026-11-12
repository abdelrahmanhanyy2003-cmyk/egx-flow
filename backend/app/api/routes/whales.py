from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import container, norm_symbol
from app.database.repositories import market_repo
from app.services.container import Container

router = APIRouter(prefix="/api/whales", tags=["whale-radar"])


@router.get("/dashboard")
async def dashboard(c: Container = Depends(container)) -> dict[str, Any]:
    return c.hub.whale_dashboard()


@router.get("/trades")
async def large_trades(
    symbol: str | None = None,
    min_value: float = Query(0, ge=0),
    min_qty: float = Query(0, ge=0),
    side: str | None = Query(None, pattern="^(buy|sell|unknown)$"),
    since: int | None = None,
    min_percentile: float = Query(0, ge=0, le=100),
    limit: int = Query(300, le=2000),
    c: Container = Depends(container),
) -> dict[str, Any]:
    sym = norm_symbol(symbol) if symbol else None
    rows: list[dict[str, Any]] = []
    for s, st in c.hub.states.items():
        if sym and s != sym:
            continue
        for x in st.large_trades:
            d = x.to_dict()
            if d["value"] < min_value or d["quantity"] < min_qty or d["percentile_rank"] < min_percentile:
                continue
            if side and d["side"] != side:
                continue
            if since and d["ts"] < since:
                continue
            rows.append(d)
    rows.sort(key=lambda r: -r["ts"])
    return {"rows": rows[:limit], "quality": c.hub.quality.value}


@router.get("/walls")
async def walls(c: Container = Depends(container)) -> dict[str, Any]:
    d = c.hub.whale_dashboard()
    return {"active": d["largest_resting"], "new": d["new_walls"], "removed": d["removed_walls"]}


@router.get("/icebergs")
async def icebergs(c: Container = Depends(container)) -> dict[str, Any]:
    return {"rows": c.hub.whale_dashboard()["icebergs"],
            "label": "Potential iceberg activity - heuristic estimates, not confirmed hidden orders."}


@router.get("/score/{symbol}")
async def score(symbol: str, c: Container = Depends(container)) -> dict[str, Any]:
    st = c.hub.states.get(norm_symbol(symbol))
    if st is None or st.whale is None:
        raise HTTPException(404, "no score yet")
    return {"symbol": st.symbol, **st.whale, "flow": st.flow.to_dict() if st.flow else None}


@router.get("/history")
async def history(kind: str | None = None, symbol: str | None = None, limit: int = Query(200, le=2000)) -> dict[str, Any]:
    rows = await asyncio.to_thread(market_repo.recent_whale_events, kind, norm_symbol(symbol) if symbol else None, limit)
    return {"rows": rows}


@router.get("/participants")
async def participants(c: Container = Depends(container)) -> dict[str, Any]:
    """Investor-type statistics: only if an authorized provider exposes them."""
    cap = c.market_provider.capabilities
    return {
        "available": cap.investor_type_stats,
        "rows": [],
        "note": ("No connected provider exposes investor-type / participant statistics. "
                 "The Younit SDK does not document such an endpoint. Plug a licensed source into the "
                 "provider interface to enable this panel."),
    }
