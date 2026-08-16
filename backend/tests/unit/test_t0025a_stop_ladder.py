"""T-0025a — the stop pipeline: the ladder, the floor, the terminal skip, the selector.

WHAT THIS FILE IS DEFENDING, AND WHY IT IS SHAPED THIS WAY

Every assertion about a registry constant is an assertion about DOCTRINE, and proving a
CONSTANT is right is not proving THE CODE READS IT. T-0024 paid for that lesson: four tests
proved the risk matrix was not multiplicatively decomposable, and every one of them operated
on the table AS DATA — so a multiplicative defect implemented at the LOOKUP passed all four
while two cells silently changed.

So each of the four rules here has at least one test that drives the PUBLIC ENTRY POINT and
compares against the registry, not against a literal retyped in this file. Where a literal
appears it is because the test is pinning that the code and the registry AGREE, and it says
so.

THE SELECTION FIXTURE IS THE DOCTRINE'S OWN WORKED TABLE (GATE-028), and it separates the
three real selector implementations at once. The fourth wrong form — first-in-ladder-order
IGNORING the floor — is caught by the floor assertion rather than by the selection fixture,
because once the mandated floor is applied it collapses into first-clearing-2R and picks the
same rung. Both are real wrong implementations; they are just not both separable HERE.

THE TIE-BREAK GETS TWO CASES AND ONLY ONE OF THEM CAN FAIL.
`GATE-028` establishes that rr falls monotonically as the stop widens, so in a
cushion-monotonic ladder the larger stop is ALWAYS earlier in ladder order — and `min()`
returns the first minimum. A tie fixture built from a monotonic ladder is therefore passed
identically by the correct implementation and by one that resolves ties on LIST POSITION.
Case A pins the doctrine (the answer is the 2R candidate, which is where intuition fails);
Case B breaks the ladder/cushion agreement so the guard can actually go red. Monotonicity is
precisely the claim nobody has measured — GATE-027 asserts it in prose and T-0030 measures
it — so a fixture that assumed it in order to test the tie-break would be assuming the thing
under test.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.rules.base import implementations
from app.services.rules.gate_027_stop_ladder import (
    COMPETING_IMBALANCE_EDGE,
    COMPETING_READING,
    COMPETING_SWEEP_PLACEMENT,
    DECLARED_IMBALANCE_EDGE,
    DECLARED_SWEEP_PLACEMENT,
    LADDER,
    ORDER_BLOCK_PRODUCER,
    RR_FLOOR,
    RR_PREFERRED,
    SELECTION_READING,
    UNLOCATABLE_REASONS,
    ClosestTo3RSelector,
    LadderInputs,
    NoCandidateReaches2R,
    RewardFloor,
    SearchEvidence,
    StopCandidate,
    StopCandidateLadder,
    StopCandidateNotComparable,
    evaluate_stop_pipeline,
    risk_reward,
)
from app.services.rules.prim_001_swings import Swing
from app.services.rules.prim_002_imbalances import Imbalance
from app.services.rules.prim_003_liquidity import LiquidityPool
from app.services.rules.prim_004_sweeps import SweepEvent
from app.services.rules.prim_005_breaks import BreakEvent
from app.services.telemetry import contract_loader as contract

T0 = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)

#: GATE-028's worked table, as PRICES rather than as rr values.
#:
#: entry 100, target 130 -> reward 30. The doctrine gives rr; the engine gives prices, and
#: deriving the prices from his rr is what makes "the larger stop" a MEASURED distance
#: instead of an assertion. 1R -> 70, 2R -> 85, 3R -> 90, 4R -> 92.5, 10R -> 97.
ENTRY, TARGET = 100.0, 130.0


def _inputs(**over) -> LadderInputs:
    """The worked table, buildable rung by rung.

    Rung 4 is absent from every fixture built here because NOTHING PRODUCES ORDER BLOCKS.
    That is the honest state and not a gap in the fixture — the doctrine's 4R row cannot be
    reproduced by this engine, and pretending otherwise is what T-0029 exists to fix.
    """
    base = dict(
        entry=ENTRY, target=TARGET, direction="LONG",
        search_window_from=T0, search_window_to=T0,
        msb=BreakEvent(id="MSB-1", tf="5m", bar_time=T0, type="MSB", scale="MAJOR",
                       consumed_swing_id="S-0", break_price=99.0, bar_index=5),
        swings=[Swing(id="S-1", tf="5m", bar_time=T0, price=70.0, kind="LOW", bar_index=9)],
        imbalances=[Imbalance(id="IMB-1", tf="5m", bar_time=T0, price_high=88.0,
                              price_low=85.0, type="FVG", direction="BULLISH",
                              is_momentum_imbalance=True)],
        pools=[LiquidityPool(id="POOL-1", tf="5m", pool_class="SWING_LEVEL", price=93.0,
                             side="LOW")],
        sweeps=[SweepEvent(id="SW-1", pool_id="POOL-1", bar_time=T0, penetration_abs=3.0,
                           penetration_pct=3.2, wick_or_close="WICK")],
        breaks=[BreakEvent(id="BRK-1", tf="5m", bar_time=T0, type="MSB", scale="MINOR",
                           consumed_swing_id="S-1", break_price=97.0, bar_index=11)],
    )
    base.update(over)
    return LadderInputs(**base)


def _candidate(rung: int, anchor: str, rr: float, *, accepted: bool = True) -> StopCandidate:
    """A priced rung whose stop price is DERIVED from rr, so cushion is real."""
    stop = ENTRY - (TARGET - ENTRY) / rr
    return StopCandidate(rung=rung, anchor=anchor, locatable=True, stop_price=stop,
                         anchor_object_id=f"OBJ-{rung}", rr=rr, accepted=accepted,
                         rejection_reason="NONE" if accepted else "RR_BELOW_2R",
                         _entry=ENTRY)


# ---------------------------------------------------------------------------
# Criterion 1 — the ladder order is the ENGINE order
# ---------------------------------------------------------------------------
def test_the_ladder_order_is_read_from_the_registry_not_retyped():
    """The order in the code and the order in the registry cannot drift, because there is
    one. This reads the registry independently rather than comparing LADDER to itself."""
    assert list(LADDER) == contract.rule("GATE-027")["values"]["ladder"]
    assert list(LADDER) == [
        "DEEPEST_SWING", "MOMENTUM_IMBALANCE", "LIQUIDITY_SWEEP_QML",
        "ORDER_BLOCK", "INNER_MSB",
    ]


def test_order_block_is_rung_four_not_rung_three():
    """The workspace (§2 H8, §3.5, §8) runs Order Block THIRD and QML fourth, and is
    SUPERSEDED for execution. The wrong source is the more findable one, so this pins the
    difference rather than trusting a comment."""
    assert LADDER.index("ORDER_BLOCK") == 3, "engine order puts ORDER_BLOCK at rung 4"
    assert LADDER.index("LIQUIDITY_SWEEP_QML") == 2, "and the swept level at rung 3"


def test_the_ladder_is_always_five_long_even_when_nothing_is_locatable():
    """Criterion 2c. A five-anchor ladder that silently returns four is the
    absence-versus-empty collapse: 'rung 3 was not locatable on this bar' is only checkable
    if something counts the slots."""
    empty = _inputs(swings=[], imbalances=[], sweeps=[], pools=[], breaks=[])
    ladder = StopCandidateLadder.build(empty)
    assert len(ladder) == 5
    assert [c.rung for c in ladder] == [1, 2, 3, 4, 5]
    assert [c.anchor for c in ladder] == list(LADDER)
    assert all(not c.locatable for c in ladder)


# ---------------------------------------------------------------------------
# Criterion 2 / 2a / 2b — rung 3 is a swept liquidity level
# ---------------------------------------------------------------------------
def test_rung_three_is_located_from_a_swept_liquidity_level():
    """NOT Quasimodo geometry. The rung is a swept prior liquidity level, located from
    PRIM-004's sweep against PRIM-003's pool."""
    ladder = StopCandidateLadder.build(_inputs())
    rung3 = ladder[2]
    assert rung3.anchor == "LIQUIDITY_SWEEP_QML"
    assert rung3.locatable is True
    assert rung3.anchor_object_id == "SW-1"
    # pool 93.0, penetration 3.0, placement BEYOND -> 90.0
    assert rung3.stop_price == pytest.approx(90.0)


def _module_ast():
    """Parse the module, so a guard can tell EXECUTABLE CODE from prose about it.

    A substring scan cannot, and that is not a detail: this module's docstring necessarily
    names `detect_order_blocks()` and `services.ict` in order to explain why it does not use
    them. Under a substring guard, DOCUMENTING the refusal is what trips the check — so the
    cheap fix is to delete the explanation, and the honest fix is to measure the right
    thing. B112 is the same defect in T-0023's producer scan, with the same remedy.
    """
    import ast

    import app.services.rules.gate_027_stop_ladder as mod

    return ast.parse(open(mod.__file__).read()), mod


def _defined_names(tree) -> set[str]:
    """Every name this module BINDS — functions, classes, assignments."""
    import ast

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names


def _called_names(tree) -> set[str]:
    """Every function this module CALLS, by its bare name."""
    import ast

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def test_no_qml_geometry_is_shipped_anywhere_in_the_module():
    """'Never ship Quasimodo geometry — the shape is drawn nowhere and that never blocked
    the rung.' The anchor TOKEN keeps its name (id stability); the DETECTOR must not exist.

    Measured over BOUND AND CALLED NAMES, never raw text: the rule is that no QML shape is
    COMPUTED, not that the word is unsayable.
    """
    tree, _ = _module_ast()
    symbols = {n.lower() for n in _defined_names(tree) | _called_names(tree)}

    # CONTROL: a name that must be present, and one that must not. An empty result is a
    # claim, and it needs the same evidence as a positive one.
    assert "risk_reward" in symbols, "CONTROL: this module must define risk_reward"
    assert "zzz_absent_control" not in symbols, "CONTROL: this must not match"

    for banned in ("quasimodo", "left_shoulder", "right_shoulder", "head_and_shoulders"):
        assert not any(banned in s for s in symbols), (
            f"{banned} is QML geometry and no QML shape is ruled anywhere"
        )


def test_rung_three_unlocatable_needs_a_real_search_failure_with_evidence():
    """Criterion 2a. `locatable: false` on rung 3 is a REAL search failure only, and each
    reason carries `search_evidence` so an auditor can contradict it from the record."""
    no_sweeps = _inputs(sweeps=[], pools=[])
    rung3 = StopCandidateLadder.build(no_sweeps)[2]
    assert rung3.locatable is False
    assert rung3.unlocatable_reason == "NO_SUCH_PRIMITIVE_IN_SEARCH_WINDOW"
    assert rung3.unlocatable_reason in UNLOCATABLE_REASONS
    assert rung3.search_evidence is not None
    assert rung3.missing_producer is None, "rung 3 has a producer; only rung 4 does not"


def test_a_search_failure_without_evidence_is_refused():
    """The guard, made to fail. A bare reason is an unfalsifiable excuse — HG-28 exists so
    the claim can be contradicted from the record alone."""
    with pytest.raises(ValueError, match="search_evidence"):
        StopCandidate(rung=3, anchor="LIQUIDITY_SWEEP_QML", locatable=False,
                      unlocatable_reason="NO_SUCH_PRIMITIVE_IN_SEARCH_WINDOW")


def test_an_invented_unlocatable_reason_is_refused():
    """The enum is a CLOSED set. The withdrawn ruling would have added a fourth value; this
    pins that the code cannot grow one locally."""
    with pytest.raises(ValueError, match="not one of"):
        StopCandidate(rung=3, anchor="LIQUIDITY_SWEEP_QML", locatable=False,
                      unlocatable_reason="QML_SHAPE_UNDEFINED_IN_SOURCE",
                      search_evidence=SearchEvidence(T0, T0))


def test_the_removed_qml_skip_licence_is_not_reachable_from_this_module():
    """T-0027 removed `QML_SHAPE_UNDEFINED_IN_SOURCE` from the schema enum. If this module
    could still emit it, T-0027 would be incomplete and this task must say so rather than
    use it."""
    assert "QML_SHAPE_UNDEFINED_IN_SOURCE" not in UNLOCATABLE_REASONS
    schema_enum = contract.schema()["$defs"]["stop_candidate"]["properties"][
        "unlocatable_reason"]["enum"]
    assert list(UNLOCATABLE_REASONS) == schema_enum, (
        "the module's closed set and the schema's must be the same set, or one of them is "
        "documentation"
    )


def test_the_placement_on_the_swept_level_is_declared_as_ours_and_unratified():
    """Criterion 2b. 'Any old liquidity sweep level' fixes the LEVEL, not where on it the
    stop sits, and his material shows both readings. Ours, stamped, with the competing
    placement recorded so a later ruling re-partitions history rather than invalidating it."""
    assert DECLARED_SWEEP_PLACEMENT.ratified is False
    values = DECLARED_SWEEP_PLACEMENT.as_values()
    assert values["stop_placement_on_swept_level"] == "BEYOND_THE_SWEPT_EXTREME"
    assert values["stop_placement_on_swept_level_ratified"] is False
    assert COMPETING_SWEEP_PLACEMENT == "AT_THE_SWEPT_LEVEL"
    assert COMPETING_SWEEP_PLACEMENT != DECLARED_SWEEP_PLACEMENT.value

    emitted = StopCandidateLadder.evaluate(_inputs()).values
    assert emitted["stop_placement_on_swept_level_ratified"] is False
    assert emitted["competing_placement"] == COMPETING_SWEEP_PLACEMENT


def test_the_imbalance_edge_is_declared_too_and_the_two_are_symmetric():
    """Review's finding, and the asymmetry was worse than either choice alone.

    `GATE-027.inputs` says "the DEEPER open momentum imbalance" — `deeper` selects WHICH
    imbalance and is HIS; WHICH EDGE the stop sits on is stated nowhere and is OURS. That is
    structurally identical to rung 3, where "any old liquidity sweep level" fixes the level
    and not the placement on it.

    Declaring one and hardcoding the other is the defect: a reader who finds
    `DECLARED_SWEEP_PLACEMENT` reasonably infers the undeclared placements are doctrine, so
    the one declaration makes the other look settled.
    """
    assert DECLARED_IMBALANCE_EDGE.ratified is False
    assert DECLARED_IMBALANCE_EDGE.value == "FAR_EDGE"
    assert COMPETING_IMBALANCE_EDGE == "NEAR_EDGE"
    assert COMPETING_IMBALANCE_EDGE != DECLARED_IMBALANCE_EDGE.value

    emitted = StopCandidateLadder.evaluate(_inputs()).values
    assert emitted["stop_placement_on_momentum_imbalance"] == "FAR_EDGE"
    assert emitted["stop_placement_on_momentum_imbalance_ratified"] is False
    assert emitted["competing_imbalance_edge"] == COMPETING_IMBALANCE_EDGE

    # THE SYMMETRY IS THE POINT. Both zone anchors carry the same four keys; if a later edit
    # declares one and not the other, this fails.
    for stem in ("stop_placement_on_swept_level", "stop_placement_on_momentum_imbalance"):
        assert stem in emitted
        assert emitted[f"{stem}_ratified"] is False
        assert emitted[f"{stem}_source"]


def test_only_the_zone_anchors_carry_a_declared_edge():
    """Rungs 1 and 5 name POINTS — "deepest LL/HH", "inner MSB" — so there is no edge to
    pick and declaring one would invent a choice the source never faced. The line is
    anchor-is-a-zone, and it selects exactly rungs 2 and 3."""
    emitted = StopCandidateLadder.evaluate(_inputs()).values
    declared = [k for k in emitted if k.startswith("stop_placement_on_") and
                not k.endswith(("_ratified", "_source"))]
    assert sorted(declared) == [
        "stop_placement_on_momentum_imbalance",
        "stop_placement_on_swept_level",
    ], "exactly the two zone anchors, no more and no fewer"


def test_the_far_edge_is_the_deeper_edge_on_both_directions():
    """FAR_EDGE must mean 'further from entry' on a short as well as a long, or the mirror
    silently places the stop inside the zone."""
    long_rung2 = StopCandidateLadder.build(_inputs())[1]
    assert long_rung2.stop_price == pytest.approx(85.0), "LONG -> the imbalance's LOW"

    short = _inputs(
        entry=100.0, target=70.0, direction="SHORT",
        imbalances=[Imbalance(id="IMB-S", tf="5m", bar_time=T0, price_high=115.0,
                              price_low=112.0, type="FVG", direction="BEARISH",
                              is_momentum_imbalance=True)],
    )
    assert StopCandidateLadder.build(short)[1].stop_price == pytest.approx(115.0), (
        "SHORT -> the imbalance's HIGH, which is the far edge from entry"
    )


# ---------------------------------------------------------------------------
# 1b-iii-CORRECTED (a) and (b) — rung 4 has no contract-side producer
# ---------------------------------------------------------------------------
def test_rung_four_reports_a_producer_gap_and_never_a_search_failure():
    """A PRODUCER GAP IS NOT A SEARCH FAILURE. Filing it as one rebuilds the
    fabricated-excuse shape the round-2 rulings deleted from rung 3."""
    rung4 = StopCandidateLadder.build(_inputs())[3]
    assert rung4.anchor == "ORDER_BLOCK"
    assert rung4.locatable is False
    assert rung4.missing_producer == ORDER_BLOCK_PRODUCER
    assert rung4.unlocatable_reason is None, (
        "rung 4 must NOT claim a search-failure reason — nothing searched"
    )
    assert rung4.search_evidence is None, "no search occurred, so there is no evidence"


def test_rung_four_uses_the_houses_own_vocabulary_for_a_missing_producer():
    """base.py:44's distinction — 'NO PRODUCER EXISTS. Permanent until someone builds one',
    deliberately not the same fact as 'the producer ran and found nothing'.

    The VOCABULARY, not the `ConditionReading` TYPE: that type is for multi-condition rules
    and binding it obliges a module to bind `quorum_blocked` too. GATE-027 has no quorum.
    See `order_block_gap`'s docstring for why the sanctioned exemption was refused.
    """
    gap = StopCandidateLadder.order_block_gap()
    assert gap["state"] == "NOT_EVALUABLE"
    assert gap["missing_producer"] == ORDER_BLOCK_PRODUCER
    assert "unread_producer" not in gap, (
        "NOT_READ would say a producer EXISTS and nobody called it — the opposite claim"
    )


def test_this_module_does_not_bind_condition_reading_and_so_needs_no_exemption():
    """The guard that caught this must stay live on this module.

    `check_partial_rules.py` fails any module binding `ConditionReading` without binding
    `quorum_blocked`, and its `INLINE_EXEMPT` list would have accepted this rule as "a
    single-condition rule, the legitimate case". The exemption was refused: the grep layer
    only fails a module whose `binds_helper` is TRUE, so an exempt module is unreachable by
    BOTH checks and one entry retires the guard for the whole file.

    This pins the refusal, so a later edit cannot re-introduce the binding quietly.
    """
    import app.services.rules.gate_027_stop_ladder as mod

    from app.services.rules import base as rules_base

    assert getattr(mod, "ConditionReading", None) is not rules_base.ConditionReading, (
        "binding ConditionReading here obliges binding quorum_blocked, and this rule has "
        "no quorum to block"
    )


def test_a_rung_cannot_claim_both_a_producer_gap_and_a_search_failure():
    """'Nobody built one' and 'I looked and found nothing' are different facts with
    different owners. A rung reporting both has decided neither."""
    with pytest.raises(ValueError, match="both"):
        StopCandidate(rung=4, anchor="ORDER_BLOCK", locatable=False,
                      missing_producer=ORDER_BLOCK_PRODUCER,
                      unlocatable_reason="NO_SUCH_PRIMITIVE_IN_SEARCH_WINDOW",
                      search_evidence=SearchEvidence(T0, T0))


def test_gate_027_declares_it_cannot_fire_without_an_order_block_producer():
    """(b) — so rung 4 lands in the implemented-but-CANNOT-FIRE bucket rather than inflating
    effective coverage. TARGET-001's precedent, which kept that figure honest."""
    assert ORDER_BLOCK_PRODUCER in StopCandidateLadder.CANNOT_FIRE_WITHOUT


