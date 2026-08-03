"""The CFT order path, exercised end to end against a MOCK (task 4.5).

NO TEST IN THIS FILE TOUCHES THE REAL ACCOUNT. Every request lands on an
in-process fake. That is not a limitation of the tests — it is the only
responsible way to exercise an order path against a funded account, and it is
why the shape of the request is asserted so precisely here: this is the last
place the body can be checked before it becomes real money.

WHAT IS VERIFIED
  * the request the adapter builds — path, method, side, volume, SL/TP
  * the response is parsed back into something the engine can use
  * every guard refuses a write when it should, independently

WHAT CANNOT BE VERIFIED WITHOUT A REAL ORDER (stated so nobody assumes otherwise)
Whether CFT ACCEPTS this body. The endpoint map was reverse-engineered from
their web terminal by network capture, so field names like `stopLoss` vs
`sl` are inferred, not documented. A mock will happily accept a body the real
venue rejects. Confirming that needs one deliberate, human-authorised order —
which is exactly the Tier-3 decision the ALLOW_LIVE_TRADING gate exists to
force. See KNOWN_ISSUES.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.exceptions import BrokerError
from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest
from app.services.broker.cft_bridge_adapter import CFTBridgeAdapter
from app.services.broker.cft_bridge_transport import BridgeTransport

UUID = "064e5cf1-6c6e-4a80-be99-2160393d69df"

#: What CFT returns on a successful open, per the terminal capture.
OPEN_OK = json.dumps({"status": "OK", "orderId": "ord-123", "positionId": "pos-456"})


def make_adapter(observe_only: bool, capture: list) -> CFTBridgeAdapter:
    """An adapter whose bridge records every request instead of sending it."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"logged_in": True, "uuid": UUID})
        payload = json.loads(request.content)
        capture.append(payload)
        return httpx.Response(200, json={"status": 200, "body": OPEN_OK})

    a = CFTBridgeAdapter(email="e@x.com", password="pw", observe_only=observe_only)
    t = BridgeTransport(bridge_url="http://bridge:8100", bridge_token="tok")
    t._client = httpx.AsyncClient(  # noqa: SLF001 - test seam
        base_url="http://bridge:8100", transport=httpx.MockTransport(handler)
    )
    a._bridge = t      # noqa: SLF001
    a._client = t      # noqa: SLF001
    a._system_uuid = UUID  # noqa: SLF001
    return a


def order(direction=DirectionType.LONG, **kw) -> OrderRequest:
    return OrderRequest(
        pair=kw.pop("pair", "BTC/USD"),
        direction=direction,
        order_type=kw.pop("order_type", OrderType.MARKET),
        lot_size=kw.pop("lot_size", 0.05),
        sl=kw.pop("sl", 61000.0),
        tp=kw.pop("tp", 64000.0),
        **kw,
    )


# ---------------------------------------------------------------------------
# The guard, first — a write must be impossible before anything else is tested
# ---------------------------------------------------------------------------
async def test_observe_only_blocks_the_order_before_any_request(capsys):
    """Nothing may reach the transport at all. Being rejected downstream is not
    the same as never being sent."""
    sent: list = []
    a = make_adapter(observe_only=True, capture=sent)

    with pytest.raises(BrokerError, match="observe-only"):
        await a.place_order(order())

    assert sent == [], "a blocked order still reached the bridge"


async def test_observe_only_blocks_close_position():
    sent: list = []
    a = make_adapter(observe_only=True, capture=sent)
    with pytest.raises(BrokerError, match="observe-only"):
        await a.close_position("pos-456")
    assert sent == []


async def test_observe_only_blocks_close_all_positions():
    sent: list = []
    a = make_adapter(observe_only=True, capture=sent)
    with pytest.raises(BrokerError, match="observe-only"):
        await a.close_all_positions()
    assert sent == []


# ---------------------------------------------------------------------------
# The request the adapter builds — the last checkable point before real money
# ---------------------------------------------------------------------------
async def test_long_order_body_is_correct():
    sent: list = []
    a = make_adapter(observe_only=False, capture=sent)

    await a.place_order(order(DirectionType.LONG, lot_size=0.05, sl=61000.0, tp=64000.0))

    assert len(sent) == 1
    req = sent[0]
    assert req["method"] == "POST"
    assert req["path"] == f"/mtr-api/{UUID}/position/open"

    body = req["body"]
    assert body["symbol"] == "BTCUSDT.cft", "USD must be normalised to CFT's USDT symbol"
    assert body["side"] == "BUY"
    assert body["volume"] == 0.05
    assert body["stopLoss"] == 61000.0
    assert body["takeProfit"] == 64000.0


async def test_short_order_sends_sell():
    """Direction is the one field where an error is unrecoverable: a SELL sent
    as BUY is an immediate, real, wrong-way position."""
    sent: list = []
    a = make_adapter(observe_only=False, capture=sent)
    await a.place_order(order(DirectionType.SHORT))
    assert sent[0]["body"]["side"] == "SELL"


