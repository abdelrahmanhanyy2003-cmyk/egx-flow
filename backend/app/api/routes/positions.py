from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.analytics.imbalance import book_imbalance
from app.api.deps import container, norm_symbol
from app.services.container import Container

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("")
async def positions(c: Container = Depends(container)) -> dict[str, Any]:
    v = c.portfolio.view()
    return {"rows": v["positions"], "quality": v["quality"], "source": v["source"]}


@router.get("/{symbol}")
async def position_detail(symbol: str, c: Container = Depends(container)) -> dict[str, Any]:
    """Everything needed for the Position Details screen in one call."""
    sym = norm_symbol(symbol)
    v = c.portfolio.view()
    pos = next((p for p in v["positions"] if p["symbol"] == sym), None)
    st = await c.hub.ensure_symbol(sym)
    if st is None:
        raise HTTPException(404, "unknown symbol")
    bids, asks = st.book.top(10)
    return {
        "position": pos,
        "is_holding": pos is not None,
        "stats": st.stats(),
        "profile": st.profile.to_dict(),
        "cvd": st.cvd.summary(),
        "cvd_series": [[p.t, p.cvd] for p in st.cvd.points][-3000:],
        "bars": [b.to_dict() for b in st.bars.series(400)],
        "imbalance": book_imbalance(bids, asks, 10).to_dict() if (bids or asks) else None,
        "large_trades": [x.to_dict() for x in list(st.large_trades)[-50:]],
        "walls": st.walls.active(),
        "wall_events": [e.to_dict() for e in list(st.wall_events)[-30:]],
        "whale": st.whale,
        "flow": st.flow.to_dict() if st.flow else None,
        "recent_trades": [t.to_dict() for t in list(st.trades)[-200:]],
        "quality": st.quality.value,
    }
