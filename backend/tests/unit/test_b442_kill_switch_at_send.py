"""B442 — the kill switch must stop an entry that has already passed its gate.

`_tick_symbol` reads `kill_switch.is_armed` in `_entry_block_reason`, then SUSPENDS (the bias fetch, the news
fetch, the signal broadcast) before `execution.execute(sig)` sends. A switch pulled inside that window armed,
enumerated the book and closed it, and the entry then opened a position the switch's report could not
mention. **Driven at fb3dab6 on both simulators the loop binds: FILLED, a 5.55555556-unit position.**

The fix, as ruled (manager, 2026-09-13): the switch's state lives in `app.core.kill_switch_state` and every
adapter reads it AT THE SEND; `ExecutionService` files the refusal `KILL_SWITCH_ARMED` (migration `0016`);
Alpaca holds a per-ACCOUNT order lock from that check through the verdict, and `close_all_positions` sweeps
twice — the second under that lock, with a wait capped by the kill switch's response deadline; a second
trigger while one runs closes nothing. Rows `K2-*` are review's registered kill set
(`agents/tasks/_runs/b442/KILL_SET.md`).

**THE ALPACA ARMS DO NOT DRIVE THE TICK, and that is measured, not chosen.** A loop bound to `AlpacaAdapter`
is halted by `B428a`'s capability gate (`REQUIRED_BROKER_CAPABILITIES = ("on_tick",)`; the adapter has none)
before `execute` is reached. So the Alpaca window is driven from `ExecutionService.execute`, whose own awaits
(`get_account`, `reference_price`) precede the send exactly as the tick's do.

No arm opens a socket except R1's, which dials a CLOSED loopback port on purpose.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import socket
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest
from app.services.execution.service import Signal
from app.services.live import crypto_loop as mod
from app.services.live.crypto_loop import LiveCryptoLoop

MARK = 159.0
ENTRY_ID = "sig-b442-entry"


# ---------------------------------------------------------------------------------------------------
# fixtures and doubles
# ---------------------------------------------------------------------------------------------------

@pytest.fixture
def switch():
    from app.services.compliance.kill_switch import kill_switch

    return kill_switch


@pytest.fixture
def no_network(monkeypatch):
    """A network call on a driven path fails event arms on a blip and passes absence arms for the wrong reason."""
    def _refuse(self, address):
        raise AssertionError(f"B442 arms open no socket; something on the driven path dialled {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)


def _bars():
    base = [MARK - 60 + i for i in range(61)]
    return pd.DataFrame({"open": base, "high": [b + 1 for b in base], "low": [b - 1 for b in base],
                         "close": base, "volume": [10.0] * 61})


class _Trace:
    reasons = ["b442"]
    summary = "b442"

    def __getattr__(self, _):
        return None


def _signal(symbol="BTC/USD"):
    return Signal(symbol=symbol, direction=DirectionType.LONG, entry=MARK, sl=MARK - 9, tp=MARK + 18,
                  order_type=OrderType.MARKET, approved=True, client_order_id="sig-b442")


def _entry_req(pair="BTC/USD", client_order_id=ENTRY_ID):
    return OrderRequest(pair=pair, direction=DirectionType.LONG, order_type=OrderType.MARKET,
                        lot_size=0.01, client_order_id=client_order_id)


def _drive_tick(monkeypatch, loop, *, arm_in_bias_fetch):
    """Everything on `_tick_symbol`'s path is stubbed EXCEPT the gate, `ExecutionService.execute` and the bound
    broker's `place_order`."""
    from app.services.compliance.kill_switch import kill_switch

    seen: dict = {"fetches": [], "executed": [], "results": [], "rejected": [], "acts": []}
    bars = _bars()

    async def _noop(*a, **k):
        return None

    async def _fetch(bsym, tf, n):
        seen["fetches"].append(tf)
        if arm_in_bias_fetch and tf == loop.bias_tf:
            assert not kill_switch.is_armed, "the switch was armed before the gate ran; this arm tests nothing"
            kill_switch.arm(reason="B442: pulled while the loop was suspended in the bias fetch")
        return bars

    real_execute = loop.execution.execute

    async def _execute(sig):
        seen["executed"].append(sig)
        res = await real_execute(sig)
        seen["results"].append(res)
        return res

    async def _rejected(pair, entry, sig, reason, trace, code=None):
        seen["rejected"].append((reason, code))

    async def _act(kind, msg):
        seen["acts"].append((kind, msg))

    sig = _signal()
    monkeypatch.setattr(mod, "_ticker_price", lambda _bsym: MARK)
    monkeypatch.setattr(mod, "evaluate_latest_bar_traced", lambda *a, **k: (sig, _Trace()))
    monkeypatch.setattr(mod.exit_shadow, "record_from_loop", lambda *a, **k: None)
    for name in ("push_tick", "push_position_open", "push_position_close", "push_position_update", "broadcast"):
        monkeypatch.setattr(mod.ws_manager, name, _noop)
    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_act", _act)
    monkeypatch.setattr(loop, "_close_at_session_end", _noop)
    monkeypatch.setattr(loop, "_shadow_evaluate", _noop)
    monkeypatch.setattr(loop, "_maybe_emit_census", _noop)
    monkeypatch.setattr(loop, "_news_context", _noop)
    monkeypatch.setattr(loop, "_record_rejected_signal", _rejected)
    monkeypatch.setattr(loop, "_record_signal_decision", _noop)
    monkeypatch.setattr(loop, "_record_abstention", _noop)
    monkeypatch.setattr(loop.execution, "execute", _execute)
    return seen


def _sdk_order(order_id, symbol, status, filled_qty):
    """A REAL `alpaca.trading.models.Order` (`a-double-can-answer-for-the-wrong-method`)."""
    from alpaca.trading.enums import OrderClass, OrderStatus, TimeInForce
    from alpaca.trading.models import Order

    now = datetime.now(timezone.utc)
    return Order(
        id=order_id, client_order_id=f"b442-{symbol}", created_at=now, updated_at=now, submitted_at=now,
        status=OrderStatus(status), time_in_force=TimeInForce.GTC, order_class=OrderClass.SIMPLE,
        extended_hours=False, symbol=symbol, qty="0.01", filled_qty=filled_qty,
        filled_avg_price="70000" if status == "filled" else None,
    )