def test_no_rule_module_reaches_into_the_pre_contract_ict_detector():
    """`detect_order_blocks()` exists in the PRE-CONTRACT strategy. Importing it would adopt
    that detector's semantics as doctrine — the move TARGET-001 refuses.

    NAMING IT IN PROSE IS FINE; IMPORTING OR CALLING IT IS ADOPTING IT. The module docstring
    has to name it to explain the refusal, so this walks imports and call sites instead of
    scanning text — otherwise documenting the refusal is what fails the check.
    """
    import ast

    tree, _ = _module_ast()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    # CONTROL: an import that must be there, and one that must not.
    assert "app.services.rules.prim_004_sweeps" in imported, "CONTROL: must hit"
    assert "app.services.zzz_absent" not in imported, "CONTROL: must not hit"

    assert not any(m.startswith("app.services.ict") for m in imported), (
        "importing the pre-contract detector adopts its semantics as doctrine"
    )
    assert "detect_order_blocks" not in _called_names(tree), (
        "the module may explain why it does not call this; it may not call it"
    )


# ---------------------------------------------------------------------------
# Criterion 4 — the full candidate table is required telemetry
# ---------------------------------------------------------------------------
def test_the_candidate_table_carries_every_rung_including_rejected_and_unlocatable():
    """'Full candidate table [{anchor, stop_price, rr, accepted}] — required telemetry,
    since conformance is tested from it.' A table containing only the winner cannot support
    conformance and IS the defect."""
    out = evaluate_stop_pipeline(_inputs())
    table = out["GATE-025"].values["candidate_table"]
    assert len(table) == 5, "every rung appears, not only the survivors"
    assert [row["rung"] for row in table] == [1, 2, 3, 4, 5]

    rejected = [row for row in table if row.get("rejection_reason") == "RR_BELOW_2R"]
    assert rejected, "the 1R rung must appear as rejected, not be dropped"
    assert rejected[0]["rr"] == pytest.approx(1.0), "with its rr present"
    assert rejected[0]["accepted"] is False


