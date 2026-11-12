"""Time bars built from classified trades (OHLCV + aggressive buy/sell volume)."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from app.domain.models import Side, Trade


@dataclass(slots=True)
class Bar:
    t: int  # bar open time (epoch ms)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    unknown_volume: float = 0.0
    estimated_volume: float = 0.0  # volume whose side was estimated
    value: float = 0.0
    trades: int = 0

    @property
    def delta(self) -> float:
        return self.buy_volume - self.sell_volume

    @property
    def vwap(self) -> float:
        return self.value / self.volume if self.volume else self.close

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["delta"] = self.delta
        d["vwap"] = round(self.vwap, 4)
        return d


class BarBuilder:
    def __init__(self, interval_ms: int = 60_000, max_bars: int = 2000) -> None:
        self.interval_ms = interval_ms
        self.bars: deque[Bar] = deque(maxlen=max_bars)

    def add(self, trade: Trade) -> Bar:
        t0 = trade.ts - trade.ts % self.interval_ms
        bar = self.bars[-1] if self.bars else None
        if bar is None or t0 > bar.t:
            bar = Bar(t0, trade.price, trade.price, trade.price, trade.price)
            self.bars.append(bar)
        elif t0 < bar.t:
            # late trade - locate its bar (rare); create none if it's older than history
            for b in reversed(self.bars):
                if b.t == t0:
                    bar = b
                    break
            else:
                return bar
        bar.high = max(bar.high, trade.price)
        bar.low = min(bar.low, trade.price)
        if t0 == self.bars[-1].t:
            bar.close = trade.price
        bar.volume += trade.quantity
        bar.value += trade.value
        bar.trades += 1
        if trade.side == Side.BUY:
            bar.buy_volume += trade.quantity
        elif trade.side == Side.SELL:
            bar.sell_volume += trade.quantity
        else:
            bar.unknown_volume += trade.quantity
        if trade.estimated:
            bar.estimated_volume += trade.quantity
        return bar

    def series(self, n: int | None = None) -> list[Bar]:
        b = list(self.bars)
        return b[-n:] if n else b
