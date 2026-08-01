"""The browser-bridge CFT adapter.

CFT is behind Cloudflare bot protection that fingerprints the TLS handshake, so
direct HTTP is refused (403) even holding a valid, freshly captured token. Only
a request issued from inside a real browser page succeeds. The bridge owns that
browser; this adapter talks to the bridge.

What these tests protect:

* the SAFETY properties survive the new transport — is_simulation stays False
  and observe_only still blocks writes. A transport swap is exactly the kind of
  change that quietly loosens a guard.
* the adapter still ADOPTS a session rather than logging in itself, and never
  sends credentials down this path.
* failures are distinguishable: bridge-down, bridge-token-wrong, and
  CFT-said-no are three different problems needing three different responses.

Everything about interpreting CFT's data is inherited from
CryptoFundTraderAdapter and is covered by test_cryptofundtrader_adapter.py; the
point of the subclass is that none of it had to be rewritten.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.exceptions import BrokerConnectionError
from app.services.broker.cft_bridge_adapter import CFTBridgeAdapter
from app.services.broker.cft_bridge_transport import BridgeResponse, BridgeTransport

UUID = "064e5cf1-6c6e-4a80-be99-2160393d69df"

BALANCE_JSON = json.dumps({
    "balance": "5090.95", "equity": "5090.95", "margin": "0.00",
    "freeMargin": "5090.95", "profit": "0", "currency": "USD",
})


def make_bridge(handler) -> BridgeTransport:
    """A BridgeTransport whose HTTP client is driven by `handler`."""
    t = BridgeTransport(bridge_url="http://bridge:8100", bridge_token="tok")
    t._client = httpx.AsyncClient(  # noqa: SLF001 - test seam
        base_url="http://bridge:8100",
        transport=httpx.MockTransport(handler),
    )
    return t


def bridge_ok(status_map: dict[str, tuple[int, str]], session: dict | None = None):
    """Handler: /status returns a live session, /call replays `status_map`."""
    sess = session if session is not None else {
        "logged_in": True, "uuid": UUID, "session_age_s": 12.0,
        "logins": 1, "calls": 3, "last_error": None,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json=sess)
        if request.url.path == "/reconnect":
            return httpx.Response(200, json={"ok": True, **sess})
        body = json.loads(request.content)
        for frag, (code, payload) in status_map.items():
            if frag in body["path"]:
                return httpx.Response(200, json={"status": code, "body": payload})
        return httpx.Response(200, json={"status": 404, "body": "not mapped"})

    return handler


def make_adapter(handler, **kw) -> CFTBridgeAdapter:
    a = CFTBridgeAdapter(email="e@x.com", password="pw", **kw)
    a._bridge = make_bridge(handler)   # noqa: SLF001
    a._client = a._bridge              # noqa: SLF001
    return a


# ---------------------------------------------------------------------------
# Safety — these must not weaken because the transport changed
# ---------------------------------------------------------------------------
def test_is_not_a_simulation():
    """CFT is a real broker. If this ever returns True, ExecutionService's
    hard assert stops protecting anything."""
    a = CFTBridgeAdapter(email="e", password="p")
    assert a.is_simulation is False


def test_observe_only_is_the_default():
    assert CFTBridgeAdapter(email="e", password="p").observe_only is True


async def test_observe_only_still_blocks_orders():
    """The write guard is inherited; prove the subclass did not bypass it."""
    from app.services.broker.base import OrderRequest
    from app.db.enums import DirectionType, OrderType

    a = make_adapter(bridge_ok({"/balance": (200, BALANCE_JSON)}), observe_only=True)
    a._system_uuid = UUID  # noqa: SLF001
    req = OrderRequest(pair="BTC/USD", direction=DirectionType.LONG,
                       order_type=OrderType.MARKET, lot_size=0.01)
    with pytest.raises(Exception) as err:
        await a.place_order(req)
    assert "observe" in str(err.value).lower() or "disabled" in str(err.value).lower()


# ---------------------------------------------------------------------------
# Connect adopts a session; it never logs in over this transport
# ---------------------------------------------------------------------------
async def test_connect_adopts_the_bridge_session(caplog):
    a = make_adapter(bridge_ok({
        "/balance": (200, BALANCE_JSON),
        "/group": (200, '"demo-group"'),
    }))
    await a.connect()

    assert a.connected is True
    assert a._system_uuid == UUID          # noqa: SLF001 - adopted, not derived
    assert a._group == "demo-group"        # noqa: SLF001


async def test_connect_never_posts_credentials():
    """Credentials belong only to the bridge's login form.

    The parent adapter POSTs email+password to /mtr-core-edge/login. Over this
    transport that would be both blocked by Cloudflare and pointless, so the
    subclass must not do it — and must not leak the password to the bridge.
    """
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json={"logged_in": True, "uuid": UUID})
        payload = json.loads(request.content)
        seen.append(payload)
        if "/balance" in payload["path"]:
            return httpx.Response(200, json={"status": 200, "body": BALANCE_JSON})
        return httpx.Response(200, json={"status": 200, "body": '""'})

    a = make_adapter(handler)
    await a.connect()

    blob = json.dumps(seen)
    assert "pw" not in blob, "the password reached the bridge transport"
    assert "mtr-core-edge/login" not in blob, "the subclass still tried to log in"


async def test_connect_validates_with_a_real_call():
    """Adopting a session must not be enough — a dead browser behind a healthy
    bridge would otherwise report 'connected'."""
    a = make_adapter(bridge_ok({"/balance": (500, "browser gone")}))
    with pytest.raises(Exception):
        await a.connect()
    assert a.connected is False


# ---------------------------------------------------------------------------
# Failures must be distinguishable
# ---------------------------------------------------------------------------
async def test_bridge_unreachable_says_so():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    a = make_adapter(handler)
    with pytest.raises(BrokerConnectionError) as err:
        await a.connect()
    msg = f"{err.value} {getattr(err.value, 'detail', '')}".lower()
    assert "bridge" in msg and ("not running" in msg or "unreachable" in msg)


async def test_bridge_token_mismatch_says_so():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    a = make_adapter(handler)
    with pytest.raises(BrokerConnectionError) as err:
        await a.connect()
    msg = f"{err.value} {getattr(err.value, 'detail', '')}".lower()
    assert "token" in msg, f"a token mismatch must name the token: {msg}"


async def test_bridge_asks_for_login_when_it_has_no_session():
    """A cold bridge logs in lazily; connect() must trigger it, so a failure
    surfaces now rather than on the first trading decision."""
    calls = {"reconnect": 0}
    cold = {"logged_in": False, "uuid": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status":
            return httpx.Response(200, json=cold)
        if request.url.path == "/reconnect":
            calls["reconnect"] += 1
            return httpx.Response(200, json={"ok": True, "logged_in": True, "uuid": UUID})
        payload = json.loads(request.content)
        if "/balance" in payload["path"]:
            return httpx.Response(200, json={"status": 200, "body": BALANCE_JSON})
        return httpx.Response(200, json={"status": 200, "body": '""'})

    a = make_adapter(handler)
    await a.connect()
    assert calls["reconnect"] == 1, "a cold bridge was not asked to log in"
    assert a._system_uuid == UUID  # noqa: SLF001


# ---------------------------------------------------------------------------
# Transport shim
# ---------------------------------------------------------------------------
def test_response_mimics_httpx():
    r = BridgeResponse(200, BALANCE_JSON, "/balance")
    assert r.status_code == 200
    assert r.json()["balance"] == "5090.95"
    assert r.is_success and isinstance(r.text, str)


async def test_missing_bridge_token_fails_closed():
    t = BridgeTransport(bridge_url="http://bridge:8100", bridge_token="")
    with pytest.raises(BrokerConnectionError) as err:
        await t.get("/balance")
    assert "token" in str(err.value).lower()


async def test_status_reports_unreachable_instead_of_raising():
    """A health check that throws is a health check nobody calls."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    t = make_bridge(handler)
    st = await t.status()
    assert st["reachable"] is False and "error" in st