class _Book:
    """A synchronous `TradingClient` double with a BOOK. An entry order stays `accepted` until the test sets
    `fill_entries`; a read that finds it filled ADDS the position. A close fills on its second read (so its
    resolution yields once) unless `close_status` pins it, and a filled close REMOVES the position."""

    def __init__(self, api_key=None, close_status=None):
        self._api_key = api_key if api_key is not None else f"PK-B442-{uuid.uuid4().hex}"
        self.calls: list[tuple] = []
        self.positions: list = []
        self.orders: dict[str, dict] = {}
        self.fill_entries = False
        self.close_status = dict(close_status or {})
        self.enumerations = 0
        self.on_enumerate = None

    def get_asset(self, symbol):
        from tests.unit.test_t0140_order_body import BTC_MIN, _asset

        self.calls.append(("get_asset", symbol))
        return _asset(symbol, min_order_size=BTC_MIN)

    def submit_order(self, order_data):
        self.calls.append(("submit_order", order_data.symbol))
        oid = uuid.uuid4()
        self.orders[str(oid)] = {"kind": "entry", "symbol": order_data.symbol, "status": "accepted", "reads": 0}
        return _sdk_order(oid, order_data.symbol, "accepted", "0")

    def get_order_by_client_id(self, client_id):
        self.calls.append(("get_order_by_client_id", client_id))
        raise RuntimeError("not scripted: no arm here expects a client_order_id lookup")

    def get_order_by_id(self, order_id, filter=None):
        self.calls.append(("get_order_by_id", str(order_id)))
        from tests.unit.test_t0136_alpaca_adapter import _Position

        o = self.orders[str(order_id)]
        o["reads"] += 1
        if o["kind"] == "entry" and self.fill_entries and o["status"] != "filled":
            o["status"] = "filled"
            self.positions.append(_Position(symbol=o["symbol"]))
        if o["kind"] == "close" and o["status"] == "accepted" and o["pinned"] is None and o["reads"] >= 2:
            o["status"] = "filled"
            self.positions = [p for p in self.positions if p.symbol != o["symbol"]]
        return _sdk_order(uuid.UUID(str(order_id)), o["symbol"], o["status"],
                          "0.01" if o["status"] == "filled" else "0")

    def get_all_positions(self):
        self.enumerations += 1
        if self.on_enumerate is not None:
            self.on_enumerate(self.enumerations)
        return list(self.positions)

    def close_position(self, symbol_or_asset_id, close_options=None):
        self.calls.append(("close_position", symbol_or_asset_id))
        oid = uuid.uuid4()
        pinned = self.close_status.get(symbol_or_asset_id)
        self.orders[str(oid)] = {"kind": "close", "symbol": symbol_or_asset_id, "status": pinned or "accepted",
                                 "reads": 0, "pinned": pinned}
        return _sdk_order(oid, symbol_or_asset_id, pinned or "accepted", "0")

    def get_orders(self, filter=None):
        return []

    def called(self, name):
        return [c for c in self.calls if c[0] == name]


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _alpaca(book, gated: set | None = None, gate: asyncio.Event | None = None):
    """An `AlpacaAdapter` over `book`. Its sleep advances a fake clock and YIELDS; a task in `gated` waits on
    `gate` first, which is how an arm holds an entry mid-resolution for as long as it needs."""
    from app.services.broker.alpaca import AlpacaAdapter

    adapter = AlpacaAdapter(book, paper=True)
    clock = _Clock()
    adapter._clock = clock

    async def _sleep(seconds):
        if gate is not None and gated is not None and asyncio.current_task() in gated:
            await gate.wait()
        await asyncio.sleep(0)
        clock.now += seconds

    adapter._sleep = _sleep
    return adapter, clock


async def _until(predicate, what="the condition"):
    for _ in range(10_000):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"never reached: {what}")


def _capture_logs():
    from app.core.logging import logger

    lines: list[dict] = []
    sink = logger.add(lambda m: lines.append({"message": m.record["message"], **m.record["extra"]}), level="DEBUG")
    return lines, lambda: logger.remove(sink)


class _Db:
    def add(self, row):
        pass

    async def flush(self):
        pass


@pytest.fixture
def quiet_trigger(monkeypatch):
    """`KillSwitch.trigger`'s websocket push, replaced; SMTP is unconfigured in tests."""
    import app.services.ws.manager as ws

    async def _no_push(**kw):
        return None

    monkeypatch.setattr(ws.ws_manager, "push_kill_switch", _no_push)


# ---------------------------------------------------------------------------------------------------
# A — THE WINDOW, DRIVEN: an entry past the gate is refused at the send
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("mode,broker", [("paper", "PaperBroker"), ("sim", "SimPropFirmBroker")])
async def test_A1_a_switch_armed_after_the_GATE_stops_the_SIMULATOR_entry(monkeypatch, switch, no_network,
                                                                        mode, broker):
    """**K2-7 too:** the refusal is a coded REJECTED row and nothing raises out of the tick — without the
    service's mapping, `KillSwitchArmed` reaches the loop's backstop and is filed `VENUE_RAISED`."""
    loop = LiveCryptoLoop(broker_mode=mode)
    assert type(loop.paper).__name__ == broker, type(loop.paper)
    seen = _drive_tick(monkeypatch, loop, arm_in_bias_fetch=True)

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    # proof the path ran: the gate passed, the bias fetch armed the switch, and the entry reached execute
    assert seen["fetches"] == [loop.entry_tf, loop.bias_tf], seen["fetches"]
    assert switch.is_armed and len(seen["executed"]) == 1, seen

    assert not loop.paper._positions, (
        f"a position opened AFTER the kill switch was armed: {list(loop.paper._positions.values())} "
        f"(execute returned {seen['results']})")

    from app.models.decision_record import REJECTION_KILL_SWITCH_ARMED

    assert [(r.get("status"), r.get("rejection_code")) for r in seen["results"]] == [
        ("REJECTED", REJECTION_KILL_SWITCH_ARMED)], seen["results"]
    assert [code for _reason, code in seen["rejected"]] == [REJECTION_KILL_SWITCH_ARMED], seen["rejected"]
    assert "Nothing was sent" in seen["rejected"][0][0]


@pytest.mark.asyncio
async def test_A2_cft_sim_reads_the_switch_AFTER_its_price_fetch(switch, no_network):
    """**K2-4.** `SimPropFirmBroker.place_order` awaits its price source before the insert; a switch armed DURING
    that await is the window. A check placed before the fetch passes, then inserts."""
    from app.core.exceptions import KillSwitchArmed
    from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker

    fetched: list[str] = []

    async def _source_that_suspends(pair):
        fetched.append(pair)
        switch.arm(reason="B442: pulled during the simulator's price fetch")
        await asyncio.sleep(0)
        return MARK

    sim = SimPropFirmBroker(PropFirmRules(starting_balance=10_000), _source_that_suspends)
    assert not switch.is_armed
    with pytest.raises(KillSwitchArmed):
        await sim.place_order(_entry_req())
    assert fetched == ["BTC/USD"], "the fetch never ran, so the window was never opened"
    assert not sim._positions, f"cft_sim inserted a position after the switch was armed: {sim._positions}"


