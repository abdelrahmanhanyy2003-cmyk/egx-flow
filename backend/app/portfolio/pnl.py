"""P&L arithmetic: FIFO realized P&L with fees, unrealized P&L, returns."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Fill:
    symbol: str
    side: str  # buy | sell
    quantity: float
    price: float
    fees: float = 0.0
    ts: str = ""
    ref: Any = None


@dataclass
class ClosedLot:
    symbol: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_ts: str
    exit_ts: str
    fees: float
    net_pnl: float
    return_pct: float


@dataclass
class FifoResult:
    open_qty: float = 0.0
    avg_cost: float = 0.0  # includes buy fees
    realized: float = 0.0
    fees: float = 0.0
    closed: list[ClosedLot] = field(default_factory=list)


def fifo(fills: list[Fill]) -> dict[str, FifoResult]:
    """FIFO matching per symbol. Buy fees are capitalised into cost; sell fees
    reduce proceeds. Short selling is not supported on this read-only journal:
    a sell beyond open quantity raises ``ValueError``."""
    lots: dict[str, deque[list[Any]]] = {}
    res: dict[str, FifoResult] = {}
    for f in fills:
        r = res.setdefault(f.symbol, FifoResult())
        q = lots.setdefault(f.symbol, deque())
        r.fees += f.fees
        if f.side == "buy":
            unit = (f.price * f.quantity + f.fees) / f.quantity
            q.append([f.quantity, unit, f.ts])
        elif f.side == "sell":
            remaining = f.quantity
            if remaining - sum(x[0] for x in q) > 1e-9:
                raise ValueError(f"sell of {f.quantity} {f.symbol} exceeds open quantity")
            fee_per_share = f.fees / f.quantity
            while remaining > 1e-12:
                lot = q[0]
                take = min(lot[0], remaining)
                proceeds = take * (f.price - fee_per_share)
                cost = take * lot[1]
                pnl = proceeds - cost
                r.realized += pnl
                r.closed.append(ClosedLot(f.symbol, take, lot[1], f.price, lot[2], f.ts,
                                          take * fee_per_share, pnl, pnl / cost * 100 if cost else 0.0))
                lot[0] -= take
                remaining -= take
                if lot[0] <= 1e-12:
                    q.popleft()
        else:
            raise ValueError(f"unknown side {f.side}")
    for sym, r in res.items():
        q = lots.get(sym, deque())
        r.open_qty = sum(x[0] for x in q)
        r.avg_cost = sum(x[0] * x[1] for x in q) / r.open_qty if r.open_qty else 0.0
    return res


def unrealized(qty: float, avg_cost: float, price: float | None) -> float | None:
    if price is None:
        return None
    return (price - avg_cost) * qty


def return_pct(avg_cost: float, price: float | None) -> float | None:
    if price is None or not avg_cost:
        return None
    return (price / avg_cost - 1) * 100