async def test_disconnect_does_not_kill_the_shared_browser():
    """One adapter going away must not cost every other caller an ~11s re-login."""
    hit = {"reconnect": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/reconnect":
            hit["reconnect"] += 1
        return httpx.Response(200, json={"logged_in": True, "uuid": UUID})

    a = make_adapter(handler)
    await a.disconnect()
    assert a.connected is False
    assert hit["reconnect"] == 0, "disconnect tore down the shared browser session"


# ---------------------------------------------------------------------------
# /group returns JSON, not a name — found end-to-end against the live account
# ---------------------------------------------------------------------------
def test_group_name_extracted_from_json_payload():
    """CFT answers /group with a large object, not the bare string the original
    adapter assumed.

    Taking .text wholesale stored ~290KB of instrument definitions as the "group
    name", which then gets sent as groupName on every quote request. Caught by
    running the adapter against the real account, not by any unit test — worth
    a regression guard now that we know the real shape.
    """
    real_shape = json.dumps({
        "id": "realRLCusd-B6", "currency": "USD", "currencyPrecision": 2,
        "symbols": {"L3USDT.cft": {"symbol": "L3USDT.cft", "leverage": 0.05},
                    "GBPUSD.b": {"symbol": "GBPUSD.b", "leverage": 0.3}},
    })
    assert CFTBridgeAdapter._parse_group(real_shape) == "realRLCusd-B6"


def test_group_parser_tolerates_other_shapes():
    p = CFTBridgeAdapter._parse_group
    assert p('"plain-group"') == "plain-group"     # bare JSON string
    assert p("plain-group") == "plain-group"       # not JSON at all
    assert p('{"name": "by-name"}') == "by-name"   # alternate key
    assert p("") == ""
    assert p('{"unexpected": 1}') == ""            # never returns a blob