@pytest.mark.asyncio
async def test_A3_ALPACA_an_entry_past_the_gate_is_refused_before_submit_order(switch, no_network):
    """**The Alpaca window, from `execute`** (the tick cannot reach Alpaca: `B428a`, see the module docstring).
    Armed inside `reference_price`, one of `execute`'s awaits before the send. **K2-8:** neither `submit_order`
    nor a client_order_id lookup ever runs, and the result is the coded refusal, not UNRESOLVED."""
    from app.models.decision_record import REJECTION_KILL_SWITCH_ARMED
    from app.services.execution.service import ExecMode, ExecutionService

    book = _Book()
    adapter, _clock = _alpaca(book)

    async def _account():
        return SimpleNamespace(equity=10_000.0)

    async def _price_then_the_switch(pair):
        switch.arm(reason="B442: pulled while execute awaited the mark")
        return MARK

    adapter.get_account = _account
    adapter.reference_price = _price_then_the_switch

    res = await ExecutionService(adapter, ExecMode.PAPER).execute(_signal())

    assert book.called("get_asset"), "place_order was never reached — this arm tested nothing"
    assert not book.called("submit_order"), f"an order was SENT after the switch was armed: {book.calls}"
    assert not book.called("get_order_by_client_id"), "a refusal was looked up as an order that was never sent"
    assert (res.get("status"), res.get("rejection_code")) == ("REJECTED", REJECTION_KILL_SWITCH_ARMED), res


@pytest.mark.asyncio
async def test_A4_ALPACA_place_order_raises_KillSwitchArmed_itself_never_a_BrokerError(switch):
    """**K2-8, at the adapter.** Raised through `_call` or inside the submission `try`, it would be a
    `BrokerError`, classified UNANSWERED, and looked up."""
    from app.core.exceptions import BrokerError, KillSwitchArmed

    book = _Book()
    adapter, _clock = _alpaca(book)
    switch.arm(reason="A4")
    with pytest.raises(KillSwitchArmed) as raised:
        await adapter.place_order(_entry_req())
    assert not isinstance(raised.value, BrokerError)
    assert book.called("get_asset") and not book.called("submit_order") and not book.called("get_order_by_client_id")


@pytest.mark.asyncio
async def test_A5_an_entry_WAITING_for_the_lock_reads_the_switch_AFTER_it_gets_the_lock(switch):
    """The check is under the lock, not before it. Entry 1 holds the account lock mid-resolution; entry 2 waits
    for it; the switch is armed; entry 1 finishes. Checked before the lock, entry 2 would already have passed."""
    from app.core.exceptions import KillSwitchArmed

    book = _Book()
    gate = asyncio.Event()
    gated: set = set()
    adapter, _clock = _alpaca(book, gated, gate)
    async with asyncio.timeout(10):
        first = asyncio.create_task(adapter.place_order(_entry_req(client_order_id="sig-b442-first")))
        gated.add(first)
        await _until(lambda: len(book.called("submit_order")) == 1, "entry 1 submitted")
        second = asyncio.create_task(adapter.place_order(_entry_req(client_order_id="sig-b442-second")))
        await _until(lambda: len(book.called("get_asset")) == 2, "entry 2 read its asset and queued on the lock")
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(book.called("submit_order")) == 1, "entry 2 submitted while entry 1 held the account lock"
        switch.arm(reason="A5")
        book.fill_entries = True
        gate.set()
        await first
        with pytest.raises(KillSwitchArmed):
            await second
    assert len(book.called("submit_order")) == 1, f"entry 2 was SENT after the switch was armed: {book.calls}"


@pytest.mark.asyncio
async def test_A6_the_KillSwitch_state_is_the_one_every_adapter_reads(no_network):
    """**K2-3.** The module singleton AND a fresh `KillSwitch()` are the core state — an instance with state of its
    own is a switch no adapter reads — and an adapter built BEFORE the switch is armed still refuses."""
    from app.core.exceptions import KillSwitchArmed
    from app.core.kill_switch_state import KILL_SWITCH_STATE
    from app.services.broker.paper import PaperBroker
    from app.services.compliance.kill_switch import KillSwitch, kill_switch

    assert kill_switch._state is KILL_SWITCH_STATE and KillSwitch()._state is KILL_SWITCH_STATE
    paper = PaperBroker(starting_balance=10_000, price_fn=lambda p: MARK)
    KillSwitch().arm(reason="A6: a fresh instance")
    assert kill_switch.is_armed and kill_switch.reason == "A6: a fresh instance"
    with pytest.raises(KillSwitchArmed):
        await paper.place_order(_entry_req())
    assert not paper._positions


@pytest.mark.asyncio
async def test_K2_17_the_loop_GATE_stays_an_armed_tick_never_reaches_execute(monkeypatch, switch, no_network):
    loop = LiveCryptoLoop(broker_mode="paper")
    seen = _drive_tick(monkeypatch, loop, arm_in_bias_fetch=False)
    switch.arm(reason="K2-17")

    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert seen["fetches"] == [loop.entry_tf], "the tick never reached the gate"
    assert not seen["executed"], "an armed tick reached execute(): the early gate is gone"
    assert any("KILL SWITCH ARMED" in msg for _kind, msg in seen["acts"]), seen["acts"]


@pytest.mark.asyncio
async def test_M1_ExecutionService_files_KILL_SWITCH_ARMED_and_raises_nothing():
    """**K2-7's real kill.** `KillSwitchArmed` is not a `BrokerError`; without the mapping it escapes `execute`."""
    from app.core.exceptions import KillSwitchArmed
    from app.models.decision_record import REJECTION_KILL_SWITCH_ARMED
    from app.services.execution.service import ExecMode, ExecutionService

    class _Refusing:
        is_simulation = True
        direction_policy = None
        sent: list = []

        async def get_account(self):
            return SimpleNamespace(equity=10_000.0)

        async def reference_price(self, pair):
            return MARK

        async def place_order(self, request):
            self.sent.append(request)
            raise KillSwitchArmed("KILL SWITCH ARMED (M1): nothing was sent")

    broker = _Refusing()
    res = await ExecutionService(broker, ExecMode.PAPER).execute(_signal())
    assert len(broker.sent) == 1
    assert (res["status"], res["rejection_code"]) == ("REJECTED", REJECTION_KILL_SWITCH_ARMED), res
    assert "M1" in res["reason"] and res["client_order_id"] == "sig-b442"


