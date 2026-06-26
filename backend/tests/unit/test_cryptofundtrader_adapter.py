"""Unit tests for the Crypto Fund Trader (Match-Trader / QFX) broker adapter.

Transport is mocked with ``httpx.MockTransport`` (no network). The login + endpoint
shapes mirror the live ``trading.cryptofundtrader.com`` API captured during discovery.
"""
from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.core.exceptions import BrokerConnectionError, BrokerError
from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest
from app.services.broker.cryptofundtrader import (
    AUTH_HEADER,
    DEFAULT_HOST,
    CryptoFundTraderAdapter,
    from_mt_symbol,
    to_mt_symbol,
)

HOST = "https://broker.example.com"
UUID = "system-uuid-1"

LOGIN_RESP = {
    "token": "core-jwt",
    "tradingAccounts": [
        {
            "tradingAccountId": "365105",
            "tradingApiToken": "tok-5k",
            "offer": {"currency": "USD", "name": "5,000$ Phase 1", "system": {"uuid": UUID}},
        },
        {
            "tradingAccountId": "373010",
            "tradingApiToken": "tok-25",
            "offer": {"currency": "USD", "name": "2,500$ Instant 1", "system": {"uuid": UUID}},
        },
    ],
    "selectedTradingAccount": {
        "tradingAccountId": "373010",
        "tradingApiToken": "tok-25",
        "group": "realRLCusd-B8",
        "offer": {"currency": "USD", "system": {"uuid": UUID}},
    },
}

BALANCE_RESP = {
    "balance": "5000.00",
    "equity": "5012.00",
    "margin": "0.00",
    "freeMargin": "5000.00",
    "marginLevel": "0",
    "profit": "12.00",
    "netProfit": "12.00",
    "currency": "USD",
    "currencyPrecision": 2,
}


def _adapter(account_id: str = "", observe_only: bool = True) -> CryptoFundTraderAdapter:
    return CryptoFundTraderAdapter(
        email="trader@example.com",
        password="secret",
        base_url=HOST,
        account_id=account_id,
        observe_only=observe_only,
    )


def _install(adapter: CryptoFundTraderAdapter, handler) -> None:
    adapter._client = httpx.AsyncClient(
        base_url=adapter._host, transport=httpx.MockTransport(handler)
    )


