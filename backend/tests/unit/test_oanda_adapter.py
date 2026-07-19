"""Unit tests for the OANDA v20 adapter.

Mirrors the CFT adapter pattern: httpx.MockTransport (no network, no respx).
Covers auth, account/position parsing, order placement (units = lots*100k +
sign by direction), partial close, and typed error handling.
"""
from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.core.exceptions import (
    BrokerConnectionError,
    BrokerError,
    BrokerRateLimitError,
)
from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest
from app.services.broker.oanda import (
    OANDA_BASE_URLS,
    OANDAAdapter,
    from_oanda_pair,
    to_oanda_pair,
)

ACCOUNT_SUMMARY = {
    "account": {
        "id": "001-001-12345-001",
        "balance": "10000.00",
        "NAV": "10050.00",
        "currency": "USD",
        "marginUsed": "250.00",
        "marginAvailable": "9800.00",
        "openTradeCount": 1,
        "unrealizedPL": "50.00",
    }
}

OPEN_POSITIONS_LONG = {
    "positions": [
        {
            "instrument": "EUR_USD",
            "long": {
                "units": "10000",
                "averagePrice": "1.08500",
                "unrealizedPL": "12.50",
                "tradeIDs": ["1234"],
                "openTime": "2026-05-29T10:00:00.000000000Z",
            },
            "short": {"units": "0"},
        }
    ]
}

OPEN_POSITIONS_SHORT = {
    "positions": [
        {
            "instrument": "USD_JPY",
            "long": {"units": "0"},
            "short": {
                "units": "-50000",
                "averagePrice": "149.50",
                "unrealizedPL": "-25.00",
                "tradeIDs": ["5678"],
                "openTime": "2026-05-29T11:00:00.000000000Z",
            },
        }
    ]
}


def _adapter() -> OANDAAdapter:
    return OANDAAdapter(api_key="tok", account_id="001-001-12345-001", environment="practice")


def _install(adapter: OANDAAdapter, handler) -> None:
    adapter._client = httpx.AsyncClient(
        base_url=OANDA_BASE_URLS["practice"],
        transport=httpx.MockTransport(handler),
    )


# ---------------------------------------------------------------------------
# Construction / helpers
# ---------------------------------------------------------------------------


def test_unknown_environment_raises():
    with pytest.raises(ValueError):
        OANDAAdapter(api_key="k", account_id="a", environment="staging")


def test_pair_round_trip():
    assert to_oanda_pair("EUR/USD") == "EUR_USD"
    assert from_oanda_pair("EUR_USD") == "EUR/USD"
    assert to_oanda_pair("EUR_USD") == "EUR_USD"


def test_broker_name():
    assert _adapter().broker_name == "oanda"


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_validates_via_summary():
    a = _adapter()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=ACCOUNT_SUMMARY)

    _install(a, handler)
    await a.connect()
    assert a.connected is True
    # connect() validates by calling the account summary endpoint
    assert any(p.endswith("/summary") for p in calls)


@pytest.mark.asyncio
async def test_connect_401_raises_typed_error():
    a = _adapter()
    _install(a, lambda req: httpx.Response(401, json={"errorMessage": "bad token"}))
    with pytest.raises(BrokerConnectionError):
        await a.connect()


@pytest.mark.asyncio
async def test_connect_429_raises_rate_limit():
    a = _adapter()
    _install(a, lambda req: httpx.Response(429, json={}, headers={"Retry-After": "60"}))
    with pytest.raises(BrokerRateLimitError) as exc:
        await a.connect()
    assert exc.value.retry_after_seconds == 60


# ---------------------------------------------------------------------------
# get_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_maps_fields():
    a = _adapter()
    _install(a, lambda req: httpx.Response(200, json=ACCOUNT_SUMMARY))
    acct = await a.get_account()
    assert acct.broker == "oanda"
    assert acct.balance == 10000.00
    assert acct.equity == 10050.00
    assert acct.currency == "USD"
    assert acct.margin_used == 250.00
    assert acct.open_trade_count == 1
    assert acct.unrealized_pl == 50.00


# ---------------------------------------------------------------------------
# get_positions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_positions_long_side():
    a = _adapter()
    _install(a, lambda req: httpx.Response(200, json=OPEN_POSITIONS_LONG))
    positions = await a.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert p.pair == "EUR/USD"
    assert p.direction == DirectionType.LONG
    assert p.entry_price == Decimal("1.08500")
    assert p.lot_size == Decimal("10000")


@pytest.mark.asyncio
async def test_get_positions_short_side():
    a = _adapter()
    _install(a, lambda req: httpx.Response(200, json=OPEN_POSITIONS_SHORT))
    positions = await a.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert p.pair == "USD/JPY"
    assert p.direction == DirectionType.SHORT
    assert p.lot_size == Decimal("50000")


@pytest.mark.asyncio
async def test_get_positions_skips_empty_positions():
    a = _adapter()
    _install(a, lambda req: httpx.Response(200, json={"positions": [
        {"instrument": "EUR_USD", "long": {"units": "0"}, "short": {"units": "0"}},
    ]}))
    positions = await a.get_positions()
    assert positions == []


# ---------------------------------------------------------------------------
# place_order — the critical unit conversion + SL/TP rounding
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Real-money write path is DISABLED. OANDA is retained only for practice/data;
# place_order / close_position / close_all_positions must REFUSE before any
# network call. These tests pin that safety property (they replace the former
# payload-construction tests, which exercised the now-unreachable code).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_place_order_refuses_real_money():
    a = _adapter()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["hit"] = True  # must never be reached
        return httpx.Response(200, json={})

    _install(a, handler)
    req = OrderRequest(
        pair="EUR/USD",
        direction=DirectionType.LONG,
        order_type=OrderType.MARKET,
        lot_size=0.1,
    )
    with pytest.raises(BrokerError):
        await a.place_order(req)
    assert "hit" not in captured  # refused before any HTTP call


@pytest.mark.asyncio
async def test_close_position_refuses_real_money():
    a = _adapter()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["hit"] = True
        return httpx.Response(200, json={})

    _install(a, handler)
    with pytest.raises(BrokerError):
        await a.close_position("EUR_USD")
    assert "hit" not in captured


@pytest.mark.asyncio
async def test_close_all_positions_refuses_real_money():
    a = _adapter()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["hit"] = True
        return httpx.Response(200, json={})

    _install(a, handler)
    with pytest.raises(BrokerError):
        await a.close_all_positions()
    assert "hit" not in captured


@pytest.mark.asyncio
async def test_oanda_is_not_simulation():
    a = _adapter()
    assert a.is_simulation is False


def test_oanda_live_host_not_constructible():
    from app.services.broker.oanda import OANDAAdapter
    with pytest.raises(ValueError):
        OANDAAdapter(api_key="k", account_id="a", environment="live")


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_4xx_raises_broker_error():
    a = _adapter()
    _install(a, lambda req: httpx.Response(400, json={"errorMessage": "bad"}))
    with pytest.raises(BrokerError):
        await a.get_account()