def test_a_rejected_candidate_keeps_its_rr_so_the_rejection_is_checkable():
    """A rejection recorded without the number it was rejected for cannot be audited."""
    table = RewardFloor.table(_inputs(), StopCandidateLadder.build(_inputs()))
    rung1 = table[0]
    assert rung1.accepted is False
    assert rung1.rejection_reason == "RR_BELOW_2R"
    assert rung1.rr == pytest.approx(1.0)
    assert rung1.rr < RR_FLOOR


def test_the_floor_is_the_registrys_and_not_a_literal():
    """Drives the PUBLIC ENTRY POINT and compares to the registry, not to a retyped 2.0."""
    registry_floor = contract.rule("GATE-025")["values"]["rr_floor"]
    assert RR_FLOOR == registry_floor
    emitted = RewardFloor.evaluate(_inputs(), StopCandidateLadder.build(_inputs()))
    assert emitted.values["rr_floor"] == registry_floor


@pytest.mark.parametrize("rr,expected", [(1.999, False), (2.0, True), (2.001, True)])
def test_the_floor_is_inclusive_at_exactly_2r(rr, expected):
    """'2R is the minimum acceptable reward' — at 2R the candidate is ACCEPTED. The edge is
    pinned because GATE-031 (T-0030) flags the degenerate runner at exactly this value, and
    the same predicate with opposite edges is how T-0022 lost time."""
    stop = ENTRY - (TARGET - ENTRY) / rr
    ladder = [StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True,
                            stop_price=stop, anchor_object_id="X", _entry=ENTRY)]
    assert RewardFloor.table(_inputs(), ladder)[0].accepted is expected


