"""Order-book imbalance and liquidity concentration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class Imbalance:
    levels: int
    bid_volume: float
    ask_volume: float
    imbalance: float  # (bid-ask)/(bid+ask) in [-1, 1]
    imbalance_pct: float  # bid share of total, 0..100
    bid_concentration: float  # HHI of bid levels (0..1); 1 = all in one level
    ask_concentration: float
    largest_bid_share: float
    largest_ask_share: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hhi(qtys: list[float]) -> float:
    s = sum(qtys)
    if s <= 0:
        return 0.0
    return sum((q / s) ** 2 for q in qtys)


def book_imbalance(
    bids: list[tuple[float, float]], asks: list[tuple[float, float]], levels: int = 10
) -> Imbalance:
    """``bids``/``asks`` are best-first (price, qty) lists."""
    bq = [q for _, q in bids[:levels]]
    aq = [q for _, q in asks[:levels]]
    b, a = sum(bq), sum(aq)
    tot = b + a
    return Imbalance(
        levels=levels,
        bid_volume=b,
        ask_volume=a,
        imbalance=(b - a) / tot if tot else 0.0,
        imbalance_pct=b / tot * 100 if tot else 50.0,
        bid_concentration=_hhi(bq),
        ask_concentration=_hhi(aq),
        largest_bid_share=max(bq) / b if b else 0.0,
        largest_ask_share=max(aq) / a if a else 0.0,
    )
