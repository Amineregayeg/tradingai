"""T-0057 — `B199`: a PER-SYMBOL liveness signal for the ORDER path.

**The monitored artefact was engineered to be immune to the condition that stops the
engine.** `shadow_health()` watches the SHADOW corpus; `T-0010` moved `_shadow_evaluate`
ABOVE the entry gates so `already in a position` would stop suppressing it. Correct, and it
fixed `B34`. It also means that on 2026-08-21 the order path froze for 62-91 hours with
`running: true`, rising equity, 12-second-old telemetry and a green `shadow_health()`.

**THE DISCRIMINATOR IS DOCTRINAL, NOT A TIMER, AND A TIMER MUST NOT COME BACK.** An engine
legitimately holding a position must not scream, and it holds one most of the time — a
staleness clock either screams all day or is set so loose it misses the incident entirely.
The signal fires on *blocked by `already in a position` AND that position has NO TARGET*,
because a position with a target closes on a win while one without can only stop out.

*If the doctrinal predicate ever looks fiddly, the tempting repair is `AND it has been quiet
for N hours` as belt-and-braces. That makes the control pair pass for free and converts the
signal back into the clock this task discarded. It is a finding to REPORT, not a term to add.*
"""
from __future__ import annotations

import ast
import inspect
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from app.services.monitoring import data_health as dh
from app.services.monitoring.data_health import (
    BLOCKED_BY_POSITION,
    ORDER_PATH_BLOCKED_BARS_FLOOR,
    order_path_symbol_state,
    entry_has_outstanding_remainder,
    outstanding_remainder_by_symbol,
)

BAR_SECONDS = 300.0  # ENTRY_TF 5m


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# ======================================================================================
# THE PRODUCTION STATE, captured read-only from tradingai-db-1 on 2026-08-23.
# Ages are the DATABASE'S OWN CLOCK, not this machine's.
#
#   run     a32c3b98-51f1-4ce6-be43-e3376f9979c7  started 2026-08-19 18:50:22.496166Z
#   now()   2026-08-23 18:16:57.911579Z
#   BTC/USD  300 records this run   newest 2026-08-21 00:05:12.63111Z   66.20 h
#   ETH/USD    7 records this run   newest 2026-08-19 19:20:31.662949Z  94.94 h
#
# And the stored evidence that neither blocking position has a target: EVERY entry
# decision this run carries signal_tp = NULL.
#   ETH/USD 2026-08-19 19:20:31  signal_tp NULL  sized_units 1.583930
#   BTC/USD 2026-08-21 00:05:12  signal_tp NULL  sized_units 0.080234
# Raw rows, query text and exit codes: agents/tasks/T-0057/_runs/
# ======================================================================================
PRODUCTION_NOW = _utc("2026-08-23 18:16:57.911579")
PRODUCTION_LAST_DECISION = {
    "BTC/USD": _utc("2026-08-21 00:05:12.631110"),
    "ETH/USD": _utc("2026-08-19 19:20:31.662949"),
}
PRODUCTION_AGE_HOURS = {"BTC/USD": 66.20, "ETH/USD": 94.94}

CONTROL_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "fixtures"
    / "t0057_btcusd_20260820_decisions.txt"
)


def _production_state(symbol: str, *, now: datetime | None = None, floor_override=None):
    """ARM 1 and ARM 7 call THIS, with the same signature, differing only in the instant."""
    return order_path_symbol_state(
        symbol=symbol,
        last_decision_at=PRODUCTION_LAST_DECISION[symbol],
        now=now or PRODUCTION_NOW,
        bar_seconds=BAR_SECONDS,
        blocked_reason=BLOCKED_BY_POSITION,
        remainder_outstanding=True,
    )


# ======================================================================================
# ARM 1 — THE PRODUCTION STATE IS THE ACCEPTANCE TEST
# ======================================================================================


@pytest.mark.parametrize("symbol", sorted(PRODUCTION_LAST_DECISION))
def test_arm1_the_signal_reproduces_B198_against_the_real_production_rows(symbol):
    """**A monitor that cannot detect the incident it was written for is not a monitor.**

    `B199` was found by hand, by querying `max(created_at)` per symbol. This asserts the
    signal reaches the same conclusion from the same rows — BOTH symbols, BOTH ages.
    """
    state = _production_state(symbol)

    assert state["withdrawn_from_trading"] is True, state
    assert state["age_hours"] == pytest.approx(PRODUCTION_AGE_HOURS[symbol], abs=0.01), (
        f"{symbol}: the age must match the database's own clock, not this machine's"
    )
    assert state["blocked_reason"] == BLOCKED_BY_POSITION
    assert state["remainder_outstanding"] is True
    assert "remainder is still outstanding" in state["verdict_reason"]


# ======================================================================================
# ARM 7 — THE CONTROL PAIR. Without it, "it fires on production right now" cannot
# distinguish a working detector from one that always fires.
# ======================================================================================