def _default_handler(positions=None, capture: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith("/mtr-core-edge/login"):
            return httpx.Response(200, json=LOGIN_RESP)
        if p.endswith("/balance"):
            return httpx.Response(200, json=BALANCE_RESP)
        if p.endswith("/group"):
            return httpx.Response(200, json={"group": "realRLCusd-B8"})
        if p.endswith("/open-positions"):
            return httpx.Response(200, json={"positions": positions or []})
        if p.endswith("/active-orders"):
            return httpx.Response(200, json={"orders": []})
        if p.endswith("/position/open") or p.endswith("/position/close"):
            if capture is not None:
                capture["path"] = p
                capture["body"] = json.loads(request.content)
            return httpx.Response(200, json={"status": "OK"})
        return httpx.Response(200, json={})

    return handler


# ---------------------------------------------------------------------------
# Construction + helpers
# ---------------------------------------------------------------------------


def test_defaults_to_cft_host():
    a = CryptoFundTraderAdapter(email="a", password="b")
    assert a._host == DEFAULT_HOST


def test_broker_name_and_default_pairs():
    a = _adapter()
    assert a.broker_name == "cryptofundtrader"
    assert "BTC/USD" in a.default_pairs


def test_symbol_round_trip():
    assert to_mt_symbol("BTC/USD") == "BTCUSDT.cft"
    assert to_mt_symbol("eth/usd") == "ETHUSDT.cft"
    assert from_mt_symbol("BTCUSDT.cft") == "BTC/USD"
    assert from_mt_symbol("MEWUSDT.cft") == "MEW/USD"


# ---------------------------------------------------------------------------
# connect / account selection
# ---------------------------------------------------------------------------


async def test_connect_selects_requested_account():
    a = _adapter(account_id="365105")
    _install(a, _default_handler())
    await a.connect()
    assert a.connected is True
    assert a._token == "tok-5k"  # the 5k account's token
    assert a._system_uuid == UUID
    assert a._account_id == "365105"
    assert a._client.headers[AUTH_HEADER] == "tok-5k"


async def test_connect_uses_selected_account_by_default():
    a = _adapter()  # no account_id
    _install(a, _default_handler())
    await a.connect()
    assert a._account_id == "373010"  # selectedTradingAccount
    assert a._token == "tok-25"
    assert a._group == "realRLCusd-B8"


async def test_connect_unknown_account_raises():
    a = _adapter(account_id="999999")
    _install(a, _default_handler())
    with pytest.raises(BrokerConnectionError):
        await a.connect()


# ---------------------------------------------------------------------------
# account / positions
# ---------------------------------------------------------------------------


async def test_get_account_parses_balance():
    a = _adapter()
    a._system_uuid = UUID
    a._token = "t"
    _install(a, _default_handler())
    a._client.headers[AUTH_HEADER] = "t"
    acct = await a.get_account()
    assert acct.broker == "cryptofundtrader"
    assert acct.balance == 5000.00
    assert acct.equity == 5012.00
    assert acct.unrealized_pl == 12.00
    assert acct.currency == "USD"


async def test_get_positions_maps_fields():
    a = _adapter()
    a._system_uuid = UUID
    positions = [
        {
            "id": "p1",
            "symbol": "BTCUSDT.cft",
            "side": "BUY",
            "openPrice": "67000",
            "currentPrice": "67300",
            "volume": "0.5",
            "stopLoss": "66000",
            "takeProfit": "69000",
            "profit": "150",
            "openTime": "2026-05-29T10:00:00Z",
        }
    ]
    _install(a, _default_handler(positions=positions))
    result = await a.get_positions()
    assert len(result) == 1
    p = result[0]
    assert p.pair == "BTC/USD"
    assert p.direction == DirectionType.LONG
    assert p.entry_price == Decimal("67000")
    assert p.lot_size == Decimal("0.5")
    assert p.sl == Decimal("66000")


# ---------------------------------------------------------------------------
# observe-only safety gate
# ---------------------------------------------------------------------------


async def test_observe_only_blocks_orders():
    a = _adapter(observe_only=True)
    a._system_uuid = UUID
    req = OrderRequest(
        pair="BTC/USD", direction=DirectionType.LONG, order_type=OrderType.MARKET, lot_size=0.1
    )
    with pytest.raises(BrokerError):
        await a.place_order(req)
    with pytest.raises(BrokerError):
        await a.close_position("p1")
    with pytest.raises(BrokerError):
        await a.close_all_positions()


# ---------------------------------------------------------------------------
# order placement when trading is enabled
# ---------------------------------------------------------------------------


async def test_place_order_when_enabled():
    a = _adapter(observe_only=False)
    a._system_uuid = UUID
    capture: dict = {}
    _install(a, _default_handler(capture=capture))
    req = OrderRequest(
        pair="BTC/USD",
        direction=DirectionType.SHORT,
        order_type=OrderType.MARKET,
        lot_size=0.25,
        sl=70000,
        tp=60000,
    )
    result = await a.place_order(req)
    assert result["status"] == "OK"
    assert capture["path"].endswith("/position/open")
    assert capture["body"]["symbol"] == "BTCUSDT.cft"
    assert capture["body"]["side"] == "SELL"
    assert capture["body"]["volume"] == 0.25
    assert capture["body"]["stopLoss"] == 70000


async def test_close_position_when_enabled():
    a = _adapter(observe_only=False)
    a._system_uuid = UUID
    capture: dict = {}
    _install(a, _default_handler(capture=capture))
    await a.close_position("p1", lot_size=0.5)
    assert capture["path"].endswith("/position/close")
    assert capture["body"]["id"] == "p1"
    assert capture["body"]["volume"] == 0.5
