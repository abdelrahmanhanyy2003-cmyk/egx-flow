"""Aggressor-side classification.

Order of precedence:

1. Provider-supplied side (only when the provider documents it as the aggressor
   side, or when the operator explicitly mapped the provider field).
2. Quote rule (Lee-Ready style) against the prevailing best bid/ask - ESTIMATED.
3. Tick rule against the previous trade price - ESTIMATED.
4. Otherwise UNKNOWN. We never invent a side.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import ClassificationMethod, Side

EPS = 1e-9


@dataclass(slots=True)
class Classification:
    side: Side
    method: ClassificationMethod
    confidence: float


class TradeClassifier:
    def __init__(self, max_quote_age_ms: int = 5000) -> None:
        self.max_quote_age_ms = max_quote_age_ms
        self._last_price: float | None = None
        self._last_dir: Side = Side.UNKNOWN

    def classify(
        self,
        price: float,
        ts: int,
        provider_side: Side | None = None,
        bid: float | None = None,
        ask: float | None = None,
        quote_ts: int | None = None,
    ) -> Classification:
        result = self._classify(price, ts, provider_side, bid, ask, quote_ts)
        # update tick state
        if self._last_price is not None:
            if price > self._last_price + EPS:
                self._last_dir = Side.BUY
            elif price < self._last_price - EPS:
                self._last_dir = Side.SELL
        self._last_price = price
        return result

    def _classify(
        self,
        price: float,
        ts: int,
        provider_side: Side | None,
        bid: float | None,
        ask: float | None,
        quote_ts: int | None,
    ) -> Classification:
        if provider_side in (Side.BUY, Side.SELL):
            return Classification(provider_side, ClassificationMethod.PROVIDER, 1.0)

        quote_fresh = (
            bid is not None
            and ask is not None
            and ask > bid
            and (quote_ts is None or 0 <= ts - quote_ts <= self.max_quote_age_ms)
        )
        if quote_fresh:
            assert bid is not None and ask is not None
            if price >= ask - EPS:
                return Classification(Side.BUY, ClassificationMethod.QUOTE_RULE, 0.9)
            if price <= bid + EPS:
                return Classification(Side.SELL, ClassificationMethod.QUOTE_RULE, 0.9)
            mid = (bid + ask) / 2
            if price > mid + EPS:
                return Classification(Side.BUY, ClassificationMethod.QUOTE_RULE, 0.65)
            if price < mid - EPS:
                return Classification(Side.SELL, ClassificationMethod.QUOTE_RULE, 0.65)
            # exactly at mid -> fall through to tick rule

        if self._last_price is not None:
            if price > self._last_price + EPS:
                return Classification(Side.BUY, ClassificationMethod.TICK_RULE, 0.55)
            if price < self._last_price - EPS:
                return Classification(Side.SELL, ClassificationMethod.TICK_RULE, 0.55)
            if self._last_dir != Side.UNKNOWN:  # zero tick -> last non-zero tick
                return Classification(self._last_dir, ClassificationMethod.TICK_RULE, 0.5)
        return Classification(Side.UNKNOWN, ClassificationMethod.UNKNOWN, 0.0)
