"""B445 + B446 — the kill switch's report must be TRUE: every row survives an adapter's abnormal exit, and a
cancelled trigger finishes its sweep and then says it was cancelled.

**B445 (driven at 56a1294):** `broker_manager.close_all_positions` caught each adapter's exception and appended one
`{"status": "error"}` row. The adapter had attached its per-position report as `partial_report` — `B366` taught the
kill switch to read it, but only from an exception the MANAGER raises, and it never does. A confirmed CLOSED
position and a close SENT-and-never-observed reached the operator as "0 position(s) closed, 1 failed".

**B446 (driven at 56a1294):** every adapter converted a cancellation into that `BrokerError`, so a cancelled
trigger stepped past it, closed the NEXT adapter's positions, and RETURNED NORMALLY.

Manager's rulings (2026-09-14): every row tagged with broker + connection id; a cancelled trigger FINISHES the
sweep (a panic stop half done is the worst state), logs every row, writes its audit row in a FRESH session, and
re-raises; the in-progress mark lives as long as the sweep; a second trigger through the route is a 409 with no
counters. Every arm drives the REAL `BrokerManager`.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.broker.base import BrokerAdapter
from tests.unit.test_b442_kill_switch_at_send import _Book, _Db, _alpaca, _capture_logs, _until
from tests.unit.test_t0136_alpaca_adapter import _Position


class Abort(BaseException):
    """An abnormal exit that is NOT a cancellation (a BaseException no per-position `except Exception` catches)."""


@pytest.fixture
def manager(monkeypatch):
    from app.services.broker.manager import broker_manager

    def _install(adapters: dict):
        monkeypatch.setattr(broker_manager, "_adapters", dict(adapters))
        return broker_manager

    return _install


@pytest.fixture
def quiet(monkeypatch):
    import app.services.ws.manager as ws

    async def _no_push(**kw):
        return None

    monkeypatch.setattr(ws.ws_manager, "push_kill_switch", _no_push)


def _abort_on(book, symbol, exc):
    real = book.close_position

    def _close(symbol_or_asset_id, close_options=None):
        if symbol_or_asset_id == symbol:
            book.calls.append(("close_position", symbol_or_asset_id))
            raise exc
        return real(symbol_or_asset_id, close_options)

    book.close_position = _close


def _by_pair(rows):
    return {r.get("pair"): r for r in rows}


# ---------------------------------------------------------------------------------------------------
# B445 — the manager keeps the adapter's report
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_M1_an_adapters_ABNORMAL_EXIT_keeps_every_row_TAGGED_and_adds_no_error_row(manager, quiet):
    from app.services.compliance.kill_switch import KillSwitch

    book = _Book()
    book.positions = [_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")]
    _abort_on(book, "ETH/USD", Abort("abnormal exit on the second position"))
    adapter, _ = _alpaca(book)
    manager({"conn-alpaca-1": adapter})

    result = await KillSwitch().trigger(_Db(), "user-1", reason="M1")

    assert [c[1] for c in book.called("close_position")] == ["BTC/USD", "ETH/USD"], "the drive never reached ETH"
    rows = _by_pair(result["details"])
    assert set(rows) == {"BTC/USD", "ETH/USD"}, f"a row was lost or an error row replaced the report: {result['details']}"
    assert rows["BTC/USD"]["disposition"] == "CLOSED"
    assert rows["ETH/USD"]["disposition"] == "FAILED" and "SENT" in rows["ETH/USD"]["reason"], rows["ETH/USD"]
    assert all((r["broker"], r["connection_id"]) == ("alpaca", "conn-alpaca-1") for r in result["details"]), (
        result["details"])
    assert not [r for r in result["details"] if r.get("status") == "error"]
    assert (result["positions_closed"], result["positions_failed_to_close"]) == (1, 1), result["message"]


@pytest.mark.asyncio
async def test_M2_an_adapter_that_could_not_ENUMERATE_still_gets_its_error_row(manager, quiet):
    """The must-miss: no report means the state of every position is unknown, and that stays loud."""
    from app.services.compliance.kill_switch import KillSwitch

    book = _Book()

    def _down():
        raise ConnectionError("venue unreachable")

    book.get_all_positions = _down
    adapter, _ = _alpaca(book)
    manager({"conn-alpaca-1": adapter})

    result = await KillSwitch().trigger(_Db(), "user-1", reason="M2")

    assert len(result["details"]) == 1, result["details"]
    row = result["details"][0]
    assert (row["status"], row["broker"], row["connection_id"]) == ("error", "alpaca", "conn-alpaca-1"), row
    assert "could not enumerate" in row["error"]
    assert result["positions_failed_to_close"] == 1


class _EmptyReportAdapter(BrokerAdapter):
    """An adapter that exits abnormally having enumerated NOTHING: `partial_report == []`."""
    broker_name = "empty"
    is_simulation = True

    async def close_all_positions(self):
        from app.core.exceptions import BrokerError

        failure = BrokerError("ended abnormally after 0 of 0 position(s)", broker="empty")
        failure.partial_report = []
        raise failure

    # the abstract contract, unused here
    async def connect(self): ...
    async def disconnect(self): ...
    async def get_account(self): ...
    async def get_positions(self): return []
    async def get_orders(self, status=None): return []
    async def get_recent_trades(self, since=None): return []
    async def place_order(self, request): ...
    async def close_position(self, position_id, lot_size=None): ...
    async def stream_prices(self, pairs, callback): ...


@pytest.mark.asyncio
async def test_M3_an_EMPTY_report_is_not_an_absent_one_no_error_row_and_it_is_logged(manager, quiet):
    from app.services.compliance.kill_switch import KillSwitch

    try:
        adapter = _EmptyReportAdapter()
    except TypeError as exc:  # an abstract member this stub missed: fail loudly, never skip
        raise AssertionError(f"the stub adapter does not satisfy BrokerAdapter: {exc}") from exc
    manager({"conn-empty": adapter})
    lines, stop = _capture_logs()
    try:
        result = await KillSwitch().trigger(_Db(), "user-1", reason="M3")
    finally:
        stop()
    assert result["details"] == [], result["details"]
    logged = [l for l in lines if l["message"] == "Kill switch: error closing positions"]
    assert logged and logged[0].get("partial_rows") == 0 and logged[0].get("connection_id") == "conn-empty", logged


@pytest.mark.asyncio
async def test_M4_the_FIRST_adapter_exits_abnormally_and_BOTH_adapters_rows_are_reported_all_tagged(manager, quiet):
    from app.services.broker.paper import PaperBroker
    from app.services.compliance.kill_switch import KillSwitch
    from tests.unit.test_b442_kill_switch_at_send import MARK, _entry_req

    book = _Book()
    book.positions = [_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")]
    _abort_on(book, "ETH/USD", Abort("abnormal exit"))
    adapter, _ = _alpaca(book)
    paper = PaperBroker(starting_balance=10_000, price_fn=lambda p: MARK)
    opened = await paper.place_order(_entry_req(client_order_id="sig-m4"))
    manager({"conn-alpaca-1": adapter, "conn-paper": paper})

    result = await KillSwitch().trigger(_Db(), "user-1", reason="M4")

    by_conn: dict = {}
    for r in result["details"]:
        by_conn.setdefault(r.get("connection_id"), []).append(r)
    assert sorted(r["pair"] for r in by_conn.get("conn-alpaca-1", [])) == ["BTC/USD", "ETH/USD"], result["details"]
    assert [r.get("position_id") for r in by_conn.get("conn-paper", [])] == [opened["position_id"]], result["details"]
    assert all(r.get("broker") for r in result["details"]), "a row does not name its broker"


# ---------------------------------------------------------------------------------------------------
# B446 — a cancelled trigger finishes, reports, and re-raises
# ---------------------------------------------------------------------------------------------------

def _slow(adapter):
    async def _sleep(_seconds):
        await asyncio.sleep(0.01)

    adapter._sleep = _sleep


@pytest.mark.asyncio
async def test_C1_a_CANCELLED_trigger_closes_EVERYTHING_logs_every_row_COMMITS_its_audit_and_RE_RAISES(
        manager, quiet, engine, monkeypatch):
    from app.db import session as dbsession
    from app.models.audit_log import AuditLog
    from app.services.compliance.kill_switch import KillSwitch

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)

    first = _Book()
    first.positions = [_Position(symbol="BTC/USD")]
    second = _Book()
    second.positions = [_Position(symbol="ETH/USD")]
    a1, _ = _alpaca(first)
    a2, _ = _alpaca(second)
    _slow(a1)
    manager({"conn-1": a1, "conn-2": a2})

    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="C1"))
            await _until(lambda: first.called("close_position"), "the first adapter's close was sent")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        stop()

    assert first.called("close_position") and second.called("close_position"), (
        "the cancelled trigger did not finish the sweep: the second adapter's position was never closed")
    assert not first.positions and not second.positions
    rows = [l for l in lines if l["message"] == "Kill switch row"]
    assert sorted((r["pair"], r["disposition"], r["connection_id"]) for r in rows) == [
        ("BTC/USD", "CLOSED", "conn-1"), ("ETH/USD", "CLOSED", "conn-2")], rows
    async with maker() as fresh:
        audits = (await fresh.execute(select(AuditLog).where(AuditLog.event_type == "KILL_SWITCH_TRIGGERED"))).scalars().all()
    assert len(audits) == 1 and audits[0].new_value["positions_closed"] == 2, [a.new_value for a in audits]


@pytest.mark.asyncio
async def test_C2_a_second_trigger_WHILE_the_cancelled_one_finishes_is_ALREADY_IN_PROGRESS(manager, quiet):
    from app.core.kill_switch_state import KILL_SWITCH_STATE
    from app.services.compliance.kill_switch import KillSwitch

    book = _Book()
    book.positions = [_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")]
    adapter, _ = _alpaca(book)
    _slow(adapter)
    manager({"conn-1": adapter})

    async with asyncio.timeout(10):
        task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="C2"))
        await _until(lambda: book.called("close_position"), "the sweep started")
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and KILL_SWITCH_STATE.trigger_started is not None, "the mark ended with the caller"
        second = await KillSwitch().trigger(_Db(), "user-2", reason="second")
        with pytest.raises(asyncio.CancelledError):
            await task

    assert second.get("already_in_progress") is True, second
    assert sorted(c[1] for c in book.called("close_position")) == ["BTC/USD", "ETH/USD"], "a position was closed twice"
    assert KILL_SWITCH_STATE.trigger_started is None


@pytest.mark.asyncio
async def test_C3_the_SWEEP_ITSELF_cancelled_reaches_the_caller_as_CancelledError_with_its_rows_logged(manager, quiet):
    """A loop shutdown cancels every task, the sweep included: the adapter must not turn that into a BrokerError, and
    the manager must hand every row reported so far up with it."""
    from app.core.kill_switch_state import KILL_SWITCH_STATE
    from app.services.broker.paper import PaperBroker
    from app.services.compliance.kill_switch import KillSwitch
    from tests.unit.test_b442_kill_switch_at_send import MARK, _entry_req

    paper = PaperBroker(starting_balance=10_000, price_fn=lambda p: MARK)
    opened = await paper.place_order(_entry_req(client_order_id="sig-c3"))
    book = _Book(close_status={"BTC/USD": "accepted"})
    book.positions = [_Position(symbol="BTC/USD")]
    adapter, _ = _alpaca(book)
    _slow(adapter)
    manager({"conn-paper": paper, "conn-alpaca": adapter})

    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="C3"))
            await _until(lambda: book.called("close_position"), "the Alpaca close was sent")
            sweeps = [t for t in asyncio.all_tasks() if getattr(t.get_coro(), "__qualname__", "") == "KillSwitch._sweep"]
            assert len(sweeps) == 1, f"expected one sweep task, found {len(sweeps)}"
            sweeps[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        stop()

    logged = {(l.get("pair"), l.get("connection_id")) for l in lines if l["message"] == "Kill switch row"}
    assert (opened["pair"], "conn-paper") in logged and ("BTC/USD", "conn-alpaca") in logged, logged
    assert KILL_SWITCH_STATE.trigger_started is None, "the mark survived a cancelled sweep"


def _mt5(close_errors):
    from tests.unit.test_t0106_mt5_adapter import _adapter, _position

    adapter, _ = _adapter(positions=[_position(f"p{i}") for i in range(1, 5)], close_errors=close_errors)
    return adapter, "position_id", ["p1", "p2", "p3", "p4"], "p2"


def _cft(close_errors):
    from tests.unit.test_t0132_cft_kill_switch_property import _adapter, _position

    adapter, _ = _adapter([_position(f"p{i}") for i in range(1, 5)], close_errors=close_errors)
    return adapter, "position_id", ["p1", "p2", "p3", "p4"], "p2"


def _alp(close_errors):
    book = _Book()
    book.positions = [_Position(symbol=s) for s in ("BTC/USD", "ETH/USD", "LTC/USD", "SOL/USD")]
    for symbol, exc in close_errors.items():
        _abort_on(book, {"p2": "ETH/USD"}[symbol], exc)
    adapter, _ = _alpaca(book)
    return adapter, "pair", ["BTC/USD", "ETH/USD", "LTC/USD", "SOL/USD"], "ETH/USD"


@pytest.mark.parametrize("factory", [_alp, _mt5, _cft], ids=["alpaca", "mt5", "cft"])
@pytest.mark.parametrize("kind", ["cancelled", "other_base_exception"])
def test_C4_every_adapter_REPORTS_ONE_ROW_PER_ENUMERATED_POSITION_and_re_raises_a_cancellation_AS_ITSELF(
        factory, kind):
    """**Ruling 4.** The manager adds no error row on top of a report, which is safe ONLY if the report covers every
    enumerated position — the ones the loop never reached included. An adapter that attached only the rows it had
    processed would silently lose positions; this fails it instead."""
    from app.core.exceptions import BrokerError

    exc = asyncio.CancelledError() if kind == "cancelled" else Abort("abnormal exit")
    adapter, key, enumerated, failed_at = factory({"p2": exc})

    with pytest.raises(BaseException) as raised:
        asyncio.run(adapter.close_all_positions())

    if kind == "cancelled":
        assert type(raised.value) is asyncio.CancelledError, f"a cancellation left as {type(raised.value).__name__}"
    else:
        assert isinstance(raised.value, BrokerError), type(raised.value)
    report = getattr(raised.value, "partial_report", None)
    assert isinstance(report, list), "no report on the exception"
    assert sorted(str(r[key]) for r in report) == sorted(enumerated), (
        f"the report does not cover every enumerated position: {[r[key] for r in report]}")
    rows = {str(r[key]): r for r in report}
    assert rows[failed_at]["disposition"] == "FAILED"
    assert [p for p in enumerated[2:] if rows[p]["disposition"] == BrokerAdapter.NOT_ATTEMPTED] == enumerated[2:]


# ---------------------------------------------------------------------------------------------------
# (e) — the route answers a second trigger with 409 and no counters
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E1_a_second_trigger_through_the_ROUTE_is_409_with_the_rows_so_far_and_NO_COUNTERS(
        client, manager, quiet):
    from app.services.compliance.kill_switch import KillSwitch

    created = await client.post("/api/prop-firm/profiles", json={"firm_name": "FTMO", "rules_json": {}})
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]

    book = _Book()
    book.positions = [_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")]
    planted = "sk-ant-PLANTEDb442secret0123456789"
    real_close = book.close_position

    def _btc_fails_with_a_credential_in_its_text(symbol_or_asset_id, close_options=None):
        if symbol_or_asset_id == "BTC/USD":
            book.calls.append(("close_position", symbol_or_asset_id))
            raise RuntimeError(f"venue said: bad auth header Bearer {planted}")
        return real_close(symbol_or_asset_id, close_options)

    book.close_position = _btc_fails_with_a_credential_in_its_text
    adapter, _ = _alpaca(book)
    _slow(adapter)
    manager({"conn-1": adapter})

    async with asyncio.timeout(10):
        first = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="first"))
        await _until(lambda: len(book.called("close_position")) == 2, "BTC's close failed and ETH's is resolving")
        resp = await client.post("/api/prop-firm/kill-switch", json={"profile_id": profile_id, "reason": "second"})
        await first

    assert resp.status_code == 409, (resp.status_code, resp.text)
    body = resp.json()
    assert "ALREADY IN PROGRESS" in body["detail"] and isinstance(body["rows_so_far"], list) and body["rows_so_far"], body
    assert all(isinstance(r, dict) and r.get("pair") for r in body["rows_so_far"]), "the rows are not JSON rows"
    assert "positions_closed" not in resp.text and "positions_failed" not in resp.text, resp.text
    # The rows carry venue text, and a response body is `B404`'s boundary: the planted credential must not leave.
    assert planted not in resp.text and "[REDACTED]" in resp.text, resp.text
    assert sorted(c[1] for c in book.called("close_position")) == ["BTC/USD", "ETH/USD"], "the 409 closed something"


@pytest.mark.asyncio
async def test_C5_an_audit_write_that_FAILS_on_the_cancelled_path_never_stops_the_CancelledError(
        manager, quiet, monkeypatch):
    from app.db import session as dbsession
    from app.services.compliance.kill_switch import KillSwitch

    class _Broken:
        async def __aenter__(self):
            raise RuntimeError("database down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(dbsession, "async_session_maker", lambda: _Broken())
    book = _Book()
    book.positions = [_Position(symbol="BTC/USD")]
    adapter, _ = _alpaca(book)
    _slow(adapter)
    manager({"conn-1": adapter})
    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="C5"))
            await _until(lambda: book.called("close_position"), "the close was sent")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        stop()
    assert any("audit row could NOT be written" in l["message"] for l in lines), "the audit failure was not logged"
