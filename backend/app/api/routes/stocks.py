from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.analytics.indicators import atr, ema, macd, relative_volume, rsi, sma
from app.analytics.vwap import anchored_vwap_series
from app.api.deps import container, norm_symbol
from app.services.container import Container

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("")
async def explorer(c: Container = Depends(container)) -> dict[str, Any]:
    return {"quality": c.hub.quality.value, "rows": c.hub.explorer(),
            "notes": ["liquidity_score is a local heuristic (near-touch depth value + spread)."]}


@router.get("/{symbol}")
async def stock(symbol: str, c: Container = Depends(container)) -> dict[str, Any]:
    sym = norm_symbol(symbol)
    st = await c.hub.ensure_symbol(sym)
    if st is None:
        raise HTTPException(404, "unknown symbol")
    return {"instrument": st.instrument.to_dict(), "stats": st.stats()}


@router.post("/{symbol}/subscribe")
async def subscribe(symbol: str, c: Container = Depends(container)) -> dict[str, Any]:
    st = await c.hub.ensure_symbol(norm_symbol(symbol))
    if st is None:
        raise HTTPException(404, "unknown symbol")
    return {"ok": True}


@router.get("/{symbol}/candles")
async def candles(symbol: str, period: str = Query("Year", pattern="^(Day|Week|Month|Year)$"),
                  date_from: str | None = None, date_to: str | None = None,
                  c: Container = Depends(container)) -> dict[str, Any]:
    sym = norm_symbol(symbol)
    try:
        cs = await c.market_provider.historical_candles(sym, period, date_from, date_to)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"provider error: {type(exc).__name__}") from None
    return {"symbol": sym, "period": period, "quality": c.hub.quality.value if c.hub.quality.value == "simulated" else "historical",
            "candles": [x.to_dict() for x in cs]}


@router.get("/{symbol}/bars")
async def bars(symbol: str, limit: int = Query(240, le=2000), c: Container = Depends(container)) -> dict[str, Any]:
    st = c.hub.states.get(norm_symbol(symbol))
    if st is None:
        raise HTTPException(404, "symbol not streaming")
    return {"symbol": st.symbol, "interval_ms": st.bars.interval_ms, "bars": [b.to_dict() for b in st.bars.series(limit)]}


@router.get("/{symbol}/indicators")
async def indicators(
    symbol: str,
    source: str = Query("intraday", pattern="^(intraday|daily)$"),
    sma_period: int = Query(20, ge=2, le=400),
    ema_period: int = Query(50, ge=2, le=400),
    rsi_period: int = Query(14, ge=2, le=200),
    atr_period: int = Query(14, ge=2, le=200),
    macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9,
    rvol_lookback: int = Query(20, ge=2, le=200),
    anchor_ts: int | None = None,
    c: Container = Depends(container),
) -> dict[str, Any]:
    sym = norm_symbol(symbol)
    st = await c.hub.ensure_symbol(sym)
    if st is None:
        raise HTTPException(404, "unknown symbol")
    if source == "daily":
        cs = await c.market_provider.historical_candles(sym, "Year")
        ts = [x.ts for x in cs]
        o, h, l_, cl, v = ([getattr(x, k) for x in cs] for k in ("open", "high", "low", "close", "volume"))
        avwap: list[Any] = []
    else:
        bars = st.bars.series()
        ts = [b.t for b in bars]
        h = [b.high for b in bars]
        l_ = [b.low for b in bars]
        cl = [b.close for b in bars]
        v = [b.volume for b in bars]
        pts = [(t.ts, t.price, t.quantity) for t in st.trades]
        avwap = anchored_vwap_series(pts, anchor_ts)[-2000:] if anchor_ts else []
    m_line, m_sig, m_hist = macd(cl, macd_fast, macd_slow, macd_signal)
    return {
        "symbol": sym, "source": source, "ts": ts, "close": cl,
        "sma": sma(cl, sma_period), "ema": ema(cl, ema_period), "rsi": rsi(cl, rsi_period),
        "macd": {"line": m_line, "signal": m_sig, "hist": m_hist},
        "atr": atr(h, l_, cl, atr_period), "rvol": relative_volume(v, rvol_lookback),
        "vwap": st.vwap.value, "vwap_bands": st.vwap.bands(1.0), "anchored_vwap": avwap,
        "params": {"sma": sma_period, "ema": ema_period, "rsi": rsi_period, "atr": atr_period,
                   "macd": [macd_fast, macd_slow, macd_signal], "rvol": rvol_lookback},
    }
