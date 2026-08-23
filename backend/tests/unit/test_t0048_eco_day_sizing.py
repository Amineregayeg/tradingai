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


# ======================================================================================
# B188's tripwire — WIDENED by T-0055 (`B191`) from ONE SYNTACTIC SHAPE to THE CLASS
# ======================================================================================


def _size_call_sites(source: str, label: str) -> list[str]:
    """Every ``<anything>.size(...)`` call in `source`, rendered as ``label:line  expr``.

    **The call's base is deliberately UNCONSTRAINED (`B191`).** The first version of this
    predicate required ``ast.Name(id="RiskMatrix")`` as the base, so of the three shapes a
    sizer cutover can be written in it caught ONE:

        RiskMatrix.size(...)        base Name('RiskMatrix')    -> caught
        RM.size(...)                base Name('RM')            -> MISSED   (aliased import)
        g32.RiskMatrix.size(...)    base Attribute(...)        -> MISSED   (module path)

    *"It uses AST" was never the property.* The narrow version was an AST-based ENUMERATION —
    of syntactic shapes rather than of strings, which is `B184`'s error one layer up.

    **Matching the attribute `size` on ANY base OVER-FIRES** if some unrelated object grows a
    ``.size()`` method. That is the trade, it was chosen deliberately, and it is stated in the
    failure message: an over-fire is a VISIBLE failure that gets read, where the narrow version
    was a SILENT PASS on the one day the guard exists for.

    **Still not covered, and recorded rather than fixed (`B196`):** a value-bound reference
    (``sizer = RiskMatrix.size`` then ``sizer(...)``) and ``getattr(RiskMatrix, "size")(...)``
    both stay silent, because both stop being an attribute call at the call site.
    """
    return [
        f"{label}:{node.lineno}  {ast.unparse(node.func)}"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "size"
    ]


def _tripwire_failure(callers: list[str]) -> str:
    """The message. **Two readings, and the reader must be able to tell them apart here.**"""
    return (
        f"A `.size(...)` call now exists in production code at {callers}.\n\n"
        "READING 1 — GATE-032's sizer reached the order path. Every live trade's size changes "
        "with it: MANIPULATED/NONE risks 1.50x base, SUPER/HEAVY skips entirely, an UNGRADED "
        "setup takes the refusal path. SOME TRADES GET BIGGER. That is a live behaviour change "
        "needing Malek's authorisation (T-0050's precedent), not a green test.\n\n"
        "READING 2 — an UNRELATED object grew a `.size()` method. This guard matches the "
        "attribute `size` on ANY base BY DESIGN (`B191`/T-0055). Keying it on the base name "
        "`RiskMatrix` missed `RM.size()` and `g32.RiskMatrix.size()` — two of the three shapes "
        "it existed to catch. The over-fire is the deliberate price of covering the class.\n\n"
        "IF IT IS READING 2: rename the unrelated method, or narrow by MODULE. Do NOT narrow by "
        "the call's base name — that restores `B191` exactly, and it restores it silently."
    )


def test_the_rung_down_cannot_reach_a_live_trade_and_this_test_says_why():
    """**B188, armed rather than only recorded.**

    No `.size(...)` call of ANY form exists under `app/` — live trades are sized from
    `fixed.RISK_PCT`. So this whole file is fixture-only, and a `0 rung-downs applied`
    production figure is consistent with no red-folder days, no calendar (`B179`), AND no sizer.

    *If this test ever fails, read the message before you touch it: one of the two readings is a
    live behaviour change that is Malek's decision, and the other is a rename.*
    """
    app_dir = pathlib.Path(__file__).resolve().parents[2] / "app"
    callers: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        callers += _size_call_sites(path.read_text(encoding="utf-8"), path.name)
    assert not callers, _tripwire_failure(callers)


