"""B437 — every Alpaca SDK call ran INLINE on the event loop, so each round trip stalled the whole process.

The fix, as ruled (manager, option (c), and the rulings on review's registered kill set `_runs/b437/KILL_SET.md`): ONE
worker thread per ACCOUNT (`AccountExecutor`, keyed by the hashed API key id), shared by every client and adapter on
the account, FIFO; a WRITE shielded once started and WITHDRAWN while still queued; the kill switch re-checked ON THE
WORKER before `submit_order`, returning a typed not-sent marker; reads unshielded.

Arms are numbered by review's rows. SYNC doubles only — an `async def` double never enters the worker, so it cannot
show a call running inline — or the REAL SDK against a loopback server. Every gate is a BOUNDED wait that fails by name
(`B452`, (2e)): a mutant must fail an arm, never hang a run.
"""
from __future__ import annotations

import ast
import asyncio
import gc
import hashlib
import json
import socket
import threading
import time
import uuid
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db.enums import DirectionType, OrderType
from tests.unit.test_b442_kill_switch_at_send import (
    _Book, _alpaca, _bounded_event, _capture_logs, _entry_req, _until, _venue_api_error,
)
from tests.unit.test_t0136_alpaca_adapter import _Account, _Position

GATE_S = 5.0          # every thread-side gate waits at most this long, then fails the arm by name


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch):
    real_connect = socket.socket.connect

    def _guarded(self, address, *a, **k):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "localhost"):
            raise AssertionError(f"B437 arm attempted a non-loopback connection: {address!r}")
        return real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", _guarded)


# ---------------------------------------------------------------------------------------------------
# doubles and instruments
# ---------------------------------------------------------------------------------------------------

TRACED = ("get_asset", "submit_order", "get_order_by_client_id", "get_order_by_id", "get_all_positions",
          "close_position", "get_orders", "get_account", "get_open_position", "cancel_order_by_id", "get")


class _Traced(_Book):
    """`_Book` whose venue members record WHICH THREAD ran them, in execution order, and can be HELD on a threading gate.
    A hold that is never released fails the arm by name after `GATE_S` (the call raises), so no arm can hang."""

    def __init__(self, api_key=None, **kw):
        super().__init__(api_key=api_key, **kw)
        self.log: list[tuple[str, int]] = []
        self.holds: dict[str, threading.Event] = {}
        self.entered: dict[str, threading.Event] = {n: threading.Event() for n in TRACED}
        self._guard = threading.Lock()
        for name in TRACED:
            setattr(self, name, self._wrap(name, getattr(self, name)))

    def _wrap(self, name, fn):
        def _traced(*args, **kwargs):
            with self._guard:
                self.log.append((name, threading.get_ident()))
            self.entered[name].set()
            hold = self.holds.get(name)
            if hold is not None and not hold.wait(GATE_S):
                raise AssertionError(f"held {name} was never released within {GATE_S}s")
            return fn(*args, **kwargs)
        return _traced

    def get_account(self):
        return _Account()

    def get_open_position(self, symbol_or_asset_id):
        return _Position(symbol=str(symbol_or_asset_id))

    def cancel_order_by_id(self, order_id):
        self.calls.append(("cancel_order_by_id", str(order_id)))
        return None

    def get(self, path, data=None, **kwargs):
        """`RESTClient.get` (`T-0144` §2.6's FILL activities read): one empty page."""
        self.calls.append(("get", str(path)))
        return []

    def threads_of(self, name):
        return {t for n, t in self.log if n == name}


class _Heartbeat:
    """Counts event-loop turns in real time while something else runs."""

    def __init__(self):
        self.ticks = 0
        self._stop = None
        self._task = None

    async def __aenter__(self):
        self._stop = asyncio.Event()

        async def _beat():
            while not self._stop.is_set():
                await asyncio.sleep(0.01)
                self.ticks += 1
        self._task = asyncio.create_task(_beat())
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc):
        self._stop.set()
        await self._task
        return False


async def _hold_worker(adapter, gate: threading.Event, what="a held read"):
    """Occupy the account's single worker with a sync job until `gate` is set (bounded)."""
    def _held():
        if not gate.wait(GATE_S):
            raise AssertionError(f"{what} was never released within {GATE_S}s")
        return "held-read-done"
    return await adapter._account_worker().run(_held, write=False, call="held_read")


# ---------------------------------------------------------------------------------------------------
# E-1  THE LOOP IS NOT BLOCKED
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("member", ["submit_order", "get_order_by_id"])
async def test_E1_the_event_loop_RUNS_while_a_SYNC_venue_call_is_in_flight(member):
    book = _Traced()
    real = getattr(book, member)

    def _slow(*a, **k):
        time.sleep(0.3)
        return real(*a, **k)

    setattr(book, member, _slow)
    adapter, _clock = _alpaca(book)
    async with asyncio.timeout(10):
        async with _Heartbeat() as beat:
            await adapter.place_order(_entry_req(client_order_id=f"sig-e1-{member}"))
    assert book.called("submit_order") and book.called("get_order_by_id"), "the drive did not reach the member"
    assert beat.ticks >= 10, f"the loop ticked {beat.ticks} times across a 0.3s {member}: it was BLOCKED"


