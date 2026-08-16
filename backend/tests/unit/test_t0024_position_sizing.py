"""T-0024 — position sizing: GATE-032, SIZE-004, GRADE-019.

THE NINE VALUES ARE HARD-CODED IN THIS FILE ON PURPOSE, AND THAT IS THE WHOLE TRANSCRIPTION
CHECK. Reading the expected values out of `GATE-032.values` and comparing them to
`RISK_MATRIX` — which is loaded from `GATE-032.values` — would assert the registry equals
itself. That is the B109 shape: a test whose NAME claims coverage its ASSERTIONS cannot have,
and it passes identically whether or not the transcription is right.

So the table is checked against THREE independent renderings of the same doctrine, all of
which are in this repository:

    1. the nine literals typed below, transcribed by hand from the rule statement
    2. the PERCENTAGES in GATE-032's prose ("Manipulated: No 1.50% · Light 0.75% ...")
    3. the DECIMALS in GATE-032's prose ("As stored in 053_untitled.md's Risk Alignment
       column in decimals: 0.015 / 0.0075 / 0 · ...")

against the fourth, `values`, which is what the code loads. A typo in any one of them fails.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.services.rules.gate_002_disturbance import HeavyDisturbanceSkip
from app.services.rules.gate_032_risk_matrix import (
    ALTCOIN_REFUSAL_REASON,
    BOX_GRADES,
    DISTURBANCE_GRADES,
    HEAVY_SKIP_REASON,
    LEGAL_RISK_PCTS,
    RISK_MATRIX,
    SIZER_IMPLEMENTATION,
    UNGRADED_REASON,
    AltcoinRiskUndefined,
    RiskCeilingConformance,
    RiskMatrix,
)
from app.services.telemetry import contract_loader as contract

#: TRANSCRIBED BY HAND from GATE-032's statement, in the statement's own row order. This is
#: the independent copy; nothing derives it from the registry.
EXPECTED_CELLS: dict[tuple[str, str], float] = {
    ("MANIPULATED", "NONE"): 0.015,
    ("MANIPULATED", "LIGHT"): 0.0075,
    ("MANIPULATED", "HEAVY"): 0.0,
    ("SUPER", "NONE"): 0.0125,
    ("SUPER", "LIGHT"): 0.005,
    ("SUPER", "HEAVY"): 0.0,
    ("STANDARD", "NONE"): 0.01,
    ("STANDARD", "LIGHT"): 0.0025,
    ("STANDARD", "HEAVY"): 0.0,
}

#: The banned vector. Its middle cell is 0.05 — ten times its siblings, 3.33x over
#: SIZE-004's ceiling, in the column GATE-032 sets to zero.
BANNED_ALTCOIN_VECTOR = "risk_altcoin_heavy_as_written"

RULES_PACKAGE = Path(__file__).resolve().parents[2] / "app" / "services" / "rules"
LIVE_PACKAGE = Path(__file__).resolve().parents[2] / "app" / "services" / "live"


def _cells_in_statement_order() -> list[tuple[str, str]]:
    """The nine keys in the order GATE-032's prose lists them: row-major, best grade first."""
    return [(box, dist) for box in BOX_GRADES for dist in DISTURBANCE_GRADES]


# ======================================================================================
# Criterion 1 — a literal table, and no MULTIPLICATIVE decomposition reproduces it
# ======================================================================================


def test_the_nine_cells_match_three_independent_transcriptions_of_the_statement() -> None:
    """The table, cross-checked against the prose percentages AND the prose decimals.

    Four renderings, one comparison each. The `values` block is what the code loads; the two
    prose renderings and the hand-typed literals are what it is checked against. No assertion
    here compares the registry to itself.
    """
    statement = contract.rule("GATE-032")["statement"]

    percents = re.findall(r"([0-9]+(?:\.[0-9]+)?)%", statement.split("As stored")[0])
    decimals = re.findall(
        r"[0-9]+(?:\.[0-9]+)?", statement.split("in decimals:")[1]
    )[:9]

    assert len(percents) == 9, f"expected nine percentages in the prose, got {percents}"
    assert len(decimals) == 9, f"expected nine decimals in the prose, got {decimals}"

    for i, key in enumerate(_cells_in_statement_order()):
        expected = EXPECTED_CELLS[key]
        assert RISK_MATRIX[key] == expected, f"{key}: values block disagrees with the literal"
        assert float(percents[i]) / 100.0 == pytest.approx(expected, abs=1e-12), (
            f"{key}: the prose percentage {percents[i]}% disagrees with {expected}"
        )
        assert float(decimals[i]) == pytest.approx(expected, abs=1e-12), (
            f"{key}: the prose decimal {decimals[i]} disagrees with {expected}"
        )

    assert set(RISK_MATRIX) == set(EXPECTED_CELLS)
    assert len(RISK_MATRIX) == 9


