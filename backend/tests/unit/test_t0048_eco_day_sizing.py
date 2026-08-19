"""T-0048 — GATE-016 ruling (b): a red-folder day sizes ONE RUNG DOWN the disturbance axis.

**The ruling introduces no new number.** Every cell Salim named is already in `RISK_MATRIX` one rung
along — Manipulated/NONE 1.50% → 0.75% IS Manipulated/LIGHT, and every LIGHT cell steps to HEAVY,
which is already `0.0`. So the arm is a DERIVATION and not a table: *a nine-value fixture would
restate numbers the repo already holds twice and become the THIRD copy, drifting toward whichever
one is edited next* (`B93`).

## THIS CANNOT AFFECT A TRADE, FOR TWO INDEPENDENT REASONS

    B179   no Finnhub key -> is_red_folder_day is FALSE on every production bar
    B188   NOTHING ON THE ORDER PATH CALLS THE SIZER AT ALL — `RiskMatrix.size(` appears in
           exactly one file in this repository and it is a test file. Live trades are sized
           from `fixed.RISK_PCT`, one constant.

**Every arm below is a FIXTURE arm, and a `0 rung-downs applied` figure would be consistent with all
three of: no red-folder days, no calendar, and no sizer.** *Three causes, one null.*
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.services.rules.gate_032_risk_matrix import (
    BOX_GRADES, DISTURBANCE_GRADES, ECO_DAY_RISK_POLICY, ECO_DAY_SKIP_REASON, RISK_MATRIX,
    RiskMatrix, next_rung,
)


@pytest.mark.parametrize("box", BOX_GRADES)
@pytest.mark.parametrize("dist", DISTURBANCE_GRADES)
def test_the_red_folder_cell_IS_the_matrix_cell_one_rung_down(box, dist):
    """`red(box, dist) == RISK_MATRIX[(box, next_rung(dist))]`, all nine cells.

    Asserted as a LOOKUP rather than against nine literals, because that is what the ruling is:
    *"one rung down the disturbance axis"* names a cell in the table we already hold.
    """
    stepped = next_rung(dist)
    expected = 0.0 if stepped is None else RISK_MATRIX[(box, stepped)]

    sizing = RiskMatrix.size(box_grade=box, disturbance_grade=dist, is_red_folder_day=True)

    assert sizing.risk_pct == expected, (
        f"{box}/{dist} on a red-folder day returned {sizing.risk_pct}; one rung down is "
        f"{expected} (RISK_MATRIX[{box},{stepped}])"
    )
    assert sizing.matrix_risk_pct == RISK_MATRIX[(box, dist)], (
        "the GRADED cell was not preserved — without it a record cannot show a step happened"
    )
    assert sizing.eco_day_step_applied is True
    assert sizing.eco_day_risk_policy == ECO_DAY_RISK_POLICY == "ONE_RUNG_DOWN"


def test_HEAVY_stays_skip_BY_THE_SAME_RULE_and_not_by_an_exception():
    """HEAVY has no next rung and is already `0.0`. **The uniformity is the point** — an explicit
    `if HEAVY: skip` would be a second statement of a thing the table already says."""
    assert next_rung("HEAVY") is None
    assert next_rung("NONE") == "LIGHT" and next_rung("LIGHT") == "HEAVY"
    for box in BOX_GRADES:
        assert RISK_MATRIX[(box, "HEAVY")] == 0.0
        sized = RiskMatrix.size(box_grade=box, disturbance_grade="HEAVY", is_red_folder_day=True)
        assert sized.risk_pct == 0.0
        # ATTRIBUTED TO THE LAYOUT, NOT THE CALENDAR: the graded cell was already zero, so the
        # red-folder day removed nothing. Reporting ECO_DAY here would blame the calendar for a
        # skip it did not cause.
        assert sized.reason_code == "HEAVY_DISTURBANCE_SKIP"


def test_a_LIGHT_day_rung_down_lands_on_SKIP_and_says_the_CALENDAR_did_it():
    """The one new outcome: a box that IS tradeable today, removed by the calendar."""
    for box in BOX_GRADES:
        sized = RiskMatrix.size(box_grade=box, disturbance_grade="LIGHT", is_red_folder_day=True)
        assert sized.outcome == "SKIP"
        assert sized.reason_code == ECO_DAY_SKIP_REASON == "ECO_DAY_RUNG_DOWN_TO_SKIP"
        assert sized.matrix_risk_pct == RISK_MATRIX[(box, "LIGHT")] > 0.0, (
            "the graded cell was already zero, so this is not the calendar's doing"
        )
        assert "refused by the CALENDAR, not by the layout" in sized.reason


def test_a_NORMAL_day_is_UNCHANGED_and_records_that_no_step_was_taken():
    """MUST-MISS. Without it, every arm above is satisfied by a sizer that steps ALWAYS."""
    for box in BOX_GRADES:
        for dist in DISTURBANCE_GRADES:
            sized = RiskMatrix.size(box_grade=box, disturbance_grade=dist)
            assert sized.risk_pct == RISK_MATRIX[(box, dist)]
            assert sized.eco_day_step_applied is False
            assert sized.is_red_folder_day is False
            # EQUAL, AND BOTH PRESENT. The pair is what lets a record show a step happened
            # rather than leaving it inferred from two numbers that differ.
            assert sized.matrix_risk_pct == sized.risk_pct


def test_NO_new_numeric_literal_entered_the_sizing_path():
    """**Asserted on the AST, not on values.** A literal that happens to EQUAL the derived value
    passes every value check in this file while making the table a second source.

    The ruling is a re-selection within a table Salim wrote. Any risk percentage appearing as a
    literal in this module is a number we introduced, whatever it equals.
    """
    from app.services.rules import gate_032_risk_matrix as module

    tree = ast.parse(inspect.getsource(module))
    cell_values = {v for v in RISK_MATRIX.values() if v != 0.0}

    # NARROWED, AND THE FIRST VERSION OF THIS ARM WAS WRONG. It flagged EVERY non-zero float on
    # the premise that "every float in a sizing module is a risk percentage by construction" —
    # and immediately hit `1e-12`, a pre-existing comparison tolerance. **A guard whose stated
    # rationale is false about its own domain will be widened or deleted by whoever it stops
    # next**, and either outcome loses the check.
    #
    # The precise property: NO RISK-CELL VALUE APPEARS AS A LITERAL. That is what a second source
    # looks like, and it is exactly what a hand-copied red-folder table would have introduced.
    planted: list[str] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, float)
                and node.value in cell_values):
            planted.append(f"line {node.lineno}: {node.value}")
    assert not planted, (
        f"a RISK CELL VALUE is written as a literal at {planted}. The nine cells come from the "
        "registry via _load_matrix(); a literal copy is a SECOND SOURCE and drifts silently in "
        "the direction of whichever copy is edited next (B93)."
    )

    # And the ruled red-folder values specifically — the ones a hand-written table would hold.
    for box in BOX_GRADES:
        stepped = next_rung("NONE")
        assert stepped is not None
        assert RISK_MATRIX[(box, stepped)] in cell_values


def test_the_step_is_a_CELL_RE_SELECTION_and_not_arithmetic():
    """`sizer_implementation` stays `LOOKUP_TABLE`. A multiplier would be GATE-033's defect
    reintroduced with a corrected constant — harder to notice than a disagreement."""
    sized = RiskMatrix.size(
        box_grade="MANIPULATED", disturbance_grade="NONE", is_red_folder_day=True
    )
    assert RiskMatrix.evaluate(sized).values["sizer_implementation"] == "LOOKUP_TABLE"

    assert sized.risk_pct == RISK_MATRIX[("MANIPULATED", "LIGHT")]
    super_red = RiskMatrix.size(
        box_grade="SUPER", disturbance_grade="NONE", is_red_folder_day=True
    )
    assert super_red.risk_pct == RISK_MATRIX[("SUPER", "LIGHT")] == 0.005
    assert super_red.risk_pct != RISK_MATRIX[("SUPER", "NONE")] * 0.5, (
        "the SUPER row is where a halving model diverges from the table — if these are equal, "
        "the step became arithmetic and test_t0024:247's must-miss is no longer protecting it"
    )


def test_the_eco_day_trio_is_emitted_on_BOTH_record_types():
    """Skips go to `setup_evaluation.risk_assessment`; fills go to `trade_execution.sizing`.
    **Emitting on one is how a red-folder skip becomes invisible in the record that holds it.**"""
    sized = RiskMatrix.size(box_grade="SUPER", disturbance_grade="NONE", is_red_folder_day=True)

    assessment = sized.as_risk_assessment()
    for key in ("eco_day_risk_policy", "matrix_risk_pct", "eco_day_step_applied",
                "is_red_folder_day"):
        assert key in assessment, f"{key} missing from the risk_assessment block"
    assert assessment["matrix_risk_pct"] == 0.0125 and assessment["risk_pct"] == 0.005

    values = RiskMatrix.evaluate(sized).values
    for key in ("eco_day_risk_policy", "matrix_risk_pct", "eco_day_step_applied",
                "is_red_folder_day"):
        assert key in values, f"{key} missing from GATE-032's evaluation values"


def test_the_rung_down_cannot_reach_a_live_trade_and_this_test_says_why():
    """**B188, armed rather than only recorded.**

    `RiskMatrix.size(` has ZERO production call sites — live trades are sized from
    `fixed.RISK_PCT`. So this whole file is fixture-only, and a `0 rung-downs applied` production
    figure is consistent with no red-folder days, no calendar (`B179`), AND no sizer.

    *If this test ever fails, the matrix reached the order path — which changes the size of every
    live trade and is Malek's decision, not a refactor.*
    """
    app_dir = pathlib.Path(__file__).resolve().parents[2] / "app"
    callers: list[str] = []
    for path in app_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "size"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "RiskMatrix"):
                callers.append(f"{path.name}:{node.lineno}")
    assert not callers, (
        f"RiskMatrix.size() is now called from production at {callers}. GATE-032 sizing has "
        "reached the order path — every live trade's size changes with it. That is a live "
        "behaviour change and needs Malek's authorisation (T-0050's precedent), not a green test."
    )
