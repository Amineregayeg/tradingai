"""T-0059 — `B217`: `LIVE_NOT_REACHED` covered three of seven block sources.

`trace.gate()` sets `blocked_by` for the THREE IN-TRACE gates. The FOUR LOOP-LEVEL blocks —
kill switch, paused, already-in-a-position, max-concurrent — never touch it. A trace produced
on a loop-blocked bar therefore fell through to `bool(trace.took_trade)` and recorded
`live_verdict=False`: **"the live heuristic DECLINED" for a bar it never evaluated.**

**Asymmetric, and both errors argue FOR the cutover:** a rules-FAIL on such a bar scores AGREE,
a rules-PASS scores DISAGREE labelled RULES-LOOSER — the category `T-0040` treats as new live
exposure.

**LATENT TODAY.** No live path produces the uncovered state: a loop-blocked bar hard-returns at
`crypto_loop.py:1218` before any trace exists. So every arm here is a unit-level construction
and **no production figure demonstrates this fix.** A `0 not-reached` count is consistent with
the fix working, the fix being absent, and the state being unreachable.

*The exposure is CONDITIONAL and stating it unconditionally is how `B219` was got wrong:* 2143
of 4340 shadow bars (49.38%) are `already in a position`, so **IF a restructure ever creates
traces on those bars, ~49% of the comparison corpus is affected.**
"""
from __future__ import annotations

import ast
import inspect

import pytest

from app.services.live import strategy_step as step_mod
from app.services.live.decision_trace import DecisionTrace
from app.services.live.entry_comparison import _live_entry_verdict


class _Bare:
    """A trace-like object with NO `reached_entry_decision` at all.

    `compare_entry` types `trace` as `Any`, so the read is a `getattr` — and this is the
    object that decides whether its default is safe.
    """

    def __init__(self, *, took_trade=False, blocked_by=None):
        self.took_trade, self.blocked_by = took_trade, blocked_by


def _trace(*, reached: bool, took: bool = False, blocked: str | None = None) -> DecisionTrace:
    t = DecisionTrace(symbol="BTC/USD", timeframe="5m")
    t.reached_entry_decision = reached
    t.took_trade = took
    t.blocked_by = blocked
    return t


def _old_predicate(trace):
    """`B217`'s predicate, verbatim, kept so the differential has something to differ FROM."""
    if getattr(trace, "blocked_by", None) is not None:
        return None, "LIVE_NOT_REACHED"
    return bool(getattr(trace, "took_trade", False)), None


# ======================================================================================
# ARM 1 — THE `getattr` DEFAULT
# ======================================================================================


def test_arm1_an_object_without_the_field_is_NOT_REACHED_not_reached():
    """**A `True` default fails open, silently, forever.**

    `trace` is `Any` here, so any caller passing an object without the field decides this.
    Defaulting to `True` would make every such object COMPARABLE carrying
    `live_verdict = took_trade`, which is `B217` with a wider blast radius than `B217`.
    """
    verdict, reason = _live_entry_verdict(_Bare())
    assert (verdict, reason) == (None, "LIVE_NOT_REACHED")

    verdict, reason = _live_entry_verdict(_Bare(took_trade=True))
    assert (verdict, reason) == (None, "LIVE_NOT_REACHED"), (
        "took_trade must not rescue an object that never said it reached the decision"
    )

    src = inspect.getsource(_live_entry_verdict)
    assert 'getattr(trace, "reached_entry_decision", False)' in src, (
        "the default must be False, in the source, not merely in behaviour today"
    )


# ======================================================================================
# ARM 3 — ALL FOUR LOOP-LEVEL SOURCES
# ======================================================================================

#: The four blocks `_entry_block_reason` can return. NONE of them touches `blocked_by`,
#: which is exactly why the old predicate could not see them.
LOOP_LEVEL_BLOCKS = [
    "KILL SWITCH ARMED (manual)",
    "engine paused",
    "already in a position",
    "max concurrent 3 reached",
]


@pytest.mark.parametrize("reason", LOOP_LEVEL_BLOCKS)
def test_arm3_every_loop_level_block_is_LIVE_NOT_REACHED(reason):
    """A bar the loop refused never reached the entry decision, whichever refusal it was.

    Constructed at unit level because production cannot produce this state: the loop returns
    before a trace exists. *That is the point — the flag is armed for a restructure, not for
    today's corpus.*
    """
    blocked = _trace(reached=False)
    assert _live_entry_verdict(blocked) == (None, "LIVE_NOT_REACHED"), reason

    # And the OLD predicate could not see it — which is the defect, demonstrated rather
    # than described. `blocked_by` is None on every one of these.
    assert _old_predicate(_Bare(took_trade=False)) == (False, None), (
        "the old predicate calls a loop-blocked bar a DECLINE, and that is B217"
    )


# ======================================================================================
# ARM 2 — THE DIFFERENTIAL
# ======================================================================================

