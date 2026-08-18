"""GRADE-036, GRADE-037, GRADE-038 — the three momentum graders, all keyed on MITIGATION STATE.

One module because all three read the same two objects — a leg and its imbalances — and a second
construction of either would be `GATE-011`'s shape.

## GRADE-037 IS THE RULE THE WHOLE CLUSTER LEANS ON, AND IT IS DECLARED

*"STRONG TREND = the trend is powered by imbalances (its pullbacks consume imbalances and produce
the next break). STRONG TREND + MOMENTUM = the trend uses imbalances **AND LEAVES UNMITIGATED
IMBALANCES BEHIND**. The discriminator is therefore **mitigation state, not candle size**: on one
leg, count the IMB boxes that were retested versus the Momentum IMB boxes that never were."*

**`fill_state` is that discriminator and every inventory already carries it.** This is the rule
`T-0039` stage 1 quoted to justify not passing `PRIM-002`'s `momentum_min_width` — and it is now
the rule that states it directly, so **the justification and the implementation converge on the
same field**. *No tier, no threshold, no `K`.*

## GRADE-038 REPORTS ITS OWN DECLARED INPUTS AS UNPOPULATED

*"The engine must record, per imbalance, its purpose verdict, whether the main target was cleared
at the time, and whether the failed box later held price from the other side."*

`Imbalance` carries exactly those three fields. **Measured on a real 320-bar inventory of 186
imbalances: all three are `None` for every one, and `target_cleared_at_failure` has ZERO assignment
sites anywhere in `app/`.**

> **So this rule reports them `NOT_READ` with the producer named rather than evaluating over
> `None`.** *A rule reporting that its own declared inputs have no producer is a stronger finding
> than a verdict computed from defaults* — and it is `T-0033`'s subject found by the rule those
> fields were declared for, which is the best available witness. **Populating them here to make a
> verdict appear would be absorbing `T-0033` to produce a number.**

## GRADE-036's PICTURE TEST IS READ ORDINALLY, AND THE TENSION IS NAMED

*"Shrinking candle bodies/ranges at a target zone = tradable; giant candles into the zone = stand
aside."*

**`GATE-035` bans `candle_body_size_threshold` in the same slice.** The two are reconcilable and
the reconciliation is the same one stage 1 made: **"shrinking" is comparative — smaller than the
ones before it, within the leg — and a comparative sentence read comparatively needs no threshold.**
What `GATE-035` bans is a *fixed* body-size test. **Neither rule is bent to fit the other; the
statement was already ordinal.**
"""
from __future__ import annotations

from typing import Any, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.grade_027_momentum_signs import (
    MOMENTUM_CLASSIFICATION_NOTE,
    MomentumLeg,
    _is_decreasing,
)
from app.services.rules.prim_002_imbalances import Imbalance
from app.services.telemetry.records import derived, from_record

#: GRADE-038's three declared per-imbalance fields, with the producer that would populate each.
#: `None` means NO producer exists — which is not the same as one that ran and found nothing.
PURPOSE_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("purpose_verdict", "GRADE-038 (this rule) — one assignment site in app/, never on the "
                        "inventory path"),
    ("target_cleared_at_failure", None),
    ("mutated_to_sr_flip", "PRIM-006 (SRFlipZones.detect) — not called on the inventory path"),
)

TrendTier = str  # "STRONG_TREND" | "STRONG_TREND_PLUS_MOMENTUM" | "NOT_A_TREND"


