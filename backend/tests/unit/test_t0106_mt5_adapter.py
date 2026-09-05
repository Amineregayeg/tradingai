"""T-0106 — the MT5 adapter skeleton, against a mock, with every assumption NAMED.

**A mock encodes OUR READING of the documentation.** Every arm written against one passes if that
reading is wrong, so the adapter ships confidently incorrect and the suite agrees — `B256`: a
differential over synthetic inputs tests the predicate and cannot test the producer, and **a mock
is a hand-built corpus for an adapter.**

So every test docstring carries a literal `ASSUMES:` marker naming the item in
`MT5_FIRST_CONNECTION.md` that would falsify it, and
`test_every_arm_in_this_file_NAMES_the_assumption_it_rests_on` parses this module and asserts it.
**As prose that rule has no way to fail** — an arm naming no assumption looks identical to one
that needs none.

**What the markers buy:** when Malek runs the checklist and an item comes back other than
predicted, the arms resting on it are findable **by grep instead of by memory**. Without the link,
a falsified assumption leaves a green suite agreeing with a world that no longer exists.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.exceptions import BrokerError, BrokerRateLimitError
from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest
from app.services.broker.mt5 import (
    ACCOUNT_TRADE_MODES,
    MetaTrader5Adapter,
    MT5AccountTypeUnreadable,
    MT5AccountTypeUnrecognised,
    MT5AuthFailed,
    MT5BrokerUnreachable,
    MT5ServerNotFound,
)


# ======================================================================================
# THE MOCK — and the five states `B291` says a friendly mock will never produce
# ======================================================================================


class TooManyRequestsException(Exception):
    """**NAMED EXACTLY AS THE SDK NAMES IT, and the exact name is load-bearing.**

    The adapter cannot `isinstance`-check a class it does not import — the SDK is not installed,
    and importing it at module scope would make the adapter module unimportable, which `B328`
    measured is SILENTLY skipped by the contract arm. So it matches on
    `type(exc).__name__ == SDK_RATE_LIMIT_EXCEPTION`.

    **This mock was first written as `_TooManyRequestsException`, following this file's private-
    class convention, and the rate-limit arms failed** — the adapter treated a 429 as a generic
    error. That is the mechanism working: a mock whose class name does not match the venue's does
    not get the venue's handling. The convention was wrong here, not the adapter — **a mock
    imitates the venue, and the venue's class is called this.**
    """

    def __init__(self, metadata: dict | None = None) -> None:
        super().__init__("too many requests")
        self.metadata = metadata or {}


class _CodedError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _TerminalState:
    def __init__(self, connected: bool = True, connected_to_broker: bool = True) -> None:
        self.connected = connected
        self.connected_to_broker = connected_to_broker


class MetaApiMock:
    """The venue's shape as our documentation describes it — no more friendly than that."""

    def __init__(
        self,
        *,
        account: dict | None = None,
        positions: list[dict] | None = None,
        deals: list[dict] | None = None,
        terminal_state: _TerminalState | None = None,
        connect_error: Exception | None = None,
        close_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.account = account if account is not None else {
            "login": "1234567", "balance": 10_000.0, "equity": 10_050.0,
            "currency": "USD", "margin": 100.0, "freeMargin": 9_900.0,
            "type": "ACCOUNT_TRADE_MODE_DEMO",
        }
        self._positions = positions if positions is not None else []
        self._deals = deals if deals is not None else []
        self.terminal_state = terminal_state or _TerminalState()
        self._connect_error = connect_error
        self._close_errors = close_errors or {}
        self.closed: list[str] = []
        self.synchronized = False

    async def connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error

    async def wait_synchronized(self) -> None:
        self.synchronized = True

    async def get_account_information(self) -> dict:
        return dict(self.account)

    async def get_positions(self) -> list[dict]:
        return [dict(p) for p in self._positions]

    async def get_orders(self) -> list[dict]:
        return []

    async def get_deals_by_time_range(self, start_time, end_time) -> list[dict]:
        return [dict(d) for d in self._deals]

    async def get_symbol_price(self, symbol: str) -> dict:
        return {"bid": 100.0, "ask": 102.0}

    async def get_symbol_specification(self, symbol: str) -> dict:
        return {"volume_min": 0.01, "volume_step": 0.01, "volume_max": 100.0,
                "contract_size": 1.0}

    async def close_position(self, position_id: str) -> dict:
        error = self._close_errors.get(position_id)
        if error is not None:
            raise error
        self.closed.append(position_id)
        return {"positionId": position_id, "status": "closed"}


def _position(pid: str, **overrides) -> dict:
    """A `MetatraderPosition` carrying only what the model marks REQUIRED, plus overrides."""
    base = {
        "id": pid, "symbol": "BTCUSD", "type": "POSITION_TYPE_BUY",
        "volume": 0.5, "openPrice": 100.0, "currentPrice": 110.0, "profit": 5.0,
        "time": "2026-08-31T10:00:00.000Z",
    }
    base.update(overrides)
    return base


def _adapter(**mock_kwargs) -> tuple[MetaTrader5Adapter, MetaApiMock]:
    mock = MetaApiMock(**mock_kwargs)
    return MetaTrader5Adapter(client=mock), mock


# ======================================================================================
# THE MARKER ARM — the rule made mechanical, because as prose it cannot fail
# ======================================================================================


def test_every_arm_in_this_file_NAMES_the_assumption_it_rests_on():
    """ASSUMES: nothing about the venue. This arm is about this file.

    Third use of the instrument (`T-0068`, `T-0098`). An arm with no marker is indistinguishable
    from one that needs none, so the marker is required of every test and the exemption has to be
    written down — as this one is.
    """
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    unmarked = [
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
        and "ASSUMES:" not in (ast.get_docstring(node) or "")
    ]
    assert not unmarked, (
        f"these arms rest on an unnamed assumption: {unmarked}. Every arm here is written "
        "against a mock that encodes our reading of the documentation; one that does not say "
        "what it assumes cannot be found when that reading turns out to be wrong."
    )


def test_every_ASSUMES_marker_names_a_checklist_item_or_says_none_does():
    """ASSUMES: nothing about the venue. It joins the markers to the document that settles them.

    A marker naming no checklist item is an assumption nobody will ever test. Where the checklist
    genuinely has no item, the marker must SAY SO — `T-0113` established the checklist is *not
    provably complete*, so finding a gap is expected rather than alarming, and an unnamed gap and
    an overlooked one look identical.
    """
    tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")):
            continue
        doc = ast.get_docstring(node) or ""
        marker = doc.split("ASSUMES:", 1)[1].split("\n\n")[0] if "ASSUMES:" in doc else ""
        if not marker:
            continue
        names_item = "checklist" in marker.lower() or "nothing about the venue" in marker.lower()
        if not names_item:
            bad.append(node.name)
    assert not bad, (
        f"these markers name no checklist item and do not say that none covers them: {bad}"
    )


# ======================================================================================
# STATE 1 — a deal with no volume / price / positionId is a BALANCE ENTRY
# ======================================================================================


def test_a_balance_entry_is_SKIPPED_and_the_skip_is_COUNTED():
    """ASSUMES: `MetatraderDeal` is 6-of-22 required, so `volume`, `price` and `positionId` can
    all be absent on a real deal (`B291`). Settled by checklist item 2.1 — which optional fields
    this broker actually omits.

    A balance entry is a credit, a correction or a commission posting. **It is not a fill.**
    Mapping it as a trade with zeroes puts a fabricated fill in the record; raising `KeyError`
    makes a normal venue event look like a bug.
    """
    adapter, _ = _adapter(deals=[
        {"id": "d1", "positionId": "p1", "symbol": "BTCUSD", "volume": 0.5, "price": 100.0,
         "profit": 5.0, "time": "2026-08-31T10:00:00.000Z"},
        {"id": "d2", "profit": -3.0, "time": "2026-08-31T11:00:00.000Z"},   # balance entry
        {"id": "d3", "symbol": "BTCUSD", "volume": 0.5, "profit": 1.0},      # no price
        {"id": "d4", "symbol": "BTCUSD", "volume": 0.5, "price": 90.0},      # no positionId
    ])
    trades = asyncio.run(adapter.get_recent_trades())

    assert [t["id"] for t in trades] == ["d1"], "only the real fill is a trade"
    assert adapter.last_trades_skipped == 3, (
        "the skip count is the difference between 'this venue sends no balance entries' and "
        f"'three were dropped and nobody said so'; got {adapter.last_trades_skipped}"
    )


def test_swap_and_commission_are_None_when_ABSENT_and_never_zero():
    """ASSUMES: `swap` and `commission` are OPTIONAL on a deal while `profit` is REQUIRED —
    MetaApi's model marks only `profit` with `Yes`. Settled by checklist item 2.2 (does this
    broker send them at all) and item 3.1 (whether `profit` already contains them).

    `None` means *the venue did not report it*; `0` means *it reported zero*. A default of `0`
    makes a venue that cannot say indistinguishable from one that charged nothing (`B215`).
    """
    adapter, _ = _adapter(deals=[
        {"id": "d1", "positionId": "p1", "symbol": "BTCUSD", "volume": 0.5, "price": 100.0,
         "profit": 5.0},
        {"id": "d2", "positionId": "p2", "symbol": "BTCUSD", "volume": 0.5, "price": 100.0,
         "profit": 5.0, "swap": 0.0, "commission": -1.5},
    ])
    absent, present = asyncio.run(adapter.get_recent_trades())

    assert absent["swap"] is None and absent["commission"] is None
    assert present["swap"] == 0.0, "a REPORTED zero must survive as a zero, not become None"
    assert present["commission"] == -1.5
    assert absent["profit"] == 5.0, "profit is REQUIRED on the venue's model and must be read"


# ======================================================================================
# STATE 2 — connected to MetaApi, NOT connected to the broker
# ======================================================================================


def test_an_unreachable_broker_makes_get_positions_RAISE_and_never_return_empty():
    """ASSUMES: MetaApi exposes TWO connection booleans and `connected_to_broker` can be False
    while `connected` is True (`B292`). Settled by checklist item 1.1 — **the item that gates
    every other reading**, and it is INFERRED from the documented flag rather than observed.

    The return type is a list and **no value in a list means "I could not ask."** An empty list
    from a broker we cannot see is indistinguishable from a flat book — which would silently
    defeat any kill-switch confirmation that re-reads positions to check the book is empty.
    """
    adapter, _ = _adapter(
        positions=[_position("p1")],
        terminal_state=_TerminalState(connected=True, connected_to_broker=False),
    )
    with pytest.raises(MT5BrokerUnreachable) as exc:
        asyncio.run(adapter.get_positions())
    assert "not to the broker" in str(exc.value).lower() or "not connected to the broker" in str(exc.value).lower()


def test_the_reachable_case_is_the_must_MISS_half_and_returns_positions():
    """ASSUMES: the same two booleans as the arm above (checklist item 1.1).

    CONTROL. An adapter that raised unconditionally would pass the arm above and be useless, so
    the same predicate must stay SILENT on a healthy connection.
    """
    adapter, _ = _adapter(positions=[_position("p1"), _position("p2")])
    positions = asyncio.run(adapter.get_positions())
    assert [p.id for p in positions] == ["p1", "p2"]


def test_a_position_carries_its_producer_and_its_pnl_key():
    """ASSUMES: MetaApi calls the open-position P&L field `profit`, and does not document whether
    it is gross or net of swap and commission. Settled by checklist item 3.1 — the one the
    checklist itself calls the most consequential unknown.

    `produced_by` says whose conventions the row follows; `pnl_source` says which key the number
    came from. Neither replaces the other (`T-0105`, `T-0102`).
    """
    adapter, _ = _adapter(positions=[_position("p1", swap=-0.25, commission=None)])
    position = asyncio.run(adapter.get_positions())[0]

    assert position.produced_by == "mt5"
    assert position.pnl_source == "profit"
    assert position.swap == Decimal("-0.25")
    assert position.commission is None, "absent, and absent is not zero"
    assert position.direction == DirectionType.LONG


# ======================================================================================
# STATE 3 — a 429 carrying recommendedRetryTime
# ======================================================================================


def test_the_adapter_USES_the_servers_retry_time_and_never_invents_one():
    """ASSUMES: a 429 arrives as a `TooManyRequestsException` whose `metadata` carries
    `recommendedRetryTime`. Settled by checklist item 1.5 — and the quota is denominated in CPU
    credits, not requests, so our per-call cost is unmeasured.

    Modelling the status and not the payload teaches the adapter to invent a backoff against a
    cost model nobody has measured.
    """
    adapter, mock = _adapter()

    async def _limited(*a, **k):
        raise TooManyRequestsException({"recommendedRetryTime": 7})

    mock.get_account_information = _limited
    with pytest.raises(BrokerRateLimitError) as exc:
        asyncio.run(adapter.get_account())
    assert exc.value.retry_after_seconds == 7, (
        f"the server asked for 7s and the adapter carried {exc.value.retry_after_seconds}"
    )


def test_a_429_with_NO_retry_time_is_SURFACED_rather_than_defaulted():
    """ASSUMES: the same 429 shape, with the field absent (checklist item 1.5).

    A guessed retry against an unmeasured cost model is exactly what this state exists to
    prevent, so the absence is reported rather than filled in.
    """
    adapter, mock = _adapter()

    async def _limited(*a, **k):
        raise TooManyRequestsException({})

    mock.get_account_information = _limited
    with pytest.raises(BrokerRateLimitError) as exc:
        asyncio.run(adapter.get_account())
    assert exc.value.retry_after_seconds is None
    assert "NO recommendedRetryTime" in str(exc.value)


def test_an_exception_with_a_DIFFERENT_name_is_not_treated_as_a_rate_limit():
    """ASSUMES: the SDK's rate-limit exception is named `TooManyRequestsException` and that name
    is stable. Settled by checklist item 1.5, which provokes a real 429 and captures the payload.

    **MUST-MISS half.** The adapter matches on a class NAME because it cannot import the class,
    so the arms above would pass for an adapter that treated EVERY error as a rate limit. This is
    the control that says the name is doing the work — and it is also the arm that goes red if
    the vendor ever renames the class, which is the failure mode of matching on a string.
    """
    adapter, mock = _adapter()

    class SomeOtherSdkError(Exception):
        pass

    async def _other(*a, **k):
        raise SomeOtherSdkError("not a 429")

    mock.get_account_information = _other
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.get_account())
    assert not isinstance(exc.value, BrokerRateLimitError)


