"""T-0050 — EXIT-001 decides the live exit, and the runner does not move its stop.

**The single most likely way this task goes wrong is porting the backtest's runner management.**
It is thirty lines away, it is more sophisticated, and it is the rule Salim has explicitly left
unruled:

    backtest/engine.py:42   runner_trail_atr = 2.5      :43  runner_max_hold = 48
                     :457   "the 30% runner TRAILS ... never below break-even"
    exit_001_v1_model:442   "The runner is PASSIVE — it does not trail, scale or move its stop"

`EXIT-003` is `OPEN`, so PASSIVE is the only attributable value. **A break-even shift IS a stop
movement**, so "only to break-even" is not a lesser version of trailing — it is the same violation
with a friendlier name, and it is the form most likely to look reasonable in review.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.db.enums import DirectionType, OrderType
from app.services.broker.paper import PaperBroker
from app.services.execution.service import ExecMode, ExecutionService, Signal
from dataclasses import replace

from app.services.live import crypto_loop as loop_mod
from app.services.rules.exit_001_v1_model import (
    DECLARED_SESSION_CLOSE, PARTIAL_AT_R, PARTIAL_FRACTION, RUNNER_FRACTION,
)

NY = ZoneInfo("America/New_York")


class _Loop:
    """The loop's exit mechanics with nothing else attached.

    `LiveCryptoLoop.__init__` reaches for market data and a database. The methods under test
    touch only `self.paper`, the two plan dicts and `_act`/`ws_manager`, so they are exercised
    against a REAL `PaperBroker` — the thing whose state the acceptance is asserted on — rather
    than against a double that would re-introduce the discard defect `T-0038` closed.
    """

    def __init__(self, broker: PaperBroker) -> None:
        self.paper = broker
        self._tranche_plans: dict[str, dict] = {}
        self._partialled: set[str] = set()
        self._last_session_close: date | None = None
        self.acts: list[tuple[str, str]] = []

    async def _act(self, kind: str, message: str) -> None:
        self.acts.append((kind, message))

    _take_partials = loop_mod.LiveCryptoLoop._take_partials
    _close_at_session_end = loop_mod.LiveCryptoLoop._close_at_session_end


@pytest.fixture(autouse=True)
def _silence_ws(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(loop_mod.ws_manager, "push_position_close", _noop)


async def _open(broker: PaperBroker, *, entry=100.0, sl=95.0, units=10.0):
    broker._marks["BTC/USDT"] = entry
    res = await broker.place_order(loop_mod.OrderRequest(
        pair="BTC/USDT", direction=DirectionType.LONG, order_type=OrderType.MARKET,
        lot_size=units, sl=sl, tp=None,
    )) if hasattr(loop_mod, "OrderRequest") else None
    if res is None:
        from app.services.broker.base import OrderRequest
        res = await broker.place_order(OrderRequest(
            pair="BTC/USDT", direction=DirectionType.LONG, order_type=OrderType.MARKET,
            lot_size=units, sl=sl, tp=None,
        ))
    return res["position_id"]


def _plan(pid: str, price: float) -> dict:
    return {"price": price, "fraction": PARTIAL_FRACTION, "direction": "LONG", "pair": "BTC/USDT"}


# ---------------------------------------------------------------------------
# The cutover itself
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_partial_fires_and_the_REMAINDER_SURVIVES_asserted_on_BROKER_STATE():
    """THE ACCEPTANCE. Two exit events on one position, and the second is not the first.

    **Asserted on broker STATE, never on the returned dict** — that is `T-0038`'s standard, and
    it is the thing its silent-discard defect turned on: an adapter that ignored `lot_size`
    returned a success dict indistinguishable from having honoured it.
    """
    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker, entry=100.0, sl=95.0, units=10.0)
    loop = _Loop(broker)
    partial_at = 100.0 + PARTIAL_AT_R * (100.0 - 95.0)   # 2R = 110
    loop._tranche_plans[pid] = _plan(pid, partial_at)

    await loop._take_partials("BTC/USDT", partial_at)

    open_now = await broker.get_positions()
    assert len(open_now) == 1, "the whole position closed — the runner did not survive the partial"
    assert float(open_now[0].lot_size) == pytest.approx(10.0 * RUNNER_FRACTION), (
        f"the remainder is not the ruled {RUNNER_FRACTION:.0%} runner"
    )
    assert pid in loop._partialled and pid not in loop._tranche_plans


@pytest.mark.asyncio
async def test_the_RUNNERS_STOP_IS_UNCHANGED_between_entry_and_termination():
    """**THE MUST-MISS, and the one this task is most likely to fail.**

    Not "it did not trail far" — UNCHANGED. A break-even move is a stop movement, and the
    backtest's `max(sl_runner, d.entry, peak - runner_trail_atr * a)` is exactly the expression
    that would look like an improvement here.
    """
    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker, entry=100.0, sl=95.0, units=10.0)
    before = broker._positions[pid]
    stop_at_entry, entry_price = before.sl, before.entry

    loop = _Loop(broker)
    loop._tranche_plans[pid] = _plan(pid, 110.0)
    await loop._take_partials("BTC/USDT", 110.0)

    after = broker._positions[pid]
    assert after.sl == stop_at_entry, (
        f"the runner's stop moved {stop_at_entry} -> {after.sl}. EXIT-001: the runner is PASSIVE. "
        "If this moved to the entry price it is a BREAK-EVEN shift, which is a stop movement and "
        "is the backtest's off-doctrine policy leaking in."
    )
    assert after.sl != entry_price or stop_at_entry == entry_price, (
        "the stop is now at break-even — see above; EXIT-003 is OPEN and nobody ruled this"
    )
    assert after.tp is None, "a take-profit appeared on the runner — it has no final target"
    assert after.entry == entry_price, "the remainder's entry moved — R would be measured wrong"


@pytest.mark.asyncio
async def test_a_price_oscillating_across_the_2R_LEVEL_cannot_bank_seventy_percent_twice():
    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker, entry=100.0, sl=95.0, units=10.0)
    loop = _Loop(broker)
    loop._tranche_plans[pid] = _plan(pid, 110.0)

    for price in (110.0, 109.0, 111.0, 110.5):
        await loop._take_partials("BTC/USDT", price)

    open_now = await broker.get_positions()
    assert len(open_now) == 1
    assert float(open_now[0].lot_size) == pytest.approx(10.0 * RUNNER_FRACTION), (
        "the partial fired more than once — the runner has been whittled away"
    )


@pytest.mark.asyncio
async def test_the_partial_does_NOT_fire_before_price_reaches_the_2R_level():
    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker, entry=100.0, sl=95.0, units=10.0)
    loop = _Loop(broker)
    loop._tranche_plans[pid] = _plan(pid, 110.0)

    await loop._take_partials("BTC/USDT", 109.99)

    assert float((await broker.get_positions())[0].lot_size) == 10.0, "banked early"
    assert pid not in loop._partialled


# ---------------------------------------------------------------------------
# SESSION_CLOSE — the runner's only other terminal reason
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_runner_terminates_at_the_declared_session_close_and_only_once_a_day(monkeypatch):
    """Built in T-0050 because **without it the runner has no termination but the stop.**

    Before the cutover every position carried a 2R take-profit; after it the remainder has no
    target at all, so an unimplemented session close leaves it riding indefinitely — which is
    not EXIT-001's model but the absence of one.
    """
    broker = PaperBroker(starting_balance=10_000.0)
    await _open(broker, entry=100.0, sl=95.0, units=10.0)
    loop = _Loop(broker)

    # T-0051 GATED THE ACTION BEHIND A FLAG THAT DEFAULTS OFF, so this test now enables it
    # explicitly. **It is testing EXIT-001's terminal condition, not the operating switch** —
    # without the flag on it would silently become a test of the suppression, pass for the wrong
    # reason, and stop saying anything about the behaviour it is named for.
    # T-0051's ARM 1/ARM 2 pair is what tests the switch itself.
    monkeypatch.setattr(
        loop_mod, "DECLARED_SESSION_FLATTEN",
        replace(loop_mod.DECLARED_SESSION_FLATTEN, enabled=True),
    )

    before_close = datetime.combine(date(2026, 8, 18), time(18, 59), tzinfo=NY)
    await loop._close_at_session_end(before_close)
    assert len(await broker.get_positions()) == 1, "closed before 19:00 NY"

    await loop._close_at_session_end(before_close.replace(hour=19, minute=0))
    assert await broker.get_positions() == [], "the runner survived SESSION_CLOSE"

    # Idempotent per NY date: a second tick in the same session must not re-close.
    await _open(broker, entry=100.0, sl=95.0, units=10.0)
    await loop._close_at_session_end(before_close.replace(hour=20, minute=0))
    assert len(await broker.get_positions()) == 1, (
        "SESSION_CLOSE fired twice in one session — a position opened after the close was cut "
        "immediately, which is a different rule from the one EXIT-001 states"
    )


def test_the_session_close_time_is_DECLARED_and_still_unratified():
    """19:00 is OURS. It enters the codex only through the EURUSD / algo HT v2.0 strand while
    our instrument trades 24/7, and question 4 to Salim is unanswered."""
    assert DECLARED_SESSION_CLOSE.ratified is False
    assert DECLARED_SESSION_CLOSE.local_time == time(19, 0)
    assert "UNANSWERED" in DECLARED_SESSION_CLOSE.source


# ---------------------------------------------------------------------------
# No new constant, and no trailing policy
# ---------------------------------------------------------------------------
def test_the_live_path_never_reaches_for_the_backtests_runner_knobs():
    """AST over the live modules, not a grep — this file NAMES both knobs in order to forbid
    them, and a substring scan would fire on its own prohibition (B161, four times tonight)."""
    live = pathlib.Path(__file__).resolve().parents[2] / "app" / "services" / "live"
    offenders: list[str] = []
    for path in sorted(live.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Name):
                name = node.id
            if name in {"runner_trail_atr", "runner_max_hold"}:
                offenders.append(f"{path.name}:{node.lineno} -> {name}")
    assert not offenders, (
        f"the live path reads the backtest's runner knobs at {offenders}. Those are EXIT-003's "
        "subject and EXIT-003 is OPEN — porting them ratifies a trailing policy by implementation."
    )


def test_the_cutover_introduced_NO_new_exit_constant():
    """`partial_frac` and `PARTIAL_AT_R` both already existed. The whole task is that one of
    them was being spent on the other's job."""
    from app.services.live import strategy_step

    src = inspect.getsource(strategy_step)
    tree = ast.parse(src)
    assigned_numbers = {
        t.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, (int, float)) and t.id.isupper()
    }
    assert not (assigned_numbers - {"PARTIAL_AT_R", "PARTIAL_FRACTION"}), (
        f"strategy_step declared new numeric constants {assigned_numbers} — the cutover is meant "
        "to READ the ratified ones, not add any"
    )
    assert PARTIAL_AT_R == 2.0 and PARTIAL_FRACTION == 0.7
    assert abs(PARTIAL_FRACTION + RUNNER_FRACTION - 1.0) < 1e-9