def _control_instants() -> list[datetime]:
    rows = [
        _utc(line.strip())
        for line in CONTROL_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(rows) >= 200, f"the control window collapsed to {len(rows)} rows"
    return rows


#: THE FOUR TRADES THIS RUN HAS EVER OPENED, read from `trades` on 2026-08-23.
#: **Every one of them has `tp = NULL`**, and three of the five blocks they caused RESOLVED.
#:   ETH/USD  2026-08-19 19:20:31 -> 20:50:38   tp NULL   resolved after ~18 bars
#:   BTC/USD  2026-08-20 03:20:12 -> 07:06:10   tp NULL   resolved after ~45 bars
#:   BTC/USD  2026-08-20 14:25:16 -> 15:02:39   tp NULL   resolved after  ~7 bars
#:   BTC/USD  2026-08-21 00:05:12 -> 01:18:21   tp NULL   the 70% tranche; the 30% RUNNER rides
CONTROL_WINDOW_EXPECTED_FIRES = 2


#: THE CONTROL WINDOW'S OWN ENTRIES AND CLOSES, read from production 2026-08-23.
#: **Both are WHOLE closes** — closed lots equal `sized_units` exactly — which is why the
#: structural term does not hold anywhere in this window.
CONTROL_ENTRIES = [
    ("BTC/USD", _utc("2026-08-20 03:20:12.470848"), 0.064343),
    ("BTC/USD", _utc("2026-08-20 14:25:16.473568"), 0.103051),
]
CONTROL_TRADES = [
    ("BTC/USD", _utc("2026-08-20 03:20:12.466177"), 0.064343),
    ("BTC/USD", _utc("2026-08-20 14:25:16.469269"), 0.103051),
]

#: With the structural term PINNED TRUE the same window fires twice, at these gaps. Kept as
#: a measurement so the green below is attributable to the STRUCTURE rather than the floor.
CONTROL_FIRES_IF_TERM_PINNED = [46.0, 8.0]


def test_arm7_the_control_window_is_GREEN_on_the_structural_term():
    """**ARM 7. `B216`'s remedy, measured.**

    The first version of this predicate fired on *blocked AND the position has no target*,
    and came back RED here — because every position this engine has ever opened has
    `tp = NULL`, so the term was true of 5 of 5 blocks and separated nothing.

    Re-keyed to *a tranche remainder is still outstanding*, the same window is GREEN, and it
    is green for a reason that can be pointed at: **both 2026-08-20 entries closed WHOLE.**
    Closed lots equal `sized_units` exactly on both, so there is no remainder at any age and
    at any floor value.

    *The floor was NOT touched to achieve this.*
    """
    remainders = outstanding_remainder_by_symbol(CONTROL_ENTRIES, CONTROL_TRADES)
    assert remainders == {"BTC/USD": False}, remainders

    instants = _control_instants()
    fired = [
        instants[i].isoformat()
        for i in range(1, len(instants))
        for state in [order_path_symbol_state(
            symbol="BTC/USD",
            last_decision_at=instants[i - 1],
            now=instants[i],
            bar_seconds=BAR_SECONDS,
            blocked_reason=BLOCKED_BY_POSITION,
            remainder_outstanding=remainders["BTC/USD"],
        )]
        if state["withdrawn_from_trading"]
    ]
    assert not fired, (
        f"the control window fired {len(fired)} times on the structural term: {fired[:3]}. "
        "Either the engine was NOT trading normally on 2026-08-20 — then the window is "
        "wrong and must be re-chosen from evidence, never widened until it passes — or the "
        "predicate fires regardless of input, which makes ARM 1 meaningless."
    )


def test_arm7_the_GREEN_comes_from_the_STRUCTURE_and_not_from_the_floor():
    """**The control on the control.** A green that the floor could have produced proves
    nothing about the structural term.

    Pin the structural term TRUE over the identical window and the identical instants: it
    fires twice, at 46 and 8 bars, on the two real blocks that later RESOLVED. So the green
    above is attributable to `remainder_outstanding` being `False` — not to the floor, which
    is unchanged between the two runs.
    """
    instants = _control_instants()
    fired = [
        state["bars_blocked"]
        for i in range(1, len(instants))
        for state in [order_path_symbol_state(
            symbol="BTC/USD",
            last_decision_at=instants[i - 1],
            now=instants[i],
            bar_seconds=BAR_SECONDS,
            blocked_reason=BLOCKED_BY_POSITION,
            remainder_outstanding=True,
        )]
        if state["withdrawn_from_trading"]
    ]
    assert fired == CONTROL_FIRES_IF_TERM_PINNED, fired


def test_arm7_the_structural_term_separates_2_of_2_BOTH_WAYS_on_the_live_run():
    """**The whole population of this run, with its denominator published.**

    `B216` showed the no-target term was true of 5 of 5 and separated nothing. The
    remainder term separates exactly, and the direction is not a coincidence: both entries
    that CLEARED are losses closing WHOLE at their stop, both that BLOCK are winners whose
    70% partial fired at 2R and left a runner.
    """
    entries = [
        ("ETH/USD", _utc("2026-08-19 19:20:31.662949"), 1.583930),
        ("BTC/USD", _utc("2026-08-20 03:20:12.470848"), 0.064343),
        ("BTC/USD", _utc("2026-08-20 14:25:16.473568"), 0.103051),
        ("BTC/USD", _utc("2026-08-21 00:05:12.631110"), 0.080234),
    ]
    trades = [
        ("ETH/USD", _utc("2026-08-19 19:20:31.658273"), 1.108751),   # PARTIAL, 70%
        ("BTC/USD", _utc("2026-08-20 03:20:12.466177"), 0.064343),   # WHOLE
        ("BTC/USD", _utc("2026-08-20 14:25:16.469269"), 0.103051),   # WHOLE
        ("BTC/USD", _utc("2026-08-21 00:05:12.626072"), 0.056164),   # PARTIAL, 70%
    ]
    per_entry = [
        outstanding_remainder_by_symbol([e], [t for t in trades if t[0] == e[0]])[e[0]]
        for e in entries
    ]
    assert per_entry == [True, False, False, True], per_entry
    assert sum(per_entry) == 2 and per_entry.count(False) == 2, (
        "2 of 2 both ways. A term true of every member of the population — which is what "
        "the no-target term was — cannot separate any subset of it."
    )


# ======================================================================================
# ARM B — the floor must be LOAD-BEARING IN BOTH DIRECTIONS
# ======================================================================================


def test_armB_the_floor_sits_below_the_SMALLER_live_age_not_merely_below_the_larger():
    """A floor above BTC's 66.20 h would fire on ETH only and still read as working.

    So the arm is keyed on the SMALLER of the two live ages. As shipped the floor is
    3 bars = 15 minutes, which is 264x below it.
    """
    smaller_age_bars = min(PRODUCTION_AGE_HOURS.values()) * 3600.0 / BAR_SECONDS
    assert ORDER_PATH_BLOCKED_BARS_FLOOR < smaller_age_bars, (
        f"floor {ORDER_PATH_BLOCKED_BARS_FLOOR} must sit below the SMALLER live age "
        f"({smaller_age_bars:.0f} bars), or it fires on one symbol and looks like it works"
    )
    for symbol in PRODUCTION_LAST_DECISION:
        assert _production_state(symbol)["withdrawn_from_trading"] is True


def test_armB_raising_the_floor_above_the_incident_turns_ARM_1_GREEN():
    """**This is what proves the ENGINEERING/ARBITRARY label is doing work.**

    A constant nothing depends on can be labelled anything. Push the floor past 94.94 h
    and the production alarm goes silent — which is exactly the tuning the plan forbids,
    demonstrated here so that forbidding it is not merely a sentence.
    """
    above_the_incident = max(PRODUCTION_AGE_HOURS.values()) * 3600.0 / BAR_SECONDS + 1.0
    original = dh.ORDER_PATH_BLOCKED_BARS_FLOOR
    try:
        dh.ORDER_PATH_BLOCKED_BARS_FLOOR = above_the_incident
        silenced = [
            s for s in PRODUCTION_LAST_DECISION
            if not _production_state(s)["withdrawn_from_trading"]
        ]
        assert sorted(silenced) == sorted(PRODUCTION_LAST_DECISION), (
            "raising the floor past the incident must silence BOTH symbols; if it does "
            "not, the floor is not the term deciding ARM 1 and the label is decoration"
        )
    finally:
        dh.ORDER_PATH_BLOCKED_BARS_FLOOR = original

    assert dh.ORDER_PATH_BLOCKED_BARS_FLOOR == original
    assert _production_state("BTC/USD")["withdrawn_from_trading"] is True


def test_armB_the_floor_is_DECLARED_engineering_and_arbitrary_at_the_constant():
    """`B46` happened because a tunable number was not flagged as tunable."""
    src = inspect.getsource(dh)
    marker = src.split("ORDER_PATH_BLOCKED_BARS_FLOOR")[0]
    declaration = marker[marker.rindex("#: **[ENGINEERING]"):]
    assert "Calibrated against ONE observation" in declaration
    assert "no longer the term\n#: carrying the separation" in declaration, (
        "B216's remedy: the constant must say it is NOT carrying the separation, because "
        "the first version put the label and the load in different places"
    )
    assert "2026-08-19 13:17:01" in declaration, (
        "the observation the number is answerable to must be NAMED, or it is invented again"
    )


# ======================================================================================
# MUST NOT FIRE — the hard half
# ======================================================================================


def test_arm3_a_position_WITH_a_target_does_not_fire_however_long_it_is_held():
    """Legitimate. It can still close on a win, so the symbol is waiting, not withdrawn."""
    state = order_path_symbol_state(
        symbol="BTC/USD",
        last_decision_at=PRODUCTION_NOW - timedelta(days=30),
        now=PRODUCTION_NOW,
        bar_seconds=BAR_SECONDS,
        blocked_reason=BLOCKED_BY_POSITION,
        remainder_outstanding=False,
    )
    assert state["withdrawn_from_trading"] is False
    assert "nothing is outstanding" in state["verdict_reason"]


def test_arm4_a_freshly_entered_symbol_inside_the_floor_does_not_fire():
    """The gap between the entry bar and the 70% fill is not a withdrawal."""
    state = order_path_symbol_state(
        symbol="BTC/USD",
        last_decision_at=PRODUCTION_NOW - timedelta(seconds=BAR_SECONDS),
        now=PRODUCTION_NOW,
        bar_seconds=BAR_SECONDS,
        blocked_reason=BLOCKED_BY_POSITION,
        remainder_outstanding=True,
    )
    assert state["withdrawn_from_trading"] is False
    assert "floor" in state["verdict_reason"]


@pytest.mark.parametrize(
    "reason",
    ["engine paused", "KILL SWITCH ARMED (manual)", "max concurrent 3 reached", None],
)
def test_arm5_arm6_any_OTHER_block_reason_does_not_fire(reason):
    """**Separability.** `wired`/`executes`/`RETAINED`/`RUNNING` were each insufficient
    alone and this adds a fifth, `TRADING`. A deliberate pause is not a withdrawal, and a
    stopped engine is `B178`'s signal — conflating them recreates the confusion.
    """
    state = order_path_symbol_state(
        symbol="BTC/USD",
        last_decision_at=PRODUCTION_LAST_DECISION["BTC/USD"],
        now=PRODUCTION_NOW,
        bar_seconds=BAR_SECONDS,
        blocked_reason=reason,
        remainder_outstanding=True,
    )
    assert state["withdrawn_from_trading"] is False
    assert "not blocked by a position" in state["verdict_reason"]


def test_the_tri_state_target_never_treats_ABSENCE_as_the_property():
    """`None` means no position was found to ask — NOT "it has no target" (`B161`)."""
    state = order_path_symbol_state(
        symbol="BTC/USD",
        last_decision_at=PRODUCTION_LAST_DECISION["BTC/USD"],
        now=PRODUCTION_NOW,
        bar_seconds=BAR_SECONDS,
        blocked_reason=BLOCKED_BY_POSITION,
        remainder_outstanding=None,
    )
    assert state["withdrawn_from_trading"] is False
    assert "no entry found" in state["verdict_reason"]


# ======================================================================================
# ARM C / ARM D — the instant is a parameter; exactly one site decides "has a target"
# ======================================================================================


def test_armC_the_predicate_takes_its_evaluation_instant_AS_A_PARAMETER():
    """If it read a clock internally, ARM 7 could not be run at all and any green it
    reported would come from a different computation than ARM 1."""
    params = inspect.signature(order_path_symbol_state).parameters
    assert "now" in params, "the evaluation instant must be a parameter"

    src = inspect.getsource(order_path_symbol_state)
    tree = ast.parse(src.lstrip())
    # ASK POSITIVELY. The first version of this arm tested `"now" in unparse(func)`, which
    # fires on `(now - last_decision_at).total_seconds()` — the PARAMETER's own name. That
    # is B161's class inside the guard written to prove B161 was avoided. Name the clocks.
    clocks = [
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("now", "utcnow", "today", "time", "monotonic")
    ]
    assert not clocks, f"the pure predicate reads a clock of its own: {clocks}"


def test_armD_exactly_one_site_decides_whether_an_entry_has_an_outstanding_remainder():
    """Two sites is `GATE-011`'s defect even when the second one is correct.

    The question this arm guards CHANGED with `B216`: it was "has a target" and is now "has
    an outstanding remainder". The rule behind ARM D is unchanged — exactly one site — and
    the guard is keyed on the comparison rather than on a name, so a second inline
    `closed < sized` cannot slip past it.
    """
    assert entry_has_outstanding_remainder(1.583930, 1.108751) is True
    assert entry_has_outstanding_remainder(0.064343, 0.064343) is False

    tree = ast.parse(inspect.getsource(dh))
    sites = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, ast.Lt) for op in node.ops)
        and "closed" in ast.unparse(node)
    ]
    assert len(sites) == 1, f"'closed_lots < sized_units' appears at {sites}; one is allowed"