# ======================================================================================
# STATE 4 — E_SRV_NOT_FOUND and E_AUTH are DISTINCT
# ======================================================================================


@pytest.mark.parametrize("code,expected", [
    ("E_SRV_NOT_FOUND", MT5ServerNotFound),
    ("E_AUTH", MT5AuthFailed),
])
def test_a_wrong_server_name_and_a_wrong_password_are_DIFFERENT_exceptions(code, expected):
    """ASSUMES: MetaApi returns these two codes distinguishably on `createAccount`/`connect`.
    Settled by checklist item 0.1 — the free one, done by getting it wrong twice on purpose, and
    **the only item needing no working account.**

    Different problems, identical symptom. One generic failure collapses *"you typed the server
    name wrong"* into *"your password is wrong"* — a day of debugging on the first attempt.
    """
    adapter, _ = _adapter(connect_error=_CodedError(code))
    with pytest.raises(expected):
        asyncio.run(adapter.connect())


def test_an_UNCLASSIFIED_connect_failure_says_it_is_neither_rather_than_guessing():
    """ASSUMES: codes other than the two documented ones can occur (checklist item 0.1 observes
    which codes this broker actually emits).

    Reporting an unknown failure as one of the two named causes would send the debugger to a
    specific wrong place, which is worse than saying it is unclassified.
    """
    adapter, _ = _adapter(connect_error=_CodedError("E_SOMETHING_NEW"))
    with pytest.raises(Exception) as exc:
        asyncio.run(adapter.connect())
    assert not isinstance(exc.value, (MT5ServerNotFound, MT5AuthFailed))
    assert "neither" in str(exc.value).lower()