@pytest.mark.asyncio
async def test_K2_9_the_switch_never_refuses_its_OWN_closes(switch, no_network):
    """Submissions only. Closes on paper, cft_sim and Alpaca proceed while armed."""
    from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker
    from app.services.broker.paper import PaperBroker
    from tests.unit.test_t0136_alpaca_adapter import _Position

    async def _mark(pair):
        return MARK

    paper = PaperBroker(starting_balance=10_000, price_fn=lambda p: MARK)
    sim = SimPropFirmBroker(PropFirmRules(starting_balance=10_000), _mark)
    for broker in (paper, sim):
        one = await broker.place_order(_entry_req(client_order_id="sig-k29-a"))
        await broker.place_order(_entry_req(pair="ETH/USD", client_order_id="sig-k29-b"))
        switch.arm(reason="K2-9")
        closed = await broker.close_position(one["position_id"])
        assert closed.get("status") not in ("error", "failed", "not_found"), (type(broker).__name__, closed)
        rest = await broker.close_all_positions()
        assert rest and not broker._positions, (type(broker).__name__, rest)
        switch.disarm()

    book = _Book()
    book.positions = [_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")]
    adapter, _clock = _alpaca(book)
    switch.arm(reason="K2-9 alpaca")
    single = await adapter.close_position("BTC/USD")
    assert single["close_confirmed"] is True, single
    report = await adapter.close_all_positions()
    assert [(r["pair"], r["disposition"]) for r in report] == [("ETH/USD", "CLOSED")], report
    assert not book.positions


# ---------------------------------------------------------------------------------------------------
# L — THE ACCOUNT LOCK AND THE TWO SWEEPS
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_L1_an_entry_RESOLVING_when_the_switch_is_pulled_is_CLOSED_by_sweep_b(switch):
    book = _Book()
    gate = asyncio.Event()
    gated: set = set()
    adapter, _clock = _alpaca(book, gated, gate)
    async with asyncio.timeout(10):
        entry = asyncio.create_task(adapter.place_order(_entry_req()))
        gated.add(entry)
        await _until(lambda: book.called("submit_order"), "the entry submitted")
        switch.arm(reason="L1")
        closing = asyncio.create_task(adapter.close_all_positions())
        await _until(lambda: book.enumerations >= 1, "sweep (a) enumerated")
        for _ in range(5):
            await asyncio.sleep(0)
        assert book.enumerations == 1, "sweep (b) enumerated while the entry still held the account lock"
        book.fill_entries = True
        gate.set()
        placed = await entry
        report = await closing

    assert placed["status"] == "FILLED", placed
    assert [(r["pair"], r["disposition"], r.get("sweep")) for r in report] == [("BTC/USD", "CLOSED", "b")], (
        f"the position the in-flight entry opened is not in the kill switch's report: {report}")
    assert not book.positions and len(book.called("close_position")) == 1


@pytest.mark.asyncio
async def test_L2_on_EXPIRY_the_row_names_the_in_flight_entry_and_says_it_may_exist(monkeypatch):
    """**K2-15**, and the wait is the DERIVED bound read live (**K2-14** — the row carries the value)."""
    import app.services.broker.alpaca as alpaca

    monkeypatch.setattr(alpaca, "ALPACA_HTTP_CONNECT_TIMEOUT_S", 0.01)
    monkeypatch.setattr(alpaca, "ALPACA_HTTP_READ_TIMEOUT_S", 0.02)
    # 0.5s, not less: the entry must still SLEEP after its first read (offset 0.25), which is where it is held.
    monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_BUDGET_S", 0.5)
    book = _Book()
    book._retry, book._retry_wait = 0, 0
    gate = asyncio.Event()
    gated: set = set()
    adapter, _clock = _alpaca(book, gated, gate)
    derived = alpaca.entry_lock_normal_hold_bound_s(book)
    assert derived < 1.0, derived

    lines, stop = _capture_logs()
    try:
        async with asyncio.timeout(10):
            entry = asyncio.create_task(adapter.place_order(_entry_req()))
            gated.add(entry)
            await _until(lambda: book.called("submit_order"), "the entry submitted")
            report = await adapter.close_all_positions()
            gate.set()
            await entry
    finally:
        stop()

    rows = [r for r in report if r.get("sweep") == "b" and r["disposition"] == "NOT_ATTEMPTED"]
    assert len(rows) == 1, report
    row = rows[0]
    assert (row["pair"], row["client_order_id"]) == ("BTC/USD", ENTRY_ID), row
    assert "MAY EXIST" in row["reason"] and "[sweep b]" in row["reason"], row["reason"]
    assert row["lock_wait_bound_s"] == derived and row["deadline_bounded"] is False, row
    assert f"{derived:.1f}s" in row["reason"], row["reason"]
    logged = [l for l in lines if "in_flight_entry_not_waited_for" in l["message"]]
    assert logged and logged[0].get("client_order_id") == ENTRY_ID, logged


@pytest.mark.asyncio
async def test_L2b_the_DEADLINE_is_measured_from_close_all_START_not_from_sweep_b(monkeypatch):
    """Sweep (a)'s enumeration takes all but 50ms of the deadline (an injected clock). Measured from sweep (b)'s
    start, the wait would be min(3C + B, 100s) and this arm times out."""
    from app.core.kill_switch_state import KILL_SWITCH_RESPONSE_DEADLINE_S
    import app.services.broker.alpaca as alpaca

    book = _Book()
    gate = asyncio.Event()
    gated: set = set()
    adapter, clock = _alpaca(book, gated, gate)
    derived = alpaca.entry_lock_normal_hold_bound_s(book)
    assert derived > KILL_SWITCH_RESPONSE_DEADLINE_S, derived

    def _slow_sweep_a(n):
        if n == 1:
            clock.now += KILL_SWITCH_RESPONSE_DEADLINE_S - 0.05

    book.on_enumerate = _slow_sweep_a
    async with asyncio.timeout(5):
        entry = asyncio.create_task(adapter.place_order(_entry_req()))
        gated.add(entry)
        await _until(lambda: book.called("submit_order"), "the entry submitted")
        report = await adapter.close_all_positions()
        gate.set()
        await entry

    rows = [r for r in report if r.get("client_order_id") == ENTRY_ID]
    assert len(rows) == 1, report
    row = rows[0]
    assert row["deadline_bounded"] is True and row["waited_s"] <= 0.05 + 1e-9, row
    assert row["lock_wait_bound_s"] == derived and f"of the up to {derived:.1f}s" in row["reason"], row["reason"]
    assert "KILL_SWITCH_RESPONSE_DEADLINE_S" in row["reason"], row["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["switch_refusal", "cancelled_mid_resolution", "submission_refused"])
async def test_K2_13_the_lock_is_RELEASED_on_every_exit_from_place_order(monkeypatch, switch, how):
    import app.services.broker.alpaca as alpaca

    book = _Book()
    gate = asyncio.Event()
    gated: set = set()
    adapter, _clock = _alpaca(book, gated, gate)
    async with asyncio.timeout(10):
        if how == "switch_refusal":
            switch.arm(reason="K2-13")
            with pytest.raises(Exception):
                await adapter.place_order(_entry_req())
            switch.disarm()
        elif how == "cancelled_mid_resolution":
            task = asyncio.create_task(adapter.place_order(_entry_req()))
            gated.add(task)
            await _until(lambda: book.called("submit_order"), "the entry submitted")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            from urllib3.exceptions import ConnectTimeoutError

            def _refused(order_data):     # NOT_CREATED by type: re-raised from inside the lock, nothing looked up
                book.calls.append(("submit_order", order_data.symbol))
                raise ConnectTimeoutError("connect timed out")

            book.submit_order = _refused
            with pytest.raises(Exception):
                await adapter.place_order(_entry_req())
            assert not book.called("get_order_by_client_id")
        assert book.called("submit_order") or how == "switch_refusal"
        lock = alpaca._ACCOUNT_LOCKS[adapter._account_key].lock
        assert not lock.locked(), f"the account lock is still held after place_order exited ({how})"
        report = await adapter.close_all_positions()
        assert not lock.locked(), "close_all_positions' sweep (b) left the account lock held"
        book.submit_order = _Book.submit_order.__get__(book)
        switch.disarm() if switch.is_armed else None
        await asyncio.wait_for(adapter.place_order(_entry_req(client_order_id="sig-b442-after")), 5)
    assert not [r for r in report if r.get("client_order_id")], report


def test_K2_14_the_bound_is_DERIVED_from_the_live_constants_and_the_client(monkeypatch):
    import app.services.broker.alpaca as alpaca

    book = _Book()
    base = alpaca.entry_lock_normal_hold_bound_s(book)
    for name, value in (("ALPACA_HTTP_CONNECT_TIMEOUT_S", alpaca.ALPACA_HTTP_CONNECT_TIMEOUT_S + 1),
                        ("ALPACA_HTTP_READ_TIMEOUT_S", alpaca.ALPACA_HTTP_READ_TIMEOUT_S + 1),
                        ("ORDER_RESOLUTION_BUDGET_S", alpaca.ORDER_RESOLUTION_BUDGET_S + 1)):
        with monkeypatch.context() as m:
            m.setattr(alpaca, name, value)
            assert alpaca.entry_lock_normal_hold_bound_s(book) > base, f"the bound ignores {name}"
    book._retry = 0
    fewer = alpaca.entry_lock_normal_hold_bound_s(book)
    assert fewer < base, "the bound ignores the client's own retry count"
    book._retry, book._retry_wait = 3, 30
    assert alpaca.entry_lock_normal_hold_bound_s(book) > base, "the bound ignores the client's retry sleep"


def test_L3a_a_lock_whose_event_loop_is_CLOSED_is_REPLACED():
    import app.services.broker.alpaca as alpaca

    key = f"account:l3a-{uuid.uuid4().hex}"

    async def _contend():
        entry = alpaca._account_lock(key)
        async with entry.lock:
            waiter = asyncio.create_task(entry.lock.acquire())
            await asyncio.sleep(0)          # a waiter binds the lock to THIS loop
        await waiter
        entry.lock.release()
        return entry

    first = asyncio.run(_contend())
    second = asyncio.run(_contend())       # a lock bound to the closed loop would raise here
    assert second is not first and second.lock is not first.lock


def test_L3b_a_SECOND_LIVE_event_loop_contending_RAISES_and_the_switch_REPORTS_it():
    """**K2-1.** Keyed by (loop, account), the second loop would get a lock of its own — no mutual exclusion —
    and this entry would be sent."""
    import app.services.broker.alpaca as alpaca

    book = _Book()
    holding, release = threading.Event(), threading.Event()
    loop_a = asyncio.new_event_loop()
    adapter_a, _ = _alpaca(book)

    async def _sleep_until_released(_seconds):
        while not release.is_set():
            await asyncio.sleep(0.005)

    adapter_a._sleep = _sleep_until_released
    original_submit = book.submit_order

    def _submit_and_signal(order_data):
        out = original_submit(order_data)
        holding.set()
        return out

    book.submit_order = _submit_and_signal
    errors: list = []

    def _run_a():
        try:
            loop_a.run_until_complete(adapter_a.place_order(_entry_req(client_order_id="sig-b442-loop-a")))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=_run_a, daemon=True)
    thread.start()
    try:
        assert holding.wait(5), f"loop A never took the account lock: {errors}"
        adapter_b, _ = _alpaca(book)
        with pytest.raises(alpaca.AccountLockLoopConflict):
            asyncio.run(asyncio.wait_for(adapter_b.place_order(_entry_req(client_order_id="sig-b442-loop-b")), 5))
        assert len(book.called("submit_order")) == 1, f"the second loop's entry was SENT: {book.calls}"

        report = asyncio.run(asyncio.wait_for(adapter_b.close_all_positions(), 5))
        rows = [r for r in report if r.get("client_order_id") == "sig-b442-loop-a"]
        assert len(rows) == 1 and rows[0]["disposition"] == "NOT_ATTEMPTED", report
        assert "DIFFERENT live event loop" in rows[0]["reason"], rows[0]["reason"]
    finally:
        release.set()
        thread.join(5)
        loop_a.close()


@pytest.mark.asyncio
async def test_L4_ONE_lock_per_ACCOUNT_across_adapters_and_the_key_is_never_logged(monkeypatch):
    import app.services.broker.alpaca as alpaca

    monkeypatch.setattr(alpaca, "ALPACA_HTTP_CONNECT_TIMEOUT_S", 0.01)
    monkeypatch.setattr(alpaca, "ALPACA_HTTP_READ_TIMEOUT_S", 0.02)
    # 0.5s, not less: the entry must still SLEEP after its first read (offset 0.25), which is where it is held.
    monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_BUDGET_S", 0.5)
    secret = f"PK-B442-SHARED-{uuid.uuid4().hex}"
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()

    lines, stop = _capture_logs()
    try:
        entry_book, same_book, other_book = _Book(api_key=secret), _Book(api_key=secret), _Book()
        for b in (entry_book, same_book, other_book):
            b._retry, b._retry_wait = 0, 0
        gate = asyncio.Event()
        gated: set = set()
        entry_adapter, _ = _alpaca(entry_book, gated, gate)
        same_adapter, _ = _alpaca(same_book)
        other_adapter, _ = _alpaca(other_book)
        async with asyncio.timeout(10):
            entry = asyncio.create_task(entry_adapter.place_order(_entry_req()))
            gated.add(entry)
            await _until(lambda: entry_book.called("submit_order"), "the entry submitted")
            same = await same_adapter.close_all_positions()
            other = await other_adapter.close_all_positions()
            gate.set()
            await entry
    finally:
        stop()

    assert [r.get("client_order_id") for r in same] == [ENTRY_ID], (
        f"a second adapter on the SAME account did not wait for its entry: {same}")
    assert other == [], f"an adapter on a DIFFERENT account waited for this one's entry: {other}"
    text = repr(lines)
    assert lines and secret not in text and digest not in text and digest[:16] not in text, (
        "the API key id, or its hash, reached a log line")


@pytest.mark.asyncio
async def test_K2_2_sweep_b_never_RE_CLOSES_a_position_whose_close_in_sweep_a_is_unconfirmed():
    """A second close on a position whose first close may still be working is a second sell."""
    from tests.unit.test_t0136_alpaca_adapter import _Position

    book = _Book(close_status={"BTC/USD": "accepted"})
    book.positions = [_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")]
    adapter, _clock = _alpaca(book)
    report = await adapter.close_all_positions()

    assert book.enumerations == 2, "sweep (b) never re-enumerated, so this arm tested nothing"
    assert [c[1] for c in book.called("close_position")] == ["BTC/USD", "ETH/USD"], book.calls
    assert [(r["pair"], r["disposition"], r["sweep"]) for r in report] == [
        ("BTC/USD", "FAILED", "a"), ("ETH/USD", "CLOSED", "a")], report


@pytest.mark.asyncio
async def test_K2_5_a_symbol_CLOSED_in_a_and_OPEN_AGAIN_is_closed_in_b_and_NO_ROW_IS_COLLAPSED():
    from tests.unit.test_t0136_alpaca_adapter import _Position

    book = _Book()
    book.positions = [_Position(symbol="BTC/USD")]

    def _reopened_between_sweeps(n):
        if n == 2:
            book.positions.append(_Position(symbol="BTC/USD"))

    book.on_enumerate = _reopened_between_sweeps
    adapter, _clock = _alpaca(book)
    report = await adapter.close_all_positions()

    assert [(r["pair"], r["disposition"], r["sweep"]) for r in report] == [
        ("BTC/USD", "CLOSED", "a"), ("BTC/USD", "CLOSED", "b")], report
    assert [r["reason"][:9] for r in report] == ["[sweep a]", "[sweep b]"]
    assert len(book.called("close_position")) == 2 and not book.positions


def _venue_api_error(status: int, body: str):
    """A REAL `alpaca.common.exceptions.APIError` as the SDK raises it: the body string plus an http error whose
    response carries the status."""
    from alpaca.common.exceptions import APIError

    return APIError(body, SimpleNamespace(response=SimpleNamespace(status_code=status), request=None))


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal,expect_closed_once", [
    ((404, '{"code":40410000,"message":"position does not exist"}'), True),
    # must-miss: B449's 404 carries no JSON code, and a 403 is a different answer — both stay FAILED
    ((404, "Not Found"), False),
    ((403, '{"code":40310000,"message":"insufficient balance"}'), False),
], ids=["404_position_does_not_exist", "404_without_code", "403"])
async def test_LAG_a_position_still_LISTED_after_its_close_filled_is_CLOSED_once_not_FAILED(
        refusal, expect_closed_once):
    """**Manager's ruling on review's note 3 (probe round 3).** The venue lists the position for one more read after its
    close fills; sweep (b) re-closes it and the venue answers `position does not exist`. It is CLOSED — sweep (a)
    confirmed the fill — once, with the lag named; any other refusal stays FAILED."""
    from tests.unit.test_t0136_alpaca_adapter import _Position

    book = _Book()
    book.positions = [_Position(symbol="BTCUSD")]
    closes = {"n": 0}
    real_close = book.close_position

    def _close(symbol_or_asset_id, close_options=None):
        closes["n"] += 1
        if closes["n"] == 1:
            return real_close(symbol_or_asset_id, close_options)
        book.calls.append(("close_position", symbol_or_asset_id))
        raise _venue_api_error(*refusal)

    def _lagging_listing(n):
        if n == 2 and not book.positions:
            book.positions.append(_Position(symbol="BTCUSD"))   # still listed after the fill

    book.close_position = _close
    book.on_enumerate = _lagging_listing
    adapter, _clock = _alpaca(book)

    report = await adapter.close_all_positions()

    assert book.enumerations == 2 and closes["n"] == 2, "sweep (b) never re-closed the lagging listing"
    if expect_closed_once:
        assert [(r["pair"], r["disposition"], r["sweep"]) for r in report] == [("BTCUSD", "CLOSED", "a")], report
        assert "listing lag" in report[0]["reason"] and "40410000" in report[0]["reason"], report[0]["reason"]
    else:
        assert [(r["pair"], r["disposition"], r["sweep"]) for r in report] == [
            ("BTCUSD", "CLOSED", "a"), ("BTCUSD", "FAILED", "b")], report


