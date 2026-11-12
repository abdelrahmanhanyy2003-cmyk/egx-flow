from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.analytics.imbalance import book_imbalance
from app.api.deps import container, norm_symbol
from app.services.container import Container

router = APIRouter(prefix="/api/orderbook", tags=["orderbook"])


def _state(c: Container, symbol: str):  # type: ignore[no-untyped-def]
    st = c.hub.states.get(norm_symbol(symbol))
    if st is None:
        raise HTTPException(404, "symbol not streaming")
    return st


@router.get("/{symbol}")
async def book(symbol: str, levels: int = Query(25, ge=1, le=200), c: Container = Depends(container)) -> dict[str, Any]:
    st = _state(c, symbol)
    return st.book.to_dict(levels) | {"quality": st.quality.value}


@router.get("/{symbol}/imbalance")
async def imbalance(symbol: str, levels: int = Query(10, ge=1, le=100), c: Container = Depends(container)) -> dict[str, Any]:
    st = _state(c, symbol)
    bids, asks = st.book.top(levels)
    return book_imbalance(bids, asks, levels).to_dict() | {"resolution": st.book.resolution.value}


@router.get("/{symbol}/heatmap")
async def heatmap(symbol: str, since: int = 0, limit: int = Query(1800, le=20000),
                  c: Container = Depends(container)) -> dict[str, Any]:
    st = _state(c, symbol)
    return {"symbol": st.symbol, "resolution": st.book.resolution.value,
            "columns": [col.to_wire() for col in st.heatmap.since(since, limit)]}


@router.get("/{symbol}/walls")
async def walls(symbol: str, c: Container = Depends(container)) -> dict[str, Any]:
    st = _state(c, symbol)
    return {"active": st.walls.active(), "events": [e.to_dict() for e in list(st.wall_events)[-100:]]}