def test_the_signal_no_longer_spends_the_partials_constant_on_the_take_profit():
    """B162, closed. `rr_partial` must not appear in the price the signal carries as `tp`."""
    from app.services.live import strategy_step

    tree = ast.parse(inspect.getsource(strategy_step))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Signal":
            kw = {k.arg for k in node.keywords}
            assert "tp" in kw, "Signal is built positionally — tp must be explicit after T-0050"
            tp = next(k.value for k in node.keywords if k.arg == "tp")
            assert isinstance(tp, ast.Constant) and tp.value is None, (
                "the signal still carries a whole-position take-profit; under EXIT-001 that "
                "price is the PARTIAL level and belongs in partial_price"
            )
            assert {"partial_price", "partial_fraction"} <= kw, (
                "the signal carries no partial — the exit collapsed back to one stage"
            )


@pytest.mark.asyncio
async def test_the_2R_EXACT_case_shows_NO_DIFFERENCE_and_that_is_the_correct_null():
    """GATE-031's degenerate runner, stated so the null is not read as a failure to discriminate.

    When the partial level IS the final target, 70% and 30% close at one price — so a 1.5R and a
    2R policy produce the identical result and the corpus cannot tell them apart. **That is a
    fact about the setup, not a weakness of the measurement**, and Salim ruled the case TAKE_AND_FLAG.
    """
    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker, entry=100.0, sl=95.0, units=10.0)
    loop = _Loop(broker)
    loop._tranche_plans[pid] = _plan(pid, 110.0)

    await loop._take_partials("BTC/USDT", 110.0)
    remainder = (await broker.get_positions())[0]
    final = await broker.close_position(pid)

    assert final["units"] == pytest.approx(float(remainder.lot_size))
    assert await broker.get_positions() == []
    # Both tranches settled at the same price: the runner earned nothing beyond the partial, and
    # the two policies are indistinguishable HERE for a reason that is in the setup.
    assert final["partial"] is False


