"""B440 + B441 + B437's D3 — a failed submission is not proof that no order exists.

MEASURED on loopback before this was built (no venue):
  * the SDK retries EVERY method on 504: it re-POSTed an order with the same client_order_id, and re-sent a
    partial close with the same qty — the quantity sold twice (B440);
  * it sends every request with NO timeout, so a hung connection blocked the event loop forever (B441);
  * `requests.ConnectionError` is BOTH "connection refused, nothing sent" and "reset after the server read the
    order" — only the exception CHAIN separates them;
  * `APIError.code` / `.message` json-decode the body and RAISE on a non-JSON one; only `.status_code` is safe;
  * a task cancelled after submission lost the order id entirely (D3, measured on a451ec1).

Rulings (manager): retry only 429, on every client; 3s connect / 10s read, set once; one builder for both
construction sites; decide "not created" by exception TYPE; a 422 is answered (one lookup, a 404 proves it), anything
sent-and-unanswered repeats the lookup within the budget and never becomes a refusal; a found order must MATCH the
request; a cancellation after submission logs the order id.

These arms open sockets to 127.0.0.1 ONLY; anything else is refused.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

from tests.unit.test_t0140_order_body import _asset, BTC_MIN, _req


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch):
    """`B432`, adapted: these arms need a real socket, and only to loopback."""
    real_connect = socket.socket.connect

    def _guarded(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost"):
            raise AssertionError(f"B440 arm attempted a non-loopback connection: {address!r}")
        return real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _guarded)


# ---------------------------------------------------------------------------------------------------
# A loopback venue
# ---------------------------------------------------------------------------------------------------

def _order_json(order_id, status="filled", client_order_id="sig-test", symbol="BTC/USD", side="buy", qty="0.01"):
    now = datetime.now(timezone.utc).isoformat()
    return {"id": order_id, "client_order_id": client_order_id, "created_at": now, "updated_at": now,
            "submitted_at": now, "asset_class": "crypto", "symbol": symbol, "qty": qty,
            "filled_qty": qty if status == "filled" else "0", "filled_avg_price": "70000" if status == "filled" else None,
            "order_class": "simple", "order_type": "market", "type": "market", "side": side,
            "time_in_force": "gtc", "status": status, "extended_hours": False}


class _Venue:
    """Scripted answers per route. Each script is a list of (status_code, body) or a callable; the last repeats."""

    def __init__(self):
        self.scripts: dict[str, list] = {}
        self.hits: dict[str, int] = {}
        self.stall_s = 0.0
        venue = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self, route):
                if route == "POST /v2/orders":
                    length = int(self.headers.get("Content-Length", 0))
                    self.rfile.read(length)
                venue.hits[route] = venue.hits.get(route, 0) + 1
                script = venue.scripts.get(route, [(404, {"code": 40410000, "message": "not found"})])
                step = script.pop(0) if len(script) > 1 else script[0]
                if step == "RESET":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
                    return
                if venue.stall_s:
                    time.sleep(venue.stall_s)
                code, body = step
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                path = self.path.split("?")[0]
                if path.startswith("/v2/orders:by_client_order_id"):
                    self._answer("GET by_client_order_id")
                elif path.startswith("/v2/orders/"):
                    self._answer("GET order")
                else:
                    self._answer(f"GET {path}")

            def do_POST(self):
                self._answer("POST /v2/orders")

            def do_DELETE(self):
                self._answer("DELETE position")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def venue():
    v = _Venue()
    yield v
    v.close()


async def _instant(_seconds):
    return None


def _built_adapter(venue_url):
    from app.services.broker.alpaca import AlpacaAdapter, build_trading_client

    client = build_trading_client("k", "s", paper=True, url_override=venue_url)
    client._retry_wait = 0
    adapter = AlpacaAdapter(client, paper=False)   # a loopback endpoint is not the paper URL (B389)
    adapter._sleep = _instant

    async def _asset_read(_pair):
        return _asset("BTC/USD", min_order_size=BTC_MIN)

    adapter._fetch_asset = _asset_read
    return adapter, client


# ---------------------------------------------------------------------------------------------------
# THE BUILDER (rulings a, b, c)
# ---------------------------------------------------------------------------------------------------

def test_B1_the_builder_retries_only_429_and_mounts_a_timeout_for_every_scheme():
    from app.services.broker.alpaca import build_trading_client

    client = build_trading_client("k", "s", paper=True)
    assert client._retry_codes == [429]
    for scheme in ("https://", "http://"):
        assert type(client._session.adapters[scheme]).__name__ == "_AlpacaTimeoutAdapter", scheme


def test_B1b_the_SDK_still_reads_the_two_attributes_the_builder_sets():
    """**Read from the installed SDK's source at test time**: the day `_one_request` stops reading
    `self._retry_codes` or `self._session`, the builder's settings do nothing and this fails first. And
    (`B442`) the day `__init__` stops storing `self._api_key`, every adapter on an account would share no
    order lock — the builder refuses, and this says why first."""
    from alpaca.common.rest import RESTClient

    one = inspect.getsource(RESTClient._one_request)
    init = inspect.getsource(RESTClient.__init__)
    assert "self._retry_codes" in one and "self._session.request" in one, one
    assert "self._retry_codes" in init and "self._session" in init
    assert "self._api_key" in init, init


@pytest.mark.parametrize("missing", ["_retry_codes", "_session", "_api_key"])
def test_B1c_the_builder_REFUSES_a_client_without_either_attribute(monkeypatch, missing):
    import requests as rq

    import alpaca.trading.client as sdk
    from app.core.exceptions import BrokerError
    from app.services.broker.alpaca import build_trading_client

    class _Renamed:
        def __init__(self, *a, **k):
            if missing != "_retry_codes":
                self._retry_codes = [429, 504]
            if missing != "_session":
                self._session = rq.Session()
            if missing != "_api_key":
                self._api_key = "k"

    monkeypatch.setattr(sdk, "TradingClient", _Renamed)
    with pytest.raises(BrokerError, match=missing):
        build_trading_client("k", "s", paper=True)


def test_B1d_BOTH_construction_sites_use_the_builder_and_neither_builds_a_TradingClient():
    root = Path(__file__).resolve().parents[2] / "app"
    for rel in ("services/broker/manager.py", "services/live/crypto_loop.py"):
        tree = ast.parse((root / rel).read_text())
        calls = [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert "build_trading_client" in calls, f"{rel} does not use the builder"
        assert "TradingClient" not in calls, f"{rel} constructs a TradingClient directly"


def test_B2_every_request_the_built_client_sends_carries_the_timeout(monkeypatch, venue):
    """**Ruling b.** Recorded at `HTTPAdapter.send`, below the subclass — the control proves the recorder
    sees `None` for a client that was not built."""
    from requests.adapters import HTTPAdapter

    from alpaca.trading.client import TradingClient
    from app.services.broker.alpaca import build_trading_client

    seen: list = []
    real_send = HTTPAdapter.send

    def _recording(self, request, **kwargs):
        seen.append(kwargs.get("timeout"))
        return real_send(self, request, **kwargs)

    monkeypatch.setattr(HTTPAdapter, "send", _recording)
    oid = str(uuid.uuid4())
    venue.scripts["GET order"] = [(200, _order_json(oid))]

    build_trading_client("k", "s", paper=True, url_override=venue.url).get_order_by_id(oid)
    TradingClient("k", "s", paper=True, url_override=venue.url).get_order_by_id(oid)
    assert seen == [(3.0, 10.0), None], seen


def test_B2b_a_stalled_venue_raises_ReadTimeout_instead_of_hanging(monkeypatch, venue):
    import app.services.broker.alpaca as alpaca

    monkeypatch.setattr(alpaca, "ALPACA_HTTP_READ_TIMEOUT_S", 0.2)
    venue.stall_s = 1.0
    venue.scripts["GET order"] = [(200, _order_json(str(uuid.uuid4())))]
    client = alpaca.build_trading_client("k", "s", paper=True, url_override=venue.url)
    t0 = time.monotonic()
    with pytest.raises(requests.exceptions.ReadTimeout):
        client.get_order_by_id(str(uuid.uuid4()))
    assert time.monotonic() - t0 < 0.9


@pytest.mark.parametrize("route,call", [
    ("POST /v2/orders", "submit"), ("DELETE position", "close_with_qty"),
], ids=["submit_order", "partial_close"])
def test_B3_a_504_is_NOT_resent_by_the_built_client_and_IS_by_a_raw_one(venue, route, call):
    """**B440, measured both ways.** The raw SDK re-sends the POST and the partial close; the built one does not."""
    from alpaca.common.exceptions import APIError
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import ClosePositionRequest, MarketOrderRequest
    from app.services.broker.alpaca import build_trading_client

    def _send(client):
        venue.hits.clear()
        venue.scripts[route] = [(504, b"gateway timeout")]
        client._retry_wait = 0
        with pytest.raises(APIError):
            if call == "submit":
                client.submit_order(MarketOrderRequest(symbol="BTC/USD", qty=0.01, side=OrderSide.BUY,
                                                       time_in_force=TimeInForce.GTC, client_order_id="sig-x"))
            else:
                client.close_position("BTCUSD", ClosePositionRequest(qty="0.003"))
        return venue.hits.get(route, 0)

    assert _send(build_trading_client("k", "s", paper=True, url_override=venue.url)) == 1
    raw = TradingClient("k", "s", paper=True, url_override=venue.url)
    assert _send(raw) == raw._retry + 1, "the raw SDK no longer re-sends on 504 — re-derive B440's premise"


# ---------------------------------------------------------------------------------------------------
# THE EXCEPTION MAP (ruling d) — real exceptions, produced by real failures
# ---------------------------------------------------------------------------------------------------

def _failure(kind, venue, monkeypatch):
    """Produce a REAL exception through the adapter's `_call`, exactly as place_order would see it."""
    import app.services.broker.alpaca as alpaca
    import urllib3.util.connection as u3

    adapter, client = _built_adapter(venue.url)

    if kind == "refused":
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        adapter, client = _built_adapter(f"http://127.0.0.1:{port}")
    elif kind == "connect_timeout":
        def _timeout(*a, **k):
            raise socket.timeout("timed out")
        monkeypatch.setattr(u3, "create_connection", _timeout)
    elif kind == "read_timeout":
        monkeypatch.setattr(alpaca, "ALPACA_HTTP_READ_TIMEOUT_S", 0.2)
        venue.stall_s = 0.6
        venue.scripts["GET order"] = [(200, _order_json(str(uuid.uuid4())))]
    elif kind == "reset":
        venue.scripts["GET order"] = ["RESET"]
    else:
        code, body = {"500_text": (500, b"internal error"), "503": (503, {"code": 1, "message": "unavailable"}),
                      "504": (504, b"gateway timeout"), "403": (403, {"code": 1, "message": "insufficient"}),
                      "422": (422, {"code": 1, "message": "client_order_id must be unique"}),
                      "429": (429, {"code": 1, "message": "rate limited"}), "404": (404, {"code": 1, "message": "nf"}),
                      "403_html": (403, b"<html><body>403 Forbidden</body></html>"),
                      "429_html": (429, b"<html><body>429 Too Many Requests</body></html>")}[kind]
        venue.scripts["GET order"] = [(code, body)]

    async def _go():
        return await adapter._call("get_order_by_id", str(uuid.uuid4()))

    try:
        asyncio.run(_go())
    except Exception as exc:  # noqa: BLE001 - the exception IS the fixture
        return exc
    raise AssertionError(f"{kind}: no failure was produced")