# ---------------------------------------------------------------------------
# Criterion 3 / 3a — the selector, and the three wrong implementations
# ---------------------------------------------------------------------------
def test_the_worked_table_selects_the_rung_the_pdf_selects():
    """GATE-028's worked table, driven through the real pipeline. The PDF's own answer is
    the Liquidity Sweep at 3R."""
    out = evaluate_stop_pipeline(_inputs())
    chosen = out["selected"]
    assert chosen.rung == 3
    assert chosen.anchor == "LIQUIDITY_SWEEP_QML"
    assert chosen.rr == pytest.approx(3.0)


def test_the_selector_separates_the_three_wrong_implementations():
    """Criterion 3a. On ONE table, each wrong form picks a DIFFERENT rung.

    The fourth wrong form — first in ladder order IGNORING the floor — is not separable
    here: with the mandated floor applied it lands on the same rung as first-clearing-2R.
    It is caught by the floor assertion instead, and the test below names that.
    """
    table = RewardFloor.table(_inputs(), StopCandidateLadder.build(_inputs()))
    survivors = [c for c in table if c.accepted]

    rule = ClosestTo3RSelector.select(table)
    highest_rr = max(survivors, key=lambda c: c.rr)
    first_clearing = survivors[0]

    assert rule.rung == 3, "argmin |rr - 3.0| — the rule"
    assert highest_rr.rung == 5, "max(key=rr) picks the 10R Inner MSB"
    assert first_clearing.rung == 2, "first clearing 2R picks the 2R Momentum Imbalance"
    assert len({rule.rung, highest_rr.rung, first_clearing.rung}) == 3, (
        "three distinct answers, so no two of these implementations can be confused"
    )