# ---------------------------------------------------------------------------
# The enforcement must be CLAIMED by the rule it enforces
# ---------------------------------------------------------------------------
def test_GATE_022_is_CLAIMED_because_the_engine_now_enforces_it():
    """**A producer with no declaration is invisible to the instrument built to find it.**

    `T-0050` made `crypto_loop._close_at_session_end` perform GATE-022's statement verbatim —
    *"any position still open at 19:00 New York time is closed"* — daily and position-wide.
    Until it was claimed, `check_rule_coverage.py` reported `GATE-022` UNIMPLEMENTED while the
    engine closed positions by it, so **every coverage figure we publish would have understated
    what the engine does.** The mirror of `T-0033`'s declared-with-no-producer, and worse in
    that direction: the missing half is the one our tooling can see.
    """
    import app.services.rules as rules_pkg
    from app.services.rules.exit_001_v1_model import SessionClose

    assert SessionClose.RULE_ID == "GATE-022"
    assert "GATE-022" in rules_pkg.implemented_ids()


def test_GATE_022_reports_NOT_ASKED_separately_from_the_session_being_open():
    """`None` is not `PASS`. A gate that answered "session open" to a caller with no clock would
    be reporting the state of the world on no evidence."""
    from app.services.rules.exit_001_v1_model import SessionClose

    assert SessionClose.evaluate().verdict == "NOT_APPLICABLE"
    assert SessionClose.evaluate(datetime(2026, 8, 18, 18, 59, tzinfo=NY)).verdict == "PASS"
    assert SessionClose.evaluate(datetime(2026, 8, 18, 19, 0, tzinfo=NY)).verdict == "FAIL"


