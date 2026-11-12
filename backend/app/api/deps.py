from __future__ import annotations

from fastapi import HTTPException, Request

from app.services.container import Container


def container(request: Request) -> Container:
    c = getattr(request.app.state, "container", None)
    if c is None:
        raise HTTPException(503, "service starting")
    return c


def norm_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if not s.isalnum() or len(s) > 16:
        raise HTTPException(400, "invalid symbol")
    return s