# ---------------------------------------------------------------------------------------------------
# E-2  EVERY _call SITE GOES THROUGH THE WORKER — names derived from the source, never copied
# ---------------------------------------------------------------------------------------------------

def _call_names_in_source() -> set[str]:
    import app.services.broker.alpaca as alpaca

    tree = ast.parse(Path(alpaca.__file__).read_text())
    names = {n.args[0].value for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_call"
             and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}
    assert len(names) >= 8, f"the source scan found only {names}: the instrument is broken"
    return names


@pytest.mark.asyncio
async def test_E2_EVERY_SDK_member_the_adapter_calls_RUNS_OFF_the_event_loop_thread():
    from requests.exceptions import ReadTimeout

    loop_thread = threading.get_ident()
    names = _call_names_in_source()
    books: list[_Traced] = []

    async def _flow(coro_factory, **book_kw):
        book = _Traced(**book_kw)
        books.append(book)
        adapter, _clock = _alpaca(book)
        try:
            async with asyncio.timeout(10):
                await coro_factory(adapter, book)
        except (Exception, asyncio.CancelledError) as exc:  # the flows are drives, not verdicts
            if isinstance(exc, TimeoutError):
                raise AssertionError(f"a drive timed out: {coro_factory.__name__}") from exc

    async def _ambiguous_submission(adapter, book):         # the client_order_id lookup
        def _timeout(order_data):
            book.calls.append(("submit_order", order_data.symbol))
            raise ReadTimeout("read timed out")
        book.submit_order = book._wrap("submit_order", _timeout)
        await adapter.place_order(_entry_req(client_order_id="sig-e2-ambiguous"))

    async def _reads(adapter, book):
        await adapter.get_account()
        await adapter.get_orders()
        await adapter.get_orders("open")
        await adapter.get_recent_trades()
        await adapter.reference_price("BTC/USD")
        await adapter.get_positions()

    async def _closes(adapter, book):
        book.positions = [_Position(symbol="BTCUSD"), _Position(symbol="ETHUSD")]
        await adapter.close_position("BTCUSD")
        await adapter.close_all_positions()

    async def _venue_management(adapter, book):             # `T-0144` (ii): what the loop's `VenueEvents` calls
        from alpaca.trading.enums import OrderStatus, TimeInForce
        from alpaca.trading.models import Order

        from datetime import datetime, timezone
        from decimal import Decimal

        now = datetime.now(timezone.utc)
        resting = Order(id=uuid.uuid4(), client_order_id="rest", created_at=now, updated_at=now, submitted_at=now,
                        status=OrderStatus.NEW, time_in_force=TimeInForce.GTC, extended_hours=False, symbol="BTC/USD",
                        qty="0.01", filled_qty="0")
        book.get_orders = book._wrap("get_orders", lambda filter=None: [resting])
        await adapter.cancel_open_orders_for("BTC/USD")                          # get_orders, cancel_order_by_id
        await adapter.fill_activities("BTC/USD", after=now)                      # get (the registered read seam)
        await adapter.place_close("BTC/USD", Decimal("0.001"), f"tai-{uuid.uuid4().hex}-s01")

    # `T-0144` R2: the `_bracket_remediation` flow (a bracket entry driven into B429's cancel/close/flat-observation
    # remediation) went with that code; `cancel_order_by_id`'s `_call` site is now R14's cancel-first (`_venue_management`).
    for flow in (_ambiguous_submission, _reads, _closes, _venue_management):
        await _flow(flow)

    seen: dict[str, set[int]] = {}
    for book in books:
        for name, thread in book.log:
            seen.setdefault(name, set()).add(thread)
    missing = sorted(names - set(seen))
    assert not missing, f"no drive reached these _call members, so this arm cannot vouch for them: {missing}"
    inline = sorted(n for n in names if loop_thread in seen[n])
    assert not inline, f"these SDK members ran ON the event loop's thread: {inline}"


# ---------------------------------------------------------------------------------------------------
# E-3, E-4, E-6  ONE WORKER PER ACCOUNT, NOT SHARED ACROSS ACCOUNTS, FIFO
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E3_ONE_worker_per_ACCOUNT_across_adapters_B_has_not_started_when_A_is_released():
    key = f"PK-B437-{uuid.uuid4().hex}"
    b1, b2 = _Traced(api_key=key), _Traced(api_key=key)
    a1, _ = _alpaca(b1)
    a2, _ = _alpaca(b2)
    release = threading.Event()
    b1.holds["get_all_positions"] = release
    async with asyncio.timeout(10):
        first = asyncio.create_task(a1.get_positions())
        await _until(b1.entered["get_all_positions"].is_set, "call A is running on the worker")
        second = asyncio.create_task(a2.get_positions())
        await asyncio.sleep(0.2)
        assert not b2.entered["get_all_positions"].is_set(), "call B started while call A held the account's worker"
        release.set()
        await first
        await second
    assert b1.threads_of("get_all_positions") == b2.threads_of("get_all_positions"), "two threads served one account"


