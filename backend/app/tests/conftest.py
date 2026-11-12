from __future__ import annotations

import os
import tempfile

import pytest

# Never require real credentials for tests; force demo mode & a temp DB.
_tmp = tempfile.mkdtemp(prefix="egxflow-test-")
os.environ.update({
    "DATA_MODE": "demo",
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{_tmp.replace(os.sep, '/')}/test.db",
    "DEMO_PREWARM_MINUTES": "2",
    "TRADING_ID": "",
    "API_KEY": "",
    "APP_ACCESS_TOKEN": "",
    "LOG_LEVEL": "WARNING",
})

from app.domain.models import ClassificationMethod, DataQuality, Side, Trade  # noqa: E402


def mk_trade(i: int, price: float, qty: float, side: Side = Side.BUY, ts: int | None = None,
             method: ClassificationMethod = ClassificationMethod.PROVIDER, symbol: str = "TEST") -> Trade:
    return Trade(
        trade_id=str(i), symbol=symbol, price=price, quantity=qty, ts=ts if ts is not None else 1_700_000_000_000 + i * 1000,
        source="test", quality=DataQuality.SIMULATED, side=side, method=method,
        confidence=1.0 if method == ClassificationMethod.PROVIDER else 0.6,
    )


@pytest.fixture
def trade_factory():
    return mk_trade