def test_first_in_ladder_order_ignoring_the_floor_is_caught_by_the_floor():
    """The fourth wrong form. It picks rung 1 at 1R, which the floor rejects — so the guard
    that catches it is the floor, not the selector."""
    table = RewardFloor.table(_inputs(), StopCandidateLadder.build(_inputs()))
    naive_first = table[0]
    assert naive_first.rung == 1
    assert naive_first.rr == pytest.approx(1.0)
    assert naive_first.accepted is False, "the floor is what rejects it"
    assert ClosestTo3RSelector.select(table).rung != naive_first.rung


def test_the_selector_never_optimises_for_the_highest_rr():
    """GATE-025 states it outright: 'The engine must NOT optimise for the highest possible
    RR — it should optimize for the best balance between market protection and reward
    potential.' The 10R rung is ACCEPTED and NOT SELECTED, and both halves matter."""
    table = RewardFloor.table(_inputs(), StopCandidateLadder.build(_inputs()))
    ten_r = [c for c in table if c.rung == 5][0]
    assert ten_r.accepted is True, "10R clears the floor — it is admissible"
    assert ClosestTo3RSelector.select(table).rung != 5, "and it is still not chosen"


def test_the_preferred_value_is_the_registrys_three_r():
    """argmin is taken against the registry's `rr_preferred`, not a literal 3.0."""
    assert RR_PREFERRED == contract.rule("GATE-025")["values"]["rr_preferred"]
    emitted = ClosestTo3RSelector.evaluate(
        RewardFloor.table(_inputs(), StopCandidateLadder.build(_inputs())))
    assert emitted.values["rr_preferred"] == RR_PREFERRED