EXPECTED = [
    ("refused", "not_created"), ("connect_timeout", "not_created"), ("403", "not_created"),
    ("429", "not_created"), ("404", "not_created"),
    # Follow-up for fb3dab6 (review): a NON-JSON 4xx — an HTML page, as a proxy sends — is still NOT_CREATED.
    # D1b's non-JSON case is a 500, unanswered either way, so a classifier reading `.code` (which json-decodes
    # the body and raises) survived.
    ("403_html", "not_created"), ("429_html", "not_created"),
    ("422", "answered"),
    ("read_timeout", "unanswered"), ("reset", "unanswered"), ("500_text", "unanswered"),
    ("503", "unanswered"), ("504", "unanswered"),
]


@pytest.mark.parametrize("kind,expected", EXPECTED, ids=[e[0] for e in EXPECTED])
def test_D1_the_exception_map_is_decided_by_TYPE(monkeypatch, venue, kind, expected):
    from app.services.broker.alpaca import classify_submission_failure

    exc = _failure(kind, venue, monkeypatch)
    assert classify_submission_failure(exc) == expected, (kind, type(exc).__name__, repr(exc.__cause__))


def test_D1b_an_exception_type_nobody_placed_is_UNANSWERED_and_a_non_JSON_body_never_raises(monkeypatch, venue):
    from app.core.exceptions import BrokerError
    from app.services.broker.alpaca import classify_submission_failure

    assert classify_submission_failure(RuntimeError("something new")) == "unanswered"
    assert classify_submission_failure(BrokerError("wrapped", broker="alpaca")) == "unanswered"
    text_500 = _failure("500_text", venue, monkeypatch)
    with pytest.raises(json.JSONDecodeError):
        _ = next(link for link in __import__("app.services.broker.alpaca", fromlist=["x"])._exception_chain(text_500)
                 if type(link).__name__ == "APIError").code   # premise: reading .code DOES raise
    assert classify_submission_failure(text_500) == "unanswered"


