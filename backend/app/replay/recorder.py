"""Market-data recorder.

Persists exactly what was received/derived - nothing is fabricated:

* every accepted trade (original event ts, receive ts, source, quality,
  classification method);
* order-book snapshots at ``book_interval_ms`` (top N levels). The recorded
  book resolution is stored on the session so replay can label it honestly;
* L1 quotes (sampled at the same interval);
* whale and liquidity events.

Writes are batched and executed off the event loop.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.core.logging import get_logger
from app.core.timeutil import cairo_date
from app.database.models import OrderBookSnapshotRow, QuoteRow, TradeRow
from app.database.repositories import market_repo
from app.domain.models import Quote, Trade
from app.market_data.orderbook_engine import OrderBook

log = get_logger(__name__)


class Recorder:
    def __init__(self, enabled: bool, book_interval_ms: int, book_levels: int = 30) -> None:
        self.enabled = enabled
        self.book_interval_ms = book_interval_ms
        self.book_levels = book_levels
        self._trades: list[dict[str, Any]] = []
        self._books: list[dict[str, Any]] = []
        self._quotes: list[dict[str, Any]] = []
        self._whale: list[dict[str, Any]] = []
        self._liq: list[dict[str, Any]] = []
        self._last_book: dict[str, int] = {}
        self._last_quote: dict[str, int] = {}
        # (date, symbol, source) -> [first, last, trades, books, quality, resolution]
        self._sess: dict[tuple[str, str, str], list[Any]] = {}
        self.written = defaultdict(int)
        self._lock = asyncio.Lock()

    def _touch(self, sym: str, ts: int, source: str, quality: str, resolution: str | None, trade: bool) -> None:
        key = (cairo_date(ts).isoformat(), sym, source)
        s = self._sess.get(key)
        if s is None:
            s = self._sess[key] = [ts, ts, 0, 0, quality, resolution or "none"]
        s[0] = min(s[0], ts)
        s[1] = max(s[1], ts)
        if trade:
            s[2] += 1
        else:
            s[3] += 1
            if resolution:
                s[5] = resolution

    def record_trade(self, t: Trade) -> None:
        if not self.enabled:
            return
        self._trades.append({
            "symbol": t.symbol, "ts": t.ts, "trade_id": t.trade_id, "price": t.price, "quantity": t.quantity,
            "value": t.value, "side": t.side.value, "method": t.method.value, "confidence": t.confidence,
            "provider_side_raw": t.provider_side_raw, "received_ts": t.received_ts or t.ts,
            "source": t.source, "quality": t.quality.value,
        })
        self._touch(t.symbol, t.ts, t.source, t.quality.value, None, True)

    def maybe_record_book(self, book: OrderBook, ts: int, source: str, quality: str) -> None:
        if not self.enabled or (not book.bids and not book.asks):
            return
        last = self._last_book.get(book.symbol, 0)
        if ts - last < self.book_interval_ms:
            return
        self._last_book[book.symbol] = ts
        bids, asks = book.top(self.book_levels)
        self._books.append({
            "symbol": book.symbol, "ts": ts, "bids": [[p, q] for p, q in bids], "asks": [[p, q] for p, q in asks],
            "resolution": book.resolution.value, "source": source, "quality": quality,
        })
        self._touch(book.symbol, ts, source, quality, book.resolution.value, False)

    def record_quote(self, q: Quote) -> None:
        if not self.enabled:
            return
        last = self._last_quote.get(q.symbol, 0)
        if q.ts - last < self.book_interval_ms:
            return
        self._last_quote[q.symbol] = q.ts
        self._quotes.append({
            "symbol": q.symbol, "ts": q.ts, "received_ts": q.received_ts or q.ts, "bid": q.bid, "ask": q.ask,
            "last": q.last, "bid_qty": q.bid_qty, "ask_qty": q.ask_qty, "volume": q.volume, "value": q.value,
            "source": q.source, "quality": q.quality.value,
        })

    def record_event(self, ev: dict[str, Any], source: str) -> None:
        if not self.enabled:
            return
        t = ev.get("type")
        if t == "wall":
            w = ev["wall"]
            self._liq.append({"symbol": w["symbol"], "ts": ev["ts"], "kind": ev["kind"], "side": w["side"],
                              "price": w["price"], "quantity": w["qty"], "payload": ev, "source": source})
        elif t in ("large_trade", "iceberg", "absorption", "flow", "cvd_divergence"):
            ts = ev.get("ts") or ev.get("last_ts") or 0
            val = ev.get("value") or ev.get("aggressive_value") or ev.get("estimated_hidden")
            self._whale.append({"symbol": ev.get("symbol"), "ts": ts, "kind": t, "value": val,
                                "payload": ev, "source": source})

    async def flush(self) -> None:
        if not self.enabled:
            return
        async with self._lock:
            trades, books, quotes = self._trades, self._books, self._quotes
            whale, liq, sess = self._whale, self._liq, self._sess
            self._trades, self._books, self._quotes, self._whale, self._liq, self._sess = [], [], [], [], [], {}
            if not (trades or books or quotes or whale or liq or sess):
                return
            try:
                await asyncio.to_thread(self._write, trades, books, quotes, whale, liq, sess)
            except Exception as exc:  # noqa: BLE001
                log.error("recorder_flush_failed", error=repr(exc)[:300])

    def _write(self, trades: list[dict[str, Any]], books: list[dict[str, Any]], quotes: list[dict[str, Any]],
               whale: list[dict[str, Any]], liq: list[dict[str, Any]], sess: dict[tuple[str, str, str], list[Any]]) -> None:
        market_repo.bulk_insert_ignore(TradeRow, trades)
        market_repo.bulk_insert_ignore(OrderBookSnapshotRow, books)
        market_repo.bulk_insert_ignore(QuoteRow, quotes)
        market_repo.save_whale_events(whale)
        market_repo.save_liquidity_events(liq)
        for (d, sym, src), (first, last, nt, nb, q, res) in sess.items():
            market_repo.upsert_session(d, sym, src, q, res, self.book_interval_ms, first, last, nt, nb)
        self.written["trades"] += len(trades)
        self.written["book_snapshots"] += len(books)
        self.written["quotes"] += len(quotes)
        self.written["whale_events"] += len(whale)
        self.written["liquidity_events"] += len(liq)