@pytest.mark.asyncio
async def test_ZW_a_ZERO_wait_still_acquires_a_FREE_lock_so_no_in_flight_row_is_invented():
    """Review's note 2: with the deadline spent (wait = 0) and NO entry in flight, sweep (b) must take the free lock and
    report nothing extra. A zero wait that never acquires would over-alarm with a "nothing recorded" row."""
    from app.core.kill_switch_state import KILL_SWITCH_RESPONSE_DEADLINE_S
    from tests.unit.test_t0136_alpaca_adapter import _Position

    book = _Book()
    book.positions = [_Position(symbol="BTCUSD")]
    adapter, clock = _alpaca(book)

    def _deadline_spent_in_sweep_a(n):
        if n == 1:
            clock.now += KILL_SWITCH_RESPONSE_DEADLINE_S + 1

    book.on_enumerate = _deadline_spent_in_sweep_a
    async with asyncio.timeout(10):
        report = await adapter.close_all_positions()

    assert book.enumerations == 2, "sweep (b) never ran"
    assert [(r["pair"], r["disposition"], r["sweep"]) for r in report] == [("BTCUSD", "CLOSED", "a")], report


def test_G1_neither_CALLER_arms_the_switch_separately():
    """(g), AST: the route and the compliance engine pass their reason to trigger(), which arms itself and keeps an
    existing reason. A separate arm() before trigger() replaced the reason of a trigger already running."""
    import ast

    backend = Path(__file__).resolve().parents[2]
    files = [backend / "app" / "api" / "routers" / "prop_firm.py", backend / "app" / "services" / "compliance" / "engine.py"]

    def _arm_calls(source: str) -> list[int]:
        return [n.lineno for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "arm"]

    assert _arm_calls("from x import kill_switch\nkill_switch.arm(reason='r')\n") == [2], "the scanner cannot see a call"
    triggers = 0
    for f in files:
        source = f.read_text()
        assert not _arm_calls(source), f"{f.name} arms the kill switch separately at lines {_arm_calls(source)}"
        triggers += source.count("kill_switch.trigger(")
    assert triggers == 2, f"expected one trigger() call in each caller, found {triggers}: the scan read the wrong files"