# ---------------------------------------------------------------------------------------------------
# place_order on an ambiguous submission (rulings d, CHANGE 1, CHANGE 2)
# ---------------------------------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def test_P1_a_504_then_NOT_FOUND_then_FOUND_resolves_to_the_FILL_not_a_refusal(venue):
    """**The manager's arm, on loopback end to end.** A 404 right after an unanswered POST proves nothing."""
    adapter, _client = _built_adapter(venue.url)
    oid = str(uuid.uuid4())
    venue.scripts["POST /v2/orders"] = [(504, b"gateway timeout")]
    venue.scripts["GET by_client_order_id"] = [(404, {"code": 1, "message": "order not found"}),
                                              (200, _order_json(oid, status="filled"))]
    venue.scripts["GET order"] = [(200, _order_json(oid, status="filled"))]

    res = _run(adapter.place_order(_req()))
    assert res["status"] == "FILLED" and res["filled_units"] == 0.01, res
    assert venue.hits["GET by_client_order_id"] == 2 and venue.hits["POST /v2/orders"] == 1


def test_P2_an_UNANSWERED_submission_never_found_is_UNRESOLVED_never_REJECTED(venue):
    from app.services.live.crypto_loop import ORDER_UNRESOLVED, classify_order_status

    adapter, _client = _built_adapter(venue.url)
    venue.scripts["POST /v2/orders"] = [(504, b"gateway timeout")]
    venue.scripts["GET by_client_order_id"] = [(404, {"code": 1, "message": "order not found"})]

    res = _run(adapter.place_order(_req()))
    assert res["status"] == "SUBMISSION_UNCONFIRMED" and classify_order_status(res["status"]) == ORDER_UNRESOLVED
    assert "not found at the venue after 6 lookup(s)" in res["reason"] and "it may still appear" in res["reason"], res["reason"]
    assert "rejection_code" not in res
    assert venue.hits["GET by_client_order_id"] == 6