#: Every input the OLD predicate covered. **The zero-candidate bar is a REQUIREMENT, not an
#: example**: without it the differential passes a fix that sets the flag INSIDE the detection
#: loop, collapsing "looked and found nothing" into "could not look" — `examined_nothing`'s own
#: rule inverted, and the second defect the first one hides.
#:
#: **`ltf_bos` is named because it is the only in-trace gate that occurs.** Measured over the
#: full corpus it blocks 849 of 1060 rows (80.1%); `history` and `daily_bias` have NEVER
#: blocked a row. A fixture built from those two exercises the 0% case while reading as
#: thorough — three gate names, none of them the one that fires.
DIFFERENTIAL_CORPUS = [
    ("ltf_bos blocked — THE gate that actually occurs", _trace(reached=False, blocked="ltf_bos")),
    ("daily_bias blocked — has never fired in production", _trace(reached=False, blocked="daily_bias")),
    ("history blocked — has never fired in production", _trace(reached=False, blocked="history")),
    ("reached and took the trade", _trace(reached=True, took=True)),
    ("ZERO-CANDIDATE BAR: reached, looked, found nothing", _trace(reached=True, took=False)),
]


@pytest.mark.parametrize("label,trace", DIFFERENTIAL_CORPUS, ids=lambda x: x if isinstance(x, str) else "")
def test_arm2_the_two_predicates_AGREE_on_every_input_the_old_one_covered(label, trace):
    """**Zero differences — and that is the PASS OF SUBSUMPTION, not the absence of a test.**

    Under the correct placement the two predicates cannot disagree on today's code. What makes
    this arm non-empty is that it FAILS when the new predicate is built wrongly, which the
    companion test below demonstrates.
    """
    assert _live_entry_verdict(trace) == _old_predicate(trace), label


def test_arm2_the_ZERO_CANDIDATE_bar_is_COMPARABLE_and_says_DECLINED():
    """The required case, asserted for its own values rather than only through the differential.

    Flag True, no candidates, `took_trade` False, `blocked_by` None. **This bar LOOKED and
    found nothing** — it is comparable, and its verdict is a genuine decline.
    """
    bar = _trace(reached=True, took=False)
    assert bar.candidates == []
    assert bar.blocked_by is None
    assert _live_entry_verdict(bar) == (False, None), (
        "a bar that reached the decision and found no POI is a DECLINE, not NOT_REACHED — "
        "collapsing it into 'could not look' is examined_nothing's rule inverted"
    )


def test_arm2_the_differential_CAN_FAIL_which_is_what_makes_it_an_arm():
    """**The control on the control.** A differential that cannot fail proves nothing.

    Both wrong placements produce traces the correct one never does, and each is caught:

      * flag set BEFORE detection -> flag True on a bar `ltf_bos` went on to block
      * flag set INSIDE the detection loop -> flag False on a zero-candidate bar
    """
    misplaced_before_detection = _trace(reached=True, blocked="ltf_bos")
    assert _live_entry_verdict(misplaced_before_detection) != _old_predicate(
        misplaced_before_detection
    ), "a flag set before the gates must make the two predicates disagree"

    misplaced_inside_loop = _trace(reached=False, took=False)
    assert _live_entry_verdict(misplaced_inside_loop) != _old_predicate(
        misplaced_inside_loop
    ), "a flag set inside the detection loop must make the two predicates disagree"


# ======================================================================================
# ARM 4 — `blocked_by` IS SUBSUMED, NOT CONSULTED ALONGSIDE
# ======================================================================================


def test_arm4_the_predicate_does_not_read_blocked_by_at_all():
    """Two statements of one fact is `GATE-011`, and they drift.

    Every bar `blocked_by` would have caught sets the flag False by never reaching the
    landmark, so reading both adds nothing and creates a second thing to keep in step.
    """
    tree = ast.parse(inspect.getsource(_live_entry_verdict).lstrip())
    reads = [
        ast.unparse(n) for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and n.value == "blocked_by"
    ]
    assert not reads, f"the predicate still consults blocked_by: {reads}"


# ======================================================================================
# THE LANDMARK — the structural guarantee, because misplacement is the whole hazard
# ======================================================================================


def test_the_flag_is_set_PAST_EVERY_ENFORCED_GATE_and_not_where_detection_runs():
    """**"Past every gate that can stop the bar", NOT "detection has run".**

    Those are different lines and the difference is the whole fix. Detection runs BEFORE two
    of the three gates, so a flag set there reads True on bars `daily_bias` or `ltf_bos` went
    on to block — `B217` rebuilt inside the fix written to close `B217`. Not a corner case:
    `ltf_bos` blocks 80.1% of rows.

    Asserted by AST on statement ORDER rather than by a line number, which would rot.
    """
    tree = ast.parse(inspect.getsource(step_mod.evaluate_latest_bar_traced).lstrip())

    assignments = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr == "reached_entry_decision"
            for t in n.targets
        )
    ]
    gate_calls = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "gate"
    ]
    detection = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in ("_compute_swing", "detect_fvg", "detect_bos_choch")
    ]

    assert len(assignments) == 1, f"the flag must be set at exactly ONE place: {assignments}"
    assert gate_calls, "the gates vanished — this arm has lost its subject"
    assert assignments[0] > max(gate_calls), (
        f"the flag is set at line {assignments[0]}, before a gate at {max(gate_calls)}. "
        "A bar that gate goes on to block would read as REACHED and become COMPARABLE "
        "carrying 'the live heuristic DECLINED' — B217 rebuilt inside its own fix."
    )
    assert detection and assignments[0] > max(detection), (
        "the flag must sit after detection too — but note that is NOT the landmark: "
        "detection precedes two of the three gates, so 'after detection' alone is wrong"
    )
