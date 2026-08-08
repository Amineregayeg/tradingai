"""Structure-box grading and the correlate layout (M4).

These are the two graders that key the 3×3 risk matrix. Nothing in the conformance suite can
tell you whether a box the engine called MANIPULATED actually is one — the scorecard says so
explicitly — so a systematically wrong grader here scores 100% CONFORMANT while mis-sizing
every trade. That is readiness gate 7's problem and it needs a human with the charts.

What these tests CAN pin is the arithmetic and the precedence: that agreement is sign-relative
rather than directional, that the ladder is monotonic in fuel count, that a missing imbalance
tap yields no grade at all, and that every ambiguous input resolves DOWN the ladder rather
than up. Each of those is a place where being wrong costs real risk on a real order.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.rules.gate_002_disturbance import (
    BANNED_INPUTS,
    AlignmentForms,
    CorrelateRead,
    CorrelationIsSelectionOnly,
    DisturbanceClassifier,
    HeavyDisturbanceSkip,
    MainAssetCountChoice,
    PanelAgreement,
    StructuralNotStatistical,
)
from app.services.rules.gate_008_roster import (
    MAIN,
    NEGATIVE,
    POSITIVE,
    AlignmentTimeframe,
    LayoutRoster,
)
from app.services.rules.grade_001_structure_box import BoxScopeDeclaration, StructureBoxes
from app.services.rules.grade_002_box_grade import (
    LADDER,
    BoxEvidence,
    BoxGradeLadder,
    ManipulatedDefinitionChoice,
    PoiTimingGate,
    grade_box,
)
from app.services.rules.grade_008_fake_msb import FakeMSBClassifier
from app.services.rules.prim_001_swings import Bar, Swing
from app.services.rules.prim_002_imbalances import Imbalance
from app.services.rules.prim_005_breaks import BreakEvent

T0 = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
TF = "15M"


def candles(rows: list[tuple[float, float, float, float]]) -> list[Bar]:
    return [Bar(time=T0 + timedelta(minutes=15 * i), high=h, low=lo, open=o, close=c)
            for i, (o, h, lo, c) in enumerate(rows)]


def swing(price: float, kind: str, i: int, tag: str = "") -> Swing:
    return Swing(id=f"sw-{i}-{kind[0]}{tag}", tf=TF, bar_time=T0 + timedelta(minutes=15 * i),
                 price=price, kind=kind, bar_index=i)  # type: ignore[arg-type]


def brk(i: int, direction: str, consumed: str, kind: str = "BOS") -> BreakEvent:
    return BreakEvent(id=f"brk-{i}", tf=TF, bar_time=T0 + timedelta(minutes=15 * i),
                      type=kind, scale="MAIN", consumed_swing_id=consumed,  # type: ignore[arg-type]
                      break_price=0.0, direction=direction, bar_index=i)  # type: ignore[arg-type]


def read(asset: str, flow: str, **kw) -> CorrelateRead:
    return CorrelateRead(  # type: ignore[arg-type]
        asset=asset, tf=TF, observed_order_flow=flow, **kw
    )


def aligned_long_layout(**overrides) -> list[CorrelateRead]:
    """A textbook BTC long: BTC/ETH/TOTAL bullish, USDT.D bearish."""
    flows = {MAIN: "BULLISH", POSITIVE[0]: "BULLISH", POSITIVE[1]: "BULLISH",
             NEGATIVE[0]: "BEARISH"}
    flows.update(overrides)
    return [read(asset, flow) for asset, flow in flows.items()]


# ===========================================================================
# GATE-008 — the roster
# ===========================================================================
def test_the_roster_is_four_named_panels_with_usdtd_negative():
    panels = LayoutRoster.for_instrument("BTC/USD")
    assert [p.asset for p in panels] == [MAIN, *POSITIVE, *NEGATIVE]
    assert LayoutRoster.layout_size() == 4
    assert [p.role for p in panels] == ["MAIN", "POSITIVE", "POSITIVE", "NEGATIVE"]
    assert next(p for p in panels if p.asset == "USDT.D").role_sign == -1


def test_a_btc_long_expects_usdtd_to_fall():
    """The roster is where 'negative' lives. Everything downstream reads the sign from here."""
    expected = LayoutRoster.expected_signs("LONG")
    assert expected[MAIN] == "BULLISH"
    assert expected["ETHUSDT.P"] == "BULLISH"
    assert expected["TOTAL"] == "BULLISH"
    assert expected["USDT.D"] == "BEARISH"
    assert LayoutRoster.expected_signs("SHORT")["USDT.D"] == "BULLISH", "not mirrored"


def test_an_altcoin_is_refused_rather_than_given_a_best_effort_layout():
    """"we can not rely on any kind of magic alignments when we trade Altcoins" — so
    GATE-001/002 have no defined behaviour, and a made-up grade would key a real size."""
    with pytest.raises(ValueError, match="no ruled layout"):
        LayoutRoster.for_instrument("SOL/USD")


# ===========================================================================
# GATE-048 — the inversion this module exists to prevent
# ===========================================================================
def test_a_falling_usdtd_on_a_long_is_agreement_not_disagreement():
    """THE headline test. A raw directional scorer reads BEARISH as −1 and counts USDT.D as
    disturbed on every correct BTC long — moving the disturbance grade one level on every
    setup, which moves the risk cell and can turn a tradable LIGHT into a HEAVY hard skip."""
    usdtd = next(p for p in LayoutRoster.PANELS if p.asset == "USDT.D")
    assert PanelAgreement.agreement_state(usdtd, "BEARISH", "LONG") == "ALIGNED"
    assert PanelAgreement.agreement_state(usdtd, "BULLISH", "LONG") == "DISTURBED"
    assert PanelAgreement.agreement_state(usdtd, "BULLISH", "SHORT") == "ALIGNED"


def test_a_textbook_long_layout_grades_none_not_light():
    """The end-to-end form of the same bug: if USDT.D were inverted, this perfectly aligned
    layout would report one disturbed asset and grade LIGHT."""
    d = DisturbanceClassifier.classify(aligned_long_layout(), direction="LONG")
    assert d.disturbed_count == 0
    assert d.grade == "NONE"
    assert all(p.agreement_state == "ALIGNED" for p in d.panels)


@pytest.mark.parametrize(
    "overrides, count, grade",
    [
        ({}, 0, "NONE"),
        ({POSITIVE[0]: "BEARISH"}, 1, "LIGHT"),
        ({POSITIVE[0]: "BEARISH", NEGATIVE[0]: "BULLISH"}, 2, "HEAVY"),
        ({POSITIVE[0]: "BEARISH", POSITIVE[1]: "BEARISH", NEGATIVE[0]: "BULLISH"}, 3, "HEAVY"),
    ],
)
def test_the_disturbance_count_is_an_absolute_boundary(overrides, count, grade):
    """0 → NONE · exactly 1 → LIGHT · 2 or more → HEAVY. The first hard boundary anywhere in
    the corpus, and an ABSOLUTE count — never a ratio (GATE-003)."""
    d = DisturbanceClassifier.classify(aligned_long_layout(**overrides), direction="LONG")
    assert (d.disturbed_count, d.grade) == (count, grade)
    assert d.layout_size == 4, "layout_size must be logged with every grade"


def test_the_main_asset_is_not_counted_but_its_disagreement_is_reported():
    """"a main asset that disagrees with its own setup is not a disturbance, it is an absent
    setup" — so it is excluded from the count and surfaced on its own channel."""
    d = DisturbanceClassifier.classify(
        aligned_long_layout(**{MAIN: "BEARISH"}), direction="LONG")
    assert d.disturbed_count == 0, "the main asset was folded into the count"
    assert d.grade == "NONE"
    assert d.main_asset_disagrees is True
    assert d.main_asset_counted is False
    assert MainAssetCountChoice.MAIN_ASSET_COUNTS is False