def test_no_single_multiplicative_modifier_can_reproduce_the_table() -> None:
    """GATE-033's defect, proved rather than asserted.

    A multiplicative model is `risk[grade][disturbance] = base[grade] x factor[disturbance]`.
    Both sides are free, but scaling `base` by c and `factor` by 1/c is the same model, so
    fix `factor[NONE] = 1` without loss of generality. Then `base[grade] = NONE[grade]`, and
    the LIGHT column forces

        factor[LIGHT] = LIGHT[grade] / NONE[grade]      for EVERY grade

    so a multiplicative model exists if and only if that ratio is the same for all three
    grades. It is not — 0.500 / 0.400 / 0.250 — therefore no such model exists, and any
    candidate factor can match AT MOST ONE row.

    The HEAVY column is excluded from the argument deliberately: an all-zero column IS
    multiplicatively expressible (factor 0), so including it would weaken the proof rather
    than strengthen it. The defect lives entirely in the LIGHT column.
    """
    ratios = {
        grade: RISK_MATRIX[(grade, "LIGHT")] / RISK_MATRIX[(grade, "NONE")]
        for grade in BOX_GRADES
    }
    assert ratios == pytest.approx(
        {"MANIPULATED": 0.500, "SUPER": 0.400, "STANDARD": 0.250}, abs=1e-12
    )

    # Three DISTINCT ratios is the proof step. If this ever became two, a single factor could
    # fit two rows and the argument below would no longer be exhaustive.
    assert len({round(r, 12) for r in ratios.values()}) == 3, (
        "the three Light/No ratios must be distinct — that is what makes a single "
        "multiplicative factor impossible rather than merely unused"
    )

    def mismatching_grades(factor: float) -> list[str]:
        return [
            grade
            for grade in BOX_GRADES
            if RISK_MATRIX[(grade, "NONE")] * factor
            != pytest.approx(RISK_MATRIX[(grade, "LIGHT")], abs=1e-12)
        ]

    # Every candidate factor that fits ANY row — the only ones worth testing, since a factor
    # fitting no row mismatches everywhere trivially — still mismatches at least two others.
    for grade, factor in ratios.items():
        mismatches = mismatching_grades(factor)
        assert len(mismatches) == 2, (
            f"factor {factor} (fitted to {grade}) should mismatch the other two grades; "
            f"it mismatches {mismatches}"
        )

    # And the shipped sizer cannot express one at all: it stamps LOOKUP_TABLE, which the
    # telemetry schema separates from MULTIPLICATIVE_MODIFIER precisely so the defect is
    # detectable in stored records.
    assert SIZER_IMPLEMENTATION == "LOOKUP_TABLE"


def test_all_three_rows_are_needed_because_manipulated_alone_confirms_the_wrong_rule() -> None:
    """WHY THREE ROWS AND NEVER ONE — do not trim this to a representative row.

    `x0.5` is the modifier GATE-033 names, and it is CORRECT on MANIPULATED, which is the row
    GATE-032's own statement leads with and therefore the row an implementer checks first:

        MANIPULATED   0.0150 x 0.5 = 0.0075   == the table          <-- agrees
        SUPER         0.0125 x 0.5 = 0.00625  vs 0.005   (+25%)     <-- wrong
        STANDARD      0.0100 x 0.5 = 0.0050   vs 0.0025  (EXACTLY DOUBLE)

    A one-row spot check therefore CONFIRMS the wrong rule, and the wrong rule doubles the
    risk on Standard — the most common grade. On a $100,000 account that is $500 where the
    doctrine says $250. No amount of care in writing a one-row test helps, because the value
    it checks agrees. The defect is in the DATA, not in the test.

    An edit reducing this to one representative row would look like a tidy-up and would
    restore the trap. That is what this docstring exists to prevent.
    """
    half = 0.5

    assert RISK_MATRIX[("MANIPULATED", "NONE")] * half == pytest.approx(
        RISK_MATRIX[("MANIPULATED", "LIGHT")], abs=1e-12
    ), "the trap: x0.5 IS correct on the first row"

    assert RISK_MATRIX[("SUPER", "NONE")] * half == pytest.approx(0.00625, abs=1e-12)
    assert RISK_MATRIX[("SUPER", "LIGHT")] == pytest.approx(0.005, abs=1e-12)
    assert RISK_MATRIX[("SUPER", "NONE")] * half != pytest.approx(
        RISK_MATRIX[("SUPER", "LIGHT")], abs=1e-12
    )

    assert RISK_MATRIX[("STANDARD", "NONE")] * half == pytest.approx(0.0050, abs=1e-12)
    assert RISK_MATRIX[("STANDARD", "LIGHT")] == pytest.approx(0.0025, abs=1e-12)
    assert RISK_MATRIX[("STANDARD", "NONE")] * half == pytest.approx(
        RISK_MATRIX[("STANDARD", "LIGHT")] * 2.0, abs=1e-12
    ), "the Standard error is exactly double, which is GATE-033's headline"


