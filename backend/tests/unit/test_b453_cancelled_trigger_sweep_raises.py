"""B453 — a CANCELLED kill-switch trigger whose sweep then RAISES must still end in `CancelledError`, logged and audited.

B446's ruling: the awaiter of a cancelled trigger sees `CancelledError`, with every row logged and the audit written in a
fresh session. Driven at ab64c03 (deployed), review's registered set `_runs/2f/KILL_SET.md`:
  [in-loop]   cancelled while the sweep ran, then the sweep raised -> the sweep's RuntimeError ESCAPED; no audit, no rows
  [post-loop] the sweep had already raised when the cancel landed -> CancelledError, but still no audit and no rows

Through the REAL `KillSwitch` and `BrokerManager`, with real adapter closes. The raise is a stubbed SIDE EFFECT after the
closes — the trigger's final "Kill switch complete" log line — never a stubbed `_run_trigger`. Every hold is bounded.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.unit.test_b442_kill_switch_at_send import _Book, _Db, _alpaca, _bounded_event, _capture_logs, _hold_sweep, _until
from tests.unit.test_t0136_alpaca_adapter import _Position


class _SweepFailure(RuntimeError):
    pass


@pytest.fixture
def quiet(monkeypatch):
    import app.services.ws.manager as ws

    async def _no_push(**kw):
        return None

    monkeypatch.setattr(ws.ws_manager, "push_kill_switch", _no_push)


@pytest.fixture
def fresh_sessions(monkeypatch, engine):
    """The fresh session, counted: how many were OPENED, and the rows COMMITTED through them."""
    from app.db import session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    opened = {"n": 0}

    def _counting():
        opened["n"] += 1
        return maker()

    monkeypatch.setattr(dbsession, "async_session_maker", _counting)
    return maker, opened


def _ks_module():
    import importlib

    # the package re-exports the INSTANCE under the module's name, so the module is imported by its dotted path
    return importlib.import_module("app.services.compliance.kill_switch")


class _RaisingLogger:
    """The kill switch module's logger, forwarding everything, except that its final "Kill switch complete" line RAISES —
    a side effect after the real closes, never a stub of the function under test."""

    def __init__(self, real, failure, before_raise):
        self._real, self._failure, self._before_raise = real, failure, before_raise

    def warning(self, message, *a, **k):
        if str(message).startswith("Kill switch complete"):
            if self._before_raise is not None:
                self._before_raise()
            raise self._failure
        return self._real.warning(message, *a, **k)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _fail_after_the_closes(monkeypatch, failure, before_raise=None):
    module = _ks_module()
    monkeypatch.setattr(module, "logger", _RaisingLogger(module.logger, failure, before_raise))


def _two_positions(monkeypatch):
    from app.services.broker.manager import broker_manager

    book = _Book()
    book.positions = [_Position(symbol="BTCUSD"), _Position(symbol="ETHUSD")]
    adapter, _ = _alpaca(book)
    monkeypatch.setattr(broker_manager, "_adapters", {"conn-1": adapter})
    return book, adapter


async def _audits(maker):
    from app.models.audit_log import AuditLog

    async with maker() as fresh:
        return (await fresh.execute(select(AuditLog).where(AuditLog.event_type == "KILL_SWITCH_TRIGGERED"))).scalars().all()


@pytest.mark.asyncio
async def test_F1_F3_F6_F7_F8_IN_LOOP_cancelled_then_the_sweep_RAISES(monkeypatch, quiet, fresh_sessions):
    from app.core.kill_switch_state import KILL_SWITCH_STATE
    from app.services.compliance.kill_switch import KillSwitch

    maker, opened = fresh_sessions
    book, adapter = _two_positions(monkeypatch)
    held = _hold_sweep(adapter)
    failure = _SweepFailure("B453: the sweep failed after its closes")
    _fail_after_the_closes(monkeypatch, failure)
    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="F in-loop"))
            await _until(lambda: book.called("close_position"), "the sweep is closing")
            task.cancel()
            for _ in range(3):
                await asyncio.sleep(0)
            assert not task.done(), "the cancelled trigger stopped waiting for its sweep"
            held.set()
            with pytest.raises(asyncio.CancelledError) as ended:
                await task
    finally:
        stop()

    assert ended.value.__cause__ is failure, f"the sweep's exception is not the cause: {ended.value.__cause__!r}"  # F-8
    assert sorted(c[1] for c in book.called("close_position")) == ["BTCUSD", "ETHUSD"]
    errors = [l for l in lines if "sweep RAISED" in l["message"]]
    assert len(errors) == 1 and errors[0]["error"].startswith("_SweepFailure"), errors                               # F-7
    rows = [l for l in lines if l["message"] == "Kill switch row" and "RAISED" in str(l.get("context"))]
    assert sorted(r["pair"] for r in rows) == ["BTCUSD", "ETHUSD"], rows
    audits = await _audits(maker)
    assert opened["n"] == 1 and len(audits) == 1, (opened, [a.new_value for a in audits])                          # F-3
    value, details = audits[0].new_value, audits[0].metadata_json["details"]
    assert value["sweep_failure"].startswith("_SweepFailure") and "B453" in value["sweep_failure"], value           # F-7
    assert value["positions_closed"] is None and value["positions_failed"] is None, value                          # F-6
    assert sorted(d["pair"] for d in details) == ["BTCUSD", "ETHUSD"], details                                      # F-6
    assert KILL_SWITCH_STATE.trigger_started is None


@pytest.mark.asyncio
async def test_F5_POST_LOOP_the_sweep_had_ALREADY_raised_when_the_cancel_landed(monkeypatch, quiet, fresh_sessions):
    """Deterministic: the sweep cancels the trigger task and then raises, so the sweep is DONE before the trigger resumes."""
    from app.services.compliance.kill_switch import KillSwitch

    maker, opened = fresh_sessions
    book, adapter = _two_positions(monkeypatch)
    failure = _SweepFailure("B453: raised after cancelling its caller")
    box: dict = {}
    _fail_after_the_closes(monkeypatch, failure, before_raise=lambda: box["task"].cancel())
    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            box["task"] = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="F post-loop"))
            with pytest.raises(asyncio.CancelledError) as ended:
                await box["task"]
    finally:
        stop()
    assert ended.value.__cause__ is failure
    assert [l for l in lines if "sweep RAISED" in l["message"]], [l["message"] for l in lines]
    audits = await _audits(maker)
    assert opened["n"] == 1 and len(audits) == 1 and "sweep_failure" in audits[0].new_value, [a.new_value for a in audits]
    assert sorted(d["pair"] for d in audits[0].metadata_json["details"]) == ["BTCUSD", "ETHUSD"]


@pytest.mark.asyncio
async def test_F4_must_miss_NO_cancellation_the_sweep_s_OWN_exception_propagates_and_NO_cancel_path_audit(
        monkeypatch, quiet, fresh_sessions):
    from app.services.compliance.kill_switch import KillSwitch

    maker, opened = fresh_sessions
    _two_positions(monkeypatch)
    failure = _SweepFailure("B453: raised with no cancellation")
    _fail_after_the_closes(monkeypatch, failure)
    async with asyncio.timeout(10):
        with pytest.raises(_SweepFailure) as raised:
            await KillSwitch().trigger(_Db(), "user-1", reason="F no-cancel")
    assert raised.value is failure, "the sweep's exception was replaced"
    assert opened["n"] == 0, "the cancel path wrote an audit for a trigger nobody cancelled"


@pytest.mark.asyncio
async def test_F6_with_NO_rows_the_log_says_UNKNOWN_and_the_audit_invents_no_counts(monkeypatch, quiet, fresh_sessions):
    from app.services.broker.manager import broker_manager
    from app.services.compliance.kill_switch import KillSwitch

    maker, _opened = fresh_sessions
    monkeypatch.setattr(broker_manager, "_adapters", {})
    box: dict = {}
    _fail_after_the_closes(monkeypatch, _SweepFailure("B453: no rows"), before_raise=lambda: box["task"].cancel())
    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            box["task"] = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="F no rows"))
            with pytest.raises(asyncio.CancelledError):
                await box["task"]
    finally:
        stop()
    assert any("UNKNOWN" in l["message"] for l in lines), [l["message"] for l in lines]
    audits = await _audits(maker)
    assert len(audits) == 1 and audits[0].new_value["positions_closed"] is None, [a.new_value for a in audits]


@pytest.mark.asyncio
async def test_F9_an_audit_COMMIT_that_fails_still_ends_CANCELLED(monkeypatch, quiet):
    from app.db import session as dbsession
    from app.services.compliance.kill_switch import KillSwitch

    class _FailingSession:
        def add(self, row):
            pass

        async def commit(self):
            raise RuntimeError("database down at commit")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(dbsession, "async_session_maker", lambda: _FailingSession())
    _two_positions(monkeypatch)
    box: dict = {}
    _fail_after_the_closes(monkeypatch, _SweepFailure("B453: audit down too"), before_raise=lambda: box["task"].cancel())
    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            box["task"] = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="F9"))
            with pytest.raises(asyncio.CancelledError):
                await box["task"]
    finally:
        stop()
    assert any("audit row could NOT be written" in l["message"] for l in lines), [l["message"] for l in lines]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["in_loop", "post_loop"])
async def test_F10_after_either_path_a_SECOND_trigger_PROCEEDS(monkeypatch, quiet, fresh_sessions, path):
    from app.services.compliance.kill_switch import KillSwitch

    ks_module = _ks_module()
    book, adapter = _two_positions(monkeypatch)
    box: dict = {}
    if path == "in_loop":
        held = _hold_sweep(adapter)
        _fail_after_the_closes(monkeypatch, _SweepFailure("F10 in-loop"))
    else:
        held = None
        _fail_after_the_closes(monkeypatch, _SweepFailure("F10 post-loop"), before_raise=lambda: box["task"].cancel())
    async with asyncio.timeout(10):
        box["task"] = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="F10 first"))
        if held is not None:
            await _until(lambda: book.called("close_position"), "the sweep is closing")
            box["task"].cancel()
            for _ in range(3):
                await asyncio.sleep(0)
            held.set()
        with pytest.raises(asyncio.CancelledError):
            await box["task"]
        monkeypatch.setattr(ks_module, "logger", ks_module.logger._real)
        second = await KillSwitch().trigger(_Db(), "user-2", reason="F10 second")
    assert not second.get("already_in_progress"), f"the first trigger's mark survived its {path} failure: {second}"



# ---------------------------------------------------------------------------------------------------
# S-F1 RULED — the audit write of EVERY cancelled path is shielded and bounded (F-11..F-17)
# ---------------------------------------------------------------------------------------------------
#
# These arms can HANG under a mutant (review's shapes A and A2), and an asyncio bound inside the arm hangs with it. So each
# scenario runs on its OWN event loop in a THREAD, and the arm's bound is `thread.join(timeout)`: a hang fails the arm by
# name. The fresh session is a SPY at `async_session_maker`, recording ADDED and COMMITTED.

import threading
import time as _time

PATHS = ["finished", "in_loop", "post_loop"]
HANG_S = 8.0


class _SpySession:
    """A fresh session whose commit is: `gate` (waits on a threading.Event, polled), `never`, or `raise_after` a delay."""

    def __init__(self, record: dict, mode: str, gate: threading.Event | None = None, delay_s: float = 0.0):
        self.record, self.mode, self.gate, self.delay_s = record, mode, gate, delay_s

    def add(self, row):
        self.record["added"] = self.record.get("added", 0) + 1
        self.record["row"] = row

    async def commit(self):
        self.record["commit_started"] = _time.monotonic()
        if self.mode == "gate":
            while not self.gate.is_set():
                await asyncio.sleep(0.01)
        elif self.mode == "never":
            while True:
                await asyncio.sleep(0.05)
        elif self.mode == "raise_after":
            await asyncio.sleep(self.delay_s)
            raise RuntimeError("the audit commit failed after the bound")
        self.record["committed"] = self.record.get("committed", 0) + 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _in_thread(scenario, what: str):
    """Run `scenario()` (a coroutine factory) on a fresh event loop in a thread; the ARM's bound is the join."""
    out: dict = {}

    def _target():
        try:
            out["value"] = asyncio.run(scenario())
        except BaseException as exc:  # noqa: BLE001 - reported to the arm
            out["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(HANG_S)
    if thread.is_alive():
        pytest.fail(f"HUNG: {what} did not finish within {HANG_S}s")
    if "error" in out:
        raise out["error"]
    return out["value"]


def _scenario(monkeypatch, path: str, *, commit_mode: str, gate: threading.Event | None = None, delay_s: float = 0.0,
              extra_cancels: int = 0, cancel_interval_s: float = 0.0, release_gate_after_s: float | None = None):
    from app.db import session as dbsession
    from app.services.compliance.kill_switch import KillSwitch

    record: dict = {}
    monkeypatch.setattr(dbsession, "async_session_maker", lambda: _SpySession(record, commit_mode, gate, delay_s))
    book, adapter = _two_positions(monkeypatch)
    box: dict = {}
    if path == "in_loop":
        _fail_after_the_closes(monkeypatch, _SweepFailure(f"S-F1 {path}"))
    elif path == "post_loop":
        _fail_after_the_closes(monkeypatch, _SweepFailure(f"S-F1 {path}"), before_raise=lambda: box["task"].cancel())

    async def _run():
        loop = asyncio.get_running_loop()
        handler_calls: list = []
        loop.set_exception_handler(lambda _l, ctx: handler_calls.append(ctx))
        held = _hold_sweep(adapter) if path in ("finished", "in_loop") else None
        box["task"] = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason=f"S-F1 {path}"))
        if held is not None:
            await _until(lambda: book.called("close_position"), "the sweep is closing")
            box["task"].cancel()
            for _ in range(3):
                await asyncio.sleep(0)
            held.set()
        await _until(lambda: "commit_started" in record, "the audit commit started")
        started = _time.monotonic()
        ended: dict = {}
        box["task"].add_done_callback(lambda _t: ended.setdefault("at", _time.monotonic()))
        # `B453` amendment (F11/F15's gap): what the record says AT THE MOMENT THE TASK ENDS. The scenario reads `record` again
        # only after its 0.4 s sleep, by which time a write left running in the background has landed — so a helper that
        # RETURNED on a second cancel passed. In a real shutdown the loop closes at the task's end and that write is lost.
        box["task"].add_done_callback(lambda _t: ended.setdefault("committed_at_end", record.get("committed", 0)))
        for _ in range(extra_cancels):
            box["task"].cancel()
            if cancel_interval_s:
                await asyncio.sleep(cancel_interval_s)
            else:
                await asyncio.sleep(0)
        if release_gate_after_s is not None:
            await asyncio.sleep(release_gate_after_s)
            gate.set()
        outcome = "returned"
        try:
            await box["task"]
        except asyncio.CancelledError:
            outcome = "cancelled"
        except BaseException as exc:  # noqa: BLE001
            outcome = f"raised {type(exc).__name__}"
        elapsed = _time.monotonic() - started
        finished_after = ended.get("at", _time.monotonic()) - started   # when the TASK ended, not when this loop looked
        await asyncio.sleep(0.4)
        import gc
        gc.collect()
        await asyncio.sleep(0.05)
        return {"outcome": outcome, "elapsed": elapsed, "finished_after": finished_after, "record": dict(record),
                "committed_at_end": ended.get("committed_at_end"),
                "handler_calls": handler_calls}
    return _run