def test_a_missing_panel_read_is_disturbed_not_skipped():
    """The layout is fixed by name, so an absent read means the alignment was never done for
    that asset. Counting it as aligned would let a broken feed manufacture a NONE grade."""
    partial = [r for r in aligned_long_layout() if r.asset != "TOTAL"]
    d = DisturbanceClassifier.classify(partial, direction="LONG")
    assert d.disturbed_count == 1
    assert next(p for p in d.panels if p.asset == "TOTAL").disturbed is True


def test_an_off_condition_disturbs_a_panel_whose_order_flow_agrees():
    """Disturbance is not only about direction — the other five conditions are structural."""
    reads = aligned_long_layout()
    reads[1] = read(POSITIVE[0], "BULLISH", expected_break_confirmed=False)
    d = DisturbanceClassifier.classify(reads, direction="LONG")
    panel = next(p for p in d.panels if p.asset == POSITIVE[0])
    assert panel.agreement_state == "ALIGNED"
    assert panel.disturbed is True
    assert "OC2_FAILED_EXPECTED_BREAK" in panel.off_conditions


def test_the_unquantifiable_off_condition_is_reported_unevaluated_not_guessed():
    """OC4 'reacts significantly before or after the others' is unquantified, and every way
    to quantify it — candle counts, time delays — is on GATE-005's ban list."""
    d = DisturbanceClassifier.classify(aligned_long_layout(), direction="LONG")
    assert d.unevaluated_off_conditions == ["OC4_OUT_OF_STEP"]

    reads = aligned_long_layout()
    reads[1] = read(POSITIVE[0], "BULLISH", reaction_out_of_step=True)
    judged = DisturbanceClassifier.classify(reads, direction="LONG")
    assert judged.unevaluated_off_conditions == []
    assert judged.disturbed_count == 1