def test_connect_calls_wait_synchronized_and_not_only_connect():
    """ASSUMES: `connect()` and `wait_synchronized()` are both required and the state between
    them is real (`T-0100`). Settled by checklist item 1.1.

    **`connect()` returning is not "connected".** Treating it as sufficient is correct against
    any mock and wrong against a venue.
    """
    adapter, mock = _adapter()
    asyncio.run(adapter.connect())
    assert mock.synchronized is True, "synchronisation was skipped"
    assert adapter.connected is True


# ======================================================================================
# STATE 5 — the account type absent, or outside the three enums
# ======================================================================================


def test_an_ABSENT_account_type_fails_closed_as_UNREADABLE():
    """ASSUMES: `type` is REQUIRED on `getAccountInformation` and arrives per call. Settled by
    checklist item 1.2 — **the item the whole safety argument rests on**, which also asks what
    happens when the read fails.
    """
    adapter, _ = _adapter(account={"login": "1", "balance": 0.0, "equity": 0.0,
                                   "currency": "USD"})
    with pytest.raises(MT5AccountTypeUnreadable):
        asyncio.run(adapter.get_account())


def test_an_UNRECOGNISED_account_type_is_a_DIFFERENT_failure_from_an_unreadable_one():
    """ASSUMES: the three documented enums are the only valid values today, and a vendor may add
    a fourth. Settled by checklist item 1.2.

    **Both fail closed, and they must not be the same exception.** One type for both means a new
    enum value from the vendor reads as an outage forever — `B215` on the one field the safety
    argument rests on.
    """
    adapter, _ = _adapter(account={"login": "1", "balance": 0.0, "equity": 0.0,
                                   "currency": "USD", "type": "ACCOUNT_TRADE_MODE_SOMETHING_NEW"})
    with pytest.raises(MT5AccountTypeUnrecognised) as exc:
        asyncio.run(adapter.get_account())
    assert exc.value.value == "ACCOUNT_TRADE_MODE_SOMETHING_NEW"
    assert not isinstance(exc.value, MT5AccountTypeUnreadable), (
        "could-not-read and read-something-new must stay distinguishable"
    )