# ---------------------------------------------------------------------------
# Criterion 3b — the tie-break, in two cases
# ---------------------------------------------------------------------------
def test_case_a_a_tie_resolves_to_the_larger_stop_which_is_the_lower_rr():
    """CASE A — the doctrine's own numbers, with the QML row dropped so |2-3| = |4-3| = 1.

    THIS IS WHERE INTUITION FAILS. 'Ties toward the larger (more cushioned) stop', and rr
    falls monotonically as the stop widens, so the larger stop has the LOWER rr: the answer
    is the 2R candidate, not the 4R one.

    This case CANNOT fail against a list-order implementation — see Case B. It is here to
    pin the DOCTRINE's direction, which is the half a reader gets wrong.
    """
    table = [_candidate(2, "MOMENTUM_IMBALANCE", 2.0), _candidate(4, "ORDER_BLOCK", 4.0)]
    chosen = ClosestTo3RSelector.select(table)
    assert abs(table[0].rr - RR_PREFERRED) == abs(table[1].rr - RR_PREFERRED), "a real tie"
    assert chosen.rr == pytest.approx(2.0), "ties to the LARGER stop = the LOWER rr"
    assert chosen.cushion > table[1].cushion, "and that is the larger cushion, measured"


def test_case_b_the_tie_breaks_on_cushion_and_not_on_list_position():
    """CASE B — the case that can actually go red.

    Ladder order and stop width DISAGREE here: rung 2 is the TIGHTER stop and rung 4 the
    wider. A `min()` over |rr - 3.0| alone returns the first minimum — rung 2 — which is
    WRONG. Only a tie-break keyed on measured cushion gets rung 4.

    Non-monotonic is legitimate rather than contrived: GATE-027's cushion-monotonic claim is
    unproven prose and T-0030 is the task that measures it.
    """
    table = [_candidate(2, "MOMENTUM_IMBALANCE", 4.0), _candidate(4, "ORDER_BLOCK", 2.0)]
    chosen = ClosestTo3RSelector.select(table)

    naive = min(table, key=lambda c: abs(c.rr - RR_PREFERRED))
    assert naive.rung == 2, "the list-order implementation picks rung 2"
    assert chosen.rung == 4, "the rule picks the larger cushion, which is rung 4"
    assert chosen.rung != naive.rung, (
        "if these ever agree this fixture has gone vacuous and proves nothing"
    )
    assert chosen.cushion > naive.cushion


def test_the_tie_break_prefers_cushion_over_ladder_position_in_both_orderings():
    """The same tie presented in both list orders must give the same answer. If reversing
    the list changes the winner, the tie-break is reading position."""
    a = _candidate(2, "MOMENTUM_IMBALANCE", 4.0)
    b = _candidate(4, "ORDER_BLOCK", 2.0)
    assert ClosestTo3RSelector.select([a, b]).rung == ClosestTo3RSelector.select([b, a]).rung


# ---------------------------------------------------------------------------
# GATE-026 — best_rr and the terminal skip
# ---------------------------------------------------------------------------
def test_best_rr_is_the_max_over_locatable_rungs():
    out = evaluate_stop_pipeline(_inputs())
    assert out["best_rr"] == pytest.approx(10.0)
    assert out["GATE-026"].values["best_rr"] == pytest.approx(10.0)