# ===========================================================================
# GATE-005 / GATE-006 — the negative gates
# ===========================================================================
def test_the_banned_statistical_inputs_are_named_so_the_negative_is_testable():
    """A conformance assertion with no enumerated tokens has nothing to assert against."""
    check = DisturbanceClassifier.banned_input_check()
    assert set(check["checked"]) == set(BANNED_INPUTS)
    assert check["present"] == []
    assert "correlation_coefficient" in CorrelationIsSelectionOnly.banned_input_check()["checked"]


def test_a_decision_built_on_a_correlation_coefficient_fails_the_ban():
    ok, present = StructuralNotStatistical.check({"structure": "MSB", "swing_id": "sw-1"})
    assert ok and present == []

    ok, present = StructuralNotStatistical.check({"correlation_coefficient": 0.71})
    assert not ok
    assert present == ["correlation_coefficient"]


# ===========================================================================
# GATE-009 / GATE-007 — alignment without rigidity
# ===========================================================================
def test_alignment_passes_without_every_asset_printing_the_same_candle():
    """"That would be too rigid." The gate must pass on any of the six forms, so this asserts
    it passes with form (a) absent — the failure mode is an engine stricter than documented,
    quietly refusing setups the trader would have taken."""
    reads = [
        read(MAIN, "BULLISH", break_state="MSB_IN_WINDOW", liquidity_objective_id="lq-1"),
        read(POSITIVE[0], "BULLISH", break_state="ALREADY_MSB_CONTINUING_BOS",
             liquidity_objective_id="lq-1"),
        read(POSITIVE[1], "BULLISH", break_state="NONE", liquidity_objective_id="lq-1"),
        read(NEGATIVE[0], "BEARISH", break_state="NONE", liquidity_objective_id="lq-1"),
    ]
    d = DisturbanceClassifier.classify(reads, direction="LONG")
    passed, forms = AlignmentForms.check(reads, d)

    assert passed
    assert "A_ALL_MSB_SAME_WINDOW" not in forms, "form (a) should not be satisfied here"
    assert "B_ALREADY_MSB_CONTINUING_BOS" in forms
    assert "E_NEGATIVE_OPPOSITE_AS_EXPECTED" in forms
    assert "F_SIMILAR_TARGET_LOGIC" in forms