class TwoTierTrendGrade(RuleImplementation):
    """GRADE-037: STRONG TREND, or STRONG TREND + MOMENTUM. Keyed on mitigation, not size."""

    RULE_ID = "GRADE-037"

    COVERAGE_NOTE = (
        "THE DISCRIMINATOR IS DECLARED, NOT DERIVED: GRADE-037's own statement says 'the "
        "discriminator is mitigation state, not candle size' and names the count -- retested IMB "
        "boxes versus Momentum IMB boxes that never were. fill_state carries it and no threshold "
        "is needed. This is the rule T-0039 stage 1 quoted to justify not passing PRIM-002's "
        "momentum_min_width, so the justification and the implementation converge on one field. "
        "The word 'unmitigated' appears nowhere in the workspace text -- the two-tier formula "
        "exists only on the image -- which the registry statement says itself. NOT WIRED."
    )

    @classmethod
    def grade(cls, leg: MomentumLeg) -> TrendTier:
        consumed = [i for i in leg.imbalances if i.fill_state != "UNFILLED"]
        left_behind = list(leg.unmitigated)
        if not consumed:
            # "Powered by imbalances" requires that pullbacks CONSUMED some. A leg that consumed
            # none is not a weak trend; it is not this rule's subject at all.
            return "NOT_A_TREND"
        return "STRONG_TREND_PLUS_MOMENTUM" if left_behind else "STRONG_TREND"

    @classmethod
    def evaluate(cls, leg: MomentumLeg | None = None) -> Any:
        if leg is None:
            return cls.evaluation(
                "NOT_APPLICABLE",
                values={"legs_examined": 0, "reason": "no leg supplied"},
                value_provenance={
                    "legs_examined": derived("count of legs this evaluation read"),
                    "reason": derived("why no verdict was reached"),
                },
            )
        consumed = [i for i in leg.imbalances if i.fill_state != "UNFILLED"]
        left_behind = list(leg.unmitigated)
        tier = cls.grade(leg)
        return cls.evaluation(
            "PASS" if tier != "NOT_A_TREND" else "NOT_APPLICABLE",
            values={
                "legs_examined": 1,
                "tier": tier,
                # THE COUNT THE STATEMENT ASKS FOR, BOTH SIDES. "Count the IMB boxes that were
                # retested versus the Momentum IMB boxes that never were" is a comparison, and
                # either number alone cannot express it.
                "retested_boxes": len(consumed),
                "never_retested_boxes": len(left_behind),
                "imbalances_in_leg": len(leg.imbalances),
                "discriminator": "fill_state — mitigation, not candle size (GRADE-037)",
                "momentum_classification": MOMENTUM_CLASSIFICATION_NOTE,
            },
            value_provenance={
                "tier": derived("GRADE-037's two tiers, from mitigation state"),
                "retested_boxes": from_record("primitives.imbalances.fill_state"),
                "never_retested_boxes": from_record("primitives.imbalances.fill_state"),
                "imbalances_in_leg": derived("count of imbalances formed inside the leg"),
                "discriminator": derived("GRADE-037 statement"),
                "legs_examined": derived("count of legs this evaluation read"),
                "momentum_classification": derived("GATE-035 conformance note"),
            },
        )


class PreferSlowedMomentum(RuleImplementation):
    """GRADE-036: prefer a target the momentum has already slowed into. A flag, not a failure."""

    RULE_ID = "GRADE-036"

    COVERAGE_NOTE = (
        "SOFT_PREFERENCE, and a deviation is a FLAG rather than a failure -- the statement says "
        "so. The picture test ('shrinking candle bodies/ranges = tradable; giant candles into "
        "the zone = stand aside') is read ORDINALLY, because GATE-035 bans "
        "candle_body_size_threshold in the same slice and 'shrinking' is comparative in the "
        "statement. Neither rule is bent to fit the other: the sentence was already ordinal. "
        "The destination half -- 'the accumulated LIQ pools left behind by the decaying leg "
        "become the targets' -- is recorded as the leg's liquidity points rather than ranked, "
        "because ranking them is TARGET-003's job and not this rule's. NOT WIRED."
    )

    @classmethod
    def evaluate(cls, leg: MomentumLeg | None = None) -> Any:
        if leg is None:
            return cls.evaluation(
                "NOT_APPLICABLE",
                values={"legs_examined": 0, "reason": "no leg supplied"},
                value_provenance={
                    "legs_examined": derived("count of legs this evaluation read"),
                    "reason": derived("why no verdict was reached"),
                },
            )
        slowing = _is_decreasing(leg.widths)
        return cls.evaluation(
            # NOT_APPLICABLE when there is nothing to compare -- a leg with fewer than two
            # unmitigated imbalances has not been found fast, it has not been read.
            "NOT_APPLICABLE" if slowing is None else ("PASS" if slowing else "FAIL"),
            values={
                "legs_examined": 1,
                "momentum_slowing": slowing,
                "widths": list(leg.widths),
                # The destination half of the statement: the pools the decaying leg left behind.
                # RECORDED, not ranked -- ranking targets is TARGET-003's rule, not this one's.
                "liquidity_points_left_behind": len(leg.swings),
                "deviation_is_a_flag_not_a_failure": True,
                "momentum_classification": MOMENTUM_CLASSIFICATION_NOTE,
            },
            value_provenance={
                "momentum_slowing": derived(
                    "ordinal over the leg's own unmitigated widths — no threshold"
                ),
                "widths": from_record("primitives.imbalances"),
                "liquidity_points_left_behind": from_record("primitives.swings"),
                "deviation_is_a_flag_not_a_failure": derived("GRADE-036 statement"),
                "legs_examined": derived("count of legs this evaluation read"),
                "momentum_classification": derived("GATE-035 conformance note"),
            },
        )


