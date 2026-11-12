"""AUTHORIZED live connectivity checks against EFG Hermes Younit.

Skipped by default. Run only with your own credentials in backend/.env:

    EGXFLOW_LIVE_TESTS=1 pytest app/tests/test_live_efg.py -v

Only read-only SDK calls are made (account_info, list_stocks, quote,
portfolio, positions). Nothing is placed, amended or cancelled.
"""

from __future__ import annotations

import os

import pytest

from app.core.config import Settings
from app.integrations.efg_hermes.authentication import sdk_available

pytestmark = pytest.mark.skipif(
    os.environ.get("EGXFLOW_LIVE_TESTS") != "1", reason="live tests disabled (set EGXFLOW_LIVE_TESTS=1)"
)


@pytest.fixture(scope="module")
def client():
    if not sdk_available():
        pytest.skip("younit SDK not installed")
    s = Settings(_env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
    if not s.has_broker_credentials:
        pytest.skip("credentials not configured")
    from app.integrations.efg_hermes.authentication import create_sdk_client
    from app.integrations.efg_hermes.client import ReadOnlyYounitClient

    c = ReadOnlyYounitClient(create_sdk_client(s))
    yield c
    c.close()


def test_live_list_stocks_and_quote(client):
    stocks = client.call("list_stocks")
    assert stocks
    q = client.call("quote", "COMI")
    assert q.symbol == "COMI"


def test_live_portfolio_read(client):
    s = client.call("portfolio")
    assert s is not None
    assert isinstance(client.call("positions"), list)
