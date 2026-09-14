"""B427 — an acknowledgement is not an outcome: orders and closes are RESOLVED, bounded, then reported.

`AlpacaAdapter.place_order` returned the SUBMISSION RESPONSE's status. An order the venue accepted and
filled a moment later was classified at the moment of acceptance — a false refusal before `T-0130`, a
halt since. And `close_position` returned `str(Order)`, so an accepted close read as closed (`B438`),
while `close_all_positions` parsed the close Order as another method's type and ended after its first
position (`B439`).

The rulings (manager): resolution inside `place_order` (A); `ORDER_RESOLUTION_BUDGET_S` = 5.0 by default,
Malek's to set, fail-safe on expiry into the UNRESOLVED seam (B); a terminal order ended with a READABLE
ZERO fill is REJECTED with `VENUE_ENDED_UNFILLED` and migration 0015 (C); a partial still working at expiry
stays PARTIALLY_FILLED at its filled size (D); closes are resolved on both routes, and an unconfirmed close
is never CLOSED. The arms follow review's pre-registered kill set (`_runs/b427/KILL_SET.md`, B-1..B-12).

#### WHAT IS NOT CLAIMED

No venue was consulted. Every order here is a real `alpaca.trading.models.Order` built from the SDK's own
return annotations, served by a double; how fast Alpaca actually fills crypto is what probe 3 will measure.
"""
from __future__ import annotations

import asyncio
import socket
import typing
import uuid
from datetime import datetime, timezone

import pytest

from tests.unit.test_t0140_order_body import Client, _asset, _req, BTC_MIN


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """`B432`: offline, enforced."""
    def _refuse(*a, **k):
        raise AssertionError(f"B427 arm attempted a network connection: {a[1:]!r}")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)


def _sdk_model(method: str):
    """The alpaca MODEL class `TradingClient.<method>` is annotated to return — read at test time, so a
    double cannot drift to another method's type (`B439`; review's B-11)."""
    from alpaca.trading.client import TradingClient

    annotated = typing.get_type_hints(getattr(TradingClient, method))["return"]

    def _leaves(t):
        args = typing.get_args(t)
        return [leaf for a in args for leaf in _leaves(a)] if args else [t]

    models = [t for t in _leaves(annotated) if isinstance(t, type) and t.__module__.startswith("alpaca.")]
    assert len(models) == 1, f"TradingClient.{method} is annotated {annotated!r}; re-derive the double"
    return models[0]


def _order(method: str, status: str | None, filled_qty="0.01", avg="70000", symbol="BTC/USD", order_id=None):
    """A real SDK Order of the class `method` returns. `status`/`filled_qty` accept raw values the model
    would refuse (None, "", a bool, a huge int) — set after construction, as a venue reply could carry."""
    from alpaca.trading.enums import OrderClass, OrderStatus, TimeInForce

    now = datetime.now(timezone.utc)
    order = _sdk_model(method)(
        id=order_id or uuid.uuid4(), client_order_id="sig-test", created_at=now, updated_at=now,
        submitted_at=now, status=OrderStatus.NEW, time_in_force=TimeInForce.GTC,
        order_class=OrderClass.SIMPLE, extended_hours=False, symbol=symbol, qty="0.01",
    )
    object.__setattr__(order, "status", OrderStatus(status) if isinstance(status, str) else status)
    object.__setattr__(order, "filled_qty", filled_qty)
    object.__setattr__(order, "filled_avg_price", avg)
    return order