class ImbalancePurposeTest(RuleImplementation):
    """GRADE-038: did each imbalance do its job, and does its failure change the trend for good?"""

    RULE_ID = "GRADE-038"

    COVERAGE_NOTE = (
        "REPORTS ITS OWN DECLARED INPUTS AS UNPOPULATED RATHER THAN EVALUATING OVER None. "
        "Imbalance carries purpose_verdict, target_cleared_at_failure and mutated_to_sr_flip -- "
        "the three fields this rule's statement names -- and MEASURED on a real 320-bar "
        "inventory of 186 imbalances all three are None for every one, with "
        "target_cleared_at_failure having ZERO assignment sites anywhere in app/. That is "
        "T-0033's subject found by the rule those fields were declared for. A verdict computed "
        "from defaults would be worth less than this NOT_READ, and populating them here would "
        "be absorbing T-0033 to produce a number. The LOCATION rule -- a failure before the "
        "target is inducement, after it is a PERMANENT TREND CHANGE -- is implemented and "
        "reachable the day the fields are populated. NOT WIRED."
    )

    @classmethod
    def unreadable_fields(cls, imbalances: Sequence[Imbalance]) -> dict[str, dict[str, Any]]:
        """Which declared inputs are unpopulated, and who would populate each."""
        out: dict[str, dict[str, Any]] = {}
        for field, producer in PURPOSE_FIELDS:
            values = {getattr(i, field, None) for i in imbalances}
            out[field] = {
                "populated": values != {None} and values != set(),
                "producer": producer,
                "distinct_values": len(values),
            }
        return out

    @classmethod
    def classify(cls, imbalance: Imbalance) -> dict[str, Any]:
        """One imbalance's purpose verdict and what its failure means, IF the fields are set.

        **Location decides meaning** — *"a failure BEFORE the target is a temporary detour (the
        inducement); a failure AFTER the target is cleared gets its own named rule — PERMANENT
        TREND CHANGE."*
        """
        verdict = getattr(imbalance, "purpose_verdict", None)
        cleared = getattr(imbalance, "target_cleared_at_failure", None)
        if verdict is None:
            return {"imbalance_id": imbalance.id, "purpose": None, "meaning": None,
                    "not_read": "purpose_verdict"}
        if verdict != "FAILED":
            return {"imbalance_id": imbalance.id, "purpose": verdict, "meaning": "SERVED"}
        if cleared is None:
            return {"imbalance_id": imbalance.id, "purpose": verdict, "meaning": None,
                    "not_read": "target_cleared_at_failure"}
        return {
            "imbalance_id": imbalance.id,
            "purpose": verdict,
            "meaning": "PERMANENT_TREND_CHANGE" if cleared else "INDUCEMENT",
            "mutated_to_sr_flip": getattr(imbalance, "mutated_to_sr_flip", None),
        }

    @classmethod
    def evaluate(cls, imbalances: Sequence[Imbalance] = ()) -> Any:
        fields = cls.unreadable_fields(imbalances)
        unreadable = [name for name, f in fields.items() if not f["populated"]]
        classified = [cls.classify(i) for i in imbalances]
        readable = [c for c in classified if c.get("meaning") is not None]

        return cls.evaluation(
            # NOT_APPLICABLE while the declared inputs are unpopulated. FAIL would claim the
            # imbalances were examined and found wanting; PASS would claim they served.
            "NOT_APPLICABLE" if unreadable or not imbalances else "PASS",
            values={
                "imbalances_examined": len(imbalances),
                "imbalances_classified": len(readable),
                "declared_fields": fields,
                "fields_not_read": unreadable,
                "classifications": classified[:20],
                "location_rule": (
                    "failure BEFORE the target = INDUCEMENT; failure AFTER the target is "
                    "cleared = PERMANENT_TREND_CHANGE (GRADE-038)"
                ),
            },
            value_provenance={
                "imbalances_examined": derived("count supplied to this rule"),
                "imbalances_classified": derived("how many reached a meaning"),
                "declared_fields": derived("GRADE-038's three declared per-imbalance fields"),
                "fields_not_read": derived("declared fields with no producer on this path"),
                "classifications": from_record("primitives.imbalances"),
                "location_rule": derived("GRADE-038 statement"),
            },
        )