def test_a_layout_read_on_mixed_timeframes_is_a_violation():
    """"All assets must be checked on the same timeframe when confirming the entry.\""""
    reads = aligned_long_layout()
    reads[2] = CorrelateRead(asset=POSITIVE[1], tf="5M", observed_order_flow="BULLISH")
    ok, why = AlignmentTimeframe.check_all(reads, TF)
    assert not ok and "different timeframes" in why

    assert AlignmentTimeframe.check_all(aligned_long_layout(), TF)[0]
    assert not AlignmentTimeframe.check("1H", "15M")[0]


# ===========================================================================
# GATE-001 — the hard filter
# ===========================================================================
def test_heavy_disturbance_blocks_even_a_manipulated_box():
    """"no trade regardless of the Structure Box." There is no override path, and the box
    grade is recorded precisely so conformance can prove the gate fired BEFORE sizing."""
    d = DisturbanceClassifier.classify(
        aligned_long_layout(**{POSITIVE[0]: "BEARISH", NEGATIVE[0]: "BULLISH"}),
        direction="LONG")
    out = HeavyDisturbanceSkip.check(d, box_grade="MANIPULATED")

    assert d.grade == "HEAVY"
    assert out["decision"] == "BLOCK"
    assert out["block_reason"] == "HEAVY_DISTURBANCE"
    assert out["risk_pct"] == 0.0
    assert out["structure_box_grade"] == "MANIPULATED", "recorded, and deliberately ignored"
    assert set(out["disturbed_asset_list"]) == {POSITIVE[0], NEGATIVE[0]}


def test_light_disturbance_does_not_block():
    d = DisturbanceClassifier.classify(
        aligned_long_layout(**{POSITIVE[0]: "BEARISH"}), direction="LONG")
    out = HeavyDisturbanceSkip.check(d, box_grade="STANDARD")
    assert d.grade == "LIGHT"
    assert out["decision"] == "CONTINUE"
    assert "risk_pct" not in out, "only the heavy path forces a risk figure"


# ===========================================================================
# GRADE-001 — the box
# ===========================================================================
#: An up-leg: swing high at bar 3, pullback low at bar 4, break above at bar 5.
UP_BARS = candles([
    (100, 102, 98, 101),    # 0
    (99, 101, 90, 95),      # 1
    (95, 105, 94, 104),     # 2
    (104, 110, 103, 109),   # 3  swing HIGH 110
    (109, 109, 100, 101),   # 4  pullback LOW 100 -> the strong low
    (101, 115, 102, 114),   # 5  break above 110
    (114, 116, 108, 112),   # 6  back toward the box, still above the gap
    (112, 113, 104, 111),   # 7  taps the 104-107 gap
    (111, 116, 110, 115),   # 8
])
UP_HIGH = swing(110, "HIGH", 3)
UP_LOW = swing(100, "LOW", 4)
UP_BREAK = brk(5, "UP", UP_HIGH.id)


def up_box():
    boxes = StructureBoxes.construct(UP_BARS, [UP_HIGH, UP_LOW], [UP_BREAK], tf=TF)
    assert len(boxes) == 1
    return boxes[0]


def test_the_box_is_capped_by_the_broken_level_and_floored_by_the_strong_low():
    box = up_box()
    assert box.direction == "UP"
    assert box.box_high == 110, "the breaking candle's overshoot is the break, not the box"
    assert box.box_low == 100
    assert box.strong_swing_price == box.box_low, "the box extreme IS the strong low"
    assert box.birth_break_type == "BOS"


def test_no_break_means_no_box_which_means_nothing_can_be_sized():
    """GRADE-001's last sentence: no box ⇒ no box grade ⇒ the risk matrix cannot be looked
    up. That has to stay distinguishable from a box that graded badly."""
    assert StructureBoxes.construct(UP_BARS, [UP_HIGH, UP_LOW], [], tf=TF) == []