async def test_stops_are_omitted_when_not_set_rather_than_sent_as_zero():
    """A stopLoss of 0.0 is not "no stop" — on some venues it is a stop at zero,
    i.e. an unprotected position. Absent must mean absent."""
    sent: list = []
    a = make_adapter(observe_only=False, capture=sent)
    await a.place_order(order(sl=None, tp=None))
    body = sent[0]["body"]
    assert "stopLoss" not in body
    assert "takeProfit" not in body


async def test_market_order_sends_no_price():
    sent: list = []
    a = make_adapter(observe_only=False, capture=sent)
    await a.place_order(order(order_type=OrderType.MARKET))
    assert "price" not in sent[0]["body"]


async def test_limit_order_carries_its_price():
    sent: list = []
    a = make_adapter(observe_only=False, capture=sent)
    await a.place_order(order(order_type=OrderType.LIMIT, price=62000.0))
    assert sent[0]["body"]["price"] == 62000.0


async def test_close_position_targets_the_right_endpoint_and_id():
    sent: list = []
    a = make_adapter(observe_only=False, capture=sent)
    await a.close_position("pos-456")
    assert sent[0]["path"] == f"/mtr-api/{UUID}/position/close"
    assert sent[0]["body"]["id"] == "pos-456"


async def test_partial_close_sends_the_volume():
    sent: list = []
    a = make_adapter(observe_only=False, capture=sent)
    await a.close_position("pos-456", lot_size=0.02)
    assert sent[0]["body"]["volume"] == 0.02


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
async def test_successful_open_returns_the_brokers_ids():
    sent: list = []
    a = make_adapter(observe_only=False, capture=sent)
    result = await a.place_order(order())
    assert result["positionId"] == "pos-456"
    assert result["orderId"] == "ord-123"


async def test_a_rejection_from_cft_raises_rather_than_looking_successful():
    """A silent failure here means the engine believes it holds a position it
    does not — worse than an error, because the stop is imaginary too."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"logged_in": True, "uuid": UUID})
        return httpx.Response(200, json={"status": 400, "body": '{"message":"insufficient margin"}'})

    a = CFTBridgeAdapter(email="e", password="p", observe_only=False)
    t = BridgeTransport(bridge_url="http://bridge:8100", bridge_token="tok")
    t._client = httpx.AsyncClient(  # noqa: SLF001
        base_url="http://bridge:8100", transport=httpx.MockTransport(handler)
    )
    a._bridge = t; a._client = t; a._system_uuid = UUID  # noqa: SLF001

    with pytest.raises(BrokerError) as err:
        await a.place_order(order())
    assert "insufficient margin" in str(getattr(err.value, "detail", err.value))


async def test_a_bridge_write_refusal_surfaces_clearly():
    """When BRIDGE_ALLOW_TRADING is off the bridge answers 403. The engine must
    see a clear reason, not a generic failure."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"logged_in": True, "uuid": UUID})
        return httpx.Response(403, json={
            "error": "trading is disabled on this bridge", "blocked": True,
        })

    a = CFTBridgeAdapter(email="e", password="p", observe_only=False)
    t = BridgeTransport(bridge_url="http://bridge:8100", bridge_token="tok")
    t._client = httpx.AsyncClient(  # noqa: SLF001
        base_url="http://bridge:8100", transport=httpx.MockTransport(handler)
    )
    a._bridge = t; a._client = t; a._system_uuid = UUID  # noqa: SLF001

    with pytest.raises(Exception) as err:
        await a.place_order(order())
    msg = f"{err.value} {getattr(err.value, 'detail', '')}".lower()
    # It must blame the BRIDGE, not the venue. Reporting this as a CFT API
    # error sends the operator to investigate the broker when the cause is a
    # local flag they can change.
    assert "bridge" in msg, f"a bridge refusal was reported as a broker error: {msg}"
    assert "disabled" in msg or "blocked" in msg


# ---------------------------------------------------------------------------
# The layer above: the engine can never route an order here at all
# ---------------------------------------------------------------------------
async def test_execution_service_refuses_this_adapter_outright():
    """ExecutionService is the ONLY path the trading engine executes through,
    and it hard-asserts is_simulation. Even a fully unlocked CFT adapter cannot
    be driven by the engine — the strategy loop physically cannot reach real
    money, independent of every flag tested above."""
    from app.services.execution.service import ExecutionService, Signal

    a = CFTBridgeAdapter(email="e", password="p", observe_only=False)
    assert a.is_simulation is False

    with pytest.raises(RuntimeError, match="simulation broker"):
        await ExecutionService(a).execute(
            Signal(symbol="BTC/USD", direction=DirectionType.LONG,
                   entry=62000.0, sl=61000.0, tp=64000.0)
        )
