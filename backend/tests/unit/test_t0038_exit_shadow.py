"""T-0038 half 2 — the tranche plan is RECORDED on the order path and executed by nothing.

**And the first thing the shadow records is that there is never a runner.**
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.db.enums import DirectionType, OrderType
from app.services.backtest.engine import Params
from app.services.execution.service import Signal
from app.services.live.decision_trace import DecisionTrace
from app.services.live.exit_shadow import GATE_NAME, record_from_loop, record_on, tranche_plan
from app.services.rules.exit_001_v1_model import PARTIAL_AT_R, PARTIAL_FRACTION, RUNNER_FRACTION

BACKEND = Path(__file__).resolve().parents[2]


def _live_signal(side=DirectionType.LONG, entry=100.0, stop=95.0, *, tp=None):
    """A signal built EXACTLY as `strategy_step` builds one."""
    params = Params()
    risk = abs(entry - stop)
    sign = 1.0 if side == DirectionType.LONG else -1.0
    target = entry + sign * params.rr_partial * risk if tp is None else tp
    return Signal("BTC/USD", side, entry, stop, target, 0.01, OrderType.MARKET, approved=True)


# ---------------------------------------------------------------------------
# THE FINDING — every live signal is the degenerate case
# ---------------------------------------------------------------------------


def test_the_live_take_profit_sits_EXACTLY_on_the_2R_partial_level():
    """`strategy_step` sets `tp = entry + p.rr_partial * risk` and `Params.rr_partial` is
    `2.0`. `EXIT-001` takes its partial at `PARTIAL_AT_R`, which is also `2.0`.

    **So the ratified 30% runner cannot exist on the live path as configured** — the target IS
    the partial level. That is a fact about the engine's configuration, surfaced by the shadow
    rather than asserted about it.
    """
    assert Params().rr_partial == PARTIAL_AT_R == 2.0

    for side in (DirectionType.LONG, DirectionType.SHORT):
        stop = 95.0 if side == DirectionType.LONG else 105.0
        record = tranche_plan(_live_signal(side, 100.0, stop))
        assert record["planned"] is True
        assert record["runner_distance"] == 0.0, f"{side} has a runner — the config changed"
        assert record["degenerate_runner"] is True
        assert record["partial_level"] == record["final_target"]


def test_a_target_beyond_2r_does_produce_a_runner():
    """MUST-MISS on the finding above: the recorder is not simply reporting `degenerate` for
    everything. A 4R target gives a real runner, so the zero is a fact about the CONFIG."""
    record = tranche_plan(_live_signal(tp=120.0))  # 2R is 110.0

    assert record["degenerate_runner"] is False
    assert record["runner_distance"] == 10.0


# ---------------------------------------------------------------------------
# RECORDED, NOT EXECUTED
# ---------------------------------------------------------------------------


def test_the_shadow_executes_nothing():
    record = tranche_plan(_live_signal())
    assert record["executed"] is False

    # AST IDENTIFIERS, NOT TEXT — AND I HIT THIS THE OBVIOUS WAY FIRST. The text form failed
    # because the module's own docstring says "Nothing here calls `close_position`", so the
    # guard tripped on the sentence that exists to state the property it checks. Second time
    # this session (T-0039's GRADE-034 guard flagged its own module), which makes it a habit
    # rather than an accident: A GUARD OVER A PROHIBITION MUST READ CODE, because the file
    # that forbids a thing is the file most likely to name it.
    import ast

    tree = ast.parse((BACKEND / "app/services/live/exit_shadow.py").read_text(encoding="utf-8"))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } | {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "close_position" not in called, (
        "Stage A records and enforces nothing; a close call here would make it Stage B"
    )
    assert "observe" in called, "must-hit: the walk does see the calls this module makes"


def test_it_is_recorded_UNENFORCED_and_is_not_a_would_block():
    trace = DecisionTrace(symbol="BTC/USD", timeframe="5m")
    record_on(trace, _live_signal())

    assert trace.blocked_by is None
    assert GATE_NAME not in trace.would_block_by, (
        "a tranche plan is not a verdict about whether to trade — would_block_by is a "
        "different rule's numerator"
    )
    gate = next(g for g in trace.gates if g.name == GATE_NAME)
    assert gate.enforced is False


def test_the_shadow_runs_AFTER_the_decision_on_the_order_path():
    loop = (BACKEND / "app/services/live/crypto_loop.py").read_text(encoding="utf-8")
    assert "exit_shadow.record_from_loop(" in loop, "must-hit: the shadow is wired"
    assert loop.index("evaluate_latest_bar_traced(") < loop.index("exit_shadow.record_from_loop(")


def test_the_doctrine_constants_come_from_the_registry_and_are_republished_intact():
    record = tranche_plan(_live_signal())
    assert record["partial_at_r"] == PARTIAL_AT_R
    assert record["partial_fraction"] == PARTIAL_FRACTION
    assert record["runner_fraction"] == RUNNER_FRACTION
    assert record["partial_fraction"] + record["runner_fraction"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# WHERE NO PLAN CAN BE BUILT IT RECORDS WHY
# ---------------------------------------------------------------------------


def test_a_signal_with_no_take_profit_records_the_reason_rather_than_vanishing():
    """*No plan* and *nobody looked* must not share a representation."""
    record = tranche_plan(
        Signal("X", DirectionType.LONG, 100.0, 95.0, None, 0.01, OrderType.MARKET)
    )

    assert record["planned"] is False
    assert "take-profit" in record["reason"]
    assert "degenerate" not in record["reason"].lower(), (
        "a missing target is not a degenerate runner — different facts, different fixes"
    )


def test_a_target_INSIDE_the_2r_level_records_the_refusal_rather_than_swallowing_it():
    """Round 3 ruled the EQUALITY case. A target inside 2R is still refused by the model, and
    the shadow records that refusal instead of hiding it."""
    record = tranche_plan(_live_signal(tp=105.0))  # 2R is 110.0

    assert record["planned"] is False
    assert "inside the 2R level" in record["reason"]


def test_a_signal_missing_entry_or_stop_records_why():
    record = tranche_plan(object())
    assert record["planned"] is False and "entry/stop/direction" in record["reason"]


# ---------------------------------------------------------------------------
# FAILURE ISOLATION
# ---------------------------------------------------------------------------


def test_a_raising_shadow_cannot_reach_the_trading_loop():
    """**A shadow that can crash the trading loop is worse than no shadow.** The decision has
    already been made by the time this runs and must not be disturbed by an observer."""

    class _Explodes:
        def observe(self, *a, **k):
            raise RuntimeError("boom")

    assert record_from_loop(_Explodes(), _live_signal()) is None


# ---------------------------------------------------------------------------
# THE 1.5R ADVICE IS MARKED, NOT CHANGED AND NOT DELETED
# ---------------------------------------------------------------------------


def test_the_1_5r_advice_is_still_there_and_is_marked_as_contradicting_doctrine():
    """Not changed: moving `1.5 -> 2.0` would make it AGREE with EXIT-001 while remaining a
    SECOND statement of it — `GATE-011`'s defect with a corrected constant, which is harder to
    notice than a disagreement. Not deleted: the three legs at step 9."""
    engine = (BACKEND / "app/services/decision/engine.py").read_text(encoding="utf-8")

    assert "r_multiple >= 1.5" in engine, "must-hit: the branch is still there"
    assert "CONTRADICTS RATIFIED DOCTRINE" in engine
    assert "Nothing executes it" in engine, "the severity must be stated, not left to a reader"
    assert "generate_risk_warning" in engine, "the deletion legs must stay recorded"