def test_the_session_close_default_records_WHO_OWNS_IT_now_that_it_enforces():
    """**The old justification expired silently and the words did not move.**

    `DECLARED_SESSION_CLOSE` used to say it was defaulted ON *"so that shadow produces the
    evidence the ruling should rest on"* — a reason that holds only while it is OFF the deciding
    path. `T-0050` converted shadow into enforcement, so evidence-gathering stopped being why it
    is on, while the sentence saying so stayed true-looking. Found by the Manager.
    """
    source = DECLARED_SESSION_CLOSE.source

    # NOT `"shadow produces the evidence" not in source`. THAT ARM FAILED WHEN FIRST WRITTEN,
    # AND IT WAS RIGHT TO: the honest rewrite QUOTES the old sentence in order to record that it
    # expired, so an absence check cannot tell quotation from use. **Sixth token-subject misread
    # in this session and the first one in an arm I wrote knowing the class** — which is the
    # measure of how cheap the mistake is. The property is not "the words are gone"; it is "the
    # CURRENT reason is stated and the old one is marked as superseded".
    assert "expired" in source.lower(), (
        "the source does not record that its own justification expired — a reader cannot tell "
        "the standing reason from the retired one"
    )
    assert "ENFORCEMENT" in source, "the source still describes this as a shadow parameter"
    assert "Malek" in source, (
        "the record must say who owns a default that closes positions daily"
    )
    # And the standing reason must be the one that survives enforcement.
    assert "no final target" in source or "TARGET-001" in source, (
        "the reason it is ON no longer names why the runner needs a terminal condition at all"
    )
    # The VALUE is his; the APPLICABILITY is question 4. authority_class tells you a ruling's
    # authority, not its scope — which is what makes `ratified=False` correct here.
    assert DECLARED_SESSION_CLOSE.ratified is False
    assert "question 4" in DECLARED_SESSION_CLOSE.source.lower()