def test_P3_a_422_is_ANSWERED_one_lookup_and_its_404_PROVES_no_order(venue):
    from app.core.exceptions import BrokerError
    from app.services.broker.alpaca import _http_status_of

    adapter, _client = _built_adapter(venue.url)
    venue.scripts["POST /v2/orders"] = [(422, {"code": 1, "message": "qty must be > 0"})]
    venue.scripts["GET by_client_order_id"] = [(404, {"code": 1, "message": "order not found"})]

    with pytest.raises(BrokerError) as exc:
        _run(adapter.place_order(_req()))
    assert _http_status_of(exc.value) == 422, "the ORIGINAL refusal was not the one raised"
    assert venue.hits["GET by_client_order_id"] == 1


def test_P4_a_422_that_WAS_a_duplicate_client_order_id_resolves_the_existing_order(venue):
    """The duplicate is found by ASKING, never by reading the message text."""
    adapter, _client = _built_adapter(venue.url)
    oid = str(uuid.uuid4())
    venue.scripts["POST /v2/orders"] = [(422, {"code": 1, "message": "client_order_id must be unique"})]
    venue.scripts["GET by_client_order_id"] = [(200, _order_json(oid, status="filled"))]
    venue.scripts["GET order"] = [(200, _order_json(oid, status="filled"))]

    res = _run(adapter.place_order(_req()))
    assert res["status"] == "FILLED", res


