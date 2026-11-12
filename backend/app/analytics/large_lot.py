"""Large Lot Tracker - unusually large executed trades and clusters.

Thresholds are dynamic: the EGP value threshold is the configured percentile of
the rolling trade-value distribution for the symbol, floored by a minimum EGP
value. During warm-up (too few observations) only the floor applies and the
method is reported as such.
"""

from __future__ import annotations

import bisect
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from app.domain.models import Trade


class RollingDistribution:
    def __init__(self, maxlen: int = 5000) -> None:
        self.values: deque[float] = deque(maxlen=maxlen)
        self._sorted: list[float] = []
        self._dirty = 0
        self.sum = 0.0

    def add(self, v: float) -> None:
        if len(self.values) == self.values.maxlen:
            self.sum -= self.values[0]
        self.values.append(v)
        self.sum += v
        self._dirty += 1

    def _ensure(self) -> None:
        if self._dirty:
            self._sorted = sorted(self.values)
            self._dirty = 0

    def percentile(self, p: float) -> float | None:
        if not self.values:
            return None
        self._ensure()
        k = (len(self._sorted) - 1) * p / 100.0
        lo = int(k)
        hi = min(lo + 1, len(self._sorted) - 1)
        return self._sorted[lo] + (self._sorted[hi] - self._sorted[lo]) * (k - lo)

    def rank(self, v: float) -> float:
        """Percentile rank (0-100) of v within the distribution."""
        if not self.values:
            return 0.0
        self._ensure()
        return bisect.bisect_right(self._sorted, v) / len(self._sorted) * 100.0

    @property
    def mean(self) -> float:
        return self.sum / len(self.values) if self.values else 0.0

    def __len__(self) -> int:
        return len(self.values)


@dataclass(slots=True)
class LargeTrade:
    trade: Trade
    value: float
    threshold: float
    percentile_rank: float
    multiple_of_avg: float
    pct_of_adv: float | None
    method: str

    def to_dict(self) -> dict[str, Any]:
        d = self.trade.to_dict()
        d.update(
            threshold=round(self.threshold, 2),
            percentile_rank=round(self.percentile_rank, 2),
            multiple_of_avg=round(self.multiple_of_avg, 2),
            pct_of_adv=None if self.pct_of_adv is None else round(self.pct_of_adv, 4),
            threshold_method=self.method,
        )
        return d


@dataclass
class LargeLotConfig:
    min_value_egp: float = 250_000.0
    percentile: float = 99.0
    size_multiple: float = 15.0
    warmup: int = 100
    window: int = 5000
    cluster_window_ms: int = 60_000
    cluster_min_trades: int = 3


@dataclass
class Cluster:
    symbol: str
    side: str
    start: int
    end: int
    count: int
    value: float
    quantity: float
    vwap: float
    trade_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LargeLotTracker:
    def __init__(self, config: LargeLotConfig | None = None) -> None:
        self.cfg = config or LargeLotConfig()
        self.values = RollingDistribution(self.cfg.window)
        self.qtys = RollingDistribution(self.cfg.window)
        self.recent: deque[LargeTrade] = deque(maxlen=500)
        self.adv: float | None = None  # average daily volume (shares), if known

    def threshold(self) -> tuple[float, str]:
        if len(self.values) < self.cfg.warmup:
            return self.cfg.min_value_egp, "floor (warming up)"
        p = self.values.percentile(self.cfg.percentile) or 0.0
        if p >= self.cfg.min_value_egp:
            return p, f"p{self.cfg.percentile:g} of last {len(self.values)} trades"
        return self.cfg.min_value_egp, "minimum value floor"

    def on_trade(self, t: Trade) -> LargeTrade | None:
        value = t.value
        thr, method = self.threshold()
        avg_q = self.qtys.mean
        rank = self.values.rank(value)
        mult = t.quantity / avg_q if avg_q else 0.0
        is_large = value >= thr or (
            len(self.qtys) >= self.cfg.warmup
            and mult >= self.cfg.size_multiple
            and value >= self.cfg.min_value_egp
        )
        # update distribution AFTER evaluation so a trade never sets its own bar
        self.values.add(value)
        self.qtys.add(t.quantity)
        if not is_large:
            return None
        lt = LargeTrade(
            trade=t,
            value=value,
            threshold=thr,
            percentile_rank=rank,
            multiple_of_avg=mult,
            pct_of_adv=(t.quantity / self.adv * 100) if self.adv else None,
            method=method,
        )
        self.recent.append(lt)
        return lt

    def clusters(self, now: int | None = None) -> list[Cluster]:
        """Group recent large trades of the same side within the cluster window."""
        out: list[Cluster] = []
        items = sorted(self.recent, key=lambda x: x.trade.ts)
        cur: Cluster | None = None
        for lt in items:
            t = lt.trade
            side = t.side.value
            if cur and side == cur.side and t.ts - cur.end <= self.cfg.cluster_window_ms:
                cur.end = t.ts
                cur.count += 1
                cur.value += lt.value
                cur.quantity += t.quantity
                cur.vwap = cur.value / cur.quantity
                cur.trade_ids.append(t.trade_id)
            else:
                if cur and cur.count >= self.cfg.cluster_min_trades:
                    out.append(cur)
                cur = Cluster(t.symbol, side, t.ts, t.ts, 1, lt.value, t.quantity, t.price, [t.trade_id])
        if cur and cur.count >= self.cfg.cluster_min_trades:
            out.append(cur)
        return out