def test_best_rr_is_none_when_no_rung_was_locatable_and_none_is_not_zero():
    """'null is the correct value when NO rung was locatable at all… a maximum over an empty
    set must be representable rather than forced to a fabricated number.'

    0.0 would collapse 'the engine could not build a ladder' into 'every candidate was
    terrible'. Different records, different remedies.
    """
    empty = _inputs(swings=[], imbalances=[], sweeps=[], pools=[], breaks=[])
    table = RewardFloor.table(empty, StopCandidateLadder.build(empty))
    assert NoCandidateReaches2R.best_rr(table) is None
    ev = NoCandidateReaches2R.evaluate(table)
    assert ev.values["best_rr"] is None
    assert ev.values["decision"] == "BLOCK"
    assert ev.values["block_reason"] == "NO_CANDIDATE_REACHES_2R"


def test_every_rung_below_2r_is_a_terminal_skip():
    """GATE-026: 'no trade is taken. This is a terminal skip — it is not licence to move the
    target, widen the reward, or re-anchor the stop outside the five categories.'"""
    table = [_candidate(1, "DEEPEST_SWING", 1.0, accepted=False),
             _candidate(2, "MOMENTUM_IMBALANCE", 1.5, accepted=False)]
    ev = NoCandidateReaches2R.evaluate(table)
    assert ev.verdict == "FAIL"
    assert ev.values["decision"] == "BLOCK"
    assert ev.values["block_reason"] == "NO_CANDIDATE_REACHES_2R"
    assert ev.values["best_rr"] == pytest.approx(1.5), (
        "best_rr is still reported — the skip must carry the evidence it was decided on"
    )
    assert ClosestTo3RSelector.select(table) is None, "nothing to select among"


# ---------------------------------------------------------------------------
# GATE-028 — the reading that shipped is logged
# ---------------------------------------------------------------------------
def test_the_selection_reading_is_logged_and_matches_the_registry():
    """GATE-028's output: 'selection_rule_id — MUST be logged so conformance can test which
    reading actually shipped, and so the learning loop can attribute outcomes to it.'"""
    ev = ClosestTo3RSelector.evaluate(
        RewardFloor.table(_inputs(), StopCandidateLadder.build(_inputs())))
    assert ev.values["selection_rule_id"] == "CLOSEST_TO_3R_TIES_TO_LARGER"
    assert ev.values["selection_rule_id"] == contract.rule("GATE-028")["values"][
        "operative_reading"]
    assert ev.values["competing_reading"] == COMPETING_READING == "LARGEST_ABOVE_2R"


def test_the_shipped_reading_is_one_the_schema_allows():
    schema_enum = contract.schema()["$defs"]["setup_evaluation"]["properties"][
        "stop_evaluation"]["properties"]["selection_rule_id"]["enum"]
    assert SELECTION_READING in schema_enum
    assert COMPETING_READING in schema_enum


def test_the_competing_reading_would_choose_a_different_stop():
    """GATE-028's whole substance: 'largest >=2R' selects the 2R Momentum Imbalance while
    'closest to 3R' selects the 3R Liquidity Sweep — TWO DIFFERENT STOPS and two different
    position sizes. If they ever agreed the DEFECT row would be moot."""
    table = RewardFloor.table(_inputs(), StopCandidateLadder.build(_inputs()))
    survivors = [c for c in table if c.accepted]
    largest_above_2r = max(survivors, key=lambda c: c.cushion)
    closest_to_3r = ClosestTo3RSelector.select(table)
    assert largest_above_2r.rung == 2
    assert closest_to_3r.rung == 3
    assert largest_above_2r.stop_price != closest_to_3r.stop_price


# ---------------------------------------------------------------------------
# Criterion 7 — four rules, four artefacts, not one function
# ---------------------------------------------------------------------------
def test_the_four_rules_are_four_distinct_implementations():
    """'A single select_stop() returning a price satisfies none of their telemetry.'"""
    registered = implementations()
    assert registered["GATE-027"] is StopCandidateLadder
    assert registered["GATE-025"] is RewardFloor
    assert registered["GATE-026"] is NoCandidateReaches2R
    assert registered["GATE-028"] is ClosestTo3RSelector
    assert len({StopCandidateLadder, RewardFloor, NoCandidateReaches2R,
                ClosestTo3RSelector}) == 4


def test_each_rule_emits_its_own_artefact_and_not_the_others():
    """The artefacts are distinct, and each rule's own id is on its own record."""
    out = evaluate_stop_pipeline(_inputs())

    assert out["GATE-027"].rule_id == "GATE-027"
    assert "ladder" in out["GATE-027"].values
    assert "candidate_table" not in out["GATE-027"].values

    assert out["GATE-025"].rule_id == "GATE-025"
    assert "candidate_table" in out["GATE-025"].values
    assert "selected_stop" not in out["GATE-025"].values

    assert out["GATE-026"].rule_id == "GATE-026"
    assert "best_rr" in out["GATE-026"].values
    assert "selected_stop" not in out["GATE-026"].values

    assert out["GATE-028"].rule_id == "GATE-028"
    assert "selected_stop" in out["GATE-028"].values
    assert "best_rr" not in out["GATE-028"].values


# ---------------------------------------------------------------------------
# rr arithmetic — the sign errors that sort perfectly well
# ---------------------------------------------------------------------------
def test_a_stop_on_the_wrong_side_of_entry_is_refused_not_scored():
    """A stop above entry on a long is not a tight stop — it is an instant loss, and its rr
    computes to a negative number that sorts fine."""
    with pytest.raises(StopCandidateNotComparable, match="wrong side"):
        risk_reward(_inputs(), 110.0)