def test_armD_the_SUM_matters_not_the_existence_of_a_partial_row():
    """**The case that nearly fooled the Manager, pinned as an arm.**

    `ETH 2026-08-19 13:17:01` closed in TWO tranches — 2.298500 then 0.985072 — summing to
    3.283572, which is its `sized_units` EXACTLY. *A partial that is later completed is not
    a withdrawal*, and a predicate keyed on "a partial row exists" would call it one.
    """
    opened = _utc("2026-08-19 13:17:01.966535")
    result = outstanding_remainder_by_symbol(
        entries=[("ETH/USD", opened, 3.283572)],
        trades=[
            ("ETH/USD", opened + timedelta(milliseconds=4), 2.298500),
            ("ETH/USD", opened + timedelta(milliseconds=4), 0.985072),
        ],
    )
    assert result["ETH/USD"] is False, "two tranches summing to the whole is NOT a remainder"


def test_armD_a_symbol_with_no_entry_at_all_is_NONE_and_never_False():
    """Absence of an entry is not evidence of no remainder — `B161`'s class."""
    assert outstanding_remainder_by_symbol(entries=[], trades=[]) == {}


def test_the_feedback_helper_is_NOT_reachable_as_a_has_target_test():
    """**`B214`, measured rather than argued, and kept although the term changed.**

    ARM D originally named `feedback._expected_r_from_geometry` as the existing single site.
    It cannot serve: its `None` merges "no target" with "target present, degenerate risk
    leg". Recorded because the reuse that looks like good hygiene would have made the signal
    fire on a trade that can still close on a win.
    """
    from app.services.evaluation.feedback import _expected_r_from_geometry as expected_r

    assert expected_r(100.0, 95.0, 110.0) == 2.0
    assert expected_r(100.0, 95.0, None) is None
    assert expected_r(100.0, 100.0, 110.0) is None