def test_exact_relation_holds_over_the_table_as_an_invariant_not_an_implementation() -> None:
    """LIGHT = NONE - 0.0075, exact for all three grades. A TEST over the table, never its source.

    The matrix IS decomposable — additively, exactly, and the registry says so in
    `values.exact_relation`. So "no decomposition reproduces it" would be a FALSE claim; only
    the MULTIPLICATIVE form is forbidden.

    This assertion is something the table cannot give you about itself: a literal lookup is
    self-consistent by construction and will happily hold a mistyped cell. The relation ties
    six of the nine cells to each other, so a typo in any one of them fails here.

    IT LIVES IN A TEST AND NOT AT IMPORT deliberately. If Salim later rules a table where the
    relation no longer holds, that is a legitimate doctrine change; an import-time assert
    would crash the engine, whereas a red test is the right severity — it demands a human
    read the diff.
    """
    relation = contract.rule("GATE-032")["values"]["exact_relation"]
    assert "LIGHT = NONE - 0.0075" in relation
    assert "exact for all three grades" in relation

    delta = 0.0075
    for grade in BOX_GRADES:
        assert RISK_MATRIX[(grade, "NONE")] - delta == pytest.approx(
            RISK_MATRIX[(grade, "LIGHT")], abs=1e-12
        ), f"{grade}: LIGHT is not NONE - {delta}"

    # And the HEAVY column is a ruled zero rather than a continuation of the relation —
    # NONE - 2 x 0.0075 would give 0.0 only for MANIPULATED and negatives for the others.
    for grade in BOX_GRADES:
        assert RISK_MATRIX[(grade, "HEAVY")] == 0.0


# ======================================================================================
# Criterion 1a — SIZE-004's TWO assertions, checked separately
# ======================================================================================


def test_size_004_checks_the_ceiling_and_membership_as_two_separate_assertions() -> None:
    """A single `<=` check passes every interpolation, which is the failure this rule catches."""
    interpolated = RiskCeilingConformance.check(0.009)
    assert interpolated["within_ceiling"] is True, "0.009 is under the 1.5% ceiling"
    assert interpolated["in_matrix_values"] is False, "0.009 is not one of the nine"
    assert interpolated["conforms"] is False

    over = RiskCeilingConformance.check(0.02)
    assert over["within_ceiling"] is False
    assert over["in_matrix_values"] is False
    assert over["conforms"] is False

    # The corrupt altcoin cell, if anything ever produced it, fails both halves.
    corrupt = RiskCeilingConformance.check(0.05)
    assert corrupt["within_ceiling"] is False
    assert corrupt["in_matrix_values"] is False

    for value in sorted(LEGAL_RISK_PCTS):
        legal = RiskCeilingConformance.check(value)
        assert legal["conforms"] is True, f"{value} is a matrix cell and must conform"


def test_the_ceiling_half_is_saturated_at_one_cell_and_dormant_at_the_other_eight() -> None:
    """LABEL WHAT THE SECOND GUARD ACTUALLY GUARDS — it is one live check plus a tripwire.

    The matrix's maximum IS SIZE-004's ceiling, exactly. So for eight of the nine cells,
    membership already implies the ceiling and the ceiling assertion cannot fail. It is a
    real boundary guard on `MANIPULATED_NONE`, where it is exactly saturated, and a tripwire
    everywhere else — it fires only if the matrix itself moves above 1.5%.

    Recorded here so a reader counts one live check and a tripwire rather than two
    independent guards. Against values NOT drawn from the table the two halves are genuinely
    independent, and that is the case the rule exists for.
    """
    ceiling = RiskCeilingConformance.MAX_RISK_PCT
    assert ceiling == 0.015
    assert max(RISK_MATRIX.values()) == ceiling

    saturated = [k for k, v in RISK_MATRIX.items() if v == ceiling]
    assert saturated == [("MANIPULATED", "NONE")]

    strictly_under = [k for k, v in RISK_MATRIX.items() if v < ceiling]
    assert len(strictly_under) == 8


