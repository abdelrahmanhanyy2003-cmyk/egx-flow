"""Classic technical indicators (pure functions, unit-tested).

All functions return lists aligned with the input; positions without enough
history are ``None``.
"""

from __future__ import annotations

from collections.abc import Sequence

Num = float | None


def sma(values: Sequence[float], period: int) -> list[Num]:
    out: list[Num] = [None] * len(values)
    if period <= 0:
        return out
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def ema(values: Sequence[float], period: int) -> list[Num]:
    """EMA seeded with the SMA of the first ``period`` values."""
    out: list[Num] = [None] * len(values)
    if len(values) < period or period <= 0:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: Sequence[float], period: int = 14) -> list[Num]:
    """Wilder's RSI."""
    out: list[Num] = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[Num], list[Num], list[Num]]:
    ef, es = ema(closes, fast), ema(closes, slow)
    line: list[Num] = [
        (f - s) if f is not None and s is not None else None for f, s in zip(ef, es)
    ]
    start = next((i for i, v in enumerate(line) if v is not None), None)
    sig: list[Num] = [None] * len(closes)
    if start is not None:
        sub = [v for v in line[start:] if v is not None]
        se = ema(sub, signal)
        for j, v in enumerate(se):
            sig[start + j] = v
    hist: list[Num] = [
        (m - s) if m is not None and s is not None else None for m, s in zip(line, sig)
    ]
    return line, sig, hist


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(len(closes)):
        if i == 0:
            out.append(highs[0] - lows[0])
        else:
            pc = closes[i - 1]
            out.append(max(highs[i] - lows[i], abs(highs[i] - pc), abs(lows[i] - pc)))
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> list[Num]:
    """Wilder's ATR seeded with the simple mean of the first ``period`` TRs."""
    tr = true_range(highs, lows, closes)
    out: list[Num] = [None] * len(tr)
    if len(tr) < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def relative_volume(volumes: Sequence[float], lookback: int = 20) -> list[Num]:
    """Volume divided by the average of the *previous* ``lookback`` values."""
    out: list[Num] = [None] * len(volumes)
    for i in range(lookback, len(volumes)):
        avg = sum(volumes[i - lookback : i]) / lookback
        out[i] = volumes[i] / avg if avg else None
    return out


def breadth(advances: int, declines: int, unchanged: int = 0) -> dict[str, float | None]:
    total = advances + declines + unchanged
    return {
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "ad_ratio": advances / declines if declines else None,
        "ad_line": advances - declines,
        "pct_advancing": advances / total * 100 if total else None,
    }


def volume_imbalance(buy_volume: float, sell_volume: float) -> float:
    """(buy - sell) / (buy + sell) in [-1, 1]."""
    tot = buy_volume + sell_volume
    return (buy_volume - sell_volume) / tot if tot else 0.0