def test_a_box_whose_break_has_not_printed_yet_is_not_the_latest_box():
    boxes = StructureBoxes.construct(UP_BARS, [UP_HIGH, UP_LOW], [UP_BREAK], tf=TF)
    assert StructureBoxes.latest(boxes, as_of_index=5) is None, "look-ahead: break is AT the bar"
    assert StructureBoxes.latest(boxes, as_of_index=6) is not None


def test_either_break_type_may_create_a_box():
    """"the slide labels the box-birth break 'MSB / BoS'" — no filtering on type."""
    msb = brk(5, "UP", UP_HIGH.id, kind="MSB")
    boxes = StructureBoxes.construct(UP_BARS, [UP_HIGH, UP_LOW], [msb], tf=TF)
    assert boxes[0].birth_break_type == "MSB"


# ===========================================================================
# GRADE-002/003/004/005/006/007 — the grade
# ===========================================================================
def imbalance_in_box() -> Imbalance:
    """A gap sitting inside the box at 104–107, which the pullback at bar 6 taps."""
    return Imbalance(id="imb-box", tf=TF, bar_time=T0, price_high=107, price_low=104,
                     type="FVG", direction="BULLISH", formed_index=5)


def test_no_imbalance_tap_means_no_grade_at_all():
    """GRADE-006's fork. The §8 key makes the tap mandatory in ALL three grades; a grader
    built from PDF Q10 would grade this box and size it at 1.50%."""
    graded = grade_box(up_box(), UP_BARS, [UP_HIGH, UP_LOW], [], as_of_index=8)
    assert graded.grade is None
    assert graded.poi_qualified is False
    assert "mandatory in all three grades" in graded.reason
    assert graded.definition_used == "SECTION_8_IMBALANCE_TAP_MANDATORY"
    assert ManipulatedDefinitionChoice.RATIFIED is False


def test_an_imbalance_tap_alone_is_standard():
    graded = grade_box(up_box(), UP_BARS, [UP_HIGH, UP_LOW], [imbalance_in_box()],
                       as_of_index=8)
    assert graded.grade == "STANDARD"
    assert graded.evidence.fuel_component_count == 1
    assert graded.evidence.imbalance_tap is True
    assert graded.evidence.inner_sweep is False
    assert graded.retest_expectation == "CAN_BE_TESTED"


def test_a_tap_plus_a_one_sided_inner_sweep_is_super():
    """The i-LIQ sweep takes out a MINOR internal low while the strong low holds. A wick
    through the strong low is not an inner sweep — it is the box failing."""
    minor_low = swing(105, "LOW", 4, tag="m")   # inside the box, above the strong low
    bars = list(UP_BARS)
    bars[7] = Bar(time=bars[7].time, high=113, low=104, open=112, close=111)  # dips to 104
    graded = grade_box(
        up_box(), bars, [UP_HIGH, UP_LOW, minor_low], [imbalance_in_box()], as_of_index=8
    )
    assert graded.grade == "SUPER"
    assert graded.evidence.fuel_component_count == 2
    assert graded.evidence.inner_sweep is True
    assert graded.evidence.swept_swing_id == minor_low.id
    assert graded.retest_expectation == "LESS_CHANCE_OF_BEING_TESTED"


def test_a_wick_through_the_strong_low_is_not_an_inner_sweep():
    minor_low = swing(105, "LOW", 4, tag="m")
    bars = list(UP_BARS)
    bars[7] = Bar(time=bars[7].time, high=113, low=99, open=112, close=111)  # below 100
    graded = grade_box(
        up_box(), bars, [UP_HIGH, UP_LOW, minor_low], [imbalance_in_box()], as_of_index=8
    )
    assert graded.evidence.inner_sweep is False
    assert graded.grade == "STANDARD"