@pytest.mark.parametrize("mode", ACCOUNT_TRADE_MODES)
def test_a_KNOWN_account_type_is_exposed_and_does_NOT_move_is_simulation(mode):
    """ASSUMES: the three documented enums (checklist item 1.2). CONTEST is INFERRED and never
    observed — a retail demo reports DEMO, so it stays open until a prop MT5 account exists, and
    the checklist says so explicitly.

    The venue's answer is exposed because `T-0076`'s recommendation depends on it. **It is not
    consulted**, because the DEMO-to-`is_simulation` mapping is Malek's to make and every value
    this flag can return IS that mapping.
    """
    adapter, _ = _adapter(account={"login": "1", "balance": 0.0, "equity": 0.0,
                                   "currency": "USD", "type": mode})
    asyncio.run(adapter.get_account())
    assert adapter.venue_account_type == mode
    assert adapter.is_simulation is False, (
        "is_simulation moved with the venue's account type. The mapping is unruled (T-0076) and "
        "True would ship it write-enabled"
    )


# ======================================================================================
# place_order REFUSES — and the refusal message is the deliverable
# ======================================================================================


def test_place_order_REFUSES_and_the_message_carries_all_three_facts():
    """ASSUMES: MetaApi's `volume` parameter is MT5 LOTS while `OrderRequest.lot_size` carries
    UNITS (`B302`, measured across five call sites). Settled by checklist item 1.3, which fetches
    the per-instrument bounds the conversion needs.

    **Not "submit units with a docstring"** — MT5 reads what arrives as lots, so that is a wrong
    decision with a note attached, 100000x too large on a standard instrument.
    """
    adapter, _ = _adapter()
    request = OrderRequest(pair="BTCUSD", direction=DirectionType.LONG,
                           order_type=OrderType.MARKET, lot_size=1234.5)
    with pytest.raises(NotImplementedError) as exc:
        asyncio.run(adapter.place_order(request))

    message = str(exc.value)
    assert "UNITS" in message, "it must say what the size arriving actually is"
    assert "LOTS" in message, "it must say what MetaApi expects"
    assert "get_symbol_specification" in message, "it must say what the conversion still needs"