def test_the_nine_cells_carry_seven_distinct_values_because_heavy_is_zero_three_times() -> None:
    """The denominator, stated. A reader expecting nine legal values is reading cell count."""
    assert len(RISK_MATRIX) == 9
    assert len(LEGAL_RISK_PCTS) == 7
    assert sorted(LEGAL_RISK_PCTS) == [0.0, 0.0025, 0.005, 0.0075, 0.01, 0.0125, 0.015]


def test_the_retired_two_percent_ceiling_stays_visible_in_every_evaluation() -> None:
    """Criterion 4 — the retirement was by OMISSION, and the rule requires it stay visible."""
    assert RiskCeilingConformance.RETIRED_CEILING == 0.02
    assert RiskCeilingConformance.MAX_RISK_PCT < RiskCeilingConformance.RETIRED_CEILING

    sizing = RiskMatrix.size(box_grade="MANIPULATED", disturbance_grade="NONE")
    ev = RiskCeilingConformance.evaluate(sizing)
    assert ev.values["retired_ceiling"] == 0.02
    assert ev.values["retirement_by_omission"] is True

    statement = contract.rule("SIZE-004")["statement"]
    assert "retired by omission" in statement or "retirement was by omission" in statement
    assert "open-questions register" in statement


# ======================================================================================
# Criterion 2 — HEAVY is a skip, and a skip is not a zero-sized fill
# ======================================================================================


@pytest.mark.parametrize("grade", BOX_GRADES)
def test_heavy_is_a_skip_and_never_a_tradeable_zero(grade: str) -> None:
    """A position of size zero is not a trade taken at zero risk; it is a trade refused."""
    sizing = RiskMatrix.size(box_grade=grade, disturbance_grade="HEAVY")

    assert sizing.outcome == "SKIP"
    assert sizing.risk_pct == 0.0
    assert sizing.is_tradeable is False, (
        "a zero that flows into the sizer and out the other side as a position IS the defect"
    )
    assert sizing.reason_code == HEAVY_SKIP_REASON
    assert sizing.matrix_cell == f"{grade}_HEAVY"

    ev = RiskMatrix.evaluate(sizing)
    assert ev.verdict == "PASS", "a ruled zero is the rule WORKING, not an inapplicable rule"
    assert ev.values["is_tradeable"] is False
    assert ev.values["outcome"] == "SKIP"


def test_no_outcome_carrying_zero_or_no_risk_is_ever_tradeable() -> None:
    """The invariant behind criterion 2, over every outcome the sizer can produce."""
    cases = [
        RiskMatrix.size(box_grade="MANIPULATED", disturbance_grade="HEAVY"),
        RiskMatrix.size(box_grade=None, disturbance_grade="NONE"),
        RiskMatrix.size(
            box_grade="MANIPULATED", disturbance_grade="NONE", instrument_class="ALTCOIN"
        ),
    ]
    for sizing in cases:
        assert not sizing.risk_pct, f"{sizing.outcome} should carry no positive risk"
        assert sizing.is_tradeable is False, f"{sizing.outcome} must not be tradeable"

    tradeable = RiskMatrix.size(box_grade="STANDARD", disturbance_grade="LIGHT")
    assert tradeable.is_tradeable is True
    assert tradeable.risk_pct == 0.0025


def test_gate_001_and_gate_032_agree_on_heavy_without_being_the_same_code_path() -> None:
    """GATE-001 decides admission; GATE-032 decides size. Conformance needs both, separately.

    They are deliberately not merged: a record must be able to show the gate fired BEFORE
    sizing rather than after, which is impossible if one call produces both facts.
    """
    assert HeavyDisturbanceSkip.RISK_PCT_ON_HEAVY == 0.0
    for grade in BOX_GRADES:
        assert RISK_MATRIX[(grade, "HEAVY")] == HeavyDisturbanceSkip.RISK_PCT_ON_HEAVY

    # ...and the two reason tokens are distinct strings, so a record never conflates them.
    assert HeavyDisturbanceSkip.BLOCK_REASON != HEAVY_SKIP_REASON


# ======================================================================================
# Criterion 3 / 3-RULING — GRADE-019 refuses, and a refusal is not a skip
# ======================================================================================