@pytest.mark.asyncio
async def test_E4_ACCOUNTS_do_not_share_a_worker_B_completes_while_A_is_held():
    b1, b2 = _Traced(), _Traced()
    a1, _ = _alpaca(b1)
    a2, _ = _alpaca(b2)
    release = threading.Event()
    b1.holds["get_all_positions"] = release
    try:
        async with asyncio.timeout(10):
            held = asyncio.create_task(a1.get_positions())
            await _until(b1.entered["get_all_positions"].is_set, "account A's call is held")
            await asyncio.wait_for(a2.get_positions(), 2)
    finally:
        release.set()
    await held


@pytest.mark.asyncio
async def test_E6_calls_on_one_account_run_in_SUBMISSION_ORDER():
    """FIFO, and a queued call does not START while the one ahead of it is still RUNNING: T-0144 R9 needs the cancel
    FINISHED before the close begins. Order of entry alone cannot see a second worker when each call returns at once."""
    book = _Traced()
    adapter, _ = _alpaca(book)
    release_x, release_y = threading.Event(), threading.Event()
    book.holds["get_all_positions"] = release_x
    book.holds["cancel_order_by_id"] = release_y
    try:
        async with asyncio.timeout(10):
            tasks = [asyncio.create_task(adapter.get_positions())]
            await _until(book.entered["get_all_positions"].is_set, "X is running")
            tasks.append(asyncio.create_task(adapter._call("cancel_order_by_id", "order-1")))
            await asyncio.sleep(0.05)
            tasks.append(asyncio.create_task(adapter._call("close_position", "BTCUSD")))
            await asyncio.sleep(0.05)
            tasks.append(asyncio.create_task(adapter._call("get_orders")))
            await asyncio.sleep(0.05)
            release_x.set()
            await _until(book.entered["cancel_order_by_id"].is_set, "Y (the cancel) is running")
            await asyncio.sleep(0.3)
            close_started_while_cancel_ran = book.entered["close_position"].is_set()
            release_y.set()
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        release_x.set()
        release_y.set()
    order = [n for n, _t in book.log]
    assert not close_started_while_cancel_ran, "close_position STARTED while cancel_order_by_id was still running"
    assert order[:4] == ["get_all_positions", "cancel_order_by_id", "close_position", "get_orders"], order


# ---------------------------------------------------------------------------------------------------
# E-5, E-12, E-14  THE REAL SDK ON LOOPBACK
# ---------------------------------------------------------------------------------------------------

@pytest.fixture
def venue():
    from tests.unit.test_b440_b441_submission_safety import _Venue

    v = _Venue()
    yield v
    v.close()


def _real_adapter(venue_url, key, *, workers=None):
    from app.services.broker.alpaca import AlpacaAdapter, build_trading_client
    from concurrent.futures import ThreadPoolExecutor

    client = build_trading_client(key, "s", paper=True, url_override=venue_url)
    client._retry_wait = 0
    adapter = AlpacaAdapter(client, paper=False)

    async def _instant(_s):
        return None

    adapter._sleep = _instant
    if workers is not None:   # the CONTROL's deliberate pool, never production
        adapter._executor._pool = ThreadPoolExecutor(max_workers=workers)
    return adapter, client


def _record_sends(monkeypatch):
    import requests

    intervals: list[tuple[int, int, float, float]] = []
    guard = threading.Lock()
    real_send = requests.Session.send

    def _send(self, request, **kw):
        start = time.monotonic()
        try:
            return real_send(self, request, **kw)
        finally:
            with guard:
                intervals.append((id(self), threading.get_ident(), start, time.monotonic()))

    monkeypatch.setattr(requests.Session, "send", _send)
    return intervals


def _overlaps(intervals):
    ordered = sorted(intervals, key=lambda i: i[2])
    return sum(1 for a, b in zip(ordered, ordered[1:]) if b[2] < a[3])


@pytest.mark.asyncio
async def test_E5_NO_Session_is_used_by_two_threads_on_the_REAL_SDK_and_the_control_sees_overlap(venue, monkeypatch):
    venue.stall_s = 0.05
    venue.scripts["GET /v2/orders"] = [(200, [])]
    intervals = _record_sends(monkeypatch)
    key = f"PK-B437-{uuid.uuid4().hex}"
    a1, _ = _real_adapter(venue.url, key)
    a2, _ = _real_adapter(venue.url, key)
    async with asyncio.timeout(20):
        await asyncio.gather(*[a.get_orders() for a in (a1, a2, a1, a2, a1, a2)])
    assert len(intervals) == 6, intervals
    assert len({t for _s, t, _a, _b in intervals}) == 1, "one account's requests ran on more than one thread"
    assert _overlaps(intervals) == 0, "two requests on one account were on the wire at once"

    intervals.clear()
    c1, _ = _real_adapter(venue.url, f"PK-B437-{uuid.uuid4().hex}", workers=2)
    async with asyncio.timeout(20):
        await asyncio.gather(*[c1.get_orders() for _ in range(6)])
    assert _overlaps(intervals) > 0, "a deliberate 2-worker pool showed no overlap: this instrument cannot see one"