#: The three ways a sizer cutover can be WRITTEN. `B191`: the narrow guard caught the first only.
B191_CALL_SHAPES = {
    "1_direct_name": "RiskMatrix.size(box_grade='SUPER', disturbance_grade='NONE')",
    "2_aliased_import": "RM.size(box_grade='SUPER', disturbance_grade='NONE')",
    "3_module_path": "g32.RiskMatrix.size(box_grade='SUPER', disturbance_grade='NONE')",
}


@pytest.mark.parametrize("shape", sorted(B191_CALL_SHAPES))
def test_t0055_the_tripwire_catches_ALL_THREE_call_shapes_and_not_just_the_named_one(shape):
    """**MUST-FIRE, all three.** Review added these to `strategy_step.py`: 1 failed, 2 passed.

    This is the arm that makes the fix DURABLE rather than one-time. Narrowing the predicate
    back to a base-name match — the tidy-looking edit that removes the over-fire — turns two of
    these three red, which is `B191` announcing itself instead of sitting silent.
    """
    assert _size_call_sites(B191_CALL_SHAPES[shape], shape), (
        f"the {shape} shape is invisible to the tripwire. If someone narrowed the predicate to "
        "avoid the over-fire, this is B191 restored — see _size_call_sites' docstring."
    )


def test_t0055_the_OVER_FIRE_is_real_deliberate_and_stated_in_the_message():
    """**The cost, demonstrated rather than described.** `some_queue.size()` DOES trip it.

    Recording it as an arm means nobody later "discovers" the over-fire and quietly narrows the
    guard to remove it. The failure message is where the choice is written down, so the message
    carrying BOTH readings is part of the fix, not decoration around it.
    """
    assert _size_call_sites("some_queue.size()", "unrelated"), (
        "the over-fire is the deliberate price of covering the class; if it stopped firing, the "
        "predicate was narrowed"
    )

    message = _tripwire_failure(["strategy_step.py:42  RiskMatrix.size"])
    assert "READING 1" in message and "READING 2" in message
    assert "SOME TRADES GET BIGGER" in message, "reading 1 must state the live consequence"
    assert "narrow by the call's base name" in message.lower(), (
        "the message must name the wrong fix, because the wrong fix is the tempting one"
    )


def test_t0055_the_predicate_is_SILENT_on_what_is_not_a_size_call():
    """**MUST-MISS.** A guard that fires on everything proves nothing when it fires."""
    for source, why in (
        ("RiskMatrix.evaluate(sizing)", "a different method"),
        ("sizer = RiskMatrix.size", "an attribute READ, with no call"),
        ("size(box_grade='SUPER')", "a bare function named size, not an attribute call"),
        ('"RiskMatrix.size(...)"', "the call written inside a STRING — B161's class"),
    ):
        assert not _size_call_sites(source, "miss"), f"the predicate over-fires on {why}"


def test_t0055_the_guard_is_SILENT_ON_APP_WHILE_LOUD_ON_THIS_FILE():
    """**The control pair. The instrument, not the answer.**

    `0 production callers` and `the predicate is broken` produce the SAME green. So run the same
    predicate over a population that is known non-empty: THIS FILE calls `RiskMatrix.size(...)`
    seven times. Loud here, silent under `app/` — the silence is about the WALK ROOT, which is
    what makes this guard about production rather than about the repository.

    *If this ever fails because t0048's fixture arms stopped calling `size()` directly, the
    control lost its subject — repoint it, do not delete it.*
    """
    own = _size_call_sites(pathlib.Path(__file__).read_text(encoding="utf-8"), "self")
    assert len(own) >= 3, (
        f"this file was the non-empty control and now has {len(own)} .size() calls — the control "
        "no longer proves the predicate can see anything"
    )

    app_dir = pathlib.Path(__file__).resolve().parents[2] / "app"
    assert app_dir.is_dir(), f"the walk root does not exist: {app_dir}"
    assert pathlib.Path(__file__).resolve() not in set(app_dir.rglob("*.py")), (
        "tests/ must be OUTSIDE the walk root by construction, not by exclusion"
    )