def test_the_ninth_member_exists_and_is_NOT_on_the_base_class():
    """ASSUMES: `getSymbolSpecification` returns `volume_min` / `volume_step` / `volume_max` /
    `contract_size`. Settled by checklist item 1.3 — the real numbers replace the ones
    `units_to_lots` was tested against, which we chose.

    It is deliberately NOT on `BrokerAdapter`: one venue has the concept, and **generalising a
    venue's concept from one venue is how `oanda.py:401`'s hardcoded `100_000` happened**.
    """
    from app.services.broker.base import BrokerAdapter

    adapter, _ = _adapter()
    spec = asyncio.run(adapter.get_symbol_specification("BTCUSD"))
    assert {"volume_min", "volume_step", "volume_max", "contract_size"} <= set(spec)
    assert not hasattr(BrokerAdapter, "get_symbol_specification"), (
        "the member migrated to the base class from a single venue's vocabulary"
    )


def test_close_position_is_DEFINED_and_refuses_with_its_reason():
    """ASSUMES: a partial close dispatches on volume in MT5 LOTS (`B302`). Settled by checklist
    item 1.3.

    Defined rather than absent: the member is abstract, so omitting it makes the class
    un-instantiable and every arm above impossible.
    """
    adapter, _ = _adapter()
    with pytest.raises(NotImplementedError) as exc:
        asyncio.run(adapter.close_position("p1", lot_size=0.1))
    assert "B302" in str(exc.value)