# ---------------------------------------------------------------------------
# THE SHORT SIDE — added because every arm above was LONG
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_partial_fires_on_a_SHORT_at_the_2R_level_BELOW_entry():
    """**Every other arm in this file is LONG, which is `B168`'s class in this file's own arms.**

    A directional feature verified at one point in its parameter space reports the behaviour of
    that point. `_take_partials` compares `price >= partial` for a long and `price <= partial`
    for a short, and `strategy_step` computes `entry - PARTIAL_AT_R * risk` for a short — two
    sign flips that a long-only suite cannot distinguish from one, or from none.

    *And B168 was recorded on a measurement whose sign flipped with exactly this axis.*
    """
    from app.services.broker.base import OrderRequest

    broker = PaperBroker(starting_balance=10_000.0)
    broker._marks["BTC/USDT"] = 100.0
    res = await broker.place_order(OrderRequest(
        pair="BTC/USDT", direction=DirectionType.SHORT, order_type=OrderType.MARKET,
        lot_size=10.0, sl=105.0, tp=None,
    ))
    pid = res["position_id"]
    stop_at_entry = broker._positions[pid].sl

    loop = _Loop(broker)
    partial_at = 100.0 - PARTIAL_AT_R * (105.0 - 100.0)    # 2R BELOW entry = 90
    loop._tranche_plans[pid] = {
        "price": partial_at, "fraction": PARTIAL_FRACTION,
        "direction": "SHORT", "pair": "BTC/USDT",
    }

    # MUST-MISS FIRST: a price ABOVE the short's partial must not fire it. Without this, a
    # comparison left as `>=` would pass the arm below on the very first tick.
    await loop._take_partials("BTC/USDT", 110.0)
    assert float((await broker.get_positions())[0].lot_size) == 10.0, (
        "the short's partial fired while price moved AGAINST it — the comparison is inverted"
    )

    await loop._take_partials("BTC/USDT", partial_at)
    open_now = await broker.get_positions()
    assert len(open_now) == 1
    assert float(open_now[0].lot_size) == pytest.approx(10.0 * RUNNER_FRACTION)
    assert broker._positions[pid].sl == stop_at_entry, (
        "the short runner's stop moved — EXIT-001's runner is passive on both sides"
    )


def test_the_signal_places_the_partial_on_the_CORRECT_SIDE_for_both_directions():
    """AST over `strategy_step`: the long adds `PARTIAL_AT_R * risk` and the short subtracts it.

    Asserted on the OPERATOR because both branches are otherwise identical text, and a copy-paste
    that kept the `+` is the single most likely defect here — it would place a short's partial
    2R in the losing direction, where price reaches it only when the trade is already wrong.
    """
    from app.services.live import strategy_step

    tree = ast.parse(inspect.getsource(strategy_step))
    ops: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Signal":
            for kw in node.keywords:
                if kw.arg == "partial_price" and isinstance(kw.value, ast.BinOp):
                    ops.append(type(kw.value.op).__name__)
    assert ops == ["Add", "Sub"], (
        f"partial_price operators are {ops}; expected one Add (long) then one Sub (short). "
        "Two Adds means the short's partial sits 2R in the LOSING direction."
    )