@pytest.mark.asyncio
async def test_E12_a_STUCK_call_is_bounded_by_B441_and_the_NEXT_call_runs_on_the_same_worker(venue, monkeypatch):
    import app.services.broker.alpaca as alpaca
    from app.core.exceptions import BrokerError

    monkeypatch.setattr(alpaca, "ALPACA_HTTP_CONNECT_TIMEOUT_S", 0.3)
    monkeypatch.setattr(alpaca, "ALPACA_HTTP_READ_TIMEOUT_S", 0.3)
    venue.scripts["GET /v2/orders"] = [(200, [])]
    venue.stall_s = 1.5                                   # accepts, and does not answer inside the read timeout
    intervals = _record_sends(monkeypatch)
    adapter, _ = _real_adapter(venue.url, f"PK-B437-{uuid.uuid4().hex}")
    async with asyncio.timeout(10):
        async with _Heartbeat() as beat:
            started = time.monotonic()
            with pytest.raises(BrokerError):
                await adapter.get_orders()
            stalled = time.monotonic() - started
    assert stalled < 1.2, f"the stuck call ran {stalled:.2f}s against a 0.3s read timeout"
    assert beat.ticks >= 10, "the loop was blocked during the stuck call"
    venue.stall_s = 0.0
    async with asyncio.timeout(10):
        assert await adapter.get_orders() == []
    assert len({t for _s, t, _a, _b in intervals}) == 1, "the stuck worker was replaced by another thread"


@pytest.mark.asyncio
async def test_E14_the_SDK_s_429_retry_SLEEP_runs_OFF_the_loop(venue):
    venue.scripts["GET /v2/orders"] = [(429, {"code": 1, "message": "rate"}), (429, {"code": 1, "message": "rate"}),
                                       (200, [])]
    adapter, client = _real_adapter(venue.url, f"PK-B437-{uuid.uuid4().hex}")
    client._retry_wait = 0.2
    async with asyncio.timeout(10):
        async with _Heartbeat() as beat:
            assert await adapter.get_orders() == []
    assert venue.hits.get("GET /v2/orders") == 3, venue.hits
    assert beat.ticks >= 20, f"the loop ticked {beat.ticks} times across two 0.2s retry sleeps: they ran inline"


# ---------------------------------------------------------------------------------------------------
# E-7  EXCEPTIONS CROSS THE THREAD INTACT
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E7_a_worker_raised_exception_keeps_its_TYPE_and_CAUSE_for_the_classifier():
    from requests.exceptions import ConnectTimeout, ReadTimeout
    from urllib3.exceptions import ConnectTimeoutError

    from app.core.exceptions import BrokerError
    from app.services.broker.alpaca import (
        SUBMISSION_ANSWERED, SUBMISSION_NOT_CREATED, SUBMISSION_UNANSWERED, classify_submission_failure,
    )

    cases = [(ReadTimeout("read timed out"), SUBMISSION_UNANSWERED),
             (ConnectTimeout(ConnectTimeoutError("connect timed out")), SUBMISSION_NOT_CREATED),
             (_venue_api_error(422, '{"code":42210000,"message":"client_order_id must be unique"}'), SUBMISSION_ANSWERED)]
    for raised, expected in cases:
        book = _Traced()

        def _raise(order_data, _raised=raised):
            raise _raised

        book.submit_order = _raise
        adapter, _ = _alpaca(book)
        async with asyncio.timeout(10):
            with pytest.raises(BrokerError) as caught:
                await adapter._call("submit_order", SimpleNamespace(symbol="BTC/USD", client_order_id="sig-e7"))
        assert caught.value.__cause__ is raised, (raised, caught.value.__cause__)
        assert classify_submission_failure(caught.value) == expected, (type(raised).__name__, expected)

    book = _Traced()

    def _read_timeout(order_data):
        book.calls.append(("submit_order", order_data.symbol))
        raise ReadTimeout("read timed out")

    book.submit_order = _read_timeout
    adapter, _ = _alpaca(book)
    async with asyncio.timeout(10):
        res = await adapter.place_order(_entry_req(client_order_id="sig-e7-flow"))
    assert res["status"] == "SUBMISSION_UNCONFIRMED" and book.called("get_order_by_client_id"), res


# ---------------------------------------------------------------------------------------------------
# E-8, E-9, E-10  CANCELLATION AND WRITES
# ---------------------------------------------------------------------------------------------------

def _cancelled_in_flight(lines):
    return [l for l in lines if "write_cancelled_in_flight" in l["message"]]