def test_an_altcoin_is_refused_with_a_named_reason_and_never_a_number() -> None:
    """The correct implementation is a REFUSAL. A synthetic altcoin, because production has none."""
    sizing = RiskMatrix.size(
        box_grade="MANIPULATED", disturbance_grade="NONE", instrument_class="ALTCOIN"
    )

    assert sizing.outcome == "REFUSED"
    assert sizing.risk_pct is None, "a refusal has no number — None, not 0.0"
    assert sizing.is_tradeable is False
    assert sizing.reason_code == ALTCOIN_REFUSAL_REASON
    assert sizing.matrix_cell == "NOT_APPLICABLE"
    assert "interpolate" in sizing.reason

    gate = RiskMatrix.evaluate(sizing)
    assert gate.verdict == "NOT_APPLICABLE", "no cell applies, and silence is not a pass"

    grade = AltcoinRiskUndefined.evaluate(sizing)
    assert grade.verdict == "PASS", "GRADE-019 fired and did what its output states"
    assert grade.values["refused"] is True
    assert grade.values["refusal_reason"] == ALTCOIN_REFUSAL_REASON

    size004 = RiskCeilingConformance.evaluate(sizing)
    assert size004.verdict == "NOT_APPLICABLE", "no risk_pct means nothing to conform"


@pytest.mark.parametrize("grade", BOX_GRADES)
@pytest.mark.parametrize("disturbance", DISTURBANCE_GRADES)
def test_the_refusal_covers_every_cell_including_heavy(grade: str, disturbance: str) -> None:
    """THE REFUSAL IS CHECKED BEFORE THE MATRIX, AND THE HEAVY CASE IS WHY.

    Checking the instrument class after the disturbance grade would let an altcoin with HEAVY
    disturbance report SKIP — which silently ASSERTS the Heavy-override that GRADE-019 says
    is *only ASSUMED* to apply to the altcoin column. Refusing first means the engine never
    leans on that assumption and never has a reason to read the altcoin vectors at all.
    """
    sizing = RiskMatrix.size(
        box_grade=grade, disturbance_grade=disturbance, instrument_class="ALTCOIN"
    )
    assert sizing.outcome == "REFUSED"
    assert sizing.reason_code == ALTCOIN_REFUSAL_REASON
    assert sizing.risk_pct is None


def test_a_refusal_and_a_skip_are_never_the_same_record() -> None:
    """Same numeric shape, opposite meanings: the strategy working versus the strategy absent."""
    skip = RiskMatrix.size(box_grade="SUPER", disturbance_grade="HEAVY")
    refusal = RiskMatrix.size(
        box_grade="SUPER", disturbance_grade="HEAVY", instrument_class="ALTCOIN"
    )

    assert skip.outcome != refusal.outcome
    assert skip.reason_code != refusal.reason_code
    assert skip.risk_pct == 0.0 and refusal.risk_pct is None
    assert RiskMatrix.evaluate(skip).verdict == "PASS"
    assert RiskMatrix.evaluate(refusal).verdict == "NOT_APPLICABLE"

    # An ungraded box is a third distinct state, not a flavour of either.
    ungraded = RiskMatrix.size(box_grade=None, disturbance_grade="NONE")
    assert ungraded.outcome == "UNGRADED_BOX"
    assert ungraded.reason_code == UNGRADED_REASON
    assert len({skip.reason_code, refusal.reason_code, ungraded.reason_code}) == 3


def test_grade_019_refuses_regardless_of_the_altcoin_trading_declared_parameter() -> None:
    """An engine-side toggle must not unlock a number the doctrine never supplied.

    `declared_parameters.altcoin_trading_enabled` records whether the engine would TRADE
    altcoins — a separate unstated question. Even were it true, the Risk Altcoin column is
    UNDEFINED and sizing still has to refuse. `refuses()` takes only the instrument class, so
    there is no signature through which the flag could reach this decision.
    """
    import inspect

    params = set(inspect.signature(AltcoinRiskUndefined.refuses).parameters)
    assert params == {"instrument_class"}, (
        f"refuses() must depend on nothing but the instrument class; it takes {params}"
    )
    assert AltcoinRiskUndefined.refuses("ALTCOIN") is True
    assert AltcoinRiskUndefined.refuses("ALIGNED_MAJOR") is False


# ======================================================================================
# 3-RULING-i — the branch cannot fire in production, and that is the finding
# ======================================================================================