@pytest.mark.parametrize("path", PATHS)
def test_F11_a_SECOND_cancel_during_the_audit_write_does_not_abandon_it(monkeypatch, quiet, path):
    gate = threading.Event()
    run = _scenario(monkeypatch, path, commit_mode="gate", gate=gate, extra_cancels=1, release_gate_after_s=0.2)
    got = _in_thread(run, f"F-11 [{path}]")
    assert got["outcome"] == "cancelled", got
    assert got["record"].get("added") == 1 and got["record"].get("committed") == 1, got["record"]
    assert got["committed_at_end"] == 1, f"the task ENDED before its audit committed (the write was left to the background): {got}"


@pytest.mark.parametrize("path", PATHS)
def test_F12_F13_the_BOUND_fires_on_a_commit_that_never_ends_and_the_task_still_ends_CANCELLED(monkeypatch, quiet, path):
    from app.services.compliance.kill_switch import KillSwitch

    monkeypatch.setattr(KillSwitch, "CANCELLED_AUDIT_BOUND_S", 0.3)
    lines, stop = _capture_logs()
    try:
        got = _in_thread(_scenario(monkeypatch, path, commit_mode="never", extra_cancels=1), f"F-12/F-13 [{path}]")
    finally:
        stop()
    assert got["outcome"] == "cancelled" and got["elapsed"] < 1.5, got
    assert any("did not finish within its bound" in l["message"] for l in lines), [l["message"] for l in lines]
    assert any(l["message"] == "Kill switch row" for l in lines), "the rows were not logged before the bound fired"