def test_P5_a_lookup_that_FAILS_after_a_422_is_UNRESOLVED(venue):
    adapter, _client = _built_adapter(venue.url)
    venue.scripts["POST /v2/orders"] = [(422, {"code": 1, "message": "whatever"})]
    venue.scripts["GET by_client_order_id"] = [(500, b"down")]
    res = _run(adapter.place_order(_req()))
    assert res["status"] == "SUBMISSION_UNCONFIRMED", res
    # Follow-up for fb3dab6 (review): the ANSWERED path makes exactly ONE lookup. The full schedule gives the same
    # verdict here, so without this count a 422 walking the UNANSWERED schedule survived.
    assert venue.hits["GET by_client_order_id"] == 1, venue.hits


def test_P6_a_NOT_CREATED_failure_raises_the_refusal_and_looks_nothing_up(venue):
    from app.core.exceptions import BrokerError

    adapter, _client = _built_adapter(venue.url)
    venue.scripts["POST /v2/orders"] = [(403, {"code": 1, "message": "insufficient balance"})]
    with pytest.raises(BrokerError):
        _run(adapter.place_order(_req()))
    assert venue.hits.get("GET by_client_order_id", 0) == 0


@pytest.mark.parametrize("field,value", [("symbol", "ETH/USD"), ("side", "sell"), ("qty", "0.02")])
def test_P7_a_FOUND_order_that_does_not_MATCH_the_request_is_not_adopted(venue, field, value):
    """**CHANGE 2.** client_order_id is 32 bits; a stranger's order with our id must not become ours."""
    adapter, _client = _built_adapter(venue.url)
    oid = str(uuid.uuid4())
    stranger = _order_json(oid, status="filled", **{field: value})
    venue.scripts["POST /v2/orders"] = [(504, b"gateway timeout")]
    venue.scripts["GET by_client_order_id"] = [(200, stranger)]

    res = _run(adapter.place_order(_req()))
    assert res["status"] == "SUBMISSION_UNCONFIRMED", res
    assert "does not match this request" in res["reason"] and f"{field} venue=" in res["reason"], res["reason"]
    assert venue.hits.get("GET order", 0) == 0, "a mismatched order was resolved as ours"


@pytest.mark.parametrize("field,venue_value,adopted", [
    # Follow-up for fb3dab6 (review): qty is compared as a DECIMAL — the venue's "0.010" IS the "0.01" we sent.
    # A string comparison survived P7, whose mismatch is "0.02".
    ("qty", "0.010", True),
    # ... and symbol by EQUALITY: "BTC/USDT" is not "BTC/USD" (T-0139's D2 trap). P7's mismatch is ETH/USD, so a
    # substring match survived.
    ("symbol", "BTC/USDT", False),
], ids=["qty_0.010_is_0.01", "symbol_BTC-USDT_is_not_BTC-USD"])
def test_P7b_the_match_is_by_VALUE_not_by_TEXT(venue, field, venue_value, adopted):
    adapter, _client = _built_adapter(venue.url)
    oid = str(uuid.uuid4())
    found = _order_json(oid, status="filled", **{field: venue_value})
    venue.scripts["POST /v2/orders"] = [(504, b"gateway timeout")]
    venue.scripts["GET by_client_order_id"] = [(200, found)]
    venue.scripts["GET order"] = [(200, found)]

    res = _run(adapter.place_order(_req()))
    if adopted:
        assert res["status"] == "FILLED", res
    else:
        assert res["status"] == "SUBMISSION_UNCONFIRMED" and f"{field} venue=" in res["reason"], res


# ---------------------------------------------------------------------------------------------------
# D3 — a cancellation after submission names the order
# ---------------------------------------------------------------------------------------------------

def _capture_logs():
    from app.core.logging import logger

    lines: list[dict] = []
    sink = logger.add(lambda m: lines.append({"message": m.record["message"], **m.record["extra"]}), level="ERROR")
    return lines, lambda: logger.remove(sink)


def test_C1_a_CANCELLED_order_after_submission_is_LOGGED_with_its_id(monkeypatch, venue):
    import app.services.broker.alpaca as alpaca

    monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_BUDGET_S", 1.0)
    adapter, _client = _built_adapter(venue.url)
    adapter._sleep = asyncio.sleep                     # REAL waits, so the cancel lands inside resolution
    oid = str(uuid.uuid4())
    venue.scripts["POST /v2/orders"] = [(200, _order_json(oid, status="accepted"))]
    venue.scripts["GET order"] = [(200, _order_json(oid, status="accepted"))]
    lines, stop = _capture_logs()

    async def _go():
        task = asyncio.create_task(adapter.place_order(_req()))
        await asyncio.sleep(0.4)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        _run(_go())
    finally:
        stop()
    hits = [l for l in lines if "order_cancelled_after_submission" in l["message"]]
    assert hits and hits[0].get("order_id") == oid and hits[0].get("client_order_id") == "sig-test", lines
    assert hits[0].get("last_status") == "accepted"