# ======================================================================================
# THE LINE TO HOLD — a timer must not come back as a second condition
# ======================================================================================


def test_no_standalone_staleness_timer_was_added_as_a_second_condition():
    """A timer makes the control pair pass for free and converts the doctrinal signal back
    into the clock the plan discarded. The bar-count floor is the ONLY temporal term, and
    it is a floor (a suppressor) rather than a trigger — so an age alone can never fire.
    """
    state = order_path_symbol_state(
        symbol="BTC/USD",
        last_decision_at=PRODUCTION_NOW - timedelta(days=365),
        now=PRODUCTION_NOW,
        bar_seconds=BAR_SECONDS,
        blocked_reason=None,
        remainder_outstanding=None,
    )
    assert state["withdrawn_from_trading"] is False, (
        "a year of silence with no doctrinal block fired the signal — a timer has come "
        "back as a trigger, and ARM 7 now passes for free"
    )


# ======================================================================================
# THE ASYNC GATHERER — the pure predicate above is only half. These arms exercise
# `order_path_health` itself: the walk, the gate call, and the wiring into `data_health`.
# ======================================================================================


class _FakePosition:
    def __init__(self, pair: str, tp: float | None) -> None:
        self.pair, self.tp = pair, tp


class _FakeBroker:
    def __init__(self, positions) -> None:
        self._positions = positions

    async def get_positions(self):
        return list(self._positions)


