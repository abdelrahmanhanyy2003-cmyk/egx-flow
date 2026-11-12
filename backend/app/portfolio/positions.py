"""Position enrichment: allocation, returns and explicit source labelling."""

from __future__ import annotations

from typing import Any

from app.domain.models import PortfolioPosition
from app.portfolio.pnl import return_pct, unrealized


def enrich_positions(
    positions: list[PortfolioPosition], live_price: dict[str, float | None], total_value: float | None
) -> list[dict[str, Any]]:
    """Fill missing values from live prices (marked local) and compute weights.

    Broker-reported fields are never overwritten; every derived field is listed
    under ``local_fields`` so the UI can distinguish them.
    """
    out: list[dict[str, Any]] = []
    rows = []
    for p in positions:
        d = p.to_dict()
        local: list[str] = []
        lp = live_price.get(p.symbol)
        if lp is not None:
            d["live_price"] = lp
        price = d["current_price"] if d["current_price"] is not None else lp
        if d["current_price"] is None and lp is not None:
            d["current_price"] = lp
            local.append("current_price")
        if d["market_value"] is None and price is not None:
            d["market_value"] = p.quantity * price
            local.append("market_value")
        if d["unrealized_pnl"] is None:
            d["unrealized_pnl"] = unrealized(p.quantity, p.avg_price, price)
            local.append("unrealized_pnl")
        if d["unrealized_pnl_pct"] is None:
            d["unrealized_pnl_pct"] = return_pct(p.avg_price, price)
            local.append("unrealized_pnl_pct")
        d["local_fields"] = local
        rows.append(d)
    denom = total_value or sum((r["market_value"] or 0) for r in rows) or None
    for d in rows:
        d["allocation_pct"] = (d["market_value"] or 0) / denom * 100 if denom else None
        d["local_fields"].append("allocation_pct")
        out.append(d)
    return out