def test_an_unfinished_fake_msb_sequence_leaves_the_box_at_super_not_manipulated():
    """Every rung is +0.25% of the account. GRADE-008 resolves downward by design, and this
    is where that decision shows up as money."""
    minor_low = swing(105, "LOW", 4, tag="m")
    bars = list(UP_BARS)
    bars[7] = Bar(time=bars[7].time, high=113, low=104, open=112, close=111)
    box = up_box()

    verdict = FakeMSBClassifier.classify(
        box, bars, breaks=[UP_BREAK], sweeps=[], htf_target_cleared=False, as_of_index=8
    )
    assert verdict.is_fake_msb is False

    graded = grade_box(box, bars, [UP_HIGH, UP_LOW, minor_low], [imbalance_in_box()],
                       as_of_index=8, fake_msb=verdict)
    assert graded.grade == "SUPER"
    assert graded.evidence.fuel_component_count == 2


def test_the_grade_is_derived_from_the_fuel_count_so_it_cannot_be_non_monotonic():
    """GRADE-005 makes a non-monotonic grader non-conforming by definition. Deriving the
    grade from the count makes that impossible rather than merely tested."""
    assert BoxGradeLadder.is_monotonic()
    assert [LADDER[n][0] for n in (1, 2, 3)] == ["STANDARD", "SUPER", "MANIPULATED"]
    assert BoxGradeLadder.grade_for(0) is None


def test_evidence_at_the_decision_bar_is_not_used():
    """GRADE-007's look-ahead guard, enforced structurally: the evidence scan stops strictly
    left of the decision bar. The tap happens at bar 7, so a decision taken AT bar 7 cannot
    see it — grading on an in-progress pullback is an early entry."""
    at_the_bar = grade_box(up_box(), UP_BARS, [UP_HIGH, UP_LOW], [imbalance_in_box()],
                           as_of_index=7)
    assert at_the_bar.grade is None
    assert at_the_bar.evidence.imbalance_tap is False

    one_later = grade_box(up_box(), UP_BARS, [UP_HIGH, UP_LOW], [imbalance_in_box()],
                          as_of_index=8)
    assert one_later.grade == "STANDARD"
    assert one_later.evidence.last_evidence_index == 7


def test_a_partially_formed_box_is_refused_even_if_evidence_is_reported():
    """The explicit half of GRADE-007: were evidence ever to arrive carrying a bar at or
    after the decision bar, the box must be refused rather than graded on it."""
    evidence = BoxEvidence(imbalance_tap=True, inner_sweep=True, fake_msb=True,
                           last_evidence_index=9)
    assert PoiTimingGate.qualified(evidence, as_of_index=8) is False
    assert PoiTimingGate.qualified(evidence, as_of_index=10) is True


def test_the_box_scope_choice_is_declared_and_flagged_unratified():
    """GRADE-009: the source never says whether the grade means the entry box or the
    destination box, and the two would key different risk cells on the same setup."""
    assert BoxScopeDeclaration.SCOPE == "ENTRY_BOX_EXEC_TF"
    assert BoxScopeDeclaration.RATIFIED is False


# ===========================================================================
# GRADE-008 — the fake MSB
# ===========================================================================
def test_a_cleared_htf_target_ends_the_sequence_at_step_one():
    verdict = FakeMSBClassifier.classify(
        up_box(), UP_BARS, breaks=[UP_BREAK], sweeps=[], htf_target_cleared=True
    )
    assert verdict.is_fake_msb is False
    assert "already cleared" in verdict.reason
    assert verdict.steps_met == []


def test_a_counter_break_with_no_sweep_behind_it_is_not_a_manipulation():
    counter = brk(6, "DOWN", UP_LOW.id)
    verdict = FakeMSBClassifier.classify(
        up_box(), UP_BARS, breaks=[UP_BREAK, counter], sweeps=[], htf_target_cleared=False
    )
    assert verdict.is_fake_msb is False
    assert "no liquidity sweep" in verdict.reason
    assert verdict.steps_met == ["HTF_TARGET_VALID"]


def test_the_detector_names_the_shortcuts_it_is_forbidden_to_use():
    """"those are implementation shortcuts rather than trading concepts" — and a negative is
    only testable if the tokens are enumerated."""
    check = FakeMSBClassifier.banned_input_check()
    assert set(check["checked"]) == {
        "reversal_within_n_candles", "max_candle_count", "fixed_time_delay"
    }
    assert check["present"] == []