class _FakeLoop:
    """Stands in for `LiveCryptoLoop`. **It does not RE-IMPLEMENT the gate** — it records
    that the gate was ASKED and returns a canned answer, which is the whole point: the
    monitor must never carry a second copy of `_entry_block_reason`."""

    def __init__(self, *, symbols, positions, block_reason) -> None:
        self.symbols = symbols
        self.paper = _FakeBroker(positions)
        self._block_reason = block_reason
        self.asked: list[str] = []

    async def _entry_block_reason(self, pair: str):
        self.asked.append(pair)
        return self._block_reason


@pytest.fixture
async def bound(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


async def _seed(
    maker, *, ended: bool, decision_minutes_ago: float | None, closed_fraction: float = 0.70
):
    """Seed a run, a last decision, and an ENTRY closed to `closed_fraction`.

    `0.70` reproduces `EXIT-001`'s tranche: the 70% partial banked, the 30% runner riding.
    `1.0` is the whole close that FREES the symbol, which is the must-not-fire case.
    """
    from decimal import Decimal

    from app.db.enums import DirectionType, OutcomeType, TradeStatus
    from app.models.decision_record import DecisionRecord
    from app.models.engine_run import EngineRun
    from app.models.trade import Trade

    now = datetime.now(tz=timezone.utc)
    run = EngineRun(started_at=now - timedelta(days=1))
    if ended:
        run.ended_at = now - timedelta(minutes=1)
    opened = now - timedelta(hours=12)
    units = Decimal("0.080234")
    async with maker() as db:
        db.add(run)
        await db.commit()
        await db.refresh(run)
        if decision_minutes_ago is not None:
            db.add(
                DecisionRecord(
                    created_at=now - timedelta(minutes=decision_minutes_ago),
                    symbol="BTC/USD", timeframe="5m",
                    inputs_hash="x", code_path_hash="y", run_id=run.id,
                )
            )
            db.add(
                DecisionRecord(
                    created_at=opened, symbol="BTC/USD", timeframe="5m",
                    inputs_hash="e", code_path_hash="y", run_id=run.id, sized_units=units,
                )
            )
            db.add(
                Trade(
                    user_id=None, broker_id="paper-1", broker="paper", pair="BTC/USD",
                    direction=DirectionType.LONG, entry_price=Decimal("73098.01"),
                    lot_size=units * Decimal(str(closed_fraction)),
                    entry_time=opened + timedelta(milliseconds=5),
                    exit_time=opened + timedelta(hours=1),
                    outcome=OutcomeType.WIN, status=TradeStatus.CLOSED, run_id=run.id,
                )
            )
            await db.commit()
    return run


@pytest.mark.asyncio
async def test_armE_a_STOPPED_engine_still_reports_a_withdrawn_symbol_separately_labelled(
    bound,
):
    """**ARM E — separability from `B178`, by construction.**

    `wired` / `executes` / `RETAINED` / `RUNNING` were each insufficient alone and this adds
    a fifth, `TRADING`. If the signal cannot fire while the engine is stopped it has been
    made a SUB-CONDITION of `RUNNING` rather than a predicate of its own.

    *So the row that matters is exactly this one: stopped AND still blocked by a target-less
    runner. Both facts must be present and separately labelled, because a reader must never
    have to infer either from the other.*
    """
    await _seed(bound, ended=True, decision_minutes_ago=600.0)
    loop = _FakeLoop(
        symbols=["BTC/USD"],
        positions=[_FakePosition("BTC/USD", None)],
        block_reason=BLOCKED_BY_POSITION,
    )

    health = await dh.order_path_health(loop)

    assert health["engine_running"] is False, "B178's fact"
    assert health["withdrawn_symbols"] == ["BTC/USD"], "this signal's fact"
    assert health["status"] == "withdrawn"
    assert health["symbols"][0]["withdrawn_from_trading"] is True


@pytest.mark.asyncio
async def test_the_gate_is_ASKED_never_restated(bound):
    """A second copy of `_entry_block_reason` in a monitoring module would be the copy that
    drifts — `GATE-011`'s defect. The monitor must CALL the gate, once per symbol."""
    await _seed(bound, ended=False, decision_minutes_ago=600.0)
    loop = _FakeLoop(
        symbols=["BTC/USD", "ETH/USD"],
        positions=[_FakePosition("BTC/USD", None)],
        block_reason=BLOCKED_BY_POSITION,
    )

    await dh.order_path_health(loop)

    assert sorted(loop.asked) == ["BTC/USD", "ETH/USD"], (
        f"the gate must be asked once per symbol; it was asked for {loop.asked}"
    )


@pytest.mark.asyncio
async def test_a_missing_loop_is_UNAVAILABLE_and_never_quietly_healthy(bound):
    """This module's rule: a component we cannot see is not `ok`. Without the loop the gate
    cannot be asked, and inferring the block reason from positions would be the second
    doctrine this task exists to avoid."""
    await _seed(bound, ended=False, decision_minutes_ago=600.0)

    health = await dh.order_path_health(None)

    assert health["status"] == "unavailable"
    assert health["watching"] is False
    assert "gate cannot be asked" in health["reason"]


@pytest.mark.asyncio
async def test_armA_a_withdrawn_order_path_turns_the_PRODUCTION_ok_FLAG_FALSE(
    bound, monkeypatch, tmp_path
):
    """**ARM A, and it is why the commit body has to say so.**

    `data_health()` builds `problems` from any component whose status is not `healthy` and
    returns `ok = not problems`; `system.py` serves that dict and `DataHealthPanel.tsx`
    branches on `health.ok`. So this component turns a production-visible boolean FALSE.

    **It SHOULD go red** — a dashboard reading `ok` while the order path has been frozen for
    94 hours IS `B199` itself. What would not be defensible is landing it silently.
    """
    async def _healthy(*a, **k):
        return {"status": "healthy", "watching": True}

    monkeypatch.setattr(dh, "shadow_health", _healthy)
    monkeypatch.setattr(dh, "panel_health", _healthy)
    monkeypatch.setattr(dh, "DOMINANCE_DIR", tmp_path / "dom")
    monkeypatch.setattr(dh, "BACKUP_DIR", tmp_path / "bak")

    await _seed(bound, ended=False, decision_minutes_ago=600.0)
    loop = _FakeLoop(
        symbols=["BTC/USD"],
        positions=[_FakePosition("BTC/USD", None)],
        block_reason=BLOCKED_BY_POSITION,
    )

    result = await dh.data_health(loop=loop)

    assert "order_path" in result, "the component must be listed, not folded into shadow"
    assert result["order_path"]["status"] == "withdrawn"
    assert "order_path" in result["problems"]
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_the_order_path_component_is_BESIDE_the_shadow_not_inside_it(bound):
    """The two corpora have different legitimate-silence rules and one predicate cannot
    carry both — merging them is `GATE-011`'s defect.

    **CHECKED STRUCTURALLY, NOT BY SUBSTRING (`T-0068`).** This asserted
    `"order_path" not in shadow_src` and fired on a COMMENT in `shadow_health` citing
    `order_path_health`'s *"the VALUES, not a colour"* rule by name. **A citation is not a
    merge, and a substring cannot tell them apart** — `B245`'s class inverted: there, prose
    survived an identifier check; here, prose TRIPPED one.

    *The property is that `shadow_health` does not CALL the order-path check or read its
    inputs — so that is what is asserted, and the prose is free to explain itself.*
    """
    import inspect as _inspect

    shadow_src = _inspect.getsource(dh.shadow_health)
    tree = ast.parse(shadow_src.lstrip())

    calls = [
        ast.unparse(n.func) for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and any(t in ast.unparse(n.func) for t in ("order_path", "_entry_block_reason"))
    ]
    assert not calls, f"shadow_health calls the order-path check: {calls}"

    names = [
        n.attr for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr == "_entry_block_reason"
    ]
    assert not names, "shadow_health reaches the entry gate"
    assert "setup_evaluation" in shadow_src, "the shadow still watches the SHADOW corpus"


def test_the_block_reason_string_is_pinned_to_the_GATES_OWN_WORDS():
    """`B167`'s vocabulary collision, pre-empted. This monitor is keyed on a string the gate
    produces, so if the gate is reworded the monitor silently stops being able to fire.

    Read from `crypto_loop`'s source by AST rather than by text, so a mention in a docstring
    cannot satisfy it — the constant must appear as a RETURNED value.
    """
    from app.services.live import crypto_loop

    tree = ast.parse(
        inspect.getsource(crypto_loop.LiveCryptoLoop._entry_block_reason).lstrip()
    )
    returned = {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    assert BLOCKED_BY_POSITION in returned, (
        f"the gate no longer returns {BLOCKED_BY_POSITION!r} — it returns {returned}. "
        "The monitor is keyed on that string and has silently stopped being able to fire."
    )


@pytest.mark.asyncio
async def test_a_WHOLE_close_frees_the_symbol_and_does_not_fire_end_to_end(bound):
    """**The structural must-miss, through the real gatherer rather than the pure term.**

    Identical to the firing case in every respect except one: the entry closed WHOLE. The
    symbol is still blocked at this instant and the decision corpus is still ten hours
    stale, so an age-based signal would fire here. The structural one does not.
    """
    await _seed(bound, ended=False, decision_minutes_ago=600.0, closed_fraction=1.0)
    loop = _FakeLoop(
        symbols=["BTC/USD"],
        positions=[],
        block_reason=BLOCKED_BY_POSITION,
    )

    health = await dh.order_path_health(loop)

    assert health["status"] == "healthy"
    assert health["withdrawn_symbols"] == []
    assert health["symbols"][0]["remainder_outstanding"] is False
    assert health["symbols"][0]["bars_blocked"] > ORDER_PATH_BLOCKED_BARS_FLOOR, (
        "the must-miss is only meaningful if the AGE would otherwise have fired"
    )


# ======================================================================================
# EVERY TERM MUST BE SHOWN TO CARRY LOAD, OR IT IS DECORATION
#
# `B216` generalised. A term nobody can demonstrate the effect of is the next arbitrary
# constant waiting to be found — so each one is removed here and the count is measured.
# ======================================================================================

ENTRY_CORPUS_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "t0057_entry_corpus.txt"
)
CURRENT_RUN = "a32c3b98"


def _corpus():
    rows = []
    for line in ENTRY_CORPUS_FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        symbol, when, sized, closed, ntrades, run = line.split("|")
        rows.append(
            {"symbol": symbol, "when": when, "sized": float(sized),
             "closed": float(closed), "ntrades": int(ntrades), "run": run}
        )
    assert len(rows) == 33, f"the corpus fixture drifted to {len(rows)} rows"
    return rows


def test_the_shipped_term_gives_EXACTLY_the_two_blockers_over_the_whole_corpus():
    """No scope term applied. `0 < closed < sized` is self-sufficient on today's data."""
    hits = [r for r in _corpus() if entry_has_outstanding_remainder(r["sized"], r["closed"])]
    assert len(hits) == 2, [(h["symbol"], h["when"]) for h in hits]
    assert {h["symbol"] for h in hits} == {"BTC/USD", "ETH/USD"}
    assert all(h["run"] == CURRENT_RUN for h in hits)
    assert all(h["closed"] / h["sized"] == pytest.approx(0.70, abs=1e-5) for h in hits), (
        "both are EXIT-001's 70% tranche — 0.700000 and 0.700002 — which is the mechanism"
    )


def test_removing_the_GREATER_THAN_ZERO_term_moves_the_count_from_2_to_7():
    """**The `> 0` term carries load, demonstrated by removing it.**

    Without it the predicate is `closed < sized`, which admits five trade-less rows
    (`B220`) and any position still wholly open — a freshly-entered symbol on ordinary
    trading. Neither is a remainder.
    """
    without = [r for r in _corpus() if r["closed"] < r["sized"]]
    with_term = [r for r in _corpus() if entry_has_outstanding_remainder(r["sized"], r["closed"])]

    assert len(without) == 7 and len(with_term) == 2, (len(without), len(with_term))
    admitted = [r for r in without if r not in with_term]
    assert all(r["ntrades"] == 0 for r in admitted), (
        "the five extra positives must all be entries with NO trade rows at all"
    )
    assert all(r["run"] != CURRENT_RUN for r in admitted)


def test_removing_the_RUN_SCOPE_changes_nothing_TODAY_and_still_carries_load():
    """**The run scope is a SECOND, INDEPENDENT guard — for a failure the corpus lacks.**

    On today's data it changes nothing, which is exactly why it has to be demonstrated on
    the case it exists for: a partial remainder STRANDED BY A KILLED RUN satisfies
    `0 < closed < sized` forever and would fire on a symbol the current engine has never
    touched. Synthetic, because the corpus contains no such row — stated plainly rather
    than dressed up as a measurement.
    """
    corpus = _corpus()
    unscoped = [r for r in corpus if entry_has_outstanding_remainder(r["sized"], r["closed"])]
    scoped = [r for r in unscoped if r["run"] == CURRENT_RUN]
    assert len(unscoped) == len(scoped) == 2, "on TODAY's corpus the scope is inert"

    stranded = {"symbol": "ETH/USD", "when": "2026-08-09 19:00:07", "sized": 4.875120,
                "closed": 3.412584, "ntrades": 1, "run": "c2b78a47"}
    widened = [
        r for r in corpus + [stranded]
        if entry_has_outstanding_remainder(r["sized"], r["closed"])
    ]
    assert len(widened) == 3, "the stranded partial must satisfy the term"
    assert len([r for r in widened if r["run"] == CURRENT_RUN]) == 2, (
        "and the run scope must be what excludes it — 3 unscoped, 2 scoped"
    )


def test_B227_the_SUM_form_is_PROVISIONAL_and_the_module_says_so():
    """**`B227`. A float comparison across three roundings that do not commute.**

    A fully SETTLED two-tranche trade can read as a remainder — in the direction that says
    the symbol is still blocked. NOT patched with an epsilon: a tolerance must exceed 1e-6
    and would then be blind to a genuine remainder smaller than that, and choosing its size
    is `B93`'s tuned threshold.

    *n for the two-tranche case is ONE. The corpus has 26 rows with `closed == sized` and
    25 are whole closes, exact by construction — so the discriminator was validated against
    the only row that could have tested it.*
    """
    doc = inspect.getdoc(entry_has_outstanding_remainder)
    assert "PROVISIONAL PENDING" in doc and "B227" in doc and "B218" in doc
    assert "NOT patched with an epsilon" in doc

    corpus = _corpus()
    exact = [r for r in corpus if r["closed"] == r["sized"]]
    two_tranche_completed = [r for r in exact if r["ntrades"] > 1]
    assert len(two_tranche_completed) <= 1, (
        f"n for the completed multi-tranche case was 1 when B227 was written; it is now "
        f"{len(two_tranche_completed)}. More rows means the rate can finally be measured — "
        "re-open B227 rather than reading this test's silence as reassurance."
    )


# ======================================================================================
# T-0080 / `B265` — THE `idle` BRANCH HAD NO PRODUCER ARM
#
# The only arm calling this producer directly asserted the OTHER branch — `unavailable` —
# which the ruling treats as a problem. **So the branch Malek's ruling is entirely about was
# the branch with no coverage.** `idle`-versus-`unavailable` IS the ruling.
#
# Measured by Review at the producer: `else "idle"` -> `else "healthy"` makes A STOPPED
# ENGINE REPORT ITSELF HEALTHY and 128 tests pass. Nothing noticed.
#
# **THE TRAP, and it is why this arm seeds a row rather than a stub.** `engine_running` is
# NOT read from the loop. Inside `order_path_health` the loop is touched in exactly two
# places — `getattr(loop, "symbols", ...)` and `loop._entry_block_reason(s)`. `engine_running`
# comes from a DATABASE query: an `EngineRun` with `ended_at IS NULL` means running, its
# absence means stopped. **A stub loop carrying `running = False` changes nothing**, and the
# arm would pass for a reason unrelated to what it claims.
# *The loop makes the gate ASKABLE; the DB decides RUNNING.*
# ======================================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["a run that ENDED", "no run has ever existed"],
)
async def test_t0080_a_STOPPED_engine_makes_the_PRODUCER_report_idle(bound, scenario):
    """**The producer arm.** Reaches the branch through `order_path_health` with a loop that
    EXISTS and is NOT RUNNING — a different input from `order_path_health(None)`, which is
    already covered and returns `unavailable`. *Confusing those two is how this branch went
    uncovered in the first place.*

    Both parametrisations produce `idle` and they are **different scenarios taking different
    paths**: an ended run gives `started` a real value; an empty table leaves it `None` and
    exercises the `active is None` fallback. The ruling's scenario is **an engine that RAN and
    was STOPPED**, so that one is first and the empty table is an addition, not a substitute.
    """
    if scenario == "a run that ENDED":
        # closed_fraction 1.0 — a WHOLE close, so no remainder is outstanding and the symbol
        # is not withdrawn. `withdrawn` would win the status expression over `engine_running`,
        # and this arm is about the engine, not the runner.
        await _seed(bound, ended=True, decision_minutes_ago=600.0, closed_fraction=1.0)

    loop = _FakeLoop(
        symbols=["BTC/USD"], positions=[], block_reason=None,
    )
    health = await dh.order_path_health(loop)

    assert health["status"] == "idle", (
        f"a stopped engine reported {health['status']!r}. If this says 'healthy', the branch "
        "that carries Malek's ruling has been inverted and the flag now says the platform is "
        "fine while nothing is running."
    )
    assert health["engine_running"] is False
    assert health["withdrawn_symbols"] == [], "the engine is the subject here, not a runner"

    # `B266`. The docstring said `watching: False` and the CODE is right: `watching` answers
    # COULD THIS CHECK LOOK, not IS THE ENGINE LIVE. Every `watching: False` in the module is
    # an `unavailable` return. An arm written from the old sentence would have failed and
    # invited the next seat to "fix" the production line.
    assert health["watching"] is True, (
        "a stopped engine is one this check CAN see — it was watching, and it reported a "
        "per-symbol verdict while stopped (ARM E)"
    )