def test_disconnect_is_a_DOCUMENTED_noop_rather_than_a_silent_pass():
    """ASSUMES: the SDK documents no close or disconnect (`B285`). Settled by checklist item 1.4,
    which inspects the connection object or asks support.
    """
    import inspect

    from app.services.broker.mt5 import MetaTrader5Adapter as Cls

    adapter, _ = _adapter()
    asyncio.run(adapter.connect())
    asyncio.run(adapter.disconnect())
    assert adapter.connected is False
    doc = inspect.getdoc(Cls.disconnect) or ""
    assert "B285" in doc and "no-op" in doc.lower(), (
        "a no-op without a docstring is indistinguishable from an omission"
    )


# ======================================================================================
# close_all_positions — Malek's PROPERTY, and the third state must be REACHABLE
# ======================================================================================


def test_a_per_position_failure_is_FAILED_and_the_loop_CONTINUES():
    """ASSUMES: MetaApi has no close-all, so the member iterates. Settled by no checklist item —
    **and that is a gap**: the checklist has no step that closes a position, so the iteration is
    exercised only against this mock until Malek runs a full trade cycle.

    `B303` is CFT catching `BrokerError` only, so a `ConnectTimeout` aborts and the rest are never
    attempted. **Abandoning positions 3 and 4 because position 2 timed out would MANUFACTURE
    `NOT_ATTEMPTED` rows for positions we could have closed** — worse, and it satisfies the ruled
    property just as well, which is why the property alone does not decide it.
    """
    adapter, mock = _adapter(
        positions=[_position(f"p{i}") for i in range(1, 5)],
        close_errors={"p2": TimeoutError("connect timeout")},   # NOT a BrokerError
    )
    report = asyncio.run(adapter.close_all_positions())

    by_id = {r["position_id"]: r for r in report}
    assert set(by_id) == {"p1", "p2", "p3", "p4"}, "every position open at pull time is reported"
    assert by_id["p2"]["disposition"] == "FAILED"
    assert "TimeoutError" in by_id["p2"]["reason"], "failed WITH A REASON, not merely failed"
    assert [by_id[p]["disposition"] for p in ("p1", "p3", "p4")] == ["CLOSED"] * 3


def test_an_ABNORMAL_EXIT_still_reports_every_position_and_names_the_untouched_ones():
    """ASSUMES: the same iteration (no checklist item covers it — see the arm above).

    **This is the arm the ruling exists for.** A cancellation is not an `Exception`, so no
    `except Exception` catches it: the loop unwinds with positions 3 and 4 never attempted, and
    **that state must be reported rather than lost with the frame** (`B303`).
    """
    adapter, mock = _adapter(
        positions=[_position(f"p{i}") for i in range(1, 5)],
        close_errors={"p2": asyncio.CancelledError()},
    )
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.close_all_positions())

    report = {r["position_id"]: r for r in exc.value.partial_report}
    assert set(report) == {"p1", "p2", "p3", "p4"}, "the report died with the frame"
    assert report["p1"]["disposition"] == "CLOSED"
    assert report["p3"]["disposition"] == "NOT_ATTEMPTED"
    assert report["p4"]["disposition"] == "NOT_ATTEMPTED"
    assert adapter.last_close_all_report is not None, (
        "the report must also survive on the adapter, for a caller holding no exception"
    )


def test_a_NOT_ATTEMPTED_row_is_never_counted_as_CLOSED_by_the_kill_switch():
    """ASSUMES: nothing about the venue. It is about `kill_switch.py`'s counting (`B330`).

    The aggregator counted any row whose `status` is not `error`/`failed` as CLOSED — so a row
    saying **nobody reached this position** was reported to the operator as a closed position, on
    the control whose whole purpose is to leave nothing open.
    """
    adapter, _ = _adapter(
        positions=[_position(f"p{i}") for i in range(1, 5)],
        close_errors={"p2": asyncio.CancelledError()},
    )
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.close_all_positions())

    for row in exc.value.partial_report:
        if row["disposition"] == "NOT_ATTEMPTED":
            assert row["status"] in ("error", "failed"), (
                "a consumer that knows only two states must land an unattempted position on the "
                "NOT-CLOSED side; kill_switch.py counts anything else as closed"
            )