class _Venue(Client):
    """A venue with STATE: the acknowledgement, then a scripted sequence of re-reads (the last repeats)."""

    def __init__(self, ack="accepted", rereads=("filled",), close_ack="accepted", close_rereads=("filled",)):
        super().__init__({"BTC/USD": _asset("BTC/USD", min_order_size=BTC_MIN)})
        self.ack, self.rereads, self.close_ack, self.close_rereads = ack, list(rereads), close_ack, list(close_rereads)
        self.scripts: dict[str, list] = {}
        self.reread_count = 0
        self.orders_filter = "UNSET"

    def _script(self, order, statuses):
        self.scripts[str(order.id)] = [s for s in statuses]
        return order

    def submit_order(self, order_data):
        self.calls.append(("submit_order", order_data.symbol, order_data.qty))
        order = _order("submit_order", self.ack, filled_qty="0", avg=None)
        return self._script(order, self.rereads)

    def close_position(self, symbol_or_asset_id, close_options=None):
        self.calls.append(("close_position", symbol_or_asset_id, close_options))
        order = _order("close_position", self.close_ack, filled_qty="0", avg=None, symbol=symbol_or_asset_id)
        return self._script(order, self.close_rereads)

    def get_order_by_id(self, order_id, filter=None):
        self.reread_count += 1
        self.calls.append(("get_order_by_id", str(order_id), getattr(filter, "nested", None)))
        script = self.scripts[str(order_id)]
        step = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(step, BaseException):
            raise step
        status, qty = step if isinstance(step, tuple) else (step, "0.01" if step == "filled" else "0")
        return _order("get_order_by_id", status, filled_qty=qty,
                      avg="70000" if status == "filled" else None, order_id=order_id)

    def get_orders(self, filter=None):
        self.orders_filter = filter
        return [_order("get_orders", "filled"), _order("get_orders", "canceled", filled_qty="0", avg=None)]


class _Clock:
    """A fake clock the fake sleep advances — no arm waits for real time."""

    def __init__(self):
        self.now = 1000.0
        self.waits: list[float] = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.waits.append(round(seconds, 6))
        self.now += seconds


def _adapter(venue: _Venue):
    from app.services.broker.alpaca import AlpacaAdapter

    adapter = AlpacaAdapter(venue, paper=True)
    clock = _Clock()
    adapter._clock = clock
    adapter._sleep = clock.sleep
    return adapter, clock


# ---------------------------------------------------------------------------------------------------
# RESOLUTION (B-1, B-2, B-5, B-6, B-7, B-8)
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_R1_an_ACCEPTED_order_that_FILLS_moments_later_is_reported_as_the_FILL_it_became():
    """**The case B427 exists for.** Before, this returned `ACCEPTED` and the loop halted."""
    venue = _Venue(ack="accepted", rereads=("new", "filled"))
    adapter, clock = _adapter(venue)
    res = await adapter.place_order(_req())

    assert (res["status"], res["filled_units"], res["fill"], res["terminal"]) == ("FILLED", 0.01, 70000.0, True), res
    r = res["resolution"]
    assert (r["resolved"], r["reads"], r["ack_status"], r["ack_filled_units"]) == (True, 2, "accepted", 0.0), r
    assert clock.waits == [0.25], f"the reads did not follow the schedule: {clock.waits}"
    rereads = [c for c in venue.calls if c[0] == "get_order_by_id"]
    assert rereads and all(c[2] is True for c in rereads), f"the re-read is not nested (B-5): {rereads}"