@pytest.mark.parametrize("path", PATHS)
def test_F14_the_bound_runs_from_the_WRITE_S_START_not_from_each_cancel(monkeypatch, quiet, path):
    from app.services.compliance.kill_switch import KillSwitch

    monkeypatch.setattr(KillSwitch, "CANCELLED_AUDIT_BOUND_S", 0.3)
    got = _in_thread(_scenario(monkeypatch, path, commit_mode="never", extra_cancels=4, cancel_interval_s=0.2),
                     f"F-14 [{path}]")
    # Four cancels, 0.2s apart, keep arriving past the 0.3s bound. A deadline fixed at the write's start ends the task near
    # 0.3s WHILE they are still arriving; a bound restarted per cancel (shape B) ends 0.3s after the LAST one, near 0.9s.
    # Measured from the TASK's own end (its done callback), not from when this loop got round to looking.
    assert got["outcome"] == "cancelled" and got["finished_after"] < 0.6, got


@pytest.mark.parametrize("path", PATHS)
def test_F15_N_cancels_during_the_write_still_end_CANCELLED_never_a_normal_return(monkeypatch, quiet, path):
    gate = threading.Event()
    got = _in_thread(_scenario(monkeypatch, path, commit_mode="gate", gate=gate, extra_cancels=3,
                               release_gate_after_s=0.1), f"F-15 [{path}]")
    assert got["outcome"] == "cancelled" and got["record"].get("committed") == 1, got
    assert got["committed_at_end"] == 1, f"the task ENDED before its audit committed (the write was left to the background): {got}"


@pytest.mark.parametrize("path", PATHS)
def test_F16_a_write_that_RAISES_after_the_bound_leaves_NO_unretrieved_exception(monkeypatch, quiet, path):
    from app.services.compliance.kill_switch import KillSwitch

    monkeypatch.setattr(KillSwitch, "CANCELLED_AUDIT_BOUND_S", 0.1)
    got = _in_thread(_scenario(monkeypatch, path, commit_mode="raise_after", delay_s=0.25), f"F-16 [{path}]")
    assert got["outcome"] == "cancelled", got
    assert not got["handler_calls"], f"the loop reported an unretrieved exception: {got['handler_calls']}"