def test_both_live_paths_hardcode_aligned_major_so_the_refusal_is_not_exercised() -> None:
    """NOT_EXERCISED, reported rather than papered over.

    Measured rather than asserted from memory: the two live call sites are read from disk.
    Deliberately NOT fixed by adding an instrument_class producer — that would be a roster
    change and GATE-008 refuses altcoin rosters on doctrine.
    """
    hardcoded = {}
    for name in ("shadow.py", "crypto_loop.py"):
        source = (LIVE_PACKAGE / name).read_text(encoding="utf-8")
        hardcoded[name] = re.findall(r'"instrument_class":\s*"([A-Z_]+)"', source)

    assert hardcoded["shadow.py"] == ["ALIGNED_MAJOR"], hardcoded
    assert hardcoded["crypto_loop.py"] == ["ALIGNED_MAJOR"], hardcoded

    # And nothing else in the engine produces the field.
    producers = [
        path.name
        for path in (LIVE_PACKAGE.parent).rglob("*.py")
        if "instrument_class" in path.read_text(encoding="utf-8")
        and path.name not in ("shadow.py", "crypto_loop.py", "gate_032_risk_matrix.py")
    ]
    assert producers == [], f"an instrument_class producer appeared: {producers}"


def test_grade_019_declares_itself_unable_to_fire_so_coverage_is_not_inflated() -> None:
    """The CANNOT FIRE bucket exists so registering a rule cannot raise EFFECTIVE coverage.

    `instrument_class` is a DATA NAME, not a rule id — 82 of 117 rules write their inputs that
    way, so the rule-id graph cannot see this edge (B44). TARGET-001 declares
    `active_institutional_destination` identically.
    """
    assert AltcoinRiskUndefined.CANNOT_FIRE_WITHOUT == ("instrument_class",)
    assert "UNABLE TO FIRE" in (AltcoinRiskUndefined.COVERAGE_NOTE or ""), (
        "TARGET-001's phrasing, reused so the two unreachable rules read alike in the "
        "coverage report"
    )

    sizing = RiskMatrix.size(
        box_grade="STANDARD", disturbance_grade="NONE", instrument_class="ALTCOIN"
    )
    ev = AltcoinRiskUndefined.evaluate(sizing)
    assert ev.values["branch_reachable_in_production"] is False
    assert ev.values["cannot_fire_without"] == ["instrument_class"]

    # GATE-032 itself is NOT in that bucket — all four of its declared dependencies have
    # producers, so it consumes real upstream output rather than a fixture.
    assert RiskMatrix.CANNOT_FIRE_WITHOUT == ()
    assert contract.rule("GATE-032")["depends_on"] == [
        "GATE-002",
        "GRADE-002",
        "GRADE-003",
        "GRADE-004",
    ]


# ======================================================================================
# 3-0 / 3-RULING-ii — the corrupt altcoin vector is never indexed
# ======================================================================================