@pytest.mark.asyncio
async def test_R2_on_EXPIRY_the_last_status_is_reported_and_the_loop_classifies_it_UNRESOLVED():
    """**B-1. A timeout is a result, not a refusal and not a fill.**"""
    from app.services.live.crypto_loop import ORDER_UNRESOLVED, classify_order_status

    venue = _Venue(ack="accepted", rereads=("accepted",))
    adapter, clock = _adapter(venue)
    res = await adapter.place_order(_req())

    assert res["status"] == "ACCEPTED" and classify_order_status(res["status"]) == ORDER_UNRESOLVED, res
    assert "rejection_code" not in res, "an expiry was filed as a refusal"
    r = res["resolution"]
    assert (r["resolved"], r["reads"], r["budget_s"]) == (False, 6, 5.0), r
    assert clock.now - 1000.0 == pytest.approx(4.5) and sum(clock.waits) <= 5.0, (
        f"a wait ran past the deadline: {clock.waits}")


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,reads", [(2.0, 4), (5.0, 6), (10.0, 9), (0.1, 1)])
async def test_R3_the_BUDGET_changes_HOW_MANY_reads_never_WHAT_an_unresolved_order_does(monkeypatch, budget, reads):
    """**B-2 / ruling B: the design does not depend on the value.** Read at call time, where Malek sets it."""
    import app.services.broker.alpaca as alpaca

    monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_BUDGET_S", budget)
    venue = _Venue(ack="accepted", rereads=("accepted",))
    adapter, clock = _adapter(venue)
    res = await adapter.place_order(_req())
    assert (res["status"], res["resolution"]["reads"]) == ("ACCEPTED", reads), res["resolution"]
    assert clock.now - 1000.0 <= budget, f"resolution ran past a {budget}s budget"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, -1.0, float("nan"), float("inf"), True, __import__("json").loads("1" + "0" * 400), 61.0, "5"],
                         ids=["zero", "negative", "nan", "inf", "bool", "huge_int", "over_ceiling", "string"])
async def test_R3b_an_UNUSABLE_budget_is_REFUSED_before_an_order_is_sent_and_CLAMPED_on_a_close(monkeypatch, bad):
    """**B-2.** Never a hang (inf, a huge int) and never an instant give-up that passes for a timeout (NaN,
    zero). Before submission a refusal sends nothing; after it — a close — refusing is a kill switch that does
    not act, so the budget is clamped to one read and the problem recorded."""
    import app.services.broker.alpaca as alpaca
    from app.core.exceptions import BrokerError

    monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_BUDGET_S", bad)
    venue = _Venue(close_ack="accepted", close_rereads=("accepted",))
    adapter, _clock = _adapter(venue)

    with pytest.raises(BrokerError, match="ORDER_RESOLUTION_BUDGET_S is"):
        await adapter.place_order(_req())
    assert not [c for c in venue.calls if c[0] == "submit_order"], "an order was sent under an unusable budget"

    closed = await adapter.close_position("BTC/USD")
    assert closed["resolution"]["budget_problem"] and closed["resolution"]["reads"] == 1, closed["resolution"]
    assert closed["close_confirmed"] is False


def test_R3c_the_module_REFUSES_an_unusable_budget_at_IMPORT():
    """The guard that stops a bad value set in the file reaching a running engine at all."""
    import ast
    import inspect

    import app.services.broker.alpaca as alpaca

    guards = [n for n in ast.parse(inspect.getsource(alpaca)).body
              if isinstance(n, ast.If) and "resolution_budget_problem(ORDER_RESOLUTION_BUDGET_S)" in ast.unparse(n.test)
              and any(isinstance(s, ast.Raise) for s in n.body)]
    assert len(guards) == 1, "no module-level refusal of an unusable ORDER_RESOLUTION_BUDGET_S"
    assert alpaca.resolution_budget_problem(alpaca.ORDER_RESOLUTION_BUDGET_S) is None


@pytest.mark.asyncio
async def test_R4_a_re_read_that_RAISES_is_NOT_terminal_and_nothing_raises_out_of_place_order():
    """**B-7.** A failed read is "not yet": polling continues, and if every read fails the verdict is the
    acknowledgement — never a refusal, never an exception after submission (K-4b's class)."""
    venue = _Venue(ack="accepted", rereads=(RuntimeError("timeout"), RuntimeError("timeout"), "filled"))
    adapter, _clock = _adapter(venue)
    res = await adapter.place_order(_req())
    assert res["status"] == "FILLED" and res["resolution"]["reads"] == 3, res["resolution"]
    assert len(res["resolution"]["read_errors"]) == 2

    venue = _Venue(ack="accepted", rereads=(RuntimeError("down"),))
    adapter, _clock = _adapter(venue)
    res = await adapter.place_order(_req())
    assert (res["status"], res["resolution"]["resolved"]) == ("ACCEPTED", False), res
    assert "rejection_code" not in res


