"""Per-symbol market state: book, trades, heatmap and all order-flow analytics.

The same class is used for live data and for historical replay, which
guarantees that replayed analytics match what was computed live.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from app.analytics.absorption import AbsorptionDetector, AbsorptionSignal
from app.analytics.accumulation import FlowEvidence, FlowSignal, evaluate_flow
from app.analytics.bars import BarBuilder
from app.analytics.cvd import CVDCalculator, detect_divergence
from app.analytics.iceberg import IcebergDetector, IcebergSignal
from app.analytics.imbalance import Imbalance, book_imbalance
from app.analytics.large_lot import LargeLotTracker, LargeTrade
from app.analytics.liquidity_walls import WallDetector, WallEvent
from app.analytics.volume_profile import VolumeProfile
from app.analytics.vwap import VWAP
from app.analytics.whale_score import WhaleInputs, whale_score
from app.core.timeutil import cairo_date
from app.domain.models import (
    BookDelta,
    BookResolution,
    BookSide,
    BookSnapshot,
    ClassificationMethod,
    DataQuality,
    Instrument,
    Quote,
    Side,
    Trade,
)
from app.market_data.heatmap import HeatColumn, HeatmapHistory
from app.market_data.normalizer import TickSizeResolver
from app.market_data.orderbook_engine import LevelChange, OrderBook
from app.market_data.trade_classifier import TradeClassifier

WINDOW_MS = 15 * 60_000


class SymbolState:
    def __init__(
        self,
        instrument: Instrument,
        *,
        heatmap_columns: int = 3600,
        depth_levels: int = 60,
        trade_limit: int = 20000,
        quality: DataQuality = DataQuality.LIVE,
        adv: float | None = None,
    ) -> None:
        self.instrument = instrument
        self.symbol = instrument.symbol
        self.quality = quality
        self.book = OrderBook(self.symbol)
        self.tick = TickSizeResolver(instrument.tick_size, instrument.tick_size_source)
        self.classifier = TradeClassifier()
        self.heatmap = HeatmapHistory(heatmap_columns, depth_levels)
        self.trades: deque[Trade] = deque(maxlen=trade_limit)
        self.cvd = CVDCalculator(reset="session")
        self.profile = VolumeProfile()
        self.bars = BarBuilder(60_000)
        self.vwap = VWAP()
        self.llt = LargeLotTracker()
        self.llt.adv = adv
        self.adv = adv
        self.walls = WallDetector(self.symbol)
        self.icebergs = IcebergDetector(self.symbol)
        self.absorption = AbsorptionDetector(self.symbol)

        self.quote: Quote | None = None
        self.quote_ts: int | None = None
        self.last_price: float | None = None
        self.open: float | None = None
        self.high: float | None = None
        self.low: float | None = None
        self.prev_close: float | None = instrument.reference_price
        self.volume = 0.0
        self.value = 0.0
        self.trade_count = 0
        self.session_key: object = None
        self.last_event_ms = 0
        self.has_depth_feed = False

        # outbound incremental buffers (drained by the broadcaster)
        self._out_trades: list[Trade] = []
        self._out_columns: list[HeatColumn] = []
        self._out_cvd_from: int = 0
        self._out_events: list[dict[str, Any]] = []
        self._alert_events: list[dict[str, Any]] = []
        self._agg: list[Any] | None = None  # [ts, side, fills] pending aggregated print

        # recent analytic events
        self.large_trades: deque[LargeTrade] = deque(maxlen=300)
        self.wall_events: deque[WallEvent] = deque(maxlen=300)
        self.iceberg_signals: list[IcebergSignal] = []
        self.absorptions: deque[AbsorptionSignal] = deque(maxlen=100)
        self.flow: FlowSignal | None = None
        self.whale: dict[str, Any] | None = None
        self.divergence: dict[str, Any] | None = None
        self.depth_hist: deque[tuple[int, float]] = deque(maxlen=900)
        self.imbalance: Imbalance | None = None
        self.imbalance_levels = 10

    # ------------------------------------------------------------------ input
    def _new_session_check(self, ts: int) -> None:
        k = cairo_date(ts)
        if k != self.session_key:
            if self.session_key is not None and self.last_price is not None:
                self.prev_close = self.last_price
            self.session_key = k
            self.open = self.high = self.low = None
            self.volume = self.value = 0.0
            self.trade_count = 0
            self.profile = VolumeProfile()
            self.vwap = VWAP()

    def on_quote(self, q: Quote) -> None:
        self.quote = q
        self.quote_ts = q.ts
        self.last_event_ms = max(self.last_event_ms, q.ts)
        if q.prev_close:
            self.prev_close = q.prev_close
        if q.last and self.last_price is None:
            self.last_price = q.last
        if q.open and self.open is None:
            self.open = q.open
        # No depth feed: build an L1-only book from best bid/ask (labelled as such).
        if not self.has_depth_feed and (q.bid or q.ask):
            bids = [(q.bid, q.bid_qty or 0.0)] if q.bid and q.bid_qty else []
            asks = [(q.ask, q.ask_qty or 0.0)] if q.ask and q.ask_qty else []
            changes = self.book.apply_snapshot(bids, asks, q.ts, BookResolution.L1_ONLY)
            self._on_book_changes(changes, q.ts)
        for p in (q.bid, q.ask, q.last):
            if p:
                self.tick.observe(p)

    def on_book_snapshot(self, s: BookSnapshot) -> None:
        if s.resolution != BookResolution.L1_ONLY:
            self.has_depth_feed = True
        changes = self.book.apply_snapshot(s.bids, s.asks, s.ts, s.resolution)
        self.last_event_ms = max(self.last_event_ms, s.ts)
        self._on_book_changes(changes, s.ts)

    def on_book_delta(self, d: BookDelta) -> None:
        self.has_depth_feed = True
        ch = self.book.apply_delta(d.side, d.price, d.quantity, d.ts)
        self.last_event_ms = max(self.last_event_ms, d.ts)
        if ch is not None:
            self._on_book_changes([ch], d.ts)

    def _on_book_changes(self, changes: list[LevelChange], ts: int) -> None:
        self.icebergs.resolution = self.book.resolution
        for ch in changes:
            self.icebergs.on_level_change(ch, ts)

    def on_trade(self, t: Trade) -> Trade:
        self._new_session_check(t.ts)
        self.tick.observe(t.price)
        if t.method == ClassificationMethod.UNKNOWN or t.side == Side.UNKNOWN:
            bid = self.book.best_bid if self.book.bids else (self.quote.bid if self.quote else None)
            ask = self.book.best_ask if self.book.asks else (self.quote.ask if self.quote else None)
            c = self.classifier.classify(t.price, t.ts, None, bid, ask, self.book.ts or self.quote_ts)
            t.side, t.method, t.confidence = c.side, c.method, c.confidence
        else:
            self.classifier.classify(t.price, t.ts, t.side)  # keep tick state current

        self.trades.append(t)
        self.last_price = t.price
        self.last_event_ms = max(self.last_event_ms, t.ts)
        if self.open is None:
            self.open = t.price
        self.high = t.price if self.high is None else max(self.high, t.price)
        self.low = t.price if self.low is None else min(self.low, t.price)
        self.volume += t.quantity
        self.value += t.value
        self.trade_count += 1
        self.cvd.add(t)
        self.profile.add_trade(t)
        self.bars.add(t)
        self.vwap.add(t.price, t.quantity, t.ts)
        self.walls.on_trade(t.price, t.quantity)
        self.icebergs.on_trade(
            t.price, t.quantity, t.side, t.ts,
            self.book.qty_at(BookSide.BID, t.price), self.book.qty_at(BookSide.ASK, t.price),
            self.book.best_bid, self.book.best_ask,
        )
        self.absorption.on_trade(t)
        self._aggregate_print(t)
        self._out_trades.append(t)
        return t

    # Fills sharing a timestamp and aggressor side are one aggressive order walking
    # the book; large-lot detection works on that aggregated print.
    def _aggregate_print(self, t: Trade) -> None:
        a = self._agg
        if a is not None and a[0] == t.ts and a[1] == t.side and t.side != Side.UNKNOWN:
            a[2].append(t)
            return
        self._flush_print()
        self._agg = [t.ts, t.side, [t]]

    def _flush_print(self) -> None:
        a = self._agg
        if a is None:
            return
        self._agg = None
        fills: list[Trade] = a[2]
        if len(fills) == 1:
            p = fills[0]
        else:
            qty = sum(f.quantity for f in fills)
            vwap = sum(f.value for f in fills) / qty
            f0 = fills[0]
            p = Trade(
                trade_id=f"{f0.trade_id}+{len(fills) - 1}", symbol=f0.symbol, price=round(vwap, 4),
                quantity=qty, ts=f0.ts, source=f0.source, quality=f0.quality, side=f0.side,
                method=f0.method, confidence=min(f.confidence for f in fills), received_ts=f0.received_ts,
            )
        lt = self.llt.on_trade(p)
        if lt is not None:
            self.large_trades.append(lt)
            d = lt.to_dict()
            d["fills"] = len(fills)
            d["price_range"] = [min(f.price for f in fills), max(f.price for f in fills)]
            self._emit({"type": "large_trade", **d})

    # --------------------------------------------------------------- periodic
    def sample(self, ts: int) -> HeatColumn | None:
        """Capture a heatmap column and update liquidity analytics."""
        if self._agg is not None and self._agg[0] < ts:
            self._flush_print()
        col = self.heatmap.capture(self.book, ts, self.last_price)
        if col is not None:
            self._out_columns.append(col)
        if self.book.bids or self.book.asks:
            bids, asks = self.book.top(self.imbalance_levels)
            self.imbalance = book_imbalance(bids, asks, self.imbalance_levels)
            depth = sum(q for _, q in bids) + sum(q for _, q in asks)
            self.depth_hist.append((ts, depth))
            evs = self.walls.update(self.book, ts, self.heatmap.typical_level, self.tick.tick)
            for e in evs:
                self.wall_events.append(e)
                self._emit({"type": "wall", **e.to_dict(), "symbol": self.symbol})
        return col

    def analytics_tick(self, ts: int) -> list[dict[str, Any]]:
        """Slower analytics (every few seconds). Returns new signal events."""
        new: list[dict[str, Any]] = []
        prev_ice = {(s.side, s.price) for s in self.iceberg_signals}
        self.iceberg_signals = self.icebergs.evaluate(ts, self.book.best_bid, self.book.best_ask)
        for s in self.iceberg_signals:
            if (s.side, s.price) not in prev_ice:
                new.append({"type": "iceberg", **s.to_dict()})
        for a in self.absorption.evaluate(ts, self.book.best_bid, self.book.best_ask, self.tick.tick,
                                          self.heatmap.typical_level):
            self.absorptions.append(a)
            new.append({"type": "absorption", **a.to_dict()})

        bars = self.bars.series(30)
        cut = ts - WINDOW_MS
        lb = sum(x.value for x in self.large_trades if x.trade.ts >= cut and x.trade.side == Side.BUY)
        ls = sum(x.value for x in self.large_trades if x.trade.ts >= cut and x.trade.side == Side.SELL)
        persistent = [w for w in self.walls.walls.values() if w.reported and w.persistence_ms >= 60_000]
        ev = FlowEvidence(
            bars=bars[-15:],
            large_buy_value=lb,
            large_sell_value=ls,
            bullish_absorptions=sum(1 for a in self.absorptions if a.ts >= cut and a.kind == "bullish"),
            bearish_absorptions=sum(1 for a in self.absorptions if a.ts >= cut and a.kind == "bearish"),
            bid_icebergs=sum(1 for s in self.iceberg_signals if s.side == "bid"),
            ask_icebergs=sum(1 for s in self.iceberg_signals if s.side == "ask"),
            bid_wall_persistence_ms=sum(w.persistence_ms for w in persistent if w.side == "bid"),
            ask_wall_persistence_ms=sum(w.persistence_ms for w in persistent if w.side == "ask"),
        )
        prev_kind = self.flow.kind if self.flow else "neutral"
        self.flow = evaluate_flow(ev)
        if self.flow.kind != "neutral" and self.flow.kind != prev_kind:
            new.append({"type": "flow", "symbol": self.symbol, "ts": ts, **self.flow.to_dict()})

        # CVD divergence on 1-minute bars (cumulative per bar)
        allbars = self.bars.series(60)
        cum, closes = [], []
        c = 0.0
        for b in allbars:
            c += b.delta
            cum.append(c)
            closes.append(b.close)
        prev_div = self.divergence
        self.divergence = detect_divergence(closes, cum, lookback=min(20, max(5, len(closes) - 1)))
        if self.divergence and (not prev_div or prev_div["kind"] != self.divergence["kind"]):
            new.append({"type": "cvd_divergence", "symbol": self.symbol, "ts": ts, **self.divergence})

        self.whale = whale_score(self._whale_inputs(ts))
        for e in new:
            self._emit(e)
        return new

    def _emit(self, ev: dict[str, Any]) -> None:
        self._out_events.append(ev)
        self._alert_events.append(ev)

    def pop_alert_events(self) -> list[dict[str, Any]]:
        out, self._alert_events = self._alert_events, []
        return out

    def _whale_inputs(self, ts: int) -> WhaleInputs:
        cut = ts - WINDOW_MS
        recent_large = [x for x in self.large_trades if x.trade.ts >= cut]
        win_value = 0.0
        largest = 0.0
        for t in reversed(self.trades):
            if t.ts < cut:
                break
            win_value += t.value
            largest = max(largest, t.value)
        large_value = sum(x.value for x in recent_large)
        session_ms = max(1, (self.trades[-1].ts - self.trades[0].ts)) if self.trades else 1
        windows = max(1.0, session_ms / WINDOW_MS)
        baseline = max(0.5, len(self.large_trades) / windows)
        depth_change = 0.0
        if len(self.depth_hist) > 2:
            old = next((d for t0, d in self.depth_hist if t0 >= ts - 300_000), self.depth_hist[0][1])
            cur = self.depth_hist[-1][1]
            depth_change = (cur - old) / old * 100 if old else 0.0
        conc = 0.0
        if self.imbalance:
            conc = (self.imbalance.bid_concentration + self.imbalance.ask_concentration) / 2
        return WhaleInputs(
            largest_trade_pctile=self.llt.values.rank(largest) if largest else 0.0,
            large_value_share=large_value / win_value if win_value else 0.0,
            large_trades_recent=len(recent_large),
            large_trades_baseline=baseline,
            rvol=self.rvol(ts),
            liquidity_concentration=conc,
            persistent_walls=sum(1 for w in self.walls.walls.values() if w.reported and w.persistence_ms >= 60_000),
            absorption_events=sum(1 for a in self.absorptions if a.ts >= cut),
            cvd_divergence=self.divergence["strength"] if self.divergence else 0.0,
            depth_change_pct=depth_change,
        )

    def rvol(self, ts: int, session_open_ms: int | None = None, session_len_ms: int = 4.5 * 3600_000) -> float | None:  # type: ignore[assignment]
        """Time-of-day adjusted relative volume vs average daily volume."""
        if not self.adv or not self.trades:
            return None
        start = session_open_ms or self.trades[0].ts
        frac = min(1.0, max(0.02, (ts - start) / session_len_ms))
        return round(self.volume / (self.adv * frac), 3)

    # ---------------------------------------------------------------- output
    def stats(self) -> dict[str, Any]:
        chg = None
        if self.last_price is not None and self.prev_close:
            chg = (self.last_price - self.prev_close) / self.prev_close * 100
        q = self.quote
        return {
            "symbol": self.symbol,
            "last": self.last_price,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "prev_close": self.prev_close,
            "change_pct": round(chg, 3) if chg is not None else (q.change_pct if q else None),
            "volume": self.volume if self.volume else (q.volume if q and q.volume else 0.0),
            "value": self.value if self.value else (q.value if q and q.value else 0.0),
            "trades": self.trade_count,
            "vwap": self.vwap.value,
            "vwap_bands": self.vwap.bands(1.0),
            "best_bid": self.book.best_bid,
            "best_ask": self.book.best_ask,
            "spread": self.book.spread,
            "tick": self.tick.tick,
            "tick_source": self.tick.source,
            "book_resolution": self.book.resolution.value,
            "quality": self.quality.value,
            "last_event_ms": self.last_event_ms,
            "rvol": self.rvol(self.last_event_ms) if self.last_event_ms else None,
            "cvd": self.cvd.summary(),
            "imbalance": self.imbalance.to_dict() if self.imbalance else None,
            "whale_score": self.whale["score"] if self.whale else None,
            "flow": self.flow.kind if self.flow else None,
        }

    def snapshot(self, columns: int = 1800, trades: int = 4000) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "instrument": self.instrument.to_dict(),
            "stats": self.stats(),
            "columns": [c.to_wire() for c in self.heatmap.since(0, columns)],
            "trades": [t.to_wire() for t in list(self.trades)[-trades:]],
            "cvd": [[p.t, p.cvd] for p in self.cvd.points][-columns * 2 :],
            "bars": [b.to_dict() for b in self.bars.series(240)],
            "book": self.book.to_dict(40),
            "profile": self.profile.to_dict(),
            "walls": self.walls.active(),
            "icebergs": [s.to_dict() for s in self.iceberg_signals],
            "large_trades": [x.to_dict() for x in list(self.large_trades)[-100:]],
            "absorptions": [a.to_dict() for a in list(self.absorptions)[-50:]],
            "flow": self.flow.to_dict() if self.flow else None,
            "whale": self.whale,
            "divergence": self.divergence,
        }

    def drain_updates(self, include_profile: bool = True) -> dict[str, Any] | None:
        if not (self._out_trades or self._out_columns or self._out_events):
            return None
        cvd = self.cvd.series_since(self._out_cvd_from)
        if self.cvd.points:
            self._out_cvd_from = self.cvd.points[-1].t - 1
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "trades": [t.to_wire() for t in self._out_trades],
            "columns": [c.to_wire() for c in self._out_columns],
            "cvd": cvd,
            "events": self._out_events,
            "stats": self.stats(),
            "book": self.book.to_dict(40),
        }
        if include_profile:
            payload["profile"] = self.profile.to_dict()
            payload["bar"] = self.bars.bars[-1].to_dict() if self.bars.bars else None
            payload["icebergs"] = [s.to_dict() for s in self.iceberg_signals]
            payload["walls"] = self.walls.active()
            payload["whale"] = self.whale
            payload["flow"] = self.flow.to_dict() if self.flow else None
        self._out_trades = []
        self._out_columns = []
        self._out_events = []
        return payload

    def discard_updates(self) -> None:
        self._out_trades = []
        self._out_columns = []
        self._out_events = []
        if self.cvd.points:
            self._out_cvd_from = self.cvd.points[-1].t - 1