@pytest.mark.asyncio
async def test_E8a_a_STARTED_submit_is_awaited_LOGGED_with_its_ids_and_RE_RAISED():
    book = _Traced()
    release = threading.Event()
    book.holds["submit_order"] = release
    adapter, _ = _alpaca(book)
    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(adapter.place_order(_entry_req(client_order_id="sig-e8a")))
            await _until(book.entered["submit_order"].is_set, "submit_order is on the wire")
            task.cancel()
            await asyncio.sleep(0.1)
            assert not task.done(), "the cancelled task did not wait for the STARTED write"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        release.set()
        stop()
    assert len(book.called("submit_order")) == 1
    logged = _cancelled_in_flight(lines)
    assert len(logged) == 1 and logged[0]["call"] == "submit_order", [l["message"] for l in lines]
    assert logged[0]["order_id"] and logged[0]["client_order_id"] == "sig-e8a", logged[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["public_close", "sweep_close", "venue_cancel", "venue_close"])
async def test_E8bcd_every_WRITE_site_is_shielded_once_started(site, switch_off):
    # `T-0144` R2: the `remediation_cancel` and `remediation_close` sites went with B429's remediation (DESIGN §7); (ii)'s
    # R14 cancel-first (`cancel_open_orders_for`) and the engine's close order (`place_close`) are the write sites now.
    from datetime import datetime, timezone
    from decimal import Decimal

    from alpaca.trading.enums import OrderStatus, TimeInForce
    from alpaca.trading.models import Order

    book = _Traced()
    book.positions = [_Position(symbol="BTCUSD")]
    now = datetime.now(timezone.utc)
    resting = Order(id=uuid.uuid4(), client_order_id="rest", created_at=now, updated_at=now, submitted_at=now,
                    status=OrderStatus.NEW, time_in_force=TimeInForce.GTC, extended_hours=False, symbol="BTC/USD",
                    qty="0.01", filled_qty="0")
    book.get_orders = book._wrap("get_orders", lambda filter=None: [resting])
    member = {"venue_cancel": "cancel_order_by_id", "venue_close": "submit_order"}.get(site, "close_position")
    release = threading.Event()
    book.holds[member] = release
    adapter, _ = _alpaca(book)
    drive = {"public_close": lambda: adapter.close_position("BTCUSD"),
             "sweep_close": lambda: adapter.close_all_positions(),
             "venue_cancel": lambda: adapter.cancel_open_orders_for("BTC/USD"),
             "venue_close": lambda: adapter.place_close("BTC/USD", Decimal("0.001"), f"tai-{uuid.uuid4().hex}-s01")}[site]
    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(drive())
            await _until(book.entered[member].is_set, f"{member} is on the wire ({site})")
            task.cancel()
            await asyncio.sleep(0.1)
            assert not task.done(), f"the cancelled task did not wait for the started {member}"
            release.set()
            with pytest.raises(BaseException) as ended:
                await task
    finally:
        release.set()
        stop()
    assert isinstance(ended.value, asyncio.CancelledError) or type(ended.value).__name__ == "BrokerError", ended.value
    logged = [l for l in _cancelled_in_flight(lines) if l["call"] == member]
    assert len(logged) == 1, [l["message"] for l in lines]


@pytest.fixture
def switch_off():
    from app.services.compliance.kill_switch import kill_switch

    return kill_switch


@pytest.mark.asyncio
async def test_E9_a_shielded_write_that_RAISES_after_the_cancel_is_logged_re_raised_and_its_exception_RETRIEVED():
    book = _Traced()
    release = threading.Event()

    def _raises(order_data):
        book.entered["submit_order"].set()
        if not release.wait(GATE_S):
            raise AssertionError("never released")
        raise RuntimeError("venue dropped the connection after reading the order")

    book.submit_order = _raises
    adapter, _ = _alpaca(book)
    loop = asyncio.get_running_loop()
    reported: list[dict] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _l, ctx: reported.append(ctx))
    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(adapter.place_order(_entry_req(client_order_id="sig-e9")))
            await _until(book.entered["submit_order"].is_set, "the write started")
            task.cancel()
            await asyncio.sleep(0.05)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        gc.collect()
        await asyncio.sleep(0.05)
    finally:
        release.set()
        stop()
        loop.set_exception_handler(previous)
    logged = _cancelled_in_flight(lines)
    assert len(logged) == 1 and logged[0]["outcome"] == "raised" and logged[0]["client_order_id"] == "sig-e9", logged
    assert not reported, f"the loop reported an unretrieved exception: {reported}"


@pytest.mark.asyncio
async def test_E10_a_write_cancelled_while_still_QUEUED_is_WITHDRAWN_and_NOTHING_is_sent(monkeypatch):
    from tests.unit.test_t0140_order_body import BTC_MIN, _asset

    book = _Traced()
    adapter, _ = _alpaca(book)

    async def _asset_read(_pair):      # the asset read would queue behind the held job too, and never reach the submit
        return _asset("BTC/USD", min_order_size=BTC_MIN)

    adapter._fetch_asset = _asset_read
    names = _queued_job_names(monkeypatch)
    first, second = threading.Event(), threading.Event()
    try:
        async with asyncio.timeout(10):
            task, held = await _queue_the_submit_behind_a_hold(
                adapter, names, lambda: asyncio.create_task(adapter.place_order(_entry_req(client_order_id="sig-e10"))),
                first, second)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            second.set()
            await asyncio.gather(*held)
            await asyncio.sleep(0.1)
    finally:
        first.set()
        second.set()
    assert not book.called("submit_order"), "a write cancelled while QUEUED was sent anyway"
    assert not book.called("get_order_by_client_id")


