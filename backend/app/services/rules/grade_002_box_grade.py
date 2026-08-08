"""GRADE-002/003/004/005/006/007 — the structure-box grade (M4).

    Standard = 1 (IMB) → 'can be tested'
    Super    = 2 (IMB+LIQ) → 'less chance of being tested'
    Manipulated = 3 (IMB+LIQ+LIQ) → 'shall not be tested'

THIS IS THE MOST CONSEQUENTIAL DETECTOR IN THE ENGINE, AND THE LEAST TESTABLE
The grade keys the 3×3 risk matrix. A grader that is systematically one tier off does not
produce a slightly wrong label — it produces a wrong position size on every trade, while
scoring 100% CONFORMANT, because nothing in the conformance suite tests whether a box the
engine called Manipulated actually is one. The scorecard says so in as many words and the
only mitigation is readiness gate 7: a human replaying records against the charts.

Everything below is therefore written to be *checkable by eye* from the evidence tuple, and
the evidence is emitted whether or not it changed the grade.

GRADE-006 IS A FORK IN THE SOURCE AND WE TAKE THE §8 SIDE, DELIBERATELY
Two incompatible definitions of the Manipulated box exist. PDF Q10 defines it as sweep +
counter-trend MSB + both sides trapped + continuation with NO imbalance tap — and never
defines Standard or Super at all, while making all three the key of the risk table. §8 / §2
A10 / §9.A IM5 require an imbalance-or-gap tap in EVERY grade.

    The engine MUST implement the §8 key (imbalance tap mandatory in all three grades) and
    MUST NOT build the grader from Q10 alone.

So `imbalance_tap` is a precondition, not a component: without it there is no grade at all,
which means no risk-matrix lookup and no trade. A grader built from Q10 would happily grade
boxes that never touched an imbalance and size them at 1.50%.

THE LADDER IS THE RULE — GRADE-005
The three grades are one ordinal ladder keyed to the count of fuel components, not three
unrelated shapes. So the grade is *derived from* the count rather than decided by three
independent predicates that might disagree; a non-monotonic grader is non-conforming by
definition, and deriving it makes that impossible rather than merely tested.

WHY UNCERTAINTY GOES DOWN THE LADDER, NEVER UP
Each rung is +0.25% of the account. Every ambiguous input here resolves toward fewer fuel
components: an unfinished fake-MSB sequence (GRADE-008) is False, and an inner sweep that
touched both sides without the sequence is SUPER, not MANIPULATED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.grade_001_structure_box import StructureBox
from app.services.rules.grade_008_fake_msb import FakeMSB
from app.services.rules.prim_001_swings import Bar, Swing
from app.services.rules.prim_002_imbalances import Imbalance

BoxGrade = Literal["STANDARD", "SUPER", "MANIPULATED"]
Side = Literal["HIGH", "LOW"]

#: GRADE-005's ladder. Fuel-component count -> grade and the doctrine's retest expectation.
#: The single source for both, so the grade cannot drift from the count it is derived from.
LADDER: dict[int, tuple[BoxGrade, str]] = {
    1: ("STANDARD", "CAN_BE_TESTED"),
    2: ("SUPER", "LESS_CHANCE_OF_BEING_TESTED"),
    3: ("MANIPULATED", "SHALL_NOT_BE_TESTED"),
}

#: GRADE-006's fork, recorded on every graded box so the choice travels with the evidence.
MANIPULATED_DEFINITION = "SECTION_8_IMBALANCE_TAP_MANDATORY"


@dataclass
class BoxEvidence:
    """What was observed around the box. Emitted whether or not it moved the grade."""

    imbalance_tap: bool
    inner_sweep: bool
    fake_msb: bool
    swept_sides: list[Side] = field(default_factory=list)
    imbalance_id: str | None = None
    swept_swing_id: str | None = None
    swept_wick_price: float | None = None
    fake_msb_reason: str | None = None
    #: Latest bar index that any evidence above came from — GRADE-007's guard reads this.
    last_evidence_index: int = -1

    @property
    def fuel_component_count(self) -> int:
        """IMB + LIQ + LIQ. The imbalance tap is component one and a precondition both."""
        if not self.imbalance_tap:
            return 0
        return 1 + int(self.inner_sweep) + int(self.fake_msb)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "imbalance_tap": self.imbalance_tap,
            "inner_sweep": self.inner_sweep,
            "fake_msb": self.fake_msb,
            "swept_sides": list(self.swept_sides),
            "fuel_component_count": self.fuel_component_count,
        }
        for key, value in (
            ("imbalance_id", self.imbalance_id),
            ("swept_swing_id", self.swept_swing_id),
            ("swept_wick_price", self.swept_wick_price),
            ("fake_msb_reason", self.fake_msb_reason),
        ):
            if value is not None:
                out[key] = value
        return out


@dataclass
class GradedBox:
    """The graded box, or the reason there is no grade."""

    box: StructureBox
    evidence: BoxEvidence
    grade: BoxGrade | None
    retest_expectation: str | None
    poi_qualified: bool
    reason: str
    definition_used: str = MANIPULATED_DEFINITION

    def as_dict(self) -> dict[str, Any]:
        out = {
            "box_id": self.box.id,
            "box_grade": self.grade,
            "retest_expectation": self.retest_expectation,
            "poi_qualified": self.poi_qualified,
            "manipulated_definition_used": self.definition_used,
            "reason": self.reason,
        }
        out.update(self.evidence.as_dict())
        return out


def grade_box(
    box: StructureBox,
    bars: Sequence[Bar],
    swings: Sequence[Swing],
    imbalances: Sequence[Imbalance],
    *,
    as_of_index: int,
    fake_msb: FakeMSB | None = None,
) -> GradedBox:
    """Grade one box from completed price action strictly left of `as_of_index`.

    The pullback is the move back INTO the box after its birth break — that is what the
    grades describe, and it is why nothing before `box.break_index` counts as evidence.
    """
    evidence = _observe(
        box, bars, swings, imbalances, as_of_index=as_of_index, fake_msb=fake_msb
    )

    # GRADE-006: no imbalance tap, no grade. Not STANDARD — no grade at all, which is what
    # stops the risk matrix from being looked up (GRADE-001's last sentence).
    if not evidence.imbalance_tap:
        return GradedBox(
            box, evidence, None, None, False,
            "no imbalance or gap tap inside the box — the §8 key makes the tap mandatory in "
            "all three grades, so this box has no grade and cannot be sized",
        )

    # GRADE-007: every component must have printed strictly left of the decision bar.
    poi_qualified = evidence.last_evidence_index < as_of_index
    if not poi_qualified:
        return GradedBox(
            box, evidence, None, None, False,
            f"evidence at bar {evidence.last_evidence_index} is not strictly left of the "
            f"decision bar {as_of_index} — grading a partially formed box is an early entry",
        )

    grade, expectation = LADDER[evidence.fuel_component_count]
    return GradedBox(
        box, evidence, grade, expectation, True,
        f"{evidence.fuel_component_count} fuel component(s) detected",
    )


def _observe(
    box: StructureBox,
    bars: Sequence[Bar],
    swings: Sequence[Swing],
    imbalances: Sequence[Imbalance],
    *,
    as_of_index: int,
    fake_msb: FakeMSB | None,
) -> BoxEvidence:
    """Collect the evidence tuple. No grading decisions are taken here."""
    start = box.break_index + 1
    stop = min(as_of_index, len(bars))
    pullback = list(range(start, stop))
    last_evidence = -1

    # --- component 1: the imbalance/gap tap -------------------------------------------
    tapped_id: str | None = None
    for imb in imbalances:
        if imb.price_high < box.box_low or imb.price_low > box.box_high:
            continue  # not inside the box's price span
        for i in pullback:
            bar = bars[i]
            if bar.high >= imb.price_low and bar.low <= imb.price_high:
                tapped_id = imb.id
                last_evidence = max(last_evidence, i)
                break
        if tapped_id:
            break

    # --- component 2: the inner-liquidity sweep ----------------------------------------
    # "a wick beyond a prior internal swing on ONE side only (the i-LIQ sweep that traps the
    # early traders positioned in the trade's own direction)".
    #
    # Own side = below for a long setup, above for a short: that is where those traders'
    # stops sit. The level swept is a MINOR internal swing — one strictly inside the box,
    # not the box extreme itself. A wick through the box extreme is not an inner sweep, it
    # is the strong low failing, and the box with it.
    own_side: Side = "LOW" if box.direction == "UP" else "HIGH"
    internal = [
        s for s in swings
        if box.swing_index <= s.bar_index <= box.break_index and s.kind == own_side
    ]
    minor = [
        s for s in internal
        if ((s.price > box.box_low) if own_side == "LOW" else (s.price < box.box_high))
    ]
    swept_sides: list[Side] = []
    swept_swing_id: str | None = None
    swept_wick: float | None = None

    for level in sorted(minor, key=lambda s: s.price, reverse=own_side == "LOW"):
        for i in pullback:
            bar = bars[i]
            beyond = bar.low < level.price if own_side == "LOW" else bar.high > level.price
            held = bar.low >= box.box_low if own_side == "LOW" else bar.high <= box.box_high
            if beyond and held:
                swept_sides.append(own_side)
                swept_swing_id = level.id
                swept_wick = bar.low if own_side == "LOW" else bar.high
                last_evidence = max(last_evidence, i)
                break
        if swept_swing_id:
            break

    inner_sweep = bool(swept_sides)

    # --- component 3: the fake MSB (GRADE-008) -----------------------------------------
    # GRADE-004 `depends_on` GRADE-008, so the sequence classifier is the specified input
    # and its verdict is taken as-is. GRADE-004's own phrasing — "wicks beyond BOTH a prior
    # high AND a prior low" — is a restatement of the same both-sides trap that the sequence
    # operationalises, not a second independent test; running it as one would double-count
    # the sweep that is already component 2.
    is_fake = bool(fake_msb and fake_msb.is_fake_msb)
    if is_fake and fake_msb and fake_msb.break_bar is not None:
        last_evidence = max(last_evidence, fake_msb.break_bar)
    if is_fake and fake_msb and fake_msb.trapped_sides:
        swept_sides = sorted({*swept_sides, "HIGH", "LOW"})  # type: ignore[list-item]

    reason = fake_msb.reason if (fake_msb is not None and not is_fake) else None

    return BoxEvidence(
        imbalance_tap=tapped_id is not None,
        inner_sweep=inner_sweep,
        fake_msb=is_fake,
        swept_sides=sorted(set(swept_sides)),
        imbalance_id=tapped_id,
        swept_swing_id=swept_swing_id,
        swept_wick_price=swept_wick,
        fake_msb_reason=reason,
        last_evidence_index=last_evidence,
    )


# ---------------------------------------------------------------------------------------
# The rule ids. Each owns its predicate over the shared evidence; none re-derives geometry.
# ---------------------------------------------------------------------------------------
class StandardBoxGrade(RuleImplementation):
    """GRADE-002: imbalance tap only. Fuel = 1. The strong swing CAN be tested."""

    RULE_ID = "GRADE-002"
    FUEL = 1

    @staticmethod
    def matches(e: BoxEvidence) -> bool:
        return e.imbalance_tap and not e.inner_sweep and not e.fake_msb


class SuperBoxGrade(RuleImplementation):
    """GRADE-003: tap + one-sided inner sweep. Fuel = 2. LESS chance of being tested."""

    RULE_ID = "GRADE-003"
    FUEL = 2

    @staticmethod
    def matches(e: BoxEvidence) -> bool:
        return e.imbalance_tap and e.inner_sweep and not e.fake_msb


class ManipulatedBoxGrade(RuleImplementation):
    """GRADE-004: tap + inner sweep + fake MSB, both sides trapped. Fuel = 3."""

    RULE_ID = "GRADE-004"
    FUEL = 3

    COVERAGE_NOTE = (
        "The third component is GRADE-008's sequence verdict, which is the dependency the "
        "registry names. An unfinished sequence leaves the box at SUPER. INTERPRETED: which "
        "internal swing counts as the i-LIQ sweep level, and the reading of GRADE-004's "
        "'wicks beyond BOTH' as a restatement of that sequence rather than a second test, "
        "are engine choices — this is the 1.50% cell and readiness gate 7 must check them "
        "against the trader's annotated charts."
    )

    @staticmethod
    def matches(e: BoxEvidence) -> bool:
        return e.imbalance_tap and e.inner_sweep and e.fake_msb


class BoxGradeLadder(RuleImplementation):
    """GRADE-005: the grade is a function of the fuel count, so it cannot be non-monotonic."""

    RULE_ID = "GRADE-005"

    @staticmethod
    def grade_for(count: int) -> BoxGrade | None:
        entry = LADDER.get(count)
        return entry[0] if entry else None

    @staticmethod
    def is_monotonic() -> bool:
        """The ladder never falls as fuel rises. Asserted rather than assumed, because
        GRADE-005 makes a non-monotonic grader non-conforming by definition."""
        order = {"STANDARD": 1, "SUPER": 2, "MANIPULATED": 3}
        counts = sorted(LADDER)
        return all(
            order[LADDER[a][0]] < order[LADDER[b][0]]
            for a, b in zip(counts, counts[1:])
        )


class ManipulatedDefinitionChoice(RuleImplementation):
    """GRADE-006: the declared, versioned choice between two incompatible definitions."""

    RULE_ID = "GRADE-006"

    DEFINITION = MANIPULATED_DEFINITION
    #: The trader has not ratified the fork. It stays visible because the losing reading
    #: would grade boxes that never touched an imbalance and size them at 1.50%.
    RATIFIED = False


class PoiTimingGate(RuleImplementation):
    """GRADE-007: grade only once all of the box's manipulation has printed."""

    RULE_ID = "GRADE-007"

    @staticmethod
    def qualified(evidence: BoxEvidence, *, as_of_index: int) -> bool:
        return evidence.last_evidence_index < as_of_index
