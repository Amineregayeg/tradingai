"""T-0030 — the two stop flags, the exit flag, and GATE-027's zone-coverage modifier.

WHICH ASSERTIONS READ WHAT, because they mean different things when they go red:

    everything in this file is CONSTRUCTED — explicit candidates, explicit zones, and
    prices derived from the doctrine's own rr values. Nothing fetches and nothing reads a
    market fixture, so a red run here is UNAMBIGUOUSLY A DEFECT.

    the corpus measurement lives in `test_t0030_ladder_over_corpus.py` and reads the
    PINNED fixture. Kept separate because a slow measurement and a fast conformance suite
    fail for different reasons and should be runnable apart.

EVERY CHECK BELOW NAMES THE INPUT THAT WOULD MAKE IT FAIL, in its own docstring. A check
whose failing input cannot be named is an assertion, not a test — this loop's fix 3, and it
is decidable by reading before anything runs.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from app.services.rules import gate_029_stop_flags as flags
from app.services.rules.base import implementations
from app.services.rules.gate_027_stop_ladder import (
    ClosestTo3RSelector, LadderInputs, RewardFloor, StopCandidate, StopCandidateLadder,
    risk_reward,
)
from app.services.rules.gate_029_stop_flags import (
    DECLARED_ADJACENCY_WINDOW, DECLARED_EPS, DECLARED_SNAP_TOLERANCE,
    DECLARED_WIDENING_ORDER, FLAG_ABOVE_RR, PARTIAL_LEVEL_R, RR_FLOOR, UNNAMED_BAND,
    DegenerateRunner, RRAboveAcceptableBand, TighterThanNecessary, ZoneObject,
    apply_zone_coverage, evaluate_stop_flags, zone_coverage_evaluation_values,
)
from app.services.rules.prim_005_breaks import BreakEvent

T0 = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)

#: The same worked-table arithmetic part one uses: entry 100, target 130, reward 30.
#: A stop at rr = R sits at 100 - 30/R, so cushion is a MEASURED distance rather than a
#: number restated from the doctrine.
ENTRY, TARGET = 100.0, 130.0


def _inputs(entry: float = ENTRY, target: float = TARGET, direction: str = "LONG") -> LadderInputs:
    return LadderInputs(
        entry=entry, target=target, direction=direction,  # type: ignore[arg-type]
        search_window_from=T0, search_window_to=T0,
    )


def _stop_at(rr: float, *, entry: float = ENTRY, target: float = TARGET) -> float:
    """The stop price giving exactly this rr on a long."""
    return entry - (target - entry) / rr


def _candidate(rung: int, rr: float, *, anchor: str = "DEEPEST_SWING",
               accepted: bool | None = None) -> StopCandidate:
    stop = _stop_at(rr)
    return StopCandidate(
        rung=rung, anchor=anchor, locatable=True, stop_price=stop, rr=rr,
        accepted=(rr >= RR_FLOOR) if accepted is None else accepted,
        anchor_object_id=f"OBJ-{rung}", _entry=ENTRY,
    )


def _ladder(*rrs: float) -> list[StopCandidate]:
    """Candidates in rung order at the given rr values."""
    return [_candidate(i, rr) for i, rr in enumerate(rrs, start=1)]


# ===========================================================================
# CRITERION 3 — GATE-029 flags, never blocks
# ===========================================================================
def test_gate_029_flags_strictly_above_four_r_and_not_at_it():
    """The output's own word is "when rr > 4.0", so 4.0 itself does not flag.

    FAILING INPUT: change `rr > FLAG_ABOVE_RR` to `>=`. The 4.0 case then flags and this
    fails. That mutation is the whole reason the boundary value is asserted rather than
    only a comfortable 5.0.
    """
    assert RRAboveAcceptableBand.flags(4.01) is True
    assert RRAboveAcceptableBand.flags(FLAG_ABOVE_RR) is False
    assert RRAboveAcceptableBand.flags(3.9) is False
    assert RRAboveAcceptableBand.flags(None) is False


def test_a_ten_r_stop_is_selected_and_flagged_and_never_rejected():
    """CRITERION 3's mutation. A 10R candidate, alone above 2R, must be TAKEN.

    Blocking above 4R is a rejection nobody ruled and would contradict GATE-025, which
    accepts anything at or above 2R. "'Overly Tight' is a LABEL, not a rejection."

    FAILING INPUT: give GATE-029 a rejection path — return a FAIL verdict, or drop the 10R
    candidate from the accepted set. Either makes `selected` None or the verdict non-PASS.
    """
    table = [_candidate(1, 1.5), _candidate(5, 10.0, anchor="INNER_MSB")]
    selected = ClosestTo3RSelector.select(table)
    assert selected is not None and selected.rung == 5, "the 10R stop must be selected"
    assert selected.accepted is True

    evaluation = RRAboveAcceptableBand.evaluate(selected)
    assert evaluation.verdict == "PASS", "GATE-029 must never refuse a trade"
    assert evaluation.values["flags"] == ["RR_ABOVE_ACCEPTABLE_BAND"]
    assert evaluation.values["blocks"] is False


def test_unnamed_band_reaches_no_predicate_with_a_candidate_actually_inside_it():
    """CRITERION 3a, WITH T-0028's 2-i CORRECTION APPLIED.

    Removing a value proves nothing unless a case actually sits inside the band, so this
    first ASSERTS a 5R selection — strictly inside `[4.0, 8.0]` — and only then asserts
    that a 5R and a 9R selection are flagged IDENTICALLY. If `unnamed_band` gated anything,
    those two would differ.

    FAILING INPUT: make the flag `UNNAMED_BAND[0] < rr < UNNAMED_BAND[1]`. The 9R case then
    stops flagging and the equality below fails. Without the in-band assertion, that same
    mutation would pass a test that only checked 5R.
    """
    low, high = UNNAMED_BAND
    inside = ClosestTo3RSelector.select([_candidate(1, 5.0)])
    assert inside is not None and inside.rr is not None
    assert low < inside.rr < high, (
        f"the in-band case is the premise of this test: {inside.rr} must sit strictly "
        f"inside {UNNAMED_BAND}"
    )

    above_band = ClosestTo3RSelector.select([_candidate(1, 9.0)])
    in_band_flags = RRAboveAcceptableBand.evaluate(inside).values["flags"]
    above_band_flags = RRAboveAcceptableBand.evaluate(above_band).values["flags"]
    assert in_band_flags == above_band_flags == ["RR_ABOVE_ACCEPTABLE_BAND"], (
        "a 5R and a 9R selection must be flagged identically — the band discriminates "
        "nothing and is annotation"
    )

    source = inspect.getsource(RRAboveAcceptableBand)
    predicate_source = inspect.getsource(RRAboveAcceptableBand.flags)
    assert "UNNAMED_BAND" not in predicate_source, (
        "the flag predicate must not read the band at all"
    )
    assert source.count("UNNAMED_BAND") == 1, (
        "the band appears exactly once, where it is RECORDED into values"
    )


def test_gate_029_records_the_hard_gate_tension_without_resolving_it():
    """CRITERION 3b. Classified HARD_GATE, blocks nothing. Recorded, not fixed.

    FAILING INPUT: delete `classification_tension` from the values, or give the rule a
    blocking path so `blocks` becomes True. Both are the two ways to "resolve" it, and
    neither is ours to take — no seat may edit the registry.
    """
    from app.services.telemetry import contract_loader as contract

    # The registry's field is `enforceability`, not `type` — checked here rather than
    # assumed, because a KeyError on the wrong field name would have made this test fail
    # for a reason unrelated to the tension it exists to record.
    assert contract.rule("GATE-029")["enforceability"] == "HARD_GATE"
    assert contract.rule("GATE-030")["enforceability"] == "SOFT_PREFERENCE", (
        "control: the same lookup distinguishes rules, so HARD_GATE above is a read and "
        "not a constant that happens to match"
    )
    evaluation = RRAboveAcceptableBand.evaluate(_candidate(1, 3.0))
    assert evaluation.values["blocks"] is False
    assert "HARD_GATE" in evaluation.values["classification_tension"]
    assert evaluation.value_provenance["classification_tension"]["object_id"] == "GATE-029"


# ===========================================================================
# CRITERION 4 — GATE-030, and the reachability predicate re-derived
# ===========================================================================
def test_gate_030_fires_with_a_reason_naming_the_wider_candidate_and_its_rr():
    """CRITERION 4c. A flag with no reason field fails the criterion.

    FAILING INPUT: emit `flags` without `reason`, or fill `reason` with a bare string that
    does not carry the passed-over rr. The rr assertions below fail on both.
    """
    table = _ladder(2.0, 3.0)          # rung 1 is wider (lower rr) and also clears 2R
    selected = ClosestTo3RSelector.select(table)
    assert selected is not None and selected.rung == 2

    evaluation = TighterThanNecessary.evaluate(table, selected)
    assert evaluation.values["flags"] == ["TIGHTER_THAN_NECESSARY"]
    reason = evaluation.values["reason"]
    assert reason["passed_over_rung"] == 1
    assert reason["passed_over_rr"] == pytest.approx(2.0)
    assert reason["selected_rr"] == pytest.approx(3.0)
    assert reason["passed_over_cushion"] > reason["selected_cushion"], (
        "the passed-over candidate must be the WIDER one — that is what the flag is about"
    )


def test_the_reachability_predicate_over_four_monotonic_ladders():
    """CRITERION 4, RE-DERIVED. The plan's biconditional is too strong, and this measures it.

    On a cushion-monotonic ladder rr RISES with rung index, so survivors are a suffix and
    the WIDEST survivor is the first of them — the lowest rr. Enumerated:

        survivors        widest rr   nearer-3R survivor exists?   flag
        [3.0, 5.0]         3.0       no                            NO
        [3.5, 5.0]         3.5       no                            NO
        [2.0, 3.0]         2.0       YES                           YES
        [2.9, 5.0]         2.9       no  (|2.9-3| = 0.1 wins)      NO   <- the separator

    The plan says the flag fires "exactly when the widest 2R-clearing candidate sits below
    3R". Rows 3 and 4 both satisfy that antecedent and DISAGREE on the outcome, so the
    condition is necessary and not sufficient. Two of the four fire on the plan's reading;
    one fires on the correct one.

    FAILING INPUT: implement the plan's biconditional — flag whenever the widest survivor
    is below 3R. The [2.9, 5.0] row then flags and this fails. That row is in the file
    precisely because it is the only one that separates the two readings.
    """
    cases = [
        ((3.0, 5.0), False),
        ((3.5, 5.0), False),
        ((2.0, 3.0), True),
        ((2.9, 5.0), False),
    ]
    plan_reading_would_fire = 0
    for rrs, expected in cases:
        table = _ladder(*rrs)
        # monotone premise: rr rises with rung index, so cushion falls
        cushions = [c.cushion for c in table]
        assert cushions == sorted(cushions, reverse=True), "the ladder must be monotonic"

        selected = ClosestTo3RSelector.select(table)
        evaluation = TighterThanNecessary.evaluate(table, selected)
        fired = evaluation.values["flags"] == ["TIGHTER_THAN_NECESSARY"]
        assert fired is expected, f"survivors {rrs}: expected fire={expected}, got {fired}"

        widest = min(c.rr for c in table if c.accepted)  # type: ignore[type-var]
        if widest < 3.0:
            plan_reading_would_fire += 1
    assert plan_reading_would_fire == 2, (
        "two of the four ladders satisfy 'widest survivor below 3R' while only one fires — "
        "that gap IS the disagreement with the plan"
    )


def test_gate_030_keys_on_cushion_and_not_on_rung_order():
    """An INVERTED ladder separates the two implementations, and inversion is measured.

    T-0030's corpus run found inversions, so "later rung == tighter stop" is not safe to
    assume. Here rung 2 carries the LARGER cushion despite the later index; a rung-order
    implementation would report no wider candidate and fail to flag.

    FAILING INPUT: replace the cushion comparison with `c.rung < selected.rung`. This test
    then reports no wider survivor and the flag does not fire.
    """
    wide_late = StopCandidate(
        rung=2, anchor="MOMENTUM_IMBALANCE", locatable=True, stop_price=_stop_at(2.0),
        rr=2.0, accepted=True, anchor_object_id="OBJ-2", _entry=ENTRY,
    )
    tight_early = StopCandidate(
        rung=1, anchor="DEEPEST_SWING", locatable=True, stop_price=_stop_at(3.0),
        rr=3.0, accepted=True, anchor_object_id="OBJ-1", _entry=ENTRY,
    )
    table = [tight_early, wide_late]
    selected = ClosestTo3RSelector.select(table)
    assert selected is tight_early, "argmin |rr - 3| picks the 3R rung whatever its index"

    evaluation = TighterThanNecessary.evaluate(table, selected)
    assert evaluation.values["flags"] == ["TIGHTER_THAN_NECESSARY"]
    assert evaluation.values["reason"]["passed_over_rung"] == 2, (
        "the wider candidate is the LATER rung here — an inverted ladder is the only "
        "shape that separates a cushion comparison from a rung-order one"
    )


def test_gate_030_is_not_applicable_rather_than_false_when_nothing_was_selected():
    """No selection is not "no wider candidate". Absence versus empty.

    FAILING INPUT: return PASS with an empty flag list when `selected` is None. The verdict
    assertion fails, and the record would then claim the rule ran and found nothing.
    """
    evaluation = TighterThanNecessary.evaluate([_candidate(1, 1.0, accepted=False)], None)
    assert evaluation.verdict == "NOT_APPLICABLE"
    assert "not_applicable_reason" in evaluation.values


# ===========================================================================
# CRITERION 5 — GATE-031, and the interlock that is ONE fixture
# ===========================================================================
def test_at_exactly_two_r_the_same_candidate_is_both_admitted_and_flagged():
    """CRITERION 5a. ONE fixture, BOTH assertions, at exactly `rr == 2.0`.

    The floor is INCLUSIVE so 2.0 is ACCEPTED; GATE-031 flags DEGENERATE_RUNNER at
    `rr <= 2.0 + eps`. The same value is both, and that is correct — admission and health
    are different questions.

    TWO SEPARATE FIXTURES DO NOT SATISFY THIS and that is not a style preference. A test
    asserting admission alone passes an implementation whose flag boundary has moved; a
    test asserting the flag alone passes one whose floor has moved to exclusive. The two
    boundaries are ONE VALUE APART, so only asserting them on the SAME candidate pins both.

    FAILING INPUT, admission side: make the floor exclusive (`rr > RR_FLOOR`). FAILING
    INPUT, flag side: make the flag exclusive (`rr < 2.0 + eps`). Each mutation breaks
    exactly one of the two assertions below, and neither breaks a test that asserts only
    the other.
    """
    inputs = _inputs()
    stop = _stop_at(2.0)
    rr = risk_reward(inputs, stop)
    assert rr == pytest.approx(2.0), "the fixture must sit ON the boundary, not near it"

    ladder = [StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True,
                            stop_price=stop, anchor_object_id="OBJ-1", _entry=ENTRY)]
    table = RewardFloor.table(inputs, ladder)
    candidate = table[0]

    assert candidate.accepted is True, (
        "GATE-025's floor is INCLUSIVE — rr == 2.0 is admissible"
    )
    assert candidate.rejection_reason == "NONE"
    assert DegenerateRunner.flags(candidate.rr) is True, (
        "GATE-031 flags DEGENERATE_RUNNER at rr <= 2.0 + eps, and 2.0 is inside that"
    )
    evaluation = DegenerateRunner.evaluate(candidate)
    assert evaluation.values["flags"] == ["DEGENERATE_RUNNER"]
    assert evaluation.verdict == "PASS", "flagging is not refusing"


def test_the_degenerate_flag_fires_at_two_r_and_not_at_three_r():
    """CRITERION 5b's two points. Necessary, and by themselves NOT sufficient — see below.

    FAILING INPUT: invert the comparison. Both assertions flip.
    """
    assert DegenerateRunner.flags(2.0) is True
    assert DegenerateRunner.flags(3.0) is False


def test_eps_is_declared_unratified_and_carries_an_authority():
    """CRITERION 5b. `eps` is STILL OURS — and the tripwire that said so has now FIRED.

    Through T-0044 this asserted `"values" not in GATE-031`, with the message *"if GATE-031
    ever gains a values block, eps stops being ours and this must be re-derived from it
    rather than declared"*. **T-0045 gave GATE-031 a values block, so the tripwire fired
    exactly as designed and the re-derivation it demanded was done — the answer is that eps
    is still ours.**

    The round-3 ruling settles the POLICY at 2R (`TAKE_AND_FLAG`, both tranches logged) and
    explicitly declines to ratify an epsilon: `epsilon_note` reads *"K-14 uses planned_rr ≤
    2.05 — engineering, declare it"*. **A registry that names our number and calls it
    engineering has not adopted it.** So `DECLARED_EPS` stays `ratified=False`.

    The tripwire is re-armed one level in: it now fires if the values block ever carries an
    epsilon as a NUMBER, which would be a ratification.

    FAILING INPUT: drop the authority field, or set `ratified=True`. Either makes an engine
    choice read as a trader ruling, which is the thing declaration exists to prevent.
    """
    from app.services.telemetry import contract_loader as contract

    values = contract.rule("GATE-031").get("values", {})
    assert "epsilon_note" in values, (
        "GATE-031's values lost epsilon_note — re-read what the registry now says about eps"
    )
    assert "declare it" in values["epsilon_note"], (
        f"GATE-031 no longer calls the epsilon engineering: {values['epsilon_note']!r}. If it "
        "RATIFIED a number, eps stops being ours and DECLARED_EPS must be re-derived from the "
        "registry rather than declared here."
    )
    assert not any(isinstance(v, (int, float)) and k.lower().endswith(("eps", "epsilon"))
                   for k, v in values.items()), (
        "GATE-031's values carry a NUMERIC epsilon — that is a ratification, and eps is no "
        "longer ours to declare"
    )
    assert DECLARED_EPS.ratified is False
    assert DECLARED_EPS.authority.startswith("ENGINEERING")
    assert DECLARED_EPS.competing is not None, "the option not taken is recorded"

    evaluation = DegenerateRunner.evaluate(_candidate(1, 2.0))
    assert evaluation.values["degenerate_runner_eps_ratified"] is False
    assert evaluation.value_provenance["degenerate_runner_eps"]["source"] == (
        "DECLARED_PARAMETER"
    )


def test_eps_is_a_parameter_so_the_firing_rate_can_be_swept_without_mutating_state():
    """CRITERION 5b's real question is "how often does it fire AT ALL", not two points.

    An eps of 0.5R passes both point assertions and flags everything between 2R and 2.5R.
    This pins that the interval is reachable as a PARAMETER, which is what makes the rate
    measurable over a sweep instead of at one value.

    FAILING INPUT: hardcode `DECLARED_EPS.value` inside `flags()` and ignore the argument.
    The 2.4 case then stops flagging under eps=0.5 and this fails.
    """
    assert DegenerateRunner.flags(2.4, eps=0.0) is False
    assert DegenerateRunner.flags(2.4, eps=0.5) is True
    # and the module constant is untouched by the sweep
    assert DECLARED_EPS.value == 0.0


def test_gate_031_invents_no_minimum_gap():
    """CRITERION 5c. Flag; do not skip, widen, or nudge.

    FAILING INPUT: make `evaluate` return FAIL, or have it alter the candidate. The verdict
    assertion catches the first; the identity assertion catches the second.
    """
    candidate = _candidate(1, 2.0)
    evaluation = DegenerateRunner.evaluate(candidate)
    assert evaluation.verdict == "PASS"
    assert evaluation.values["minimum_gap_invented"] is False
    assert candidate.stop_price == _stop_at(2.0), "the candidate must be untouched"
    assert candidate.rr == pytest.approx(2.0)


def test_gate_031_records_that_the_runner_it_protects_is_undefined():
    """CRITERION 5d. The compounding gap, on every record.

    FAILING INPUT: delete the note, or set `runner_management_rules_defined` to True. The
    flag would then report a degenerate runner while implying the runner has rules.
    """
    evaluation = DegenerateRunner.evaluate(_candidate(1, 2.0))
    assert evaluation.values["runner_management_rules_defined"] is False
    assert "NEVER DEFINED" in evaluation.values["runner_management_rules_note"]
    assert "036_Single_Trade_Management.md" in (
        evaluation.values["runner_management_rules_note"]
    )


# ===========================================================================
# CRITERION 6 — the zone-coverage modifier, which is GATE-027's
# ===========================================================================
def test_a_stop_inside_a_zone_is_extended_to_the_far_edge_of_the_whole_zone():
    """CRITERION 6. "extend to the far edge of the whole zone" — PRIM-006, zones never lines.

    FAILING INPUT: extend to the NEAR edge, or to the zone's midpoint. The final stop then
    sits inside the zone and the containment assertion fails.
    """
    inputs = _inputs()
    stop = _stop_at(3.0)                       # 90.0
    zone = ZoneObject(kind="IMBALANCE", price_high=91.0, price_low=88.0, id="IMB-9")
    selected = StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True,
                             stop_price=stop, rr=3.0, accepted=True, _entry=ENTRY)

    coverage = apply_zone_coverage(inputs, selected, [zone])
    assert coverage.widened is True
    assert coverage.final_stop == pytest.approx(88.0), "the far edge on a long is the low"
    assert not zone.contains(coverage.final_stop) or coverage.final_stop == zone.price_low
    assert coverage.covering_zone is not None and coverage.covering_zone.id == "IMB-9"
    assert coverage.final_rr is not None and coverage.final_rr < coverage.original_rr  # type: ignore[operator]


def test_the_widening_clears_every_overlapping_zone_not_just_the_first_supplied():
    """Two zones both contain the stop; covering only one leaves the stop inside the other.

    FAILING INPUT: take `containing[0]` instead of the furthest. The final stop then sits
    inside the deeper zone and the assertion below fails. Supply order is reversed here on
    purpose so a first-match implementation is caught rather than accidentally right.
    """
    inputs = _inputs()
    shallow = ZoneObject(kind="IMBALANCE", price_high=91.0, price_low=89.0, id="Z-SHALLOW")
    deep = ZoneObject(kind="SR_FLIP", price_high=90.5, price_low=86.0, id="Z-DEEP")
    selected = StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True,
                             stop_price=90.0, rr=3.0, accepted=True, _entry=ENTRY)

    coverage = apply_zone_coverage(inputs, selected, [shallow, deep])
    assert coverage.final_stop == pytest.approx(86.0)
    for zone in (shallow, deep):
        assert coverage.final_stop <= zone.price_low, (
            f"the final stop must clear {zone.id} entirely"
        )


def test_the_modifier_never_tightens_a_stop():
    """A zone whose far edge sits nearer entry must not pull the stop in.

    FAILING INPUT: drop the "never tighten" guard and always take the far edge. The stop
    then moves from 85.0 up to 89.0, cushion shrinks, and this fails.
    """
    inputs = _inputs()
    selected = StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True,
                             stop_price=85.0, rr=2.0, accepted=True, _entry=ENTRY)
    zone = ZoneObject(kind="IMBALANCE", price_high=92.0, price_low=89.0, id="Z-ABOVE")
    # The stop is BELOW this zone, so nothing contains it and nothing may move.
    coverage = apply_zone_coverage(inputs, selected, [zone])
    assert coverage.widened is False
    assert coverage.final_stop == 85.0


def test_an_adjacent_zone_is_reported_and_never_widened_onto():
    """CRITERION 6a's second residual. Default: do not widen, flag `zone_adjacent_uncovered`.

    FAILING INPUT: set `DECLARED_SNAP_TOLERANCE` to a positive number and snap. The stop
    then moves and `widened` becomes True. Separately: set the ADJACENCY window to 0.0 and
    the zone stops being reported, which is the silent-empty-measurement failure the two
    parameters are separate to prevent.
    """
    inputs = _inputs()
    selected = StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True,
                             stop_price=90.0, rr=3.0, accepted=True, _entry=ENTRY)
    # height 2.0, nearest edge 1.0 away -> inside a 1.0-zone-height reporting window
    near = ZoneObject(kind="IMBALANCE", price_high=89.0, price_low=87.0, id="Z-NEAR")

    coverage = apply_zone_coverage(inputs, selected, [near])
    assert coverage.widened is False, "an adjacent zone must not move the stop"
    assert coverage.final_stop == 90.0
    assert [z.id for z in coverage.adjacent_uncovered] == ["Z-NEAR"]
    assert DECLARED_SNAP_TOLERANCE.value == 0.0
    assert DECLARED_ADJACENCY_WINDOW.value > 0.0, (
        "the reporting window must not be zero, or an open residual reads as measured-at-zero"
    )


def test_widening_can_manufacture_a_degenerate_runner_and_lands_on_the_flagged_side():
    """CRITERION 6b. The ordering choice has a consequence and this is it, asserted.

    A candidate at rr 2.3 is admitted and NOT degenerate. The zone widening lowers rr past
    2.0, and under `DECLARED_WIDENING_ORDER` GATE-031 reads the FINAL stop — so the flag
    that did not fire before the modifier ran fires after it. The doctrine question is NOT
    resolved here; the consequence is recorded so a later ratification knows the cost.

    FAILING INPUT: evaluate GATE-031 on the PRE-widening stop. The post-widening assertion
    then reports no flag and this fails — which is exactly the alternative ordering, so
    this test is what makes the declared choice observable rather than stated.
    """
    inputs = _inputs()
    before = _stop_at(2.3)                       # 86.956...
    selected = StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True,
                             stop_price=before, rr=2.3, accepted=True, _entry=ENTRY)
    assert DegenerateRunner.flags(selected.rr) is False, "not degenerate before widening"

    zone = ZoneObject(kind="SR_FLIP", price_high=88.0, price_low=84.0, id="Z-WIDE")
    out = evaluate_stop_flags(inputs, [selected], selected, [zone])

    coverage = out["zone_coverage"]
    assert coverage.widened is True and coverage.final_stop == pytest.approx(84.0)
    assert coverage.final_rr == pytest.approx(30.0 / 16.0)          # 1.875
    assert coverage.widened_below_floor is True, (
        "the widened stop no longer clears 2R — RECORDED, and not acted on"
    )
    assert out["GATE-031"].values["flags"] == ["DEGENERATE_RUNNER"], (
        "the modifier MANUFACTURED the flag; that is the consequence 6b asks to be pinned"
    )
    # and nothing was re-selected or dropped: admission is GATE-025's
    assert out["selected_before_zone_coverage"] is selected
    assert out["selected_after_zone_coverage"].rung == selected.rung


def test_the_widening_order_is_declared_with_the_option_not_taken():
    """CRITERION 6a's first residual, and the one that changes which candidate wins.

    FAILING INPUT: drop `competing`, or mark it ratified. A choice with one option written
    down reads as a fact — GATE-027 already declares two placements for that reason.
    """
    assert DECLARED_WIDENING_ORDER.ratified is False
    assert DECLARED_WIDENING_ORDER.competing == (
        "BEFORE_FLOOR — widen first, then admit, which changes which candidates clear 2R"
    )
    assert DECLARED_WIDENING_ORDER.authority.startswith("ENGINEERING")


def test_the_zone_modifier_is_attributed_to_gate_027_and_corroborated_by_prim_006():
    """The artefact's owner is the registry's answer, not ours: GATE-027 note (b).

    Two rules state the same requirement and the corroboration is IN THE RECORD rather than
    in a comment, which is what makes it checkable.

    FAILING INPUT: attribute `zone_coverage` to GATE-028 (the rule that owns the selected
    stop) or to a new id. The object_id assertions fail.
    """
    inputs = _inputs()
    selected = StopCandidate(rung=1, anchor="DEEPEST_SWING", locatable=True,
                             stop_price=90.0, rr=3.0, accepted=True, _entry=ENTRY)
    coverage = apply_zone_coverage(inputs, selected, [])
    values, provenance = zone_coverage_evaluation_values(coverage)

    assert provenance["zone_coverage"]["object_id"] == "GATE-027"
    assert provenance["zone_coverage"]["field"] == "notes"
    assert provenance["zone_coverage_corroboration"]["object_id"] == "PRIM-006"
    assert values["zone_coverage"]["widened"] is False, (
        "the block is emitted even when nothing widened — 'no zone contained the stop' and "
        "'the modifier did not run' are different facts"
    )


def test_gate_027_still_owns_its_own_coverage_entry():
    """THE TRAP THIS MODULE DECLINED, PINNED SO A LATER SEAT CANNOT TAKE IT QUIETLY.

    `base.py` offers `ALLOW_SHARED_ID` for "a rule legitimately implemented in more than one
    place", and the zone modifier is exactly that case on paper. Taking it would have
    replaced `StopCandidateLadder` in `_IMPLEMENTATIONS['GATE-027']`, because
    `__init_subclass__` ends in an unconditional assignment — and with it the coverage
    report would lose `CANNOT_FIRE_WITHOUT = (ORDER_BLOCK_PRODUCER,)`, which is the only
    channel by which rung 4's producer gap reaches that report. No behaviour would change.

    FAILING INPUT: add a `RuleImplementation` subclass in `gate_029_stop_flags.py` claiming
    `RULE_ID = "GATE-027"` with `ALLOW_SHARED_ID = True` on both classes. This fails
    immediately, and it fails on the thing that would actually have been lost.
    """
    assert implementations()["GATE-027"] is StopCandidateLadder
    # WHAT WOULD BE LOST HAS CHANGED, AND THE GUARD IS STILL WORTH KEEPING.
    #
    # Through T-0045 this asserted `CANNOT_FIRE_WITHOUT == ("order_block_detector",)`, because
    # that tuple was the ONLY channel by which rung 4's producer gap reached the coverage report,
    # and a shared-id takeover would have silently dropped it. **T-0046 built PRIM-007 and removed
    # the tuple**, so the thing at risk is no longer a declaration — it is the ladder's five-rung
    # `build` itself, including the per-call producer gap that replaced the per-rule one.
    assert not getattr(StopCandidateLadder, "CANNOT_FIRE_WITHOUT", ()), (
        "GATE-027 declares a producer gap again — PRIM-007 exists; see T-0046"
    )
    assert hasattr(StopCandidateLadder, "build") and hasattr(StopCandidateLadder, "rung2_pool_report"), (
        "a shared-id takeover replaced the ladder in _IMPLEMENTATIONS — the five-rung build and "
        "the rung-2 denominators would go with it, and no behaviour would appear to change"
    )

    # THE FIRST VERSION OF THIS GUARD WAS A SUBSTRING SCAN AND IT FAILED ON MY OWN
    # DOCSTRING — the module has to NAME `ALLOW_SHARED_ID` in order to explain why it was
    # refused, and under a substring scan documenting the refusal is what breaks the check.
    # The previous session hit the identical shape and its ruling is the one followed here:
    # do not weaken the guard and do not delete the explanation — narrow it over AST, which
    # matches a BINDING and never prose. Re-attacked below rather than trusted.
    import ast

    tree = ast.parse(inspect.getsource(flags))
    bound_names = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    } | {
        node.target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert "ALLOW_SHARED_ID" not in bound_names, (
        "the hatch is not taken: no class in this module may set ALLOW_SHARED_ID"
    )
    claimed = {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "RULE_ID" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    }
    assert "GATE-027" not in claimed, (
        f"no class here may claim GATE-027; this module claims {sorted(claimed)}"
    )

    # THE RE-ATTACK. A guard rewritten until it stops failing is this register's most filed
    # defect, and the rewrite is exactly when it stops being trustworthy. Injecting the
    # violation into the AST the guard reads must still be caught.
    injected = ast.parse(
        "class Sneak(RuleImplementation):\n"
        "    RULE_ID = 'GATE-027'\n"
        "    ALLOW_SHARED_ID = True\n"
    )
    injected_names = {
        t.id for n in ast.walk(injected) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
    }
    assert "ALLOW_SHARED_ID" in injected_names and "RULE_ID" in injected_names, (
        "the guard must catch a real binding — if this fails the guard above is vacuous "
        "and would pass a module that took the hatch"
    )


# ===========================================================================
# CRITERION 9 — three rules, three artefacts, tested separately
# ===========================================================================
def test_each_rule_produces_its_own_distinct_artefact():
    """CRITERION 9. A flag, a flag with a reason, and a post-selection price adjustment.

    FAILING INPUT: merge any two rules into one evaluation, or have one rule emit another's
    flag. The disjointness assertion fails.
    """
    inputs = _inputs()
    table = _ladder(2.0, 3.0, 5.0)
    selected = ClosestTo3RSelector.select(table)
    out = evaluate_stop_flags(inputs, table, selected, [])

    assert out["GATE-029"].rule_id == "GATE-029"
    assert out["GATE-030"].rule_id == "GATE-030"
    assert out["GATE-031"].rule_id == "GATE-031"

    flag_sets = {
        rule_id: set(out[rule_id].values["flags"])
        for rule_id in ("GATE-029", "GATE-030", "GATE-031")
    }
    all_flags = [f for flags_ in flag_sets.values() for f in flags_]
    assert len(all_flags) == len(set(all_flags)), "no flag may be emitted by two rules"
    assert flag_sets["GATE-030"] == {"TIGHTER_THAN_NECESSARY"}
    # the modifier's artefact is a PRICE, not a flag
    assert "zone_coverage" in out and hasattr(out["zone_coverage"], "final_stop")


def test_nothing_under_live_imports_this_module():
    """CRITERION 12. Shadow only; nothing under `live/` may import what T-0030 built.

    Control pair in the same check, so the instrument is visible: the must-HIT proves the
    scan reads these files at all, and the must-MISS proves it can return empty for a real
    absence rather than for a broken path.

    FAILING INPUT: add `from app.services.rules.gate_029_stop_flags import ...` to any file
    under `app/services/live/`. The must-MISS count goes to 1 and this fails.
    """
    from pathlib import Path

    live = Path(__file__).resolve().parents[2] / "app" / "services" / "live"
    sources = list(live.rglob("*.py"))
    assert sources, "the scan found no files at all — the instrument, not the answer"

    must_hit = [p.name for p in sources if "prim_001_swings" in p.read_text()]
    must_miss = [p.name for p in sources if "gate_029_stop_flags" in p.read_text()]
    zzz_miss = [p.name for p in sources if "zzz_absent_module" in p.read_text()]

    assert must_hit, "control: live/ does import SOME rules module, so the scan works"
    assert zzz_miss == [], "control: an absent token returns empty"
    assert must_miss == [], f"live/ must not import T-0030's module, found in {must_miss}"
