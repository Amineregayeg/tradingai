"""B437b — `B462` (the queued job holds its executor) and `B463` (a call's write/read class is DERIVED from the SDK member's
source, and a call in neither class is refused). Arms are named by review's registered rows (`_runs/b437b/KILL_SET.md`: H, W).

Sync doubles only (an `async def` double never enters the worker thread, `B437`); every gate is a bounded wait.
"""
from __future__ import annotations

import asyncio
import gc
import threading
import uuid

import pytest

pytestmark = pytest.mark.asyncio

GATE_S = 5.0


# ---------------------------------------------------------------------------------------------------
# H — B462: the job holds its executor until it ends
# ---------------------------------------------------------------------------------------------------

class _Counted:
    """A sync client double whose `get_account` counts the calls in flight ON THE ACCOUNT (a counter shared by every client
    built with the same `book`), and can be held on a threading gate."""

    def __init__(self, book: dict, key: str, gate: threading.Event | None = None):
        self._api_key = key
        self.book, self.gate = book, gate

    def get_account(self):
        with self.book["lock"]:
            self.book["inflight"] += 1
            self.book["peak"] = max(self.book["peak"], self.book["inflight"])
        self.book["entered"].set()
        try:
            if self.gate is not None and not self.gate.wait(GATE_S):
                raise AssertionError("the held read was never released")
            return None
        finally:
            with self.book["lock"]:
                self.book["inflight"] -= 1
                self.book["ended"].append(self.gate is not None)


async def _abandon_a_held_read(book: dict, key: str, gate: threading.Event):
    """Start a read that holds, cancel its caller, and return — so NOTHING of the caller survives: not the adapter, not
    the task, not its frames (review's drive 2; drive 1, which kept the frame, does not reproduce)."""
    from app.services.broker.alpaca import AlpacaAdapter

    adapter = AlpacaAdapter(_Counted(book, key, gate), paper=True)
    task = asyncio.ensure_future(adapter._call("get_account"))
    if not await asyncio.to_thread(book["entered"].wait, GATE_S):
        raise AssertionError("the held read never started")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    del task, adapter


async def test_H1_H3_an_ABANDONED_read_s_executor_is_not_replaced_while_its_job_runs_PEAK_one_call_per_account():
    """Drop every reference the cancelled caller held, collect, then call on the same account from a NEW adapter while the
    abandoned read still runs. Counted INSIDE the jobs, not by threads: at most one call at a time on the account."""
    from app.services.broker.alpaca import AlpacaAdapter

    key = f"PK-B462-{uuid.uuid4().hex}"
    book = {"lock": threading.Lock(), "inflight": 0, "peak": 0, "entered": threading.Event(), "ended": []}
    gate = threading.Event()
    try:
        async with asyncio.timeout(15):
            await _abandon_a_held_read(book, key, gate)
            for _ in range(3):
                gc.collect()
                await asyncio.sleep(0.05)
            second = AlpacaAdapter(_Counted(book, key), paper=True)
            call = asyncio.create_task(second._call("get_account"))
            await asyncio.sleep(0.3)               # a second worker would have run it by now
            peak_while_held = book["peak"]
            gate.set()
            await asyncio.wait_for(call, GATE_S)
    finally:
        gate.set()
    assert peak_while_held == 1, (
        f"two calls ran on one account at once (peak {peak_while_held}): the abandoned read's executor was collected "
        f"and the new adapter got a second worker (B462)")
    assert book["ended"] == [True, False], f"the second call did not wait for the abandoned read: {book['ended']}"


def test_H4_the_job_s_hold_ENDS_with_the_job_and_the_worker_thread_exits():
    """The strong reference lives on the job and nowhere longer: once nothing else holds the executor, it is collected
    and its thread exits (the complement of H-1; E16b pins the registry side)."""
    import weakref

    from app.services.broker.alpaca import AlpacaAdapter

    book = {"lock": threading.Lock(), "inflight": 0, "peak": 0, "entered": threading.Event(), "ended": []}

    async def _use():
        adapter = AlpacaAdapter(_Counted(book, f"PK-B462-{uuid.uuid4().hex}"), paper=True)
        await adapter._call("get_account")
        return weakref.ref(adapter._executor), list(adapter._executor._pool._threads)

    ref, threads = asyncio.run(_use())
    import time

    deadline = time.monotonic() + GATE_S
    while ref() is not None and time.monotonic() < deadline:
        gc.collect()
        time.sleep(0.02)
    assert ref() is None, "the executor outlived its last job and every adapter: a leaked strong reference"
    for t in threads:
        t.join(GATE_S)
    assert threads and not any(t.is_alive() for t in threads)