def test_a_stop_at_entry_is_refused_rather_than_returning_infinity():
    """inf would win every selector, forever."""
    with pytest.raises(StopCandidateNotComparable, match="risk is zero"):
        risk_reward(_inputs(), ENTRY)


def test_a_wrong_side_anchor_becomes_an_unlocatable_rung_with_its_reason():
    """It is not dropped — it is recorded with the reason the enum has for exactly this."""
    ladder = [StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True,
                            stop_price=110.0, anchor_object_id="S-9", _entry=ENTRY)]
    row = RewardFloor.table(_inputs(), ladder)[0]
    assert row.locatable is False
    assert row.unlocatable_reason == "PRIMITIVE_ON_WRONG_SIDE_OF_ENTRY"
    assert row.search_evidence is not None


def test_a_short_computes_rr_the_other_way_round():
    """The mirror. A short's stop sits ABOVE entry and its target BELOW."""
    short = _inputs(entry=100.0, target=70.0, direction="SHORT")
    assert risk_reward(short, 110.0) == pytest.approx(3.0)
    with pytest.raises(StopCandidateNotComparable):
        risk_reward(short, 90.0)


def test_a_target_on_the_wrong_side_of_entry_is_refused_at_construction():
    """A negative reward would make every rr a sign error wearing a number."""
    with pytest.raises(ValueError, match="reward is negative"):
        _inputs(entry=100.0, target=90.0, direction="LONG")


# ---------------------------------------------------------------------------
# Structural guards on the candidate itself
# ---------------------------------------------------------------------------
def test_a_locatable_rung_without_a_price_is_refused():
    """'A located anchor with no price is a truncated ladder wearing a tick.'"""
    with pytest.raises(ValueError, match="no stop_price"):
        StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True)


def test_an_unlocatable_rung_carrying_a_price_is_refused():
    with pytest.raises(ValueError, match="not locatable but carries"):
        StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=False, stop_price=70.0)


def test_the_deepest_swing_is_the_deepest_and_not_the_nearest():
    """Rung 1 is the widest cushion BY DEFINITION and that is why it sits first. Two swings,
    and the nearer one must lose."""
    inputs = _inputs(swings=[
        Swing(id="S-near", tf="5m", bar_time=T0, price=95.0, kind="LOW", bar_index=9),
        Swing(id="S-deep", tf="5m", bar_time=T0, price=70.0, kind="LOW", bar_index=10),
    ])
    rung1 = StopCandidateLadder.build(inputs)[0]
    assert rung1.anchor_object_id == "S-deep"
    assert rung1.stop_price == pytest.approx(70.0)


def test_swings_before_the_msb_are_not_eligible():
    """'Deepest LL/HH AFTER the MSB.' A deeper swing that printed before it is not the
    trade's structure."""
    inputs = _inputs(swings=[
        Swing(id="S-old", tf="5m", bar_time=T0, price=50.0, kind="LOW", bar_index=1),
        Swing(id="S-new", tf="5m", bar_time=T0, price=70.0, kind="LOW", bar_index=9),
    ])
    rung1 = StopCandidateLadder.build(inputs)[0]
    assert rung1.anchor_object_id == "S-new", "S-old is deeper but predates the MSB"


def test_the_inner_msb_is_the_innermost_break_not_the_outermost():
    """Rung 5 is the TIGHTEST by definition — the mirror of rung 1."""
    inputs = _inputs(breaks=[
        BreakEvent(id="B-far", tf="5m", bar_time=T0, type="MSB", scale="MINOR",
                   consumed_swing_id="S-1", break_price=80.0, bar_index=11),
        BreakEvent(id="B-inner", tf="5m", bar_time=T0, type="MSB", scale="MINOR",
                   consumed_swing_id="S-1", break_price=97.0, bar_index=12),
    ])
    rung5 = StopCandidateLadder.build(inputs)[4]
    assert rung5.anchor_object_id == "B-inner"


def test_a_filled_imbalance_is_not_an_open_momentum_imbalance():
    """'The deeper OPEN momentum imbalance.' A filled one is not a cushion."""
    inputs = _inputs(imbalances=[
        Imbalance(id="IMB-filled", tf="5m", bar_time=T0, price_high=88.0, price_low=85.0,
                  type="FVG", direction="BULLISH", is_momentum_imbalance=True,
                  fill_state="FILLED"),
    ])
    rung2 = StopCandidateLadder.build(inputs)[1]
    assert rung2.locatable is False
    assert rung2.unlocatable_reason == "NO_SUCH_PRIMITIVE_IN_SEARCH_WINDOW"


def test_a_non_momentum_imbalance_is_not_rung_two():
    """PRIM-002 leaves `is_momentum_imbalance` None when no declared threshold was supplied.
    None is 'not assessed' and must not be read as True."""
    inputs = _inputs(imbalances=[
        Imbalance(id="IMB-unassessed", tf="5m", bar_time=T0, price_high=88.0,
                  price_low=85.0, type="FVG", direction="BULLISH",
                  is_momentum_imbalance=None),
    ])
    assert StopCandidateLadder.build(inputs)[1].locatable is False