@pytest.mark.asyncio
async def test_G2_a_second_ROUTE_request_during_a_running_trigger_leaves_the_FIRST_reason(client, monkeypatch,
                                                                                        quiet_trigger, switch):
    from app.services.broker.manager import broker_manager
    from app.services.compliance.kill_switch import KillSwitch

    created = await client.post("/api/prop-firm/profiles", json={"firm_name": "FTMO", "rules_json": {}})
    profile_id = created.json()["id"]
    book = _book_with_two_positions()
    adapter, _clock = _alpaca(book)
    gate = asyncio.Event()

    async def _held(_seconds):
        await gate.wait()

    adapter._sleep = _held
    monkeypatch.setattr(broker_manager, "_adapters", {"alpaca": adapter})
    async with asyncio.timeout(10):
        first = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="the FIRST reason"))
        await _until(lambda: book.called("close_position"), "the first trigger is closing")
        resp = await client.post("/api/prop-firm/kill-switch", json={"profile_id": profile_id, "reason": "SECOND"})
        reason_during = switch.reason
        gate.set()
        await first
    assert resp.status_code == 409, resp.text
    assert reason_during == "the FIRST reason" and switch.reason == "the FIRST reason", (reason_during, switch.reason)


@pytest.mark.asyncio
async def test_G3_a_compliance_BREACH_reason_still_reaches_the_AUDIT_row(db_session, monkeypatch, quiet_trigger):
    """(g): the engine no longer arms first, so the breach's detail must travel through trigger()'s own reason."""
    from app.models.audit_log import AuditLog
    from app.services.broker.manager import broker_manager
    from tests.unit.test_compliance_engine import _evaluate, _make_profile

    monkeypatch.setattr(broker_manager, "_adapters", {})
    profile = await _make_profile(db_session)
    state = await _evaluate(db_session, profile, equity=4750.0, balance=5000.0, daily_pnl=-250.0)
    assert state == "HALTED", state
    audits = [o for o in db_session.new if isinstance(o, AuditLog)] or (
        await db_session.execute(__import__("sqlalchemy").select(AuditLog))).scalars().all()
    reasons = [a.new_value.get("reason") for a in audits if a.event_type == "KILL_SWITCH_TRIGGERED"]
    assert len(reasons) == 1 and reasons[0].startswith("Compliance rule breached for profile"), reasons
    assert "daily_loss=" in reasons[0] and "limit=" in reasons[0], reasons[0]