# ---------------------------------------------------------------------------------------------------
# W — B463: the class of a call is derived from the SDK member's source; neither is refused
# ---------------------------------------------------------------------------------------------------

def _adapter_call_names() -> set[str]:
    import ast
    import inspect

    import app.services.broker.alpaca as alpaca

    tree = ast.parse(inspect.getsource(alpaca))
    return {n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_call"
            and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}


def _planted_client_class():
    """A `TradingClient` subclass with one planted member per request verb, a GET-only member, and a member that sends
    nothing. A fresh class per call, so the classification cache never answers for an earlier plant."""
    from alpaca.trading.client import TradingClient

    class _Planted(TradingClient):
        def flatten_via_post(self):
            return self.post("/v2/planted")

        def flatten_everything(self):
            return self.delete("/v2/planted")

        def flatten_via_patch(self):
            return self.patch("/v2/planted", {})

        def flatten_via_put(self):
            return self.put("/v2/planted", {})

        def peek_planted(self):
            return self.get("/v2/planted")

        def sends_nothing(self):
            self.ran = True
            return "ran"

    return _Planted


def test_W1_every_call_the_adapter_makes_is_CLASSIFIED_and_the_writes_it_makes_are_WRITES():
    from alpaca.trading.client import TradingClient

    from app.services.broker.alpaca import CALL_READ, CALL_WRITE, classify_call

    client = TradingClient("PK-B463", "s", paper=True)
    names = _adapter_call_names()
    assert len(names) >= 10, f"the source scan found only {sorted(names)}: the instrument is broken"
    unclassified = sorted(n for n in names if classify_call(client, n) not in (CALL_WRITE, CALL_READ))
    assert not unclassified, f"these _call names are in neither class and would be refused: {unclassified}"
    for write in ("submit_order", "close_position", "cancel_order_by_id"):
        assert write in names and classify_call(client, write) == CALL_WRITE, write
    for read in ("get_all_positions", "get_order_by_id", "get_account"):
        assert classify_call(client, read) == CALL_READ, read


@pytest.mark.parametrize("member", ["flatten_via_post", "flatten_everything", "flatten_via_patch", "flatten_via_put"])
async def test_W2_W5_a_member_is_a_WRITE_by_the_VERB_its_source_calls_not_by_its_NAME_and_RUNS_SHIELDED(member):
    """One plant per verb on a `TradingClient` subclass, under names no list or pattern knows. `_call` must dispatch each
    with `write=True` (shielded)."""
    from app.services.broker.alpaca import CALL_WRITE, AccountExecutor, AlpacaAdapter, classify_call

    client = _planted_client_class()(f"PK-B463-{uuid.uuid4().hex}", "s", paper=True)
    assert classify_call(client, member) == CALL_WRITE, member
    adapter = AlpacaAdapter(client, paper=True)
    seen: dict = {}

    async def _spy(self, fn, args=(), kwargs=None, *, write=False, call="", describe=None, guard=None):
        seen["write"], seen["call"] = write, call
        return None

    original = AccountExecutor.run
    AccountExecutor.run = _spy
    try:
        await asyncio.wait_for(adapter._call(member), GATE_S)
    finally:
        AccountExecutor.run = original
    assert seen == {"write": True, "call": member}, seen


async def test_W3_a_member_in_NEITHER_class_is_REFUSED_and_never_RUN():
    from app.core.exceptions import BrokerError
    from app.services.broker.alpaca import AlpacaAdapter, classify_call

    client = _planted_client_class()(f"PK-B463-{uuid.uuid4().hex}", "s", paper=True)
    assert classify_call(client, "sends_nothing") is None
    adapter = AlpacaAdapter(client, paper=True)
    with pytest.raises(BrokerError, match="refusing Alpaca call 'sends_nothing'"):
        await asyncio.wait_for(adapter._call("sends_nothing"), GATE_S)
    assert not getattr(client, "ran", False), "a call in neither class was RUN"
    assert classify_call(client, "peek_planted") == "read"


async def test_W4_an_UNREADABLE_source_REFUSES_loudly_it_never_becomes_an_empty_write_set(monkeypatch):
    import inspect

    from app.core.exceptions import BrokerError
    from app.services.broker.alpaca import AlpacaAdapter

    client = _planted_client_class()(f"PK-B463-{uuid.uuid4().hex}", "s", paper=True)
    adapter = AlpacaAdapter(client, paper=True)

    def _unreadable(obj):
        raise OSError("could not get source code")

    monkeypatch.setattr(inspect, "getsource", _unreadable)
    with pytest.raises(BrokerError, match="unreadable"):
        await asyncio.wait_for(adapter._call("flatten_everything"), GATE_S)