@pytest.mark.asyncio
async def test_R5b_the_resolver_stops_ONLY_on_TERMINAL_ORDER_STATUSES(monkeypatch):
    """**B-6. One terminal set, B429's.** `pending_cancel` and `done_for_day` can still fill, so reading goes on
    through them; stopping there would report a still-live order as its last word."""
    venue = _Venue(ack="accepted", rereads=("pending_cancel", "done_for_day", ("canceled", "0")))
    adapter, _clock = _adapter(venue)
    res = await adapter.place_order(_req())
    assert (res["status"], res["venue_status"], res["resolution"]["reads"]) == ("REJECTED", "canceled", 3), res


@pytest.mark.asyncio
async def test_R6_waiting_between_reads_does_NOT_block_the_event_loop(monkeypatch):
    """**B-8.** The default sleep is `asyncio.sleep`: another task runs DURING resolution. Real time, kept to
    a tenth of a second."""
    import app.services.broker.alpaca as alpaca
    from app.services.broker.alpaca import AlpacaAdapter

    assert AlpacaAdapter.__dict__["_sleep"].__func__ is asyncio.sleep
    monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_BUDGET_S", 0.1)
    monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_READ_OFFSETS_S", (0.0, 0.05, 0.1))
    adapter = AlpacaAdapter(_Venue(ack="accepted", rereads=("accepted",)), paper=True)

    ticks: list[int] = []
    finished = asyncio.Event()

    async def _other_task():
        while not finished.is_set():
            ticks.append(1)
            await asyncio.sleep(0.005)

    other = asyncio.create_task(_other_task())
    await adapter.place_order(_req())
    during = len(ticks)
    finished.set()
    await other
    assert during >= 3, f"another task ran only {during} time(s) while the resolver waited — the wait blocked"


# ---------------------------------------------------------------------------------------------------
# THE MAPPING (B-3, B-4, B-6; rulings C and D)
# ---------------------------------------------------------------------------------------------------

MAPPING = [
    ("filled", "0.01", "FILLED", True, None, "fill"),
    ("filled", None, "FILLED", True, None, "fill"),
    ("partially_filled", "0.004", "PARTIALLY_FILLED", False, None, "partial_still_working_D"),
    ("canceled", "0.004", "PARTIALLY_FILLED", True, None, "canceled_partial_B4"),
    ("expired", "0.004", "PARTIALLY_FILLED", True, None, "expired_partial_B4"),
    ("canceled", "0", "REJECTED", True, "VENUE_ENDED_UNFILLED", "canceled_zero_C"),
    ("expired", "0.000", "REJECTED", True, "VENUE_ENDED_UNFILLED", "expired_zero_C"),
    ("rejected", "0", "REJECTED", True, "VENUE_ENDED_UNFILLED", "rejected_zero_C"),
    ("canceled", None, "CANCELED", True, None, "unreadable_None_B3"),
    ("canceled", "", "CANCELED", True, None, "unreadable_blank_B3"),
    ("canceled", "nan", "CANCELED", True, None, "unreadable_nan_B3"),
    ("canceled", True, "CANCELED", True, None, "unreadable_bool_B3"),
    ("canceled", __import__("json").loads("1" + "0" * 400), "CANCELED", True, None, "unreadable_huge_int_B3"),
    ("canceled", "-0.001", "CANCELED", True, None, "negative"),
    ("replaced", "0", "REPLACED", True, None, "replaced"),
    ("accepted", "0", "ACCEPTED", False, None, "acknowledged"),
    ("pending_cancel", "0", "PENDING_CANCEL", False, None, "pending_cancel_not_terminal_B6"),
    ("done_for_day", "0", "DONE_FOR_DAY", False, None, "done_for_day_not_terminal_B6"),
    (None, "0", "SUBMITTED", False, None, "no_status"),
]


