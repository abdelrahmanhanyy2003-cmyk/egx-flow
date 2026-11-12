"""DEMO order-flow simulator.

Generates a self-consistent limit order book per symbol with:

* realistic resting liquidity profile (thinner at touch, thicker deeper);
* Poisson market-order arrivals walking the book (aggressor side is known);
* regime switching (accumulation / distribution / balanced) that biases flow;
* persistent large "walls" that are later consumed or pulled;
* iceberg-style levels whose displayed size is replenished from a hidden reserve;
* occasional large block-like aggressive orders.

Every event is stamped ``DataQuality.SIMULATED`` and source ``demo``.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from app.domain.models import (
    BookDelta,
    BookResolution,
    BookSide,
    BookSnapshot,
    ClassificationMethod,
    DataQuality,
    IndexValue,
    MarketEvent,
    MarketStats,
    Quote,
    Side,
    Trade,
)
from app.market_data.normalizer import rp

SRC = "demo"
Q = DataQuality.SIMULATED


@dataclass
class _Wall:
    side: BookSide
    price: float
    extra: float
    expires: int
    pull: bool  # True -> will be pulled before being hit (spoof-like behaviour)


@dataclass
class _Iceberg:
    side: BookSide
    price: float
    peak: float
    reserve: float


@dataclass
class SymSim:
    symbol: str
    price: float
    tick: float
    adv: float
    rng: random.Random
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    regime: str = "balanced"
    regime_until: int = 0
    walls: list[_Wall] = field(default_factory=list)
    icebergs: list[_Iceberg] = field(default_factory=list)
    trade_seq: int = 0
    prev_close: float = 0.0
    last: float = 0.0
    volume: float = 0.0
    value: float = 0.0
    n_trades: int = 0
    open: float | None = None
    high: float = 0.0
    low: float = 0.0
    anchor: float = 0.0

    def __post_init__(self) -> None:
        self.prev_close = self.price
        self.last = self.price
        self.anchor = self.price
        self.high = self.low = self.price
        # typical resting level size: ~ value of a few hundred thousand EGP
        self.base_qty = max(100.0, (self.adv / 4000.0))
        self.levels = 40
        mid = self.price
        bb = rp(math.floor(mid / self.tick) * self.tick)
        for i in range(self.levels):
            self.bids[rp(bb - i * self.tick)] = self._level_size(i)
            self.asks[rp(bb + (i + 1) * self.tick)] = self._level_size(i)

    # ------------------------------------------------------------- helpers
    def _level_size(self, dist: int) -> float:
        shape = 0.45 + 0.9 * (1 - math.exp(-dist / 6.0))
        return float(max(1, int(self.base_qty * shape * self.rng.lognormvariate(0, 0.45))))

    @property
    def best_bid(self) -> float:
        return max(self.bids) if self.bids else self.last - self.tick

    @property
    def best_ask(self) -> float:
        return min(self.asks) if self.asks else self.last + self.tick

    def _set(self, side: BookSide, price: float, qty: float, out: list[tuple[BookSide, float, float]]) -> None:
        book = self.bids if side == BookSide.BID else self.asks
        price = rp(price)
        qty = float(max(0, int(qty)))
        if qty <= 0:
            if price in book:
                del book[price]
                out.append((side, price, 0.0))
        elif book.get(price) != qty:
            book[price] = qty
            out.append((side, price, qty))

    # --------------------------------------------------------------- step
    def step(self, ts: int, dt_s: float) -> tuple[list[tuple[BookSide, float, float]], list[Trade]]:
        rng = self.rng
        changes: list[tuple[BookSide, float, float]] = []
        trades: list[Trade] = []

        if ts >= self.regime_until:
            drift = (self.last - self.anchor) / self.anchor
            weights = {"accumulation": 1.0 - drift * 8, "distribution": 1.0 + drift * 8, "balanced": 1.4}
            regs = list(weights)
            self.regime = rng.choices(regs, [max(0.1, weights[r]) for r in regs])[0]
            self.regime_until = ts + int(rng.uniform(6, 18) * 60_000)

        buy_bias = {"accumulation": 0.58, "distribution": 0.42, "balanced": 0.5}[self.regime]
        bb, ba = self.best_bid, self.best_ask

        # 1) passive liquidity churn near the touch (a random subset of levels)
        protected = {(w.side, w.price) for w in self.walls} | {(i.side, i.price) for i in self.icebergs}
        for _ in range(6):
            side = BookSide.BID if rng.random() < 0.5 else BookSide.ASK
            # the touch itself is mostly replenished by the spread-filling rule below
            dist = 0 if rng.random() < 0.08 else min(self.levels - 1, 1 + int(rng.expovariate(1 / 7)))
            price = rp((bb - dist * self.tick) if side == BookSide.BID else (ba + dist * self.tick))
            if (side, price) in protected:
                continue
            book = self.bids if side == BookSide.BID else self.asks
            cur = book.get(price, 0.0)
            target = self._level_size(dist)
            # regime: accumulators refresh bids, distributors refresh offers
            if (self.regime == "accumulation" and side == BookSide.BID) or (
                self.regime == "distribution" and side == BookSide.ASK
            ):
                target *= 1.25
            new = cur + (target - cur) * rng.uniform(0.2, 0.7)
            self._set(side, price, new, changes)

        # keep the spread tight: fill an empty touch
        if ba - bb > 2 * self.tick + 1e-9 and rng.random() < 0.7:
            side = BookSide.BID if rng.random() < buy_bias else BookSide.ASK
            p = bb + self.tick if side == BookSide.BID else ba - self.tick
            self._set(side, p, self._level_size(0) * 0.6, changes)

        # 2) walls: occasionally create a large resting order 3-12 ticks away
        if rng.random() < 0.0035 * dt_s * 4 and len(self.walls) < 3:
            side = BookSide.BID if rng.random() < buy_bias + 0.05 else BookSide.ASK
            d = rng.randint(3, 12)
            p = rp((self.best_bid - d * self.tick) if side == BookSide.BID else (self.best_ask + d * self.tick))
            extra = self.base_qty * rng.uniform(6, 14)
            self.walls.append(_Wall(side, p, extra, ts + int(rng.uniform(2, 15) * 60_000), rng.random() < 0.35))
            book = self.bids if side == BookSide.BID else self.asks
            self._set(side, p, book.get(p, 0.0) + extra, changes)
        for w in list(self.walls):
            book = self.bids if w.side == BookSide.BID else self.asks
            near = abs(w.price - (self.best_bid if w.side == BookSide.BID else self.best_ask)) <= 2 * self.tick
            if ts >= w.expires or (w.pull and near) or w.price not in book:
                if w.price in book:
                    self._set(w.side, w.price, max(0.0, book[w.price] - w.extra), changes)
                self.walls.remove(w)

        # 3) icebergs: start occasionally at the touch on the regime side
        if rng.random() < 0.002 * dt_s * 4 and len(self.icebergs) < 2 and self.regime != "balanced":
            side = BookSide.BID if self.regime == "accumulation" else BookSide.ASK
            p = self.best_bid if side == BookSide.BID else self.best_ask
            peak = self.base_qty * rng.uniform(0.6, 1.2)
            self.icebergs.append(_Iceberg(side, rp(p), peak, peak * rng.uniform(6, 15)))
            self._set(side, p, peak, changes)

        # 4) aggressive orders
        lam = (self.adv / (4.5 * 3600)) / (self.base_qty * 0.35) * dt_s
        n = _poisson(rng, lam)
        for _ in range(n):
            side = Side.BUY if rng.random() < buy_bias else Side.SELL
            size = self.base_qty * 0.35 * rng.lognormvariate(0, 0.9)
            if rng.random() < 0.012:  # block-like large aggressive order
                size *= rng.uniform(8, 25)
            trades.extend(self._execute(side, size, ts, changes))

        # 5) maintain depth & mean-reversion anchor
        self._trim_and_extend(changes)
        if trades:
            self.last = trades[-1].price
        return changes, trades

    def _execute(
        self, side: Side, size: float, ts: int, changes: list[tuple[BookSide, float, float]]
    ) -> list[Trade]:
        out: list[Trade] = []
        remaining = float(max(1, int(size)))
        opp_side = BookSide.ASK if side == Side.BUY else BookSide.BID
        book = self.asks if side == Side.BUY else self.bids
        guard = 0
        while remaining > 0 and book and guard < 12:
            guard += 1
            price = min(book) if side == Side.BUY else max(book)
            avail = book[price]
            fill = min(avail, remaining)
            remaining -= fill
            left = avail - fill
            ice = next((i for i in self.icebergs if i.side == opp_side and i.price == price), None)
            if left <= 0 and ice is not None and ice.reserve > 0:
                refill = min(ice.peak, ice.reserve)
                ice.reserve -= refill
                left = refill
                if ice.reserve <= 0:
                    self.icebergs.remove(ice)
            self._set(opp_side, price, left, changes)
            self.trade_seq += 1
            t = Trade(
                trade_id=f"D{self.symbol}{ts}{self.trade_seq}",
                symbol=self.symbol,
                price=price,
                quantity=fill,
                ts=ts,
                source=SRC,
                quality=Q,
                side=side,
                method=ClassificationMethod.PROVIDER,  # simulator ground truth
                confidence=1.0,
                seq=self.trade_seq,
            )
            out.append(t)
            self.volume += fill
            self.value += fill * price
            self.n_trades += 1
            if self.open is None:
                self.open = price
            self.high = max(self.high, price)
            self.low = min(self.low, price)
        return out

    def _trim_and_extend(self, changes: list[tuple[BookSide, float, float]]) -> None:
        if not self.bids or not self.asks:
            # rebuild an empty side around last price
            if not self.bids:
                top = (min(self.asks) if self.asks else self.last) - self.tick
                for i in range(10):
                    self._set(BookSide.BID, top - i * self.tick, self._level_size(i), changes)
            if not self.asks:
                bot = (max(self.bids) if self.bids else self.last) + self.tick
                for i in range(10):
                    self._set(BookSide.ASK, bot + i * self.tick, self._level_size(i), changes)
        bb, ba = self.best_bid, self.best_ask
        lo, hi = bb - self.levels * self.tick, ba + self.levels * self.tick
        for p in [p for p in self.bids if p < lo]:
            self._set(BookSide.BID, p, 0, changes)
        for p in [p for p in self.asks if p > hi]:
            self._set(BookSide.ASK, p, 0, changes)
        # extend deep levels if the book became shallow
        if len(self.bids) < self.levels * 0.7:
            deepest = min(self.bids)
            for i in range(1, 4):
                self._set(BookSide.BID, deepest - i * self.tick, self._level_size(self.levels - 4 + i), changes)
        if len(self.asks) < self.levels * 0.7:
            deepest = max(self.asks)
            for i in range(1, 4):
                self._set(BookSide.ASK, deepest + i * self.tick, self._level_size(self.levels - 4 + i), changes)

    def quote(self, ts: int) -> Quote:
        bb, ba = self.best_bid, self.best_ask
        return Quote(
            symbol=self.symbol, bid=bb, ask=ba, last=self.last,
            bid_qty=self.bids.get(bb), ask_qty=self.asks.get(ba), ts=ts, source=SRC, quality=Q,
            received_ts=ts, open=self.open, high=self.high, low=self.low, prev_close=self.prev_close,
            volume=self.volume, value=self.value, trades_count=self.n_trades,
            change_pct=(self.last - self.prev_close) / self.prev_close * 100,
        )


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(rng.gauss(lam, math.sqrt(lam))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


class MarketSim:
    def __init__(self, universe: list[tuple[str, str, str, float, float, float]], seed: int, index_base: float) -> None:
        self.rng = random.Random(seed)
        self.syms: dict[str, SymSim] = {}
        for i, (sym, _n, _s, px, tick, adv) in enumerate(universe):
            self.syms[sym] = SymSim(sym, px, tick, adv, random.Random(seed * 1000 + i))
        self.index_base = index_base
        self.index_weights = {s: 1 / len(self.syms) for s in self.syms}

    def step(self, ts: int, dt_s: float, emit: Callable[[MarketEvent], None], with_quotes: bool) -> None:
        for s in self.syms.values():
            changes, trades = s.step(ts, dt_s)
            # trades first: they executed against the pre-update book
            for t in trades:
                emit(t)
            for side, price, qty in changes:
                emit(BookDelta(s.symbol, side, price, qty, ts, SRC, Q, received_ts=ts))
            if with_quotes:
                emit(s.quote(ts))

    def snapshots(self, ts: int) -> list[MarketEvent]:
        out: list[MarketEvent] = []
        for s in self.syms.values():
            bids = sorted(s.bids.items(), key=lambda x: -x[0])
            asks = sorted(s.asks.items(), key=lambda x: x[0])
            out.append(BookSnapshot(s.symbol, bids, asks, ts, SRC, Q, BookResolution.DEPTH_UPDATES, received_ts=ts))
        return out

    def market_events(self, ts: int) -> list[MarketEvent]:
        adv = dec = unch = 0
        val = vol = 0.0
        n = 0
        idx_ret = 0.0
        for s in self.syms.values():
            r = (s.last - s.prev_close) / s.prev_close
            idx_ret += r * self.index_weights[s.symbol]
            adv += r > 1e-9
            dec += r < -1e-9
            unch += abs(r) <= 1e-9
            val += s.value
            vol += s.volume
            n += s.n_trades
        idx = self.index_base * (1 + idx_ret)
        return [
            MarketStats(1, "Open (DEMO)", val, vol, n, adv, dec, unch, ts, SRC, Q),
            IndexValue(1, "EGX30 (DEMO)", round(idx, 2), round(idx_ret * 100, 3),
                       round(idx - self.index_base, 2), ts, SRC, Q),
        ]