def test_K2_18_the_response_deadline_is_below_the_proxy_EFFECTIVE_api_read_timeout():
    """Read `deploy/nginx-web.conf` at test time: the directive inside `location /api/`, else one inherited from
    the enclosing `server`, else nginx's default of 60s — never "not found, so skip". Controls, each a modified
    copy, validate the READER (a text search finds `/ws`'s 3600s when `/api/` has none)."""
    from app.core.kill_switch_state import KILL_SWITCH_RESPONSE_DEADLINE_S

    conf = (Path(__file__).resolve().parents[3] / "deploy" / "nginx-web.conf").read_text()
    effective = _effective_api_read_timeout_s(conf)
    assert effective == 120.0, f"the reader did not find the /api/ directive it must find: {effective}"
    assert KILL_SWITCH_RESPONSE_DEADLINE_S < effective

    in_api = re.compile(r"(location /api/ \{[^}]*?)\n\s*proxy_read_timeout [^;]*;", re.S)
    assert in_api.search(conf), "the control could not locate the /api/ directive to delete"
    without = in_api.sub(r"\1", conf)
    assert _effective_api_read_timeout_s(without) == 60.0
    assert not KILL_SWITCH_RESPONSE_DEADLINE_S < _effective_api_read_timeout_s(without)

    ws_only = without                        # /ws keeps its 3600s; /api/ has none
    assert "proxy_read_timeout 3600s" in ws_only and _effective_api_read_timeout_s(ws_only) == 60.0

    server_level = re.sub(r"server \{", "server {\n    proxy_read_timeout 150s;", without, count=1)
    assert _effective_api_read_timeout_s(server_level) == 150.0
    short_server = re.sub(r"server \{", "server {\n    proxy_read_timeout 90s;", without, count=1)
    assert _effective_api_read_timeout_s(short_server) == 90.0
    assert not KILL_SWITCH_RESPONSE_DEADLINE_S < _effective_api_read_timeout_s(short_server)


def _effective_api_read_timeout_s(conf: str) -> float:
    """nginx inheritance for one directive: `location /api/` -> its enclosing `server` -> 60s default."""
    tokens = re.findall(r"\{|\}|;|[^\s{};]+", re.sub(r"#[^\n]*", "", conf))
    stack: list[dict] = [{"name": ("root",), "directives": {}, "children": []}]
    words: list[str] = []
    for tok in tokens:
        if tok == "{":
            block = {"name": tuple(words), "directives": {}, "children": []}
            stack[-1]["children"].append(block)
            stack.append(block)
            words = []
        elif tok == "}":
            stack.pop()
            words = []
        elif tok == ";":
            if words:
                stack[-1]["directives"][words[0]] = words[1:]
            words = []
        else:
            words.append(tok)
    servers = [b for b in stack[0]["children"] if b["name"][:1] == ("server",)]
    assert len(servers) == 1, f"expected one server block, found {len(servers)}"
    apis = [b for b in servers[0]["children"] if b["name"] == ("location", "/api/")]
    assert len(apis) == 1, f"expected one `location /api/`, found {len(apis)}"
    for block in (apis[0], servers[0]):
        value = block["directives"].get("proxy_read_timeout")
        if value:
            m = re.fullmatch(r"(\d+)(ms|s|m|h)?", value[0])
            assert m, f"unreadable proxy_read_timeout {value!r}"
            return float(m.group(1)) * {"ms": 0.001, "s": 1, None: 1, "m": 60, "h": 3600}[m.group(2)]
    return 60.0


# ---------------------------------------------------------------------------------------------------
# K2-6, K2-10, K2-11, K2-12 — THE TRIGGER
# ---------------------------------------------------------------------------------------------------

def _book_with_two_positions():
    from tests.unit.test_t0136_alpaca_adapter import _Position

    book = _Book()
    book.positions = [_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")]
    return book


@pytest.mark.asyncio
async def test_K2_6_a_SECOND_trigger_while_one_runs_CLOSES_NOTHING(monkeypatch, quiet_trigger):
    from app.services.broker.manager import broker_manager
    from app.services.compliance.kill_switch import KillSwitch

    book = _book_with_two_positions()
    adapter, _clock = _alpaca(book)
    monkeypatch.setattr(broker_manager, "_adapters", {"alpaca": adapter})
    async with asyncio.timeout(10):
        first_task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="first"))
        await _until(lambda: book.called("close_position"), "the first trigger sent its first close")
        second = await KillSwitch().trigger(_Db(), "user-2", reason="second")
        first = await first_task

    assert sorted(c[1] for c in book.called("close_position")) == ["BTC/USD", "ETH/USD"], (
        f"a position was closed TWICE: {book.called('close_position')}")
    assert second["already_in_progress"] is True and "ALREADY IN PROGRESS" in second["message"], second
    # Manager's ruling on (e), landed with `B446`: the in-progress answer carries NO counters — a `positions_closed: 0`
    # became the route's "0 closed" at the moment an operator is most likely to misread it.
    assert second["details"] and not {"positions_closed", "positions_failed_to_close",
                                      "positions_not_attempted"} & set(second), second
    assert second["in_progress_for_s"] >= 0
    assert first["positions_closed"] == 2 and not first.get("already_in_progress"), first


