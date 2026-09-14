"""B428b commit (ii) — what `AlpacaAdapter` gives `VenueEvents` (`T-0144` DESIGN §2.5–§2.6, R7', R14, B457, probe round 7).
Arms named by review's rows (`_runs/b428b_ii/KILL_SET.md`): the registered read seam, X-1 / X-3c (FILL pages and the bound),
C-2 (cancel-first by canonical pair), the close as a SELL order (C-1, K2-9, S-3 and B-2/B-3 re-anchored from (i) onto
the order site, where `B457`'s amendment pins the VALUE), G-2's 404, `filled_at`, and P-4's canonical symbol match.

Every venue answer is the SDK's own model (`a-double-can-answer-for-the-wrong-method`); nothing opens a socket.
"""
from __future__ import annotations

import asyncio
import socket
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.broker.alpaca import AlpacaAdapter
from tests.unit.test_b442_kill_switch_at_send import _venue_api_error
from tests.unit.test_t0140_order_body import BTC_MIN, _asset

pytestmark = pytest.mark.asyncio

FILLED_AT = datetime(2026, 9, 14, 12, 0, 0, 654321, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _refuse(self, address):
        raise AssertionError(f"(ii) adapter arms open no socket; something dialled {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)


def _sdk_order(*, symbol="BTC/USD", qty="0.01", status="filled", client_order_id="c", side="sell", filled_at=FILLED_AT,
               order_id=None, price="70000"):
    from alpaca.trading.enums import OrderClass, OrderSide, OrderStatus, TimeInForce
    from alpaca.trading.models import Order

    now = datetime.now(timezone.utc)
    return Order(id=order_id or uuid.uuid4(), client_order_id=client_order_id, created_at=now, updated_at=now,
                 submitted_at=now, filled_at=filled_at if status == "filled" else None, status=OrderStatus(status),
                 time_in_force=TimeInForce.GTC, order_class=OrderClass.SIMPLE, extended_hours=False, symbol=symbol,
                 qty=qty, filled_qty=qty if status == "filled" else "0", filled_avg_price=price if status == "filled" else None,
                 side=OrderSide(side))


class _Venue:
    """A synchronous `TradingClient` double: closes fill at once, orders are found by id and client id (404 otherwise),
    OPEN orders are listed, cancels are recorded (or fail by id), and FILL activities page by `page_token`."""

    def __init__(self, *, open_orders=(), fills=(), cancel_fails=()):
        self._api_key = f"PK-II-{uuid.uuid4().hex}"
        self.calls: list[tuple] = []
        self.by_id: dict[str, object] = {}
        self.by_client: dict[str, object] = {}
        self.open_orders = list(open_orders)
        self.fills = list(fills)
        self.cancel_fails = set(cancel_fails)
        self.orders_error: Exception | None = None
        self.lookup_error: Exception | None = None

    def get_asset(self, symbol):
        self.calls.append(("get_asset", symbol))
        return _asset(symbol, min_order_size=BTC_MIN)

    def submit_order(self, order_data):
        self.calls.append(("submit_order", order_data))
        order = _sdk_order(symbol=order_data.symbol, qty=str(order_data.qty), client_order_id=order_data.client_order_id,
                           side=getattr(order_data.side, "value", order_data.side))
        self.by_id[str(order.id)] = order
        self.by_client[order_data.client_order_id] = order
        return order

    def get_order_by_id(self, order_id, filter=None):
        self.calls.append(("get_order_by_id", str(order_id)))
        return self.by_id[str(order_id)]

    def get_order_by_client_id(self, client_id):
        self.calls.append(("get_order_by_client_id", client_id))
        if self.lookup_error is not None:
            raise self.lookup_error
        if client_id not in self.by_client:
            raise _venue_api_error(404, '{"code": 40410000, "message": "order not found"}')
        return self.by_client[client_id]

    def get_orders(self, filter=None):
        self.calls.append(("get_orders", filter))
        if self.orders_error is not None:
            raise self.orders_error
        return list(self.open_orders)

    def cancel_order_by_id(self, order_id):
        self.calls.append(("cancel_order_by_id", str(order_id)))
        if str(order_id) in self.cancel_fails:
            raise _venue_api_error(422, '{"code": 42210000, "message": "order is not cancelable"}')

    def get(self, path, data=None, **kwargs):
        """FILL activities newest first; `page_token` = the last row's id of the previous page (probe round 7)."""
        self.calls.append(("get", path, dict(data or {})))
        assert path == "/account/activities/FILL", path
        params = dict(data or {})
        rows = sorted(self.fills, key=lambda r: r["transaction_time"], reverse=True)
        token = params.get("page_token")
        if token is not None:
            ids = [r["id"] for r in rows]
            rows = rows[ids.index(token) + 1:]
        return [dict(r) for r in rows[: int(params["page_size"])]]

    def called(self, name):
        return [c for c in self.calls if c[0] == name]


def _adapter(venue=None, *, paper=True):
    venue = venue or _Venue()
    adapter = AlpacaAdapter(venue, paper=paper)

    async def _instant(_s):
        return None

    adapter._sleep = _instant
    return adapter, venue


async def _bounded(coro):
    async with asyncio.timeout(20):
        return await coro


# ---------------------------------------------------------------------------------------------------
# the registered read seam
# ---------------------------------------------------------------------------------------------------

def test_the_READ_SEAM_get_classifies_as_a_READ_and_every_other_unverbed_name_is_still_REFUSED():
    from app.services.broker import alpaca as mod

    client = _Venue()
    assert set(mod.REGISTERED_READ_SEAMS) == {"get"}, "the registration grew: each name needs a ruling"
    assert mod.classify_call(client, "get") == mod.CALL_READ
    assert mod.classify_call(client, "submit_order") == mod.CALL_WRITE
    for raw in ("post", "delete", "patch", "put", "_request"):
        assert mod.classify_call(client, raw) is None, f"the raw HTTP member {raw!r} is no longer REFUSED"


def test_the_READ_SEAM_trusts_the_SOURCE_not_the_name():
    import ast

    from app.services.broker import alpaca as mod

    get_only = ast.parse('def get(self, path):\n    return self._request("GET", path)\n')
    posts = ast.parse('def get(self, path):\n    return self._request("POST", path)\n')
    mixed = ast.parse('def get(self, path, verb):\n    self._request("GET", path)\n    return self._request(verb, path)\n')
    nothing = ast.parse('def get(self, path):\n    return path\n')
    assert mod._issues_only_http_get(get_only) is True
    assert not mod._issues_only_http_get(posts) and not mod._issues_only_http_get(mixed)
    assert not mod._issues_only_http_get(nothing), "a member issuing NO request passed as a read"


# ---------------------------------------------------------------------------------------------------
# X-1 / X-3c — FILL pages and the bound
# ---------------------------------------------------------------------------------------------------

def _fill(i, *, symbol="BTC/USD", order="close-1", side="sell", qty="0.0001", price="90", at=None):
    return {"id": f"2026091412000{i:02d}::{uuid.uuid4()}", "activity_type": "FILL", "order_id": order, "symbol": symbol,
            "side": side, "qty": qty, "price": price,
            "transaction_time": (at or FILLED_AT + timedelta(seconds=i)).isoformat().replace("+00:00", "Z")}


async def test_X1_every_PAGE_is_read_by_page_token_and_X3c_the_bound_keeps_FULL_precision(monkeypatch):
    from app.services.broker import alpaca as mod

    monkeypatch.setattr(mod, "FILL_ACTIVITY_PAGE_SIZE", 2)
    fills = [_fill(i) for i in range(1, 6)] + [_fill(6, symbol="ETH/USD"), _fill(7, symbol="BTCUSD")]
    adapter, venue = _adapter(_Venue(fills=fills))
    rows = await _bounded(adapter.fill_activities("BTC/USD", after=FILLED_AT))

    assert len(rows) == 6, f"{len(rows)} rows: the listing stopped before its last page"
    assert {r["symbol"] for r in rows} == {"BTC/USD", "BTCUSD"}, "the canonical pair filter"
    gets = venue.called("get")
    assert len(gets) == 4 and "page_token" not in gets[0][2], gets
    for (_n, _p, prev), (_n2, _p2, nxt) in zip(gets, gets[1:]):
        assert nxt["page_token"] and nxt["after"] == prev["after"], (prev, nxt)
    assert gets[0][2]["after"] == "2026-09-14T12:00:00.654321+00:00", "X-3c: the bound lost precision"
    assert all(isinstance(r["transaction_time"], datetime) and r["transaction_time"].tzinfo for r in rows)
    assert rows[0]["qty"] == Decimal("0.0001") and rows[0]["price"] == Decimal("90")


async def test_X1_a_listing_that_does_NOT_END_or_a_row_that_cannot_be_READ_raises_never_a_partial_list(monkeypatch):
    from app.core.exceptions import BrokerError
    from app.services.broker import alpaca as mod

    monkeypatch.setattr(mod, "FILL_ACTIVITY_PAGE_SIZE", 1)
    monkeypatch.setattr(mod, "FILL_ACTIVITY_MAX_PAGES", 3)
    adapter, _venue = _adapter(_Venue(fills=[_fill(i) for i in range(1, 6)]))
    with pytest.raises(BrokerError, match="did not end"):
        await _bounded(adapter.fill_activities("BTC/USD", after=FILLED_AT))
    monkeypatch.setattr(mod, "FILL_ACTIVITY_PAGE_SIZE", 100)
    broken = _fill(1)
    broken["price"] = None
    adapter, _venue = _adapter(_Venue(fills=[_fill(2), broken]))
    with pytest.raises(BrokerError, match="unreadable FILL"):
        await _bounded(adapter.fill_activities("BTC/USD", after=FILLED_AT))
    with pytest.raises(BrokerError, match="venue fill time"):
        await _bounded(adapter.fill_activities("BTC/USD", after=None))


# ---------------------------------------------------------------------------------------------------
# C-2 — cancel-first, by canonical pair
# ---------------------------------------------------------------------------------------------------

async def test_C2_resting_orders_for_the_PAIR_are_cancelled_by_CANONICAL_match_and_nothing_else():
    ids = {name: uuid.uuid4() for name in ("slash", "venue", "eth", "usdt")}
    open_orders = [_sdk_order(symbol="BTC/USD", status="new", order_id=ids["slash"]),
                   _sdk_order(symbol="BTCUSD", status="new", order_id=ids["venue"]),
                   _sdk_order(symbol="ETH/USD", status="new", order_id=ids["eth"]),
                   _sdk_order(symbol="BTC/USDT", status="new", order_id=ids["usdt"])]
    adapter, venue = _adapter(_Venue(open_orders=open_orders, cancel_fails={str(ids["venue"])}))
    out = await _bounded(adapter.cancel_open_orders_for("BTC/USD"))

    assert sorted(out["resting"]) == sorted([str(ids["slash"]), str(ids["venue"])]), out
    assert out["cancelled"] == [str(ids["slash"])] and [f[0] for f in out["failed"]] == [str(ids["venue"])], out
    assert out["complete"] is True
    assert {c[1] for c in venue.called("cancel_order_by_id")} == {str(ids["slash"]), str(ids["venue"])}
    (request,) = [c[1] for c in venue.called("get_orders")]
    assert (str(getattr(request.status, "value", request.status)), request.limit, request.nested) == ("open", 200, True)
    assert not getattr(request, "symbols", None), "a server-side symbol filter: the canonical match is ours"


async def test_C2_an_UNREADABLE_or_FULL_listing_is_NOT_complete_and_cancels_nothing(monkeypatch):
    from app.services.broker import alpaca as mod

    adapter, venue = _adapter()
    venue.orders_error = _venue_api_error(500, '{"code": 1, "message": "boom"}')
    out = await _bounded(adapter.cancel_open_orders_for("BTC/USD"))
    assert out["complete"] is False and out["failed"] and not venue.called("cancel_order_by_id"), out

    monkeypatch.setattr(mod, "CANCEL_SCAN_ORDER_LIMIT", 2)
    full = [_sdk_order(symbol="ETH/USD", status="new"), _sdk_order(symbol="ETH/USD", status="new")]
    adapter, venue = _adapter(_Venue(open_orders=full))
    out = await _bounded(adapter.cancel_open_orders_for("BTC/USD"))
    assert out["complete"] is False, "a FULL page was read as everything resting"


# ---------------------------------------------------------------------------------------------------
# the close: a SELL order (C-1, K2-9, S-3, B-2/B-3)
# ---------------------------------------------------------------------------------------------------

async def test_C1_a_close_is_a_MARKET_GTC_SELL_carrying_its_client_id_and_NEVER_close_position():
    cid = "tai-" + "a" * 32 + "-s01"
    adapter, venue = _adapter()
    result = await _bounded(adapter.place_close("BTC/USD", Decimal("0.0002"), cid))

    ((_n, sent),) = venue.called("submit_order")
    assert (sent.symbol, str(sent.side.value), str(sent.type.value), str(sent.time_in_force.value)) == (
        "BTC/USD", "sell", "market", "gtc"), sent
    assert sent.client_order_id == cid and len(cid) == 40
    assert result["status"] == "FILLED" and result["side"] == "sell" and result["client_order_id"] == cid, result
    assert result["filled_at"] == FILLED_AT, f"filled_at {result.get('filled_at')!r} lost or truncated"
    assert not venue.called("close_position") and not hasattr(venue, "close_position")


async def test_K2_9_an_ARMED_kill_switch_does_NOT_refuse_a_close_and_the_pair_REFUSES_an_entry():
    from app.core.exceptions import KillSwitchArmed
    from app.services.broker.base import OrderRequest
    from app.db.enums import DirectionType, OrderType
    from app.services.compliance.kill_switch import kill_switch

    kill_switch.arm(reason="(ii) K2-9: a close is protective")
    adapter, venue = _adapter()
    result = await _bounded(adapter.place_close("BTC/USD", Decimal("0.0002"), "tai-" + "b" * 32 + "-s01"))
    assert result["status"] == "FILLED" and len(venue.called("submit_order")) == 1
    with pytest.raises(KillSwitchArmed):
        await _bounded(adapter.place_order(OrderRequest(pair="BTC/USD", direction=DirectionType.LONG,
                                                        order_type=OrderType.MARKET, lot_size=0.0002,
                                                        client_order_id="tai-" + "c" * 32)))
    assert len(venue.called("submit_order")) == 1, "the entry was SENT with the switch armed"


async def test_S3_a_close_BELOW_the_eleven_dollar_ENTRY_minimum_is_SENT():
    adapter, venue = _adapter()
    result = await _bounded(adapter.place_close("BTC/USD", Decimal("0.000057828"), "tai-" + "d" * 32 + "-p01"))
    assert result["status"] == "FILLED" and len(venue.called("submit_order")) == 1, "a $4.49 close was refused"


@pytest.mark.parametrize("qty, expected", [
    (Decimal("0.0000578289"), "0.000057828"),       # quantised DOWN to the 1e-9 grid, never HALF_EVEN up
    (Decimal("0.00001"), "0.00001"),
    (Decimal("0.000012345999"), "0.000012345"),
])
async def test_B2_B3_the_close_quantity_is_the_EXACT_quantised_value_and_never_ABOVE_what_was_asked(qty, expected):
    """`B457`'s amendment: `MarketOrderRequest.qty` is a FLOAT in the SDK, so the text's format is an equivalent mutant at an
    order site. What is pinned is the value: the float's shortest repr is the 9-dp quantised decimal, exactly."""
    adapter, venue = _adapter()
    await _bounded(adapter.place_close("BTC/USD", qty, "tai-" + "e" * 32 + "-s01"))
    ((_n, sent),) = venue.called("submit_order")
    assert Decimal(repr(sent.qty)) == Decimal(expected) and Decimal(repr(sent.qty)) <= qty, (sent.qty, expected)


async def test_B3_a_close_that_quantises_to_NOTHING_is_refused_and_sends_nothing():
    from app.core.exceptions import BrokerError

    adapter, venue = _adapter()
    with pytest.raises(BrokerError, match="quantises"):
        await _bounded(adapter.place_close("BTC/USD", Decimal("0.0000000001"), "tai-" + "f" * 32 + "-s01"))
    assert not venue.called("submit_order")


# ---------------------------------------------------------------------------------------------------
# G-2's probe, the fill rows' client ids, the kind
# ---------------------------------------------------------------------------------------------------

async def test_G2_find_order_by_client_id_is_None_ONLY_on_a_404_and_carries_the_venue_fill_time():
    from app.core.exceptions import BrokerError

    adapter, venue = _adapter()
    assert await _bounded(adapter.find_order_by_client_id("tai-" + "1" * 32 + "-s01")) is None
    cid = "tai-" + "2" * 32 + "-s01"
    await _bounded(adapter.place_close("BTC/USD", Decimal("0.0002"), cid))
    found = await _bounded(adapter.find_order_by_client_id(cid))
    assert found["client_order_id"] == cid and found["status"] == "FILLED" and found["filled_at"] == FILLED_AT, found
    venue.lookup_error = _venue_api_error(500, '{"code": 1, "message": "boom"}')
    with pytest.raises(BrokerError):
        await _bounded(adapter.find_order_by_client_id(cid))


async def test_X2_order_client_id_is_the_venues_client_id_for_the_order():
    adapter, venue = _adapter()
    cid = "tai-" + "3" * 32 + "-x01"
    result = await _bounded(adapter.place_close("BTC/USD", Decimal("0.0002"), cid))
    assert await _bounded(adapter.order_client_id(result["position_id"])) == cid


def test_the_adapter_is_a_VENUE_and_labels_PAPER_by_its_account():
    assert AlpacaAdapter.position_events_kind == "venue"
    assert _adapter(paper=True)[0].is_paper_venue is True and _adapter(paper=False)[0].is_paper_venue is False


def test_P4_a_looked_up_order_matches_across_the_venues_TWO_SPELLINGS_and_not_another_pair():
    adapter, _venue = _adapter()
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    sent = MarketOrderRequest(symbol="BTC/USD", qty="0.0002", side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
                              client_order_id="tai-" + "4" * 32 + "-s01")
    assert adapter._submission_mismatch(_sdk_order(symbol="BTCUSD", qty="0.0002"), sent) is None
    assert adapter._submission_mismatch(_sdk_order(symbol="BTC/USD", qty="0.0002"), sent) is None
    assert "symbol" in (adapter._submission_mismatch(_sdk_order(symbol="BTC/USDT", qty="0.0002"), sent) or "")
    assert "symbol" in (adapter._submission_mismatch(_sdk_order(symbol="ETHUSD", qty="0.0002"), sent) or "")