def test_C1b_a_cancellation_BEFORE_submission_logs_no_order(venue):
    adapter, _client = _built_adapter(venue.url)

    async def _slow_asset(_pair):
        await asyncio.sleep(1.0)

    adapter._fetch_asset = _slow_asset
    lines, stop = _capture_logs()

    async def _go():
        task = asyncio.create_task(adapter.place_order(_req()))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        _run(_go())
    finally:
        stop()
    assert not [l for l in lines if "after_submission" in l["message"]], lines
    assert venue.hits.get("POST /v2/orders", 0) == 0


def test_C2_a_CANCELLED_close_after_submission_is_LOGGED_with_its_id(monkeypatch, venue):
    import app.services.broker.alpaca as alpaca

    monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_BUDGET_S", 1.0)
    adapter, _client = _built_adapter(venue.url)
    adapter._sleep = asyncio.sleep
    oid = str(uuid.uuid4())
    venue.scripts["DELETE position"] = [(200, _order_json(oid, status="accepted", side="sell"))]
    venue.scripts["GET order"] = [(200, _order_json(oid, status="accepted", side="sell"))]
    lines, stop = _capture_logs()

    async def _go():
        task = asyncio.create_task(adapter.close_position("BTCUSD"))
        await asyncio.sleep(0.4)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        _run(_go())
    finally:
        stop()
    hits = [l for l in lines if "close_cancelled_after_submission" in l["message"]]
    assert hits and hits[0].get("order_id") == oid, lines


# ---------------------------------------------------------------------------------------------------
# The kill switch's reason says which it was
# ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind,phrase", [("reset", "MAY HAVE REACHED the venue"), ("403", "did not take this close")])
def test_K1_a_failed_close_says_whether_it_MAY_HAVE_REACHED_the_venue(venue, kind, phrase):
    from tests.unit.test_t0136_alpaca_adapter import _Position

    adapter, _client = _built_adapter(venue.url)

    async def _positions():
        return [_Position(symbol="BTC/USD")]

    adapter._raw_positions = _positions
    venue.scripts["DELETE position"] = ["RESET"] if kind == "reset" else [(403, {"code": 1, "message": "no"})]
    report = _run(adapter.close_all_positions())
    assert report[0]["disposition"] == "FAILED" and phrase in report[0]["reason"], report[0]["reason"]


# ---------------------------------------------------------------------------------------------------
# WALL TIME (review's X-10) and D3 over EVERY await after submission (X-12)
# ---------------------------------------------------------------------------------------------------

def test_W1_the_resolver_STOPS_at_the_budget_when_each_read_is_SLOW():
    """**X-10, a defect in a451ec1.** The budget limited the read SCHEDULE: a slow read pushed later offsets into
    the past and every one still read — review's fake clock gave 6 reads over 18s against 5s. No read STARTS once
    the budget is spent; the one in flight finishes, so the bound is budget + one call."""
    from tests.unit.test_b427_order_resolution import _Venue as ScriptedVenue, _adapter as scripted_adapter

    venue = ScriptedVenue(ack="accepted", rereads=("accepted",))
    adapter, clock = scripted_adapter(venue)
    real_read = venue.get_order_by_id

    def _slow_read(order_id, filter=None):
        clock.now += 3.0                          # each read takes 3s of wall time
        return real_read(order_id, filter)

    venue.get_order_by_id = _slow_read
    res = _run(adapter.place_order(_req()))
    r = res["resolution"]
    assert r["reads"] == 2 and r["resolved"] is False, r
    assert r["elapsed_s"] <= r["budget_s"] + 3.0, f"resolution ran {r['elapsed_s']}s against a {r['budget_s']}s budget"