@pytest.mark.parametrize("venue_status,qty,status,terminal,code,_id", MAPPING, ids=[m[5] for m in MAPPING])
def test_M1_ONE_mapping_from_a_venue_order_to_the_engines_result(venue_status, qty, status, terminal, code, _id):
    from app.services.broker.alpaca import AlpacaAdapter

    got = AlpacaAdapter(_Venue(), paper=True)._order_result(_order("get_order_by_id", venue_status, filled_qty=qty))
    assert (got["status"], got["terminal"], got.get("rejection_code")) == (status, terminal, code), got


@pytest.mark.parametrize("venue_status,qty,status,terminal,code,_id", MAPPING, ids=[m[5] for m in MAPPING])
def test_M1b_what_the_LOOP_does_with_each_mapped_result(venue_status, qty, status, terminal, code, _id):
    """The classifier decides, unchanged: a readable-zero ending is a REFUSAL, an unreadable one UNRESOLVED."""
    from app.services.live import crypto_loop as mod

    expected = (mod.ORDER_FILLED if status == "FILLED" else mod.ORDER_PARTIALLY_FILLED if status == "PARTIALLY_FILLED"
                else mod.ORDER_REFUSED if status == "REJECTED" else mod.ORDER_UNRESOLVED)
    assert mod.classify_order_status(status) == expected


@pytest.mark.asyncio
async def test_M2_a_CANCELED_partial_is_sized_by_its_TERMINAL_filled_quantity_NEVER_by_units():
    """**B-4.** The loop reads a PARTIALLY_FILLED size from `filled_units` only; `units` is what we SENT."""
    from app.services.live.crypto_loop import LiveCryptoLoop

    from decimal import Decimal

    from app.services.broker.alpaca import ALPACA_CRYPTO_FEE_RATE
    from tests.unit.test_t0136_alpaca_adapter import _Position

    venue = _Venue(ack="accepted", rereads=(("canceled", "0.004"),))
    held_after = Decimal("0.004") * (Decimal(1) - ALPACA_CRYPTO_FEE_RATE)   # `T-0144` R5': the fee is taken in kind
    listings = iter([[], [_Position(symbol="BTCUSD", qty=str(held_after))]])   # before the send, then after the fill
    venue.positions_read = lambda: next(listings)
    venue.get_all_positions = venue.positions_read
    adapter, _clock = _adapter(venue)
    res = await adapter.place_order(_req(lot=0.01))
    assert (res["status"], res["venue_status"], res["terminal"]) == ("PARTIALLY_FILLED", "canceled", True), res
    # sized by what the TERMINAL fill left in the position — never by `units`, what we sent
    assert res["units_check"]["filled"] == "0.004" and res["units_check"]["within"] is True, res["units_check"]
    assert LiveCryptoLoop._position_units(res) == float(held_after) and res["units"] != float(held_after)


@pytest.mark.asyncio
async def test_M3_an_order_ENDED_UNFILLED_is_recorded_as_a_REFUSAL_with_its_OWN_CODE(monkeypatch):
    """**Ruling C, through the loop.** A true row, not a halt: no position exists."""
    from tests.unit.test_t0130_order_result_three_states import _drive_tick

    venue = _Venue(ack="accepted", rereads=(("canceled", "0"),))
    adapter, _clock = _adapter(venue)
    result = await adapter.place_order(_req())
    assert result["rejection_code"] == "VENUE_ENDED_UNFILLED" and "ended it (canceled)" in result["reason"]

    async def _execute(_sig):
        return dict(result)

    loop, _acts = _drive_tick(monkeypatch, _execute)
    codes: list = []

    async def _rejected(pair, entry, sig, reason, trace, code=None):
        codes.append((reason, code))

    monkeypatch.setattr(loop, "_record_rejected_signal", _rejected)
    await loop._tick_symbol("BTC/USD", "BTCUSDT")
    assert codes == [(result["reason"], "VENUE_ENDED_UNFILLED")] and loop.halt_reason is None, (codes, loop.halt_reason)