@pytest.mark.asyncio
async def test_t0080_idle_and_unavailable_are_DIFFERENT_INPUTS_to_the_same_producer(bound):
    """The pair, because the ruling is precisely the difference between them.

    `idle` — the engine is stopped, and that is not a problem.
    `unavailable` — we cannot ASK the gate, and that IS a problem.

    Asserting either alone leaves the other free to collapse into it, which is `B215`'s
    could-not-ask versus asked-and-fine, one predicate over.
    """
    await _seed(bound, ended=True, decision_minutes_ago=600.0, closed_fraction=1.0)

    stopped = await dh.order_path_health(
        _FakeLoop(symbols=["BTC/USD"], positions=[], block_reason=None)
    )
    cannot_ask = await dh.order_path_health(None)

    # `B272`/`T-0086`. The last assertion here USED TO BE `stopped != cannot_ask`, and it
    # could not fail: it fires only if the two are EQUAL, and the line above pins them to two
    # DIFFERENT literals — so if they were ever equal, that line had already failed. The guard
    # was not lost; **the DIAGNOSIS was**, because the sentence explaining `B215` sat on the
    # dead assertion and never printed.
    #
    # Split so each state names its own failure, and the `B215` sentence moved onto an
    # assertion that CAN fire — option (a): a property over inputs the literals do not pin.
    assert stopped["status"] == "idle", (
        "a stopped engine must report `idle` — the state Malek's ruling allow-lists"
    )
    assert cannot_ask["status"] == "unavailable", (
        "a missing loop means the gate cannot be ASKED, which is a problem and not an absence "
        "of news — collapsing it into `idle` is `B215` at the level of this component"
    )
    assert stopped["watching"] is True, "a stopped engine is one this check CAN see"
    assert cannot_ask["watching"] is False, "and a missing loop is one it cannot"

    # THE PROPERTY THE OLD SENTENCE NAMED, over inputs the literals above do not pin: one of
    # these states is ALLOW-LISTED by the ruling and the other is a PROBLEM. That can break
    # while both literals stay correct — admit `unavailable` to `OK_STATUSES` and the two
    # statuses are still `idle` and `unavailable`, so the pins above pass and this fires.
    assert stopped["status"] in dh.OK_STATUSES, (
        f"{stopped['status']!r} left the allow-list — a stopped engine is not broken"
    )
    assert cannot_ask["status"] not in dh.OK_STATUSES, (
        f"{cannot_ask['status']!r} joined the allow-list. A component we cannot SEE would read "
        "as one that is fine — `B215`'s could-not-ask versus asked-and-fine, and it would make "
        "the ok flag unreadable either way"
    )