def test_close_all_RAISES_rather_than_reporting_nothing_when_it_cannot_enumerate():
    """ASSUMES: the two connection booleans (checklist item 1.1).

    Returning `[]` because the position list could not be read would say *there was nothing to
    close* — `B292`'s collapse, on the kill switch's own path.
    """
    adapter, _ = _adapter(
        positions=[_position("p1")],
        terminal_state=_TerminalState(connected=True, connected_to_broker=False),
    )
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.close_all_positions())
    assert "could not enumerate" in str(exc.value).lower()


# ======================================================================================
# The remaining built members
# ======================================================================================


def test_get_account_normalises_the_venues_fields():
    """ASSUMES: `getAccountInformation` returns `login`, `balance`, `equity`, `currency`,
    `margin` and `freeMargin`. Settled by checklist item 1.2, which reads the payload.
    """
    adapter, _ = _adapter()
    account = asyncio.run(adapter.get_account())
    assert account.broker == "mt5"
    assert account.balance == 10_000.0 and account.equity == 10_050.0
    assert account.margin_available == 9_900.0


def test_reference_price_is_the_MID_and_its_absence_is_not_an_exception():
    """ASSUMES: `getSymbolPrice` returns `bid` and `ask`. No checklist item covers the quote
    shape — **a gap**; items 1.3 and 1.5 touch symbols and rate limits but nothing reads a quote.

    An adapter that forgets this member silently rejects EVERY market order as *no reference
    price available*, which reads as a market-data fault (`base.py:195`).
    """
    adapter, mock = _adapter()
    assert asyncio.run(adapter.reference_price("BTCUSD")) == 101.0

    async def _no_quote(symbol: str):
        return {}

    mock.get_symbol_price = _no_quote
    assert asyncio.run(adapter.reference_price("BTCUSD")) is None


def test_the_adapter_declares_no_default_pairs_despite_the_asset_class_being_ruled():
    """ASSUMES: MT5 brokers name the same instrument differently (`BTCUSD`, `BTCUSD.x`, …). No
    checklist item asks for the symbol STRINGS directly — item 1.3 asks for specifications and
    presupposes you already know the names, which is a gap worth recording.

    `B305` is ruled: crypto CFDs, BTC and ETH. **That settles the asset class, not the venue's
    vocabulary**, and filling these in from the ruling would be inventing a venue's symbols.
    """
    adapter, _ = _adapter()
    assert adapter.default_pairs == []


# ======================================================================================
# B336 — THE DIRECTION MAPPING, which 30 green arms did not touch
# ======================================================================================


def test_a_SELL_position_reads_as_SHORT():
    """ASSUMES: `MetatraderPosition.type` is one of `POSITION_TYPE_BUY` / `POSITION_TYPE_SELL`.
    **Settled by no checklist item, and it did not need one** — `T-0133` put the SDK on disk and
    its model states exactly those two values, so this is read from the package rather than from
    our reading of the docs.

    `B336`: making every position LONG unconditionally passed 30 of 30, and the word `SELL`
    occurred nowhere in this file. **This is the arm whose absence that measured.**
    """
    adapter, _ = _adapter(positions=[_position("p1", type="POSITION_TYPE_SELL")])
    positions = asyncio.run(adapter.get_positions())
    assert positions[0].direction == DirectionType.SHORT


def test_a_BUY_position_reads_as_LONG():
    """ASSUMES: the same two documented values (see the arm above; no checklist item covers it).

    The must-hit half. Without it the arm above passes under a mapping that answers SHORT for
    everything, which is the mirror of the defect being fixed.
    """
    adapter, _ = _adapter(positions=[_position("p1", type="POSITION_TYPE_BUY")])
    assert asyncio.run(adapter.get_positions())[0].direction == DirectionType.LONG


@pytest.mark.parametrize("bad_type", [
    0, 1,                                # the INTEGER codes native MT5 actually uses
    "buy", "sell", "",                   # casings and emptiness the old endswith() swallowed
    "POSITION_TYPE_SELL_BUY_STOP",       # ends with BUY and is not a buy
])
def test_an_UNRECOGNISED_position_type_RAISES_rather_than_defaulting_to_SHORT(bad_type):
    """ASSUMES: the two documented values are the only ones today, and a vendor may add more.
    No checklist item asks what the field can carry — **a gap**, and item 1.1 prints the position
    list, so running it would expose an undocumented value rather than settle it in advance.

    **The old mapping was a DEFAULT wearing a mapping's clothes.** `endswith("BUY")` answered
    SHORT for every one of these, including the integer codes and the string that ends in `BUY`
    without being a buy. **A wrong direction inverts the sign of every number downstream**, and
    there is no value of `DirectionType` that means *I could not tell*.
    """
    adapter, _ = _adapter(positions=[_position("p1", type=bad_type)])
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.get_positions())
    assert "not one of" in str(exc.value)