# ---------------------------------------------------------------------------------------------------
# CLOSES (B-10, B-11, B-12; B438, B439)
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("rereads,confirmed,status", [
    (("filled",), True, "FILLED"),
    (("new", "filled"), True, "FILLED"),
    (("accepted",), False, "ACCEPTED"),
    ((("canceled", "0"),), False, "REJECTED"),
    ((("canceled", "0.004"),), False, "PARTIALLY_FILLED"),
], ids=["filled", "fills_later", "never_fills", "ended_unfilled", "partially_closed"])
async def test_C1_close_position_is_CONFIRMED_only_by_a_terminal_FILL(rereads, confirmed, status):
    # `T-0144` R2-4: the `lot_size` "partial" parametrisation is gone — the adapter REFUSES a partial close by position
    # (engine partials are sell orders), pinned in `test_b428b_ii_r2_deletion.py`. The whole close is unchanged.
    venue = _Venue(close_ack="accepted", close_rereads=rereads)
    adapter, _clock = _adapter(venue)
    out = await adapter.close_position("BTC/USD")
    assert (out["close_confirmed"], out["status"]) == (confirmed, status), out
    assert "result" not in out, "the close order is still being stringified"
    assert out["resolution"]["ack_status"] == "accepted"


@pytest.mark.asyncio
async def test_C2_the_KILL_SWITCH_counts_an_accepted_but_unfilled_close_as_FAILED_never_CLOSED(monkeypatch):
    """**B-10 on the most safety-critical surface.** Driven through `KillSwitch.trigger` and the real
    `broker_manager`, with real SDK Orders."""
    from app.services.broker.manager import broker_manager
    from app.services.compliance.kill_switch import KillSwitch
    from tests.unit.test_t0136_alpaca_adapter import _Position, _adapter as t0136_adapter

    adapter, _mock = t0136_adapter(positions=[_Position(symbol="BTC/USD"), _Position(symbol="ETH/USD")],
                                   close_status={"BTC/USD": "filled", "ETH/USD": "accepted"})
    monkeypatch.setattr(broker_manager, "_adapters", {"alpaca": adapter})

    async def _no_push(**kw):
        return None

    import app.services.ws.manager as ws

    monkeypatch.setattr(ws.ws_manager, "push_kill_switch", _no_push)

    class _Db:
        def add(self, row):
            pass

        async def flush(self):
            pass

    result = await KillSwitch().trigger(_Db(), "user-1", reason="b427 arm")
    assert (result["positions_closed"], result["positions_failed_to_close"]) == (1, 1), result["message"]
    assert "1 position(s) closed, 1 failed" in result["message"]


# ---------------------------------------------------------------------------------------------------
# get_orders, and where the budget is set
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_O1_get_orders_HONOURS_its_filter_and_speaks_the_ENGINES_spelling():
    from alpaca.trading.enums import QueryOrderStatus

    from app.core.exceptions import BrokerError

    venue = _Venue()
    adapter, _clock = _adapter(venue)
    rows = await adapter.get_orders("open")
    assert venue.orders_filter.status == QueryOrderStatus.OPEN, "the status filter is still dead"
    assert [(r["status"], r["venue_status"]) for r in rows] == [("FILLED", "filled"), ("REJECTED", "canceled")]

    await adapter.get_orders()
    assert venue.orders_filter is None
    with pytest.raises(BrokerError, match="cannot filter by 'filled'"):
        await adapter.get_orders("filled")


def test_F1_the_budget_Malek_sets_in_fixed_config_IS_the_adapters():
    import app.services.broker.alpaca as alpaca
    import app.services.live.fixed_config as fixed

    assert fixed.ORDER_RESOLUTION_BUDGET_S is alpaca.ORDER_RESOLUTION_BUDGET_S
    assert alpaca.ENDED_ORDER_STATUSES == alpaca.TERMINAL_ORDER_STATUSES - {"filled", "replaced"}