def _docstring_node_ids(tree: ast.Module) -> set[int]:
    """Ids of every Constant node that is a module/class/function docstring."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                if isinstance(first.value.value, str):
                    ids.add(id(first.value))
    return ids


def test_the_corrupt_altcoin_heavy_vector_is_never_read_by_any_rule_module() -> None:
    """NOT "read it and reject it" — DO NOT INDEX IT. Enforced by AST, not by paragraph.

    A code path that reads a corrupt cell is one edit away from using it. So the constraint
    is checked mechanically over the whole rules package: the name may appear in a DOCSTRING,
    where it explains why the vector is quarantined, and nowhere else — no string literal, no
    attribute, no identifier.

    A CLASS-ATTRIBUTE STRING COUNTS AS EXECUTABLE CODE, AND THIS TEST CAUGHT THAT ON ITS
    FIRST RUN. `AltcoinRiskUndefined.COVERAGE_NOTE` is prose to a human and an assignment to
    the parser, so it named the vector and failed here. It was reworded rather than exempted:
    an exemption is a hole a later edit can hide in, and the note lost nothing by referring
    to the `_as_written` suffix instead.

    This is what makes the requirement survive a refactor. A comment saying "never read this"
    is exactly the kind of finding that survives into a constant while the check does not
    survive with it (B109).
    """
    offenders: list[str] = []
    for path in sorted(RULES_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = _docstring_node_ids(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                if BANNED_ALTCOIN_VECTOR in node.value:
                    offenders.append(f"{path.name}:{node.lineno} string literal")
            elif isinstance(node, ast.Attribute) and BANNED_ALTCOIN_VECTOR in node.attr:
                offenders.append(f"{path.name}:{node.lineno} attribute")
            elif isinstance(node, ast.Name) and BANNED_ALTCOIN_VECTOR in node.id:
                offenders.append(f"{path.name}:{node.lineno} name")

    assert offenders == [], (
        f"{BANNED_ALTCOIN_VECTOR} is indexed in executable code at {offenders}. Its middle "
        "cell is 0.05 — 3.33x over SIZE-004's ceiling, in the column GATE-032 zeroes. "
        "GRADE-019 is implemented as a refusal precisely so nothing needs to read it."
    )

    # The check is not vacuous: the name IS present in this package, in prose.
    prose_hits = [
        path.name
        for path in sorted(RULES_PACKAGE.rglob("*.py"))
        if BANNED_ALTCOIN_VECTOR in path.read_text(encoding="utf-8")
    ]
    assert prose_hits == ["gate_032_risk_matrix.py"], (
        "the quarantine is explained in exactly one module's docstring; if that prose is "
        "deleted the AST check above would still pass while nothing recorded WHY"
    )


def test_the_0_05_outlier_is_left_unreconciled_and_not_corrected() -> None:
    """3a — record it, do not fix it. A plausible typo fix is still an implementer editing doctrine.

    Three independent signatures say it is a dropped decimal — exactly ten times its
    siblings, the only broken step in an otherwise monotonic descent, and 3.33x over
    SIZE-004's ceiling. The source that would settle it is in the 84% of citations this
    machine does not hold, so it is labelled INFERENCE and left as written.
    """
    values = contract.rule("GRADE-019")["values"]
    assert values[BANNED_ALTCOIN_VECTOR] == [0.0075, 0.05, 0.0025], (
        "the registry must still carry the vector AS WRITTEN — correcting it here would be "
        "an implementer editing the authoritative database"
    )
    assert values["risk_altcoin_no"] == values["risk_altcoin_light"] == [
        0.0075,
        0.005,
        0.0025,
    ], "disturbance-INVARIANT, which no base-x-modifier scheme can express at all"

    # The three signatures, arithmetically.
    no, light, heavy = (
        values["risk_altcoin_no"],
        values["risk_altcoin_light"],
        values[BANNED_ALTCOIN_VECTOR],
    )
    assert heavy[1] == pytest.approx(light[1] * 10.0, abs=1e-12), "exactly ten"
    assert no[0] > no[1] > no[2], "the No column descends"
    assert not (heavy[0] > heavy[1] > heavy[2]), "the Heavy column does NOT — the middle is largest"
    assert heavy[1] > RiskCeilingConformance.MAX_RISK_PCT * 3.0, "3.33x over the ceiling"

    # And nothing the sizer can emit is that value, whatever a reader of the vector might do.
    assert 0.05 not in LEGAL_RISK_PCTS
    assert RiskCeilingConformance.check(0.05)["conforms"] is False


def test_grade_019_output_governs_its_contradicting_triage_note() -> None:
    """The Manager's 2026-08-16 ruling, pinned so the contradiction cannot be silently resolved.

    `output` says refuse; `triage_note` says ship the partial. Both fields are still in the
    registry and this task does not edit either — the registry is not the implementing seat's
    to change. The ruling is that `output` governs, and the implementation follows `output`.
    """
    rule = contract.rule("GRADE-019")
    assert "UNDEFINED (refuse)" in rule["output"]
    assert "PARTIAL: ship" in rule["triage_note"], (
        "the contradiction is still present — if this ever fails, the registry was edited "
        "and the ruling needs revisiting rather than the test relaxing"
    )
    # The implementation followed `output`, not `triage_note`: the partial scale never
    # reaches a risk_pct.
    for scale_value in (0.0075, 0.005, 0.0025):
        sizing = RiskMatrix.size(
            box_grade="STANDARD", disturbance_grade="NONE", instrument_class="ALTCOIN"
        )
        assert sizing.risk_pct != scale_value
    assert sizing.risk_pct is None


# ======================================================================================
# Criteria 5, 6, 6-i, 6a — what this task does NOT do
# ======================================================================================


def test_gate_032_declares_that_only_the_risk_pct_half_is_implemented() -> None:
    """Criterion 5 — implemented means registered, so the missing half must be named."""
    note = RiskMatrix.COVERAGE_NOTE or ""
    assert "PARTIALLY IMPLEMENTED" in note
    assert "SIZE-001" in note and "SIZE-002" in note
    assert "quantity" in note.lower()
    assert "position quantity" in contract.rule("GATE-032")["output"]

    # There is no quantity anywhere on the sizing object — the half is absent, not stubbed.
    sizing = RiskMatrix.size(box_grade="SUPER", disturbance_grade="NONE")
    assert not hasattr(sizing, "quantity")
    assert "quantity" not in RiskMatrix.evaluate(sizing).values


def test_nothing_under_live_imports_the_sizer() -> None:
    """Criterion 6 — shadow only. Replacing the live sizer is a separate task with a deploy."""
    importers = [
        path.name
        for path in sorted(LIVE_PACKAGE.rglob("*.py"))
        if "gate_032_risk_matrix" in path.read_text(encoding="utf-8")
    ]
    assert importers == [], f"the sizer is wired into live code: {importers}"


def test_the_live_flat_risk_pct_is_exactly_the_standard_none_cell() -> None:
    """Criterion 6a — the live engine sizes every setup as the most conservative non-zero row.

    So the matrix's effect on live sizing is UPWARD for Super and Manipulated boxes (to 1.25%
    and 1.5%) and DOWNWARD to 0.25-0.75% on any Light disturbance. Recorded before anyone
    wires it.

    Criterion 6-i: `fixed_config.py`'s own docstring says this value "is not a knob... It was
    never settable", which denies the premise of the rule this task implements. That file is
    deliberately NOT edited here — the conflict is recorded in KNOWN_ISSUES.md instead.
    """
    from app.services.live import fixed_config

    assert fixed_config.RISK_PCT == RISK_MATRIX[("STANDARD", "NONE")] == 0.01

    source = (LIVE_PACKAGE / "fixed_config.py").read_text(encoding="utf-8")
    assert "never settable" in source, (
        "the config prose contradicting GATE-032 must still be there — this test is the "
        "tripwire that says the conflict is unresolved, not that it is fixed"
    )
    assert fixed_config.RISK_PCT != RISK_MATRIX[("MANIPULATED", "NONE")]


# ======================================================================================
# Telemetry — every branch, every value pinned to a provenance
# ======================================================================================


def test_every_verdict_branch_pins_a_provenance_for_every_value() -> None:
    """`set(values) == set(value_provenance)` on all four outcomes x all three rules.

    A branch that ADDS a value is exactly where provenance gets forgotten, and a missing
    entry is invisible in a green run — EXIT-001's NOT_APPLICABLE record failed this until a
    mutation run surfaced it on an unrelated test.
    """
    sizings = [
        RiskMatrix.size(box_grade="MANIPULATED", disturbance_grade="NONE"),
        RiskMatrix.size(box_grade="STANDARD", disturbance_grade="LIGHT"),
        RiskMatrix.size(box_grade="SUPER", disturbance_grade="HEAVY"),
        RiskMatrix.size(box_grade=None, disturbance_grade="LIGHT"),
        RiskMatrix.size(
            box_grade="SUPER", disturbance_grade="NONE", instrument_class="ALTCOIN"
        ),
    ]
    seen_outcomes = {s.outcome for s in sizings}
    assert seen_outcomes == {"SIZED", "SKIP", "UNGRADED_BOX", "REFUSED"}, seen_outcomes

    for sizing in sizings:
        for rule in (RiskMatrix, RiskCeilingConformance, AltcoinRiskUndefined):
            ev = rule.evaluate(sizing)
            assert set(ev.values) == set(ev.value_provenance), (
                f"{rule.RULE_ID} / {sizing.outcome}: unpinned "
                f"{set(ev.values) ^ set(ev.value_provenance)}"
            )
            assert all("source" in p for p in ev.value_provenance.values())
            assert ev.verdict in ("PASS", "FAIL", "NOT_APPLICABLE")

    # A FAIL branch exists and is reachable — with a value no matrix cell can produce.
    fail = RiskCeilingConformance.check(0.05)
    assert fail["conforms"] is False


def test_the_sizer_stamps_the_cell_id_not_only_the_number() -> None:
    """A mis-sized trade must be attributable to a mis-graded BOX versus a mis-graded DISTURBANCE.

    Two different upstream defects produce one wrong number; the cell id is what separates
    them after the fact.
    """
    schema_cells = {
        f"{box}_{dist}" for box in BOX_GRADES for dist in DISTURBANCE_GRADES
    }
    for (box, dist) in RISK_MATRIX:
        sizing = RiskMatrix.size(box_grade=box, disturbance_grade=dist)
        assert sizing.matrix_cell in schema_cells
        assert sizing.matrix_cell == f"{box}_{dist}"
        assert RiskMatrix.evaluate(sizing).values["matrix_cell"] == sizing.matrix_cell

    block = RiskMatrix.size(
        box_grade="SUPER", disturbance_grade="NONE"
    ).as_risk_assessment()
    assert block["sizer_implementation"] == "LOOKUP_TABLE"
    assert block["matrix_cell"] == "SUPER_NONE"
    assert block["risk_pct"] == 0.0125
    assert block["box_grade"] == "SUPER"

    ungraded = RiskMatrix.size(
        box_grade=None, disturbance_grade="NONE"
    ).as_risk_assessment()
    assert ungraded["box_grade"] == "NONE", "the schema's enum member for 'no grade'"
    assert ungraded["matrix_cell"] == "NOT_APPLICABLE"
