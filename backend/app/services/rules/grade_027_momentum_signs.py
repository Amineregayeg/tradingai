"""GRADE-027 and GRADE-028 — the forward and slowdown momentum signs, read STRUCTURALLY.

Two rules in one module because they read the same object — **a leg** — from opposite ends, and a
second construction of it would be `GATE-011`'s shape. `GRADE-027` records the three signs that
momentum is still running toward a target; `GRADE-028` records the four that it is decaying after
target clearance.

## THE CLASSIFICATION USES NO SIZE THRESHOLD, AND THAT IS DOCTRINE RATHER THAN CAUTION

`PRIM-002` can mark momentum imbalances, but only through a parameter this slice forbids::

    prim_002_imbalances.py:214   imb.is_momentum_imbalance = (
                                     imb.width >= momentum_min_width
                                     and imb.fill_state == "UNFILLED")

**`GATE-035` bans `imbalance_tiers_0.8_0.4` BY NAME**, and a fixed width test on an imbalance is
that class. So `momentum_min_width` is **not passed** anywhere in this cluster and
`is_momentum_imbalance` stays `None` — see `MOMENTUM_CLASSIFICATION_NOTE`, which exists so that a
later seat does not close the gap by passing the parameter and defeat the ban while tidying up.

**What replaces it is DECLARED rather than derived.** `GRADE-037`: *STRONG TREND + MOMENTUM = the
trend uses imbalances **and leaves UNMITIGATED imbalances behind***. Unmitigated is
`fill_state == "UNFILLED"`, which every inventory already carries — **so the discriminator is
mitigation state, and the rule can be quoted rather than a reading defended.** The doctrine says the
same thing in its own words: *"the large gaps left behind by impulsive moves and NEVER FILLED."*

**Size enters only where the STATEMENT is itself comparative** — `GRADE-028` sign (1), *"the number
of momentum imbalances reduces toward none **and they get smaller**"*. Smaller than the ones before
it, within the leg. **Reading a comparative sentence comparatively is reading; supplying a `K` is
inventing**, and seven of this cluster's nine rules have `values: null`, so there is no `K` to read.

## THE LEG IS THE BREAK SERIES, NOT A DEFINITION OF OURS

Eight rule statements use the word "leg" and **none defines one**. `PRIM-005` already carries the
concept — *"this walks the series forward, carrying the leg direction, and each break both
classifies against the current direction and updates it"* — so a leg here is **the bar span between
consecutive break events**, with `BreakEvent.direction` as its direction. **Nothing is invented: the
breaks are the boundaries.**
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_001_swings import Bar, Swing
from app.services.rules.prim_002_imbalances import Imbalance
from app.services.rules.prim_005_breaks import BreakEvent
from app.services.telemetry.records import derived, from_record

#: Why `is_momentum_imbalance` is `None` on every inventory this cluster reads.
#:
#: **BY DOCTRINE, NOT BY OVERSIGHT.** `PRIM-002` populates it only when `momentum_min_width` is
#: supplied, and that is a fixed width test on an imbalance — `GATE-035`'s
#: `imbalance_tiers_0.8_0.4`, banned by name by a rule in this same slice. **The tidy fix is the
#: banned one**: a later reader meets an unpopulated field beside a working writer and closes the
#: gap. This note is what stops that, and it names the parameter so the connection is not left to
#: be re-derived.
MOMENTUM_CLASSIFICATION_NOTE = (
    "is_momentum_imbalance is deliberately NOT populated by this cluster. Setting it requires "
    "PRIM-002's `momentum_min_width`, a fixed width test on an imbalance, which is GATE-035's "
    "banned `imbalance_tiers_0.8_0.4` class. The classification used here is MITIGATION STATE "
    "(fill_state == UNFILLED), which GRADE-037 states as the discriminator and which needs no "
    "declared number. DO NOT 'fix' the None by passing momentum_min_width."
)


def unmitigated(imbalances: Sequence[Imbalance]) -> list[Imbalance]:
    """The momentum imbalances of a leg: the ones price left behind and never came back to.

    `GRADE-037`'s discriminator, quoted rather than derived. **No width test.**
    """
    return [imb for imb in imbalances if imb.fill_state == "UNFILLED"]


@dataclass(frozen=True)
class MomentumLeg:
    """One span between consecutive breaks, with what formed inside it.

    **`start_index` is exclusive of the opening break and `end_index` inclusive of the closing
    one**, so a break belongs to the leg it ends. Stated because an off-by-one here silently
    reassigns every imbalance on a boundary.
    """

    start_index: int
    end_index: int
    direction: str | None
    imbalances: tuple[Imbalance, ...] = ()
    swings: tuple[Swing, ...] = ()

    @property
    def unmitigated(self) -> tuple[Imbalance, ...]:
        return tuple(unmitigated(self.imbalances))

    @property
    def widths(self) -> tuple[float, ...]:
        """Formation-ordered widths of the unmitigated imbalances. ORDINAL USE ONLY."""
        return tuple(imb.width for imb in sorted(self.unmitigated, key=lambda i: i.formed_index))

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_index": self.start_index,
            "end_index": self.end_index,
            "direction": self.direction,
            "imbalances": len(self.imbalances),
            "unmitigated": len(self.unmitigated),
            "swings": len(self.swings),
        }


def legs_from_breaks(
    breaks: Sequence[BreakEvent],
    imbalances: Sequence[Imbalance] = (),
    swings: Sequence[Swing] = (),
) -> list[MomentumLeg]:
    """Split the series into legs at the break events. **The breaks ARE the boundaries.**

    Returns `[]` when there are fewer than two breaks: **one break does not bound a span, and
    emitting a leg from it would be inventing the boundary this function exists to avoid
    inventing.** An empty list is a real answer here and callers must not fill it in.
    """
    ordered = sorted(
        (b for b in breaks if b.bar_index is not None), key=lambda b: b.bar_index
    )
    if len(ordered) < 2:
        return []

    out: list[MomentumLeg] = []
    for opening, closing in zip(ordered, ordered[1:]):
        lo, hi = opening.bar_index, closing.bar_index
        out.append(
            MomentumLeg(
                start_index=lo,
                end_index=hi,
                direction=closing.direction,
                imbalances=tuple(
                    i for i in imbalances if i.formed_index is not None and lo < i.formed_index <= hi
                ),
                swings=tuple(
                    s for s in swings if s.bar_index is not None and lo < s.bar_index <= hi
                ),
            )
        )
    return out


def _spacing(swings: Sequence[Swing]) -> list[float]:
    """Absolute price gaps between consecutive liquidity points, in formation order."""
    ordered = sorted((s for s in swings if s.bar_index is not None), key=lambda s: s.bar_index)
    return [abs(b.price - a.price) for a, b in zip(ordered, ordered[1:])]


def _is_decreasing(values: Sequence[float]) -> bool | None:
    """Is the sequence non-increasing overall? `None` when there is nothing to compare.

    **ORDINAL. No threshold.** *"They get smaller"* is a comparative sentence and is read
    comparatively; a `K` would be invented. **`None` rather than `False` on fewer than two
    values** — a sequence with nothing to compare has not been found non-decreasing, it has not
    been evaluated, and collapsing those is the failure this whole cluster keeps meeting.
    """
    if len(values) < 2:
        return None
    return values[-1] <= values[0]


class ForwardMomentumSigns(RuleImplementation):
    """GRADE-027: the three signs that momentum is still running toward the target."""

    RULE_ID = "GRADE-027"

    COVERAGE_NOTE = (
        "BUILT WITHOUT ANY SIZE THRESHOLD. GRADE-037 supplies the discriminator -- a trend that "
        "leaves UNMITIGATED imbalances behind -- and `fill_state` already carries it, so no "
        "declared number is needed and none is invented. GATE-035 bans the alternative by name. "
        "NOT WIRED: nothing under app/services/live/ evaluates this yet; T-0039 builds the "
        "producer and the seam is a later task. Sign (3) reads BreakEvent origin and is the one "
        "sign whose evidence is a relationship rather than a count."
    )

    @classmethod
    def signs(
        cls, leg: MomentumLeg, breaks: Sequence[BreakEvent] = ()
    ) -> dict[str, dict[str, Any]]:
        """The three signs, each with the coordinates the statement asks for.

        *"Emit each as a boolean with the bar index and price coordinates of the evidence."*
        """
        left_behind = leg.unmitigated
        spacing = _spacing(leg.swings)
        # (3) "price still using its own imbalances to push -- pullbacks bounce off their own
        # gaps and produce the next break": a break whose bar falls inside an imbalance formed
        # EARLIER in the same leg. Structural, and it needs no size or distance test.
        pushing = [
            {"break_id": b.id, "bar_index": b.bar_index, "imbalance_id": imb.id,
             "price_low": imb.price_low, "price_high": imb.price_high}
            for b in breaks
            if b.bar_index is not None and leg.start_index < b.bar_index <= leg.end_index
            for imb in leg.imbalances
            if imb.formed_index is not None and imb.formed_index < b.bar_index
            and imb.price_low <= b.break_price <= imb.price_high
        ]
        return {
            "momentum_imbalances_left_unfilled": {
                "fired": bool(left_behind),
                "count": len(left_behind),
                "coordinates": [
                    {"imbalance_id": i.id, "bar_index": i.formed_index,
                     "price_low": i.price_low, "price_high": i.price_high}
                    for i in left_behind
                ],
            },
            "large_distance_between_liquidity_points": {
                # ORDINAL: is the spacing WIDENING across this leg? "Something pulls the price
                # heavily" is comparative. A "wide enough" test would be
                # `fixed_pct_distance_to_liquidity`, banned by GATE-035 by name.
                "fired": None if len(spacing) < 2 else spacing[-1] >= spacing[0],
                "spacing_points": len(spacing),
                "coordinates": [{"gap": g} for g in spacing],
            },
            "price_uses_its_own_imbalances_to_push": {
                "fired": bool(pushing),
                "count": len(pushing),
                "coordinates": pushing,
            },
        }

    @classmethod
    def evaluate(
        cls, leg: MomentumLeg | None = None, breaks: Sequence[BreakEvent] = ()
    ) -> Any:
        """PASS when any forward sign fired; NOT_APPLICABLE when there is no leg to read.

        **NOT_APPLICABLE rather than FAIL on a missing leg**, and the distinction is the one
        this cluster keeps meeting: no leg means the rule could not look, not that it looked
        and found no momentum.
        """
        if leg is None:
            return cls.evaluation(
                "NOT_APPLICABLE",
                values={
                    "legs_examined": 0,
                    "reason": "no leg supplied — fewer than two breaks bound no span",
                    "momentum_classification": MOMENTUM_CLASSIFICATION_NOTE,
                },
                value_provenance={
                    "legs_examined": derived("count of legs this evaluation read"),
                    "reason": derived("why no verdict was reached"),
                    "momentum_classification": derived("GATE-035 conformance note"),
                },
            )

        signs = cls.signs(leg, breaks)
        fired = [name for name, s in signs.items() if s["fired"] is True]
        values: dict[str, Any] = {
            "legs_examined": 1,
            "leg": leg.as_dict(),
            "signs": signs,
            "signs_fired": fired,
            "signs_total": len(signs),
            "momentum_classification": MOMENTUM_CLASSIFICATION_NOTE,
        }
        return cls.evaluation(
            "PASS" if fired else "FAIL",
            values=values,
            value_provenance={
                "leg": from_record("primitives.breaks"),
                "signs": derived("GRADE-027's three forward signs, read structurally"),
                "signs_fired": derived("names of the signs whose evidence was present"),
                "signs_total": derived("the statement's three"),
                "legs_examined": derived("count of legs this evaluation read"),
                "momentum_classification": derived("GATE-035 conformance note"),
            },
        )


class MomentumSlowdownSigns(RuleImplementation):
    """GRADE-028: the four slowdown signs, which fire AFTER target clearance.

    **The missing producer for `GATE-041`'s three `NOT_EVALUABLE` conditions** — and building it
    resolves those three and no others. `GATE-041`'s remaining four conditions are `NOT_READ`
    (`PRIM-002` x2, `PRIM-005`, `PRIM-006`), and the one it makes MANDATORY,
    `micro_msb_confirms`, is among them. **So this does not make `GATE-041` able to fire, and
    `CANNOT_FIRE_WITHOUT` is deliberately NOT cleared.**
    """

    RULE_ID = "GRADE-028"

    COVERAGE_NOTE = (
        "RESOLVES 3 OF GATE-041's 7 CONDITIONS AND NO MORE. The other four are NOT_READ with "
        "existing producers (PRIM-002 x2, PRIM-005, PRIM-006) and include the MANDATORY one, "
        "micro_msb_confirms. GATE-041.CANNOT_FIRE_WITHOUT is left set on purpose: clearing it "
        "would report the rule unblocked while it remains structurally unable to authorise a "
        "Reverse, and would move effective coverage 50/79 -> 51/79 for an edit rather than for "
        "a capability. Wiring PRIM-002/005/006 into GATE-041 is a separate task. "
        "No size threshold: see MOMENTUM_CLASSIFICATION_NOTE."
    )

    @classmethod
    def signs(cls, leg: MomentumLeg) -> dict[str, dict[str, Any]]:
        """The four slowdown signs, plus the pre-hunt variant, with coordinates."""
        left_behind = sorted(leg.unmitigated, key=lambda i: i.formed_index or 0)
        widths = leg.widths
        spacing = _spacing(leg.swings)
        opposite = [
            i for i in left_behind
            if leg.direction is not None and i.direction is not None
            and str(i.direction) != str(leg.direction)
        ]
        # (3) "imbalances fail their purpose one after another (no new BOS/MSB out of them)".
        # `purpose_verdict` is the field that would answer this and NOTHING POPULATES IT --
        # 1 assignment site, and `target_cleared_at_failure` has ZERO anywhere in app/. So it
        # is reported NOT_READ with its producer named, GATE-041's pattern, rather than
        # evaluated over a field that is structurally None. A verdict over invented values is
        # worth less than an honest not-read.
        return {
            "momentum_imbalances_reduce_and_shrink": {
                # ORDINAL, both halves: fewer than before AND smaller than before. "They get
                # smaller" is comparative in the statement and is read comparatively.
                "fired": _is_decreasing(widths),
                "unmitigated_count": len(left_behind),
                "coordinates": [
                    {"imbalance_id": i.id, "bar_index": i.formed_index, "width": i.width}
                    for i in left_behind
                ],
            },
            "liquidity_point_spacing_tightens": {
                "fired": None if len(spacing) < 2 else spacing[-1] <= spacing[0],
                "spacing_points": len(spacing),
                "coordinates": [{"gap": g} for g in spacing],
            },
            "imbalances_fail_their_purpose": {
                "fired": None,
                "not_read": "purpose_verdict",
                "producer": "GRADE-038 (unimplemented) — and PRIM-002's purpose_verdict has "
                            "one assignment site while target_cleared_at_failure has zero",
                "coordinates": [],
            },
            "opposite_side_momentum_imbalance": {
                "fired": bool(opposite),
                "count": len(opposite),
                "coordinates": [
                    {"imbalance_id": i.id, "bar_index": i.formed_index,
                     "direction": i.direction, "leg_direction": leg.direction}
                    for i in opposite
                ],
            },
            "pre_hunt_close_range_liquidity": {
                # "a slowed trend building extra close-range liquidity right before the final
                # sweep": MORE liquidity points AND tighter spacing, both ordinal.
                "fired": (
                    None if len(spacing) < 2
                    else (spacing[-1] <= spacing[0] and len(leg.swings) > len(left_behind))
                ),
                "liquidity_points": len(leg.swings),
                "coordinates": [{"gap": g} for g in spacing],
            },
        }

    @classmethod
    def evaluate(cls, leg: MomentumLeg | None = None) -> Any:
        if leg is None:
            return cls.evaluation(
                "NOT_APPLICABLE",
                values={
                    "legs_examined": 0,
                    "reason": "no leg supplied — fewer than two breaks bound no span",
                    "momentum_classification": MOMENTUM_CLASSIFICATION_NOTE,
                },
                value_provenance={
                    "legs_examined": derived("count of legs this evaluation read"),
                    "reason": derived("why no verdict was reached"),
                    "momentum_classification": derived("GATE-035 conformance note"),
                },
            )

        signs = cls.signs(leg)
        fired = [n for n, s in signs.items() if s["fired"] is True]
        unread = [n for n, s in signs.items() if s.get("not_read")]
        return cls.evaluation(
            "PASS" if fired else "FAIL",
            values={
                "legs_examined": 1,
                "leg": leg.as_dict(),
                "signs": signs,
                "signs_fired": fired,
                "signs_total": len(signs),
                # THE UNREAD COUNT IS PUBLISHED. A slowdown verdict taken over four of five
                # signs is not the same claim as one taken over five, and the difference is
                # invisible in the verdict.
                "signs_not_read": unread,
                "momentum_classification": MOMENTUM_CLASSIFICATION_NOTE,
            },
            value_provenance={
                "leg": from_record("primitives.breaks"),
                "signs": derived("GRADE-028's four signs plus the pre-hunt variant"),
                "signs_fired": derived("names of the signs whose evidence was present"),
                "signs_total": derived("the statement's four, plus the pre-hunt variant"),
                "signs_not_read": derived("signs whose input field nothing populates"),
                "legs_examined": derived("count of legs this evaluation read"),
                "momentum_classification": derived("GATE-035 conformance note"),
            },
        )