def _queued_job_names(monkeypatch) -> list[str]:
    """`B469`: the NAME (`call`) of every job put on an account worker, in order, AS IT IS QUEUED — `AccountExecutor.run`
    submits the job to the pool before its first await, so a name is here once its job is on the queue. (These arms used
    to wait for the entry to HOLD the account lock. Since T-0144 R5' the first job under that lock is the BEFORE read,
    `get_all_positions`, not the submit, so they withdrew a READ and armed the switch before any submit existed.)"""
    from app.services.broker.alpaca import AccountExecutor

    names: list[str] = []
    original = AccountExecutor.run

    async def _run(self, fn, args=(), kwargs=None, **kw):
        names.append(kw.get("call", ""))
        return await original(self, fn, args, kwargs, **kw)

    monkeypatch.setattr(AccountExecutor, "run", _run)
    return names


async def _queue_the_submit_behind_a_hold(adapter, names: list[str], start_entry, first: threading.Event,
                                          second: threading.Event):
    """Hold the worker, start the entry, and once its BEFORE read is queued, queue a SECOND hold behind that read; then
    release the first. The read runs, and the SUBMIT is QUEUED behind the second hold — found there by name. Returns the
    entry's task and the two hold tasks."""
    held = [asyncio.create_task(_hold_worker(adapter, first))]
    await _until(lambda: names.count("held_read") == 1, "the first hold is queued")
    task = start_entry()
    await _until(lambda: "get_all_positions" in names, "the entry's BEFORE read is queued behind the first hold")
    held.append(asyncio.create_task(_hold_worker(adapter, second, what="the second hold")))
    await _until(lambda: names.count("held_read") == 2, "the second hold is queued behind the BEFORE read")
    first.set()
    await _until(lambda: "submit_order" in names, "the submit is QUEUED on the account worker, behind the second hold")
    assert not second.is_set() and names.count("submit_order") == 1, names
    return task, held


@pytest.mark.asyncio
async def test_E10p_on_the_REAL_SDK_a_queued_submit_cancelled_sends_ZERO_POSTs_and_looks_nothing_up(venue, monkeypatch):
    adapter, _ = _real_adapter(venue.url, f"PK-B437-{uuid.uuid4().hex}")

    async def _asset_read(_pair):
        from tests.unit.test_t0140_order_body import BTC_MIN, _asset
        return _asset("BTC/USD", min_order_size=BTC_MIN)

    adapter._fetch_asset = _asset_read
    names = _queued_job_names(monkeypatch)
    first, second = threading.Event(), threading.Event()
    try:
        async with asyncio.timeout(10):
            task, held = await _queue_the_submit_behind_a_hold(
                adapter, names, lambda: asyncio.create_task(adapter.place_order(_entry_req(client_order_id="sig-e10p"))),
                first, second)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            second.set()
            await asyncio.gather(*held)
            await asyncio.sleep(0.2)
    finally:
        first.set()
        second.set()
    assert venue.hits.get("POST /v2/orders", 0) == 0, f"an order went out after the cancel: {venue.hits}"
    assert venue.hits.get("GET by_client_order_id", 0) == 0, venue.hits


# ---------------------------------------------------------------------------------------------------
# E-11  THE SWITCH AT THE SEND, ON THE WORKER
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E11_a_switch_armed_while_the_submit_is_QUEUED_is_REJECTED_KILL_SWITCH_ARMED_with_ZERO_POSTs(
        venue, switch_off, monkeypatch):
    from app.models.decision_record import REJECTION_KILL_SWITCH_ARMED
    from app.services.broker.alpaca import AlpacaAdapter
    from app.services.execution.service import ExecMode, ExecutionService, Signal

    adapter, _ = _real_adapter(venue.url, f"PK-B437-{uuid.uuid4().hex}")
    # a loopback endpoint is not the paper URL, so the adapter reports is_simulation False and ExecutionService refuses
    # it outright; this arm is about the worker's check, so the flag is set for it
    monkeypatch.setattr(AlpacaAdapter, "is_simulation", property(lambda self: True))

    async def _asset_read(_pair):
        from tests.unit.test_t0140_order_body import BTC_MIN, _asset
        return _asset("BTC/USD", min_order_size=BTC_MIN)

    async def _account():
        return SimpleNamespace(equity=10_000.0)

    async def _mark(_pair):
        return 159.0

    adapter._fetch_asset, adapter.get_account, adapter.reference_price = _asset_read, _account, _mark
    sig = Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=159.0, sl=150.0, tp=None,
                 order_type=OrderType.MARKET, approved=True, client_order_id="sig-e11")
    names = _queued_job_names(monkeypatch)
    first, second = threading.Event(), threading.Event()
    try:
        async with asyncio.timeout(10):
            task, held = await _queue_the_submit_behind_a_hold(
                adapter, names, lambda: asyncio.create_task(ExecutionService(adapter, ExecMode.PAPER).execute(sig)),
                first, second)
            switch_off.arm(reason="E-11: pulled while the submit waited on the worker")
            second.set()
            await asyncio.gather(*held)
            res = await task
    finally:
        first.set()
        second.set()
    assert venue.hits.get("POST /v2/orders", 0) == 0, f"the submit went out after the switch was armed: {venue.hits}"
    assert venue.hits.get("GET by_client_order_id", 0) == 0, "a refusal was looked up as an order"
    assert (res.get("status"), res.get("rejection_code")) == ("REJECTED", REJECTION_KILL_SWITCH_ARMED), res