def test_W2_the_client_order_id_lookup_STOPS_at_the_budget_when_each_lookup_is_SLOW():
    from tests.unit.test_b427_order_resolution import _Venue as ScriptedVenue, _adapter as scripted_adapter

    venue = ScriptedVenue()
    adapter, clock = scripted_adapter(venue)
    lookups = []

    def _submit_504(order_data):
        raise requests.exceptions.ReadTimeout("read timed out")

    def _slow_lookup(client_id):
        lookups.append(clock.now)
        clock.now += 3.0
        raise RuntimeError("still not found")

    venue.submit_order = _submit_504
    venue.get_order_by_client_id = _slow_lookup
    res = _run(adapter.place_order(_req()))
    assert res["status"] == "SUBMISSION_UNCONFIRMED" and len(lookups) == 2, (len(lookups), res.get("reason"))
    assert "after 2 lookup(s)" in res["reason"]


def test_W3_a_cancellation_during_the_PROTECTION_re_read_is_LOGGED_with_the_order_id():
    """**X-12.** D3 covers every await after submission, not only the resolver's sleep. The protection re-read
    does not suspend today; under B437's executor it will — so it is made to suspend here."""
    from tests.unit.test_b429_stop_is_placed import PROTECTED, _adapter as b429_adapter, _placed
    from tests.unit.test_b429_stop_is_placed import _req as b429_req

    adapter = b429_adapter(_placed(status="accepted"), reread=PROTECTED)
    scripted_call = adapter._call

    async def _suspending_call(name, *args, **kwargs):
        if name == "get_order_by_id":
            await asyncio.sleep(1.0)
        return await scripted_call(name, *args, **kwargs)

    adapter._call = _suspending_call
    lines, stop = _capture_logs()

    async def _go():
        task = asyncio.create_task(adapter.place_order(b429_req()))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        _run(_go())
    finally:
        stop()
    hits = [l for l in lines if "order_cancelled_after_submission" in l["message"]]
    assert hits and hits[0].get("order_id") == "order-1", lines


def test_K2_a_close_whose_OUTCOME_raises_does_not_stop_the_kill_switch_reaching_the_next_position(monkeypatch):
    """**Structural survival** (manager): `_close_outcome` raising on the first position is caught INSIDE the
    per-position guard, the row says the close was SENT, and the second close is still sent."""
    from tests.unit.test_t0136_alpaca_adapter import _Position, _adapter as t0136_adapter

    adapter, mock = t0136_adapter(positions=[_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")])
    real_outcome = adapter._close_outcome
    calls = {"n": 0}

    async def _first_raises(order):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("outcome unreadable")
        return await real_outcome(order)

    monkeypatch.setattr(adapter, "_close_outcome", _first_raises)
    report = _run(adapter.close_all_positions())
    by_pair = {r["pair"]: r for r in report}
    assert len(mock.closed) == 2, "the second close was never sent"
    assert by_pair["BTC/USD"]["disposition"] == "FAILED" and "was SENT" in by_pair["BTC/USD"]["reason"]
    assert "outcome unreadable" in by_pair["BTC/USD"]["reason"], "the reason is not _close_outcome's own exception"
    assert "_in_flight" not in by_pair["BTC/USD"] and "never observed" not in by_pair["BTC/USD"]["reason"].lower(), (
        "position 1 was left marked in flight")
    assert by_pair["ETH/USD"]["disposition"] == "CLOSED"


def test_K3_a_CANCELLATION_while_a_close_resolves_still_reaches_the_ABNORMAL_EXIT_handler(monkeypatch):
    """**X-16.** The inner per-position handler catches `Exception`, NOT `BaseException`: a cancellation during
    `_close_outcome` must end the kill switch's loop with its partial report, the in-flight row saying SENT."""
    import app.services.broker.alpaca as alpaca
    from app.core.exceptions import BrokerError
    from tests.unit.test_t0136_alpaca_adapter import _Position, _adapter as t0136_adapter

    monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_BUDGET_S", 1.0)
    adapter, mock = t0136_adapter(positions=[_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")],
                                   close_status="accepted")
    adapter._sleep = asyncio.sleep

    async def _go():
        task = asyncio.create_task(adapter.close_all_positions())
        await asyncio.sleep(0.4)
        task.cancel()
        with pytest.raises(BrokerError) as exc:
            await task
        return exc.value

    failure = _run(_go())
    rows = {r["pair"]: r for r in failure.partial_report}
    assert "SENT" in rows["BTC/USD"]["reason"] and "CancelledError" in rows["BTC/USD"]["reason"], rows["BTC/USD"]
    assert rows["ETH/USD"]["disposition"] == "NOT_ATTEMPTED" and len(mock.closed) == 1