@pytest.mark.asyncio
async def test_K2_6b_the_in_progress_answer_carries_FINISHED_adapters_rows_AND_the_one_in_flight(
        monkeypatch, quiet_trigger):
    """"The rows reported so far" has two sources: adapters `broker_manager` has finished, and the live report of
    the one it is awaiting. K2-6 has one adapter, so it sees only the second."""
    from app.services.broker.manager import broker_manager
    from app.services.broker.paper import PaperBroker
    from app.services.compliance.kill_switch import KillSwitch

    paper = PaperBroker(starting_balance=10_000, price_fn=lambda p: MARK)
    opened = await paper.place_order(_entry_req(client_order_id="sig-k26b"))
    book = _book_with_two_positions()
    adapter, _clock = _alpaca(book)
    monkeypatch.setattr(broker_manager, "_adapters", {"paper": paper, "alpaca": adapter})
    async with asyncio.timeout(10):
        first_task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="first"))
        await _until(lambda: book.called("close_position"), "the Alpaca sweep started, after paper finished")
        second = await KillSwitch().trigger(_Db(), "user-2", reason="second")
        await first_task

    ids = [r.get("position_id") for r in second["details"]]
    assert opened["position_id"] in ids, f"the FINISHED adapter's rows are missing from the answer: {second['details']}"
    assert any(r.get("sweep") == "a" for r in second["details"]), (
        f"the IN-FLIGHT adapter's live rows are missing from the answer: {second['details']}")
    assert not any(str(k).startswith("_") for r in second["details"] for k in r), "private row keys leaked"


@pytest.mark.asyncio
@pytest.mark.parametrize("how", ["raises", "cancelled"])
async def test_K2_10_a_trigger_that_RAISES_or_is_CANCELLED_never_leaves_the_switch_in_progress(
        monkeypatch, quiet_trigger, how):
    from app.core.kill_switch_state import KILL_SWITCH_STATE
    from app.services.broker.manager import broker_manager
    from app.services.compliance.kill_switch import KillSwitch

    book = _book_with_two_positions()
    adapter, _clock = _alpaca(book)
    monkeypatch.setattr(broker_manager, "_adapters", {"alpaca": adapter})
    real_run = KillSwitch._run_trigger
    stuck = asyncio.Event()
    release = asyncio.Event()

    async def _broken(self, db, user_id, reason=None):
        if how == "raises":
            raise RuntimeError("audit store down")
        stuck.set()
        await release.wait()
        return {"positions_closed": 0, "positions_failed_to_close": 0, "positions_not_attempted": 0,
                "reason": reason, "details": [], "message": "stub sweep"}

    monkeypatch.setattr(KillSwitch, "_run_trigger", _broken)
    async with asyncio.timeout(10):
        if how == "raises":
            with pytest.raises(RuntimeError):
                await KillSwitch().trigger(_Db(), "user-1", reason="breaks")
        else:
            # `B446` (manager's ruling): a cancelled trigger FINISHES its sweep, and the mark lives as long as the
            # sweep — then the cancellation is re-raised and the mark is gone.
            task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="cancelled"))
            await stuck.wait()
            task.cancel()
            for _ in range(20):
                await asyncio.sleep(0)
            assert not task.done(), "the cancelled trigger stopped waiting for its sweep"
            assert KILL_SWITCH_STATE.trigger_started is not None, "the mark was cleared while the sweep still ran"
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert KILL_SWITCH_STATE.trigger_started is None, "the in-progress mark survived the failed trigger"

        KillSwitch().disarm()                         # K2-12's refusal LIFTS after a failed trigger
        monkeypatch.setattr(KillSwitch, "_run_trigger", real_run)
        again = await KillSwitch().trigger(_Db(), "user-1", reason="again")
    assert not again.get("already_in_progress") and again["positions_closed"] == 2, again


@pytest.mark.asyncio
async def test_K2_11_trigger_ARMS_itself_so_sends_are_refused_DURING_the_sweep(monkeypatch, quiet_trigger, switch):
    from app.core.exceptions import KillSwitchArmed
    from app.services.broker.manager import broker_manager
    from app.services.broker.paper import PaperBroker
    from app.services.compliance.kill_switch import KillSwitch

    book = _book_with_two_positions()
    adapter, _clock = _alpaca(book)
    monkeypatch.setattr(broker_manager, "_adapters", {"alpaca": adapter})
    paper = PaperBroker(starting_balance=10_000, price_fn=lambda p: MARK)
    assert not switch.is_armed
    async with asyncio.timeout(10):
        task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="trigger only"))
        await _until(lambda: book.called("close_position"), "the sweep started")
        with pytest.raises(KillSwitchArmed):
            await paper.place_order(_entry_req())
        await task
    assert switch.is_armed and switch.reason == "trigger only" and not paper._positions


@pytest.mark.asyncio
async def test_K2_11b_trigger_KEEPS_the_reason_an_armed_switch_already_has(monkeypatch, quiet_trigger, switch):
    from app.services.broker.manager import broker_manager
    from app.services.compliance.kill_switch import KillSwitch

    monkeypatch.setattr(broker_manager, "_adapters", {})
    switch.arm(reason="compliance breach: daily loss")
    await KillSwitch().trigger(_Db(), "user-1", reason="operator")
    assert switch.reason == "compliance breach: daily loss"


@pytest.mark.asyncio
async def test_K2_12_disarm_DURING_a_sweep_is_REFUSED_and_the_switch_stays_armed(monkeypatch, quiet_trigger, switch):
    from app.core.exceptions import ComplianceError
    from app.services.broker.manager import broker_manager
    from app.services.compliance.kill_switch import KillSwitch

    book = _book_with_two_positions()
    adapter, _clock = _alpaca(book)
    monkeypatch.setattr(broker_manager, "_adapters", {"alpaca": adapter})
    async with asyncio.timeout(10):
        task = asyncio.create_task(KillSwitch().trigger(_Db(), "user-1", reason="K2-12"))
        await _until(lambda: book.called("close_position"), "the sweep started")
        with pytest.raises(ComplianceError, match="still closing positions"):
            switch.disarm()
        assert switch.is_armed
        await task
    switch.disarm()
    assert not switch.is_armed


# ---------------------------------------------------------------------------------------------------
# R1 — carried from fb3dab6's review: a refused connection AT submit_order, through place_order
# ---------------------------------------------------------------------------------------------------

def test_R1_a_connection_REFUSED_at_submit_order_raises_and_looks_nothing_up(monkeypatch):
    """P6 drove the NOT_CREATED branch with an HTTP 403; D1 classified a refused connection only at `_call`. This
    composes them: a closed local port, reached by `submit_order` itself, through `place_order`. The asset read is
    stubbed by `_built_adapter`, so the refusal lands on the POST and not on `get_asset` (the manager's run died there)."""
    from app.core.exceptions import BrokerError
    from tests.unit.test_b440_b441_submission_safety import _built_adapter, _req

    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    adapter, _client = _built_adapter(f"http://127.0.0.1:{port}")

    calls: list[str] = []
    real_call = adapter._call

    async def _recording(name, *args, **kwargs):
        calls.append(name)
        return await real_call(name, *args, **kwargs)

    adapter._call = _recording
    raised, result = None, None
    try:
        result = asyncio.run(adapter.place_order(_req()))
    except BrokerError as exc:
        raised = exc

    assert calls[:1] == ["submit_order"], f"the order was never submitted: {calls}"
    assert calls == ["submit_order"], f"a refused submission was followed by {calls[1:]}; result {result}"
    assert raised is not None and "ConnectionError" in str(raised), (raised, result)