@pytest.mark.asyncio
async def test_E11t_a_submit_that_RETURNS_None_with_the_switch_DISARMED_is_never_a_kill_switch_refusal():
    from app.core.exceptions import KillSwitchArmed

    book = _Traced()

    def _returns_none(order_data):
        book.calls.append(("submit_order", order_data.symbol))
        return None

    book.submit_order = _returns_none
    adapter, _ = _alpaca(book)
    async with asyncio.timeout(10):
        try:
            res = await adapter.place_order(_entry_req(client_order_id="sig-e11t"))
        except KillSwitchArmed as exc:
            raise AssertionError(f"a None response was read as the kill switch's refusal: {exc}") from exc
        except Exception:  # noqa: BLE001 - any venue-shaped failure is acceptable; a switch refusal is not
            res = None
    assert book.called("submit_order")
    assert not (isinstance(res, dict) and res.get("rejection_code") == "KILL_SWITCH_ARMED"), res


@pytest.mark.asyncio
async def test_E11k_with_the_switch_ARMED_closes_and_cancels_still_go_OUT(switch_off):
    book = _Traced()
    book.positions = [_Position(symbol="BTCUSD")]
    adapter, _ = _alpaca(book)
    switch_off.arm(reason="E-11k")
    async with asyncio.timeout(10):
        await adapter._call("cancel_order_by_id", "order-9")
        await adapter.close_position("BTCUSD")
    assert book.called("cancel_order_by_id") and book.called("close_position"), book.calls


# ---------------------------------------------------------------------------------------------------
# E-15, E-16, E-17, E-18, E-19
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E15_no_THREAD_NAME_and_no_LOG_LINE_carries_the_account():
    secret = f"PK-B437-{uuid.uuid4().hex}"
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    slices = {digest[i:i + 12] for i in range(len(digest) - 11)}
    book = _Traced(api_key=secret)
    release = threading.Event()
    book.holds["get_all_positions"] = release
    adapter, _ = _alpaca(book)
    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(adapter.get_positions())
            await _until(book.entered["get_all_positions"].is_set, "the call is running")
            names = [t.name for t in threading.enumerate()]
            release.set()
            await task
            await adapter.place_order(_entry_req(client_order_id="sig-e15"))
    finally:
        release.set()
        stop()
    text = " ".join(names) + " " + json.dumps([{k: str(v) for k, v in l.items()} for l in lines])
    assert secret not in text and digest not in text, "the account key or its hash reached a thread name or a log line"
    assert not [s for s in slices if s in text], "a 12-character slice of the account hash reached a thread name or log"


@pytest.mark.asyncio
async def test_E16_the_worker_OUTLIVES_one_adapter_and_does_NOT_multiply():
    key = f"PK-B437-{uuid.uuid4().hex}"
    b1 = _Traced(api_key=key)
    a1, _ = _alpaca(b1)
    others = [_alpaca(_Traced(api_key=key))[0] for _ in range(4)]
    async with asyncio.timeout(10):
        await a1.get_positions()
        for a in others:
            await a.get_positions()
        executor = others[0]._executor
        assert all(a._executor is executor for a in others) and len(executor._pool._threads) <= 1
        await a1.disconnect()
        del a1
        gc.collect()
        assert await others[0].get_positions() is not None


def test_E16b_the_worker_thread_EXITS_when_no_adapter_on_the_account_remains():
    """The registry holds executors WEAKLY, as `account_executor`'s comment claims: once every adapter on the account is
    gone the executor is collected and its thread exits. A strong registry keeps one thread per account for ever (the
    candidate's X7, lost when this file was renumbered by review's rows and restored after the record run found E-g alive)."""
    async def _use():
        adapter, _ = _alpaca(_Traced(api_key=f"PK-B437-{uuid.uuid4().hex}"))   # a key no other arm's adapter shares
        await adapter.get_positions()
        executor = adapter._executor
        return weakref.ref(executor), list(executor._pool._threads)

    ref, threads = asyncio.run(_use())
    assert threads, "no worker thread was ever started"
    deadline = time.monotonic() + GATE_S
    while ref() is not None and time.monotonic() < deadline:
        gc.collect()
        time.sleep(0.02)
    assert ref() is None, "the account executor outlived every adapter on the account"
    for t in threads:
        t.join(GATE_S)
    assert not any(t.is_alive() for t in threads), "the worker thread did not exit"