def test_an_ABSENT_position_type_RAISES_and_is_not_silently_a_SHORT():
    """ASSUMES: `type` is present on every position MetaApi returns (`B291` marks it required).
    Settled by checklist item 1.1, which prints the position list.

    `raw.get("type", "")` made the absent case indistinguishable from a malformed one AND from a
    genuine SELL. Absent is *could not ask*; SHORT is an answer (`B215`).
    """
    raw = _position("p1")
    del raw["type"]
    adapter, _ = _adapter(positions=[raw])
    with pytest.raises(BrokerError):
        asyncio.run(adapter.get_positions())


# ======================================================================================
# B338 first half — a value we could not READ must never become a zero
# ======================================================================================


@pytest.mark.parametrize("field,value", [
    ("openPrice", "1,234.50"),   # a thousands separator is the realistic shape
    ("volume", "0.5 lots"),
])
def test_an_UNPARSEABLE_required_number_RAISES_rather_than_becoming_zero(field, value):
    """ASSUMES: the venue's model types `openPrice` and `volume` numeric, so a non-numeric value
    is a CONTRACT VIOLATION rather than a missing optional. Verified against the installed package
    (`T-0133`), not against a checklist item — **no item covers malformed payloads**, which is a
    gap worth recording.

    `B338`: `_dec` returned `None` for a value it could not parse, and both callers wrote
    `or Decimal("0")`. **A price the adapter could not read became a position with an entry price
    of zero** — a number every downstream P&L and risk calculation consumes happily.
    """
    adapter, _ = _adapter(positions=[_position("p1", **{field: value})])
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.get_positions())
    assert field in str(exc.value)


def test_an_ABSENT_required_number_RAISES_and_is_not_a_zero():
    """ASSUMES: `openPrice` is required on `MetatraderPosition` (`B291`). Settled by checklist
    item 1.1, which prints a real position payload.
    """
    raw = _position("p1")
    del raw["openPrice"]
    adapter, _ = _adapter(positions=[raw])
    with pytest.raises(BrokerError):
        asyncio.run(adapter.get_positions())


def test_a_LEGITIMATE_zero_survives_and_is_not_read_as_a_failure():
    """ASSUMES: nothing about the venue. It is about the fix not overshooting.

    **`or Decimal("0")` could not tell a parse failure from a real zero, and neither may the
    replacement** — in the opposite direction. A genuine `swap` of `0` must stay `0`, and a
    genuine absent `swap` must stay `None`. This is the must-MISS control for both new raises.
    """
    adapter, _ = _adapter(positions=[_position("p1", swap=0, commission=0.0)])
    position = asyncio.run(adapter.get_positions())[0]
    assert position.swap == Decimal("0") and position.commission == Decimal("0")

    adapter2, _ = _adapter(positions=[_position("p2")])          # neither field present
    plain = asyncio.run(adapter2.get_positions())[0]
    assert plain.swap is None and plain.commission is None, (
        "an absent optional must stay None — B215 is not repealed by B338"
    )


def test_an_UNPARSEABLE_OPTIONAL_number_RAISES_and_is_not_read_as_ABSENT():
    """ASSUMES: `swap` and `commission` are optional but NUMERIC when present (`B291`, and the
    installed model types them `float`). No checklist item covers malformed payloads — the same
    gap the required-field arm names.

    **Found by predicting a mutation rather than by running one.** Reverting `_dec` to swallow
    parse errors leaves every REQUIRED field still raising, because `_required_dec` rejects the
    `None` that swallowing produces — so the required arms could not see the change and I nearly
    recorded `_dec`'s raise as unmeasured. **For an OPTIONAL field the swallow is invisible: an
    unreadable `swap` becomes `None`, which is this file's own word for *the venue did not send
    it*.** That is `B215` collapsed by the fix for `B338`.
    """
    adapter, _ = _adapter(positions=[_position("p1", swap="1,2")])
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.get_positions())
    assert "swap" in str(exc.value)