def test_E17_two_SEQUENTIAL_event_loops_on_one_account_both_complete():
    book = _Traced()
    adapter, _ = _alpaca(book)
    for _ in range(2):
        assert asyncio.run(asyncio.wait_for(adapter.get_positions(), 5)) is not None


@pytest.mark.asyncio
async def test_E18_a_cancelled_RUNNING_read_returns_AT_ONCE_while_its_thread_is_still_held():
    book = _Traced()
    release = threading.Event()
    book.holds["get_all_positions"] = release
    adapter, _ = _alpaca(book)
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(adapter.get_positions())
            await _until(book.entered["get_all_positions"].is_set, "the read is running")
            cancelled_at = time.monotonic()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), 1.0)
            assert time.monotonic() - cancelled_at < 0.5 and not release.is_set()
    finally:
        release.set()


@pytest.mark.asyncio
async def test_E19_a_DISCARDED_read_that_RAISES_logs_NOTHING_on_the_loop():
    book = _Traced()
    release = threading.Event()

    def _raises():
        book.entered["get_all_positions"].set()
        if not release.wait(GATE_S):
            raise AssertionError("never released")
        raise RuntimeError("the read failed after its awaiter left")

    book.get_all_positions = _raises
    adapter, _ = _alpaca(book)
    loop = asyncio.get_running_loop()
    reported: list[dict] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _l, ctx: reported.append(ctx))
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(adapter.get_positions())
            await _until(book.entered["get_all_positions"].is_set, "the read is running")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            await asyncio.sleep(0.2)
            gc.collect()
            await asyncio.sleep(0.05)
    finally:
        release.set()
        loop.set_exception_handler(previous)
    assert not reported, f"the loop reported the discarded read's exception: {reported}"


# ---------------------------------------------------------------------------------------------------
# E-S1  SWEEP (b)'s WAIT NEVER PASSES THE DEADLINE, HOWEVER MANY READS ARE QUEUED — and what close-all then costs
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("queued_reads", [0, 5])
async def test_ES1_sweep_b_never_waits_past_the_DEADLINE_however_many_reads_are_queued(monkeypatch, queued_reads):
    import app.services.broker.alpaca as alpaca

    deadline = 0.6
    monkeypatch.setattr(alpaca, "KILL_SWITCH_RESPONSE_DEADLINE_S", deadline)
    book = _Traced()
    book.positions = [_Position(symbol="ETHUSD")]
    gate = _bounded_event()
    gated: set = set()
    adapter, _ = _alpaca(book, gated, gate)
    adapter._clock = time.monotonic
    read_s = 0.2
    marks: dict = {}
    real_sweep_b = adapter._close_sweep_b

    async def _timed_sweep_b(report, started_at):
        marks["b_start"] = time.monotonic()
        return await real_sweep_b(report, started_at)

    adapter._close_sweep_b = _timed_sweep_b

    def _slow_positions(real=book.get_all_positions):
        time.sleep(read_s)
        return real()

    async with asyncio.timeout(10):
        entry = asyncio.create_task(adapter.place_order(_entry_req(client_order_id="sig-es1")))
        gated.add(entry)
        await _until(lambda: entry in adapter.parked, "the entry holds the lock mid-resolution")
        book.get_all_positions = _slow_positions
        readers = [asyncio.create_task(adapter.get_positions()) for _ in range(queued_reads)]
        await asyncio.sleep(0)
        started = time.monotonic()
        report = await adapter.close_all_positions()
        wall = time.monotonic() - started
        gate.set()
        await asyncio.gather(entry, *readers, return_exceptions=True)
    rows = [r for r in report if r.get("client_order_id") == "sig-es1"]
    assert len(rows) == 1 and rows[0]["waited_s"] <= deadline + 1e-9, report
    # THE CAP RUNS FROM CLOSE-ALL'S START: (b) may wait only what the deadline has LEFT when (b) begins. With queued reads
    # (and sweep (a)'s own reads) eating into it, a cap restarted at (b) waits the whole deadline again.
    left = max(0.0, alpaca.KILL_SWITCH_RESPONSE_DEADLINE_S - (marks["b_start"] - started))
    assert rows[0]["waited_s"] <= left + 0.05, (rows[0]["waited_s"], left, report)
    # ...and the expiry row SAYS the deadline cut it short, naming the module's constant
    assert rows[0]["deadline_bounded"] is True and "KILL_SWITCH_RESPONSE_DEADLINE_S" in rows[0]["reason"], rows[0]
    # E-S1r: the measurement the stated residual carries — close-all's wall time with and without queued reads.
    print(f"\nE-S1r queued_reads={queued_reads} read_s={read_s} deadline={deadline} close_all_wall={wall:.2f}s "
          f"waited_s={rows[0]['waited_s']}")
