"""TARGET-006 — perfect > relative (≤0.30%) > separate pools, and equals outrank the deep V.

    "Perfect equal highs/lows are treated as the strongest form of equal liquidity." … "> 0.30%
    treated as SEPARATE liquidity pools, not equals." … "sideways consolidation is not V-shaped
    liquidity 'but if it is an equal lows/high it is more concerning then the V-shaped'" [sic]
    … "The 0.30% threshold is not a standalone trading signal… A relative equal high/low only
    strengthens the quality of a liquidity target; it does not automatically make it the
    active destination."

## THE SAME SHAPE AS TARGET-005, ONE MODULE OVER, AND IT WAS NEARLY MISSED

`PRIM-003` already carries this classifier. `prim_003_liquidity.py:70` declares
`RELATIVE_EQUALS_MAX_DIFF_PCT = 0.3` as *"TARGET-006, verbatim from the registry `values`"*;
`:156` says *"Class 2, ranked by TARGET-006: perfect > relative (≤0.30%) > separate pools"*;
its `COVERAGE_NOTE` lists *"EQUAL_HIGHS_LOWS (TARGET-006)"*. Only the rule *id* was unclaimed.

**T-0028's scope ruling closed the two-homes trap on TARGET-005 and left it open here**,
because the check asked *"does PRIM-004 already do this?"* — which it does not, truthfully and
irrelevantly. The rule-id probe (`grep RULE_ID = "TARGET-006"` → no file) is a TRUE negative
and it is exactly the arm that misleads: the id was absent, the mechanism was not. What found
it was probing the OBJECT's other names — `equals_class`, `EQUAL_HIGHS_LOWS`,
`RELATIVE_EQUALS_MAX_DIFF_PCT`, `SEPARATE_POOLS` — separately, with per-probe counts.

**So this module claims the id and rebuilds nothing.** It reads `LiquidityPool.equals_class`,
`.equals_diff_pct` and `.boosters`, and `EqualsMeasurement` for the tier that emits no pool.

## THE THIRD TIER WAS A TYPE VALUE WITH NO DATA BEHIND IT

`SEPARATE_POOLS` was declared in `EqualsClass`, allowed by `TELEMETRY_SCHEMA.json:544`, named
in TARGET-006's `output` — and assigned nowhere in the repository. The classifier reached the
`> 0.30%` branch and `continue`d, discarding the measurement. `TELEMETRY_SCHEMA.json:550` asks
for the opposite in as many words: *"the measured difference that produced `equals_class`.
Record it even when the class is `SEPARATE_POOLS`."*

**The fix was evidentiary and not behavioural, and the distinction is the whole reason it was
safe.** `PRIM-003.equals_classification` now returns all three tiers; `equal_highs_lows` still
emits pools for two. **The pool inventory is unchanged** — which matters because
`test_equals_are_ranked_by_target_006_and_separate_pools_emit_nothing` has asserted that count
difference since before this rule was claimed, and a third pool object would double-count
liquidity that is already inventoried as two swing levels.

## WHAT THIS RULE DOES NOT BUILD, AND SAYS SO

**The quality boost has no consumer and this module does not become one.** `boosters` is
written by `PRIM-003` and read NOWHERE else under `app/` — measured, zero read sites outside
`prim_003_liquidity.py`. So *"never a destination selector"* currently holds because nothing
reads it at all, **not because anything refuses to**, and the two are different facts with
different lifespans. Reporting the vacuity is this rule's job; building a ranking consumer
nobody has specified would be inventing the boost's magnitude, which the doctrine never gives.

`equals_outrank_v_shaped` is likewise recorded as an ORDERING the engine cannot yet apply:
`TARGET-007`, the deep-V definition, is `status: OPEN` and `PRIM-003` deliberately does not
build `INSTITUTIONAL_LEVEL` for that reason. **There is no V-shaped object to outrank.**
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app.services.rules.base import (
    ConditionReading, RuleImplementation, quorum_blocked,
)
from app.services.rules.prim_003_liquidity import (
    RELATIVE_EQUALS_MAX_DIFF_PCT, EqualsMeasurement, LiquidityPool,
)
from app.services.rules.target_005_clearance import DeclaredPercentage
from app.services.telemetry.records import RuleEvaluation, derived, from_primitive

#: The three tiers, in the rule's own ranking order. Listed so a record can say WHICH
#: vocabulary was checked — a rule made of a category list is defeated by a category nobody
#: enumerated (GATE-038's lesson, applied to a smaller list).
EQUALS_TIERS: tuple[str, ...] = ("PERFECT", "RELATIVE", "SEPARATE_POOLS")

#: The default when a requirement of this rule cannot be read. CLASSIFY_ONLY: the tier
#: assignment is complete and checkable, and the ranking half is not — so the honest outcome
#: is that the classification stands and NO ranking claim is made.
#:
#: WHY IT POINTS THIS WAY, stated next to the rule it belongs to because `quorum_blocked`
#: deliberately refuses a fallback: TARGET-006's own closing clause is that a relative equal
#: "does not automatically make it the active destination". So the conservative direction is
#: to apply no boost at all, which is what CLASSIFY_ONLY means. GATE-041's CONTINUE and
#: GATE-040's FORWARD point opposite ways for the same reason — each is conservative FOR ITS
#: OWN STATEMENT, and that is why the default cannot be inherited from a shared helper.
CLASSIFY_ONLY = "CLASSIFY_ONLY"

#: HIS number, OUR denominator — the same split as TARGET-005's ~1%, and the carrier is
#: imported rather than redeclared for the same reason the value is.
#:
#: `_pct` READS `PRIM-003`'s constant instead of restating `0.3`. A literal here would be a
#: second home for the threshold this module exists to check, and it would keep agreeing with
#: itself after someone changed the primitive.
DECLARED_RELATIVE_EQUALS = DeclaredPercentage(
    name="relative_equals_max_diff",
    pct=RELATIVE_EQUALS_MAX_DIFF_PCT,
    authority="TRADER, self-labelled provisional",
    source=(
        "TARGET-006 values.relative_equals_max_diff_pct = 0.3, with his own hedge carried in "
        "the same block: values.self_labelled = 'an initial calibration value and may be "
        "refined during validation' (answers Q4). The registry also records that the number "
        "is NEW — nowhere in the workspace text or the chart images — so no corpus exists to "
        "calibrate it against. Declared, never fitted."
    ),
    measured_from="MEAN_OF_THE_PAIR",
    measured_from_authority="ENGINEERING",
    measured_from_source=(
        "TARGET-006 says 'price difference <= 0.30%' and never says of what; unlike "
        "TARGET-005 it carries no pct_of_what field at all, which is NOT the same as being "
        "documented-unstated. PRIM-003 measures `abs(a.price - b.price) / abs(mean) * 100` "
        "against the mean of the two levels and states that basis at prim_003_liquidity.py:"
        "162. Stamped here with its authority so a later ruling can recompute stored history."
    ),
)


@dataclass(frozen=True)
class EqualsConformance:
    """What the emitted output says about TARGET-006, per tier. Nothing is reclassified."""

    pools_by_tier: dict[str, int]
    measurements_by_tier: dict[str, int]
    #: Pools whose `boosters` carry EQUALS — the quality signal, emitted and unread.
    boosted_pools: int
    #: The widest and narrowest difference recorded in each tier, so a tier that has gone
    #: vacuous is visible rather than inferred (GATE-038's amplifier_rate lesson).
    diff_pct_range_by_tier: dict[str, tuple[float, float] | None]

    def as_dict(self) -> dict[str, Any]:
        return {
            "pools_by_tier": dict(self.pools_by_tier),
            "measurements_by_tier": dict(self.measurements_by_tier),
            "boosted_pools": self.boosted_pools,
            "diff_pct_range_by_tier": {
                k: list(v) if v is not None else None
                for k, v in self.diff_pct_range_by_tier.items()
            },
        }


class EqualsRanking(RuleImplementation):
    """TARGET-006: the three tiers, checked over PRIM-003's output."""

    RULE_ID = "TARGET-006"

    #: DECLARED, and the opposite answer to TARGET-005's in the same task — deliberately.
    #:
    #: For TARGET-005 the post-sweep reaction producer EXISTS (`SweepEvents._reaction`), so
    #: declaring one there would have understated coverage. Here the V-shaped liquidity
    #: object genuinely does not exist and cannot: TARGET-007 is OPEN because "a 'Deep-V' is
    #: not defined by a fixed retracement percentage or ATR value", and PRIM-003 declines to
    #: build INSTITUTIONAL_LEVEL for that reason. So TARGET-006 returns NOT_APPLICABLE
    #: forever unless a violation appears — registered, green, and deciding nothing, which
    #: is exactly what this bucket exists to keep out of the effective-coverage figure.
    #:
    #: Named as the missing DATA rather than a rule id, following TARGET-001: no registry
    #: rule PRODUCES a V-shaped object, so a rule-id graph cannot see the edge (B44).
    #:
    #: The BOOST's absence is NOT listed here, because it is a different absence: the
    #: producer exists and nothing calls it. That is NOT_READ, reported per-condition —
    #: "nobody has built this" and "somebody forgot to call this" have different owners,
    #: different fixes and different lifespans (base.py:80-86).
    CANNOT_FIRE_WITHOUT = ("v_shaped_liquidity",)

    COVERAGE_NOTE = (
        "CONFORMANCE ONLY, AND IMPLEMENTED-BUT-BLOCKED: PASS is unreachable today because "
        "both non-classification requirements are unreadable, so this rule returns "
        "NOT_APPLICABLE unless a tier violation appears. The classifier lives in PRIM-003 "
        "(prim_003_liquidity.py:156 — 'Class 2, ranked by TARGET-006'), which was built to "
        "this rule before the id was claimed; this module claims the id and READS the "
        "emitted equals_class / equals_diff_pct / boosters. PARTIAL, and the gap is named: "
        "the quality BOOST has no consumer anywhere under app/ — boosters has zero read "
        "sites outside prim_003_liquidity.py — so 'a booster, never a destination selector' "
        "holds vacuously today. And equals-outrank-V-shaped cannot be applied because "
        "TARGET-007 is OPEN and PRIM-003 builds no INSTITUTIONAL_LEVEL to rank against. "
        "NOT WIRED — nothing under app/services/live/ imports THIS module, measured with "
        "prim_003_liquidity as the must-hit arm. AND THE HONEST HALF, which B142 exists to "
        "stop being glossed: live/shadow.py:46 DOES import PRIM-003, the module T-0028 "
        "edited. The shadow calls LiquidityPools.detect only; `equals_classification` has no "
        "caller under live/, and the pool inventory detect returns is unchanged — asserted, "
        "not asserted-about. So the edit is inert on the live path rather than absent from it."
    )

    @classmethod
    def declared_parameters(cls) -> dict[str, Any]:
        return dict(DECLARED_RELATIVE_EQUALS.as_values())

    @classmethod
    def boost_conditions(cls, booster_read_sites: int) -> list[ConditionReading]:
        """The two things TARGET-006 asks for beyond classification, honestly stated.

        `booster_read_sites` is supplied by the caller — measured, not assumed — so that the
        day something DOES consume the boost, this reports TRUE without an edit here.
        """
        return [
            ConditionReading(
                name="quality_boost_applied_to_target",
                state="TRUE" if booster_read_sites else "NOT_READ",
                unread_producer=(
                    None if booster_read_sites
                    else "PRIM-003.LiquidityPool.boosters (emitted, zero read sites)"
                ),
            ),
            ConditionReading(
                name="equals_outrank_v_shaped_liquidity",
                state="NOT_EVALUABLE",
                missing_producer=(
                    "v_shaped_liquidity — TARGET-007 is OPEN ('a Deep-V is not defined by a "
                    "fixed retracement percentage or ATR value') and PRIM-003 builds no "
                    "INSTITUTIONAL_LEVEL for that reason, so there is nothing to outrank"
                ),
            ),
        ]

    @classmethod
    def conformance(
        cls,
        pools: Sequence[LiquidityPool],
        measurements: Sequence[EqualsMeasurement] = (),
    ) -> tuple[EqualsConformance, list[str]]:
        """Read the tiers off the emitted objects. Returns `(conformance, violations)`."""
        equals_pools = [p for p in pools if p.pool_class == "EQUAL_HIGHS_LOWS"]

        pools_by_tier = {t: 0 for t in EQUALS_TIERS}
        for p in equals_pools:
            if p.equals_class in pools_by_tier:
                pools_by_tier[p.equals_class] += 1

        measurements_by_tier = {t: 0 for t in EQUALS_TIERS}
        for m in measurements:
            measurements_by_tier[m.equals_class] += 1

        ranges: dict[str, tuple[float, float] | None] = {}
        for tier in EQUALS_TIERS:
            diffs = [m.equals_diff_pct for m in measurements if m.equals_class == tier]
            ranges[tier] = (min(diffs), max(diffs)) if diffs else None

        violations: list[str] = []

        # THE THIRD TIER IS A SEPARATION, NOT A DEGRADATION. A pool carrying it would mean
        # the classifier had emitted an equals object for two levels that are not equals.
        for p in equals_pools:
            if p.equals_class == "SEPARATE_POOLS":
                violations.append(
                    f"{p.id} is an EQUAL_HIGHS_LOWS pool classed SEPARATE_POOLS — above "
                    "0.30% the two levels are distinct pools, already inventoried as swing "
                    "levels; an equals object here double-counts the same liquidity"
                )
            if p.equals_class == "RELATIVE" and (
                p.equals_diff_pct is None
                or p.equals_diff_pct > DECLARED_RELATIVE_EQUALS.pct
            ):
                violations.append(
                    f"{p.id} is classed RELATIVE with equals_diff_pct="
                    f"{p.equals_diff_pct} — outside the declared "
                    f"{DECLARED_RELATIVE_EQUALS.pct}% band"
                )
            if p.equals_class == "PERFECT" and p.equals_diff_pct not in (0, 0.0):
                violations.append(
                    f"{p.id} is classed PERFECT with a non-zero difference "
                    f"{p.equals_diff_pct}"
                )
            if p.equals_class in ("PERFECT", "RELATIVE") and "EQUALS" not in p.boosters:
                violations.append(
                    f"{p.id} is an equals pool carrying no EQUALS booster — the rule's "
                    "output requires the boost to be recorded on the target's quality"
                )

        # THE SCHEMA'S REQUIREMENT, CHECKED RATHER THAN ASSUMED: every measurement carries a
        # difference, including the tier that emits no pool.
        for m in measurements:
            if m.equals_diff_pct is None:
                violations.append(
                    f"{m.id} records no equals_diff_pct — TELEMETRY_SCHEMA.json:550 "
                    "requires the measured difference even when the class is SEPARATE_POOLS"
                )

        return EqualsConformance(
            pools_by_tier=pools_by_tier,
            measurements_by_tier=measurements_by_tier,
            boosted_pools=sum(1 for p in equals_pools if "EQUALS" in p.boosters),
            diff_pct_range_by_tier=ranges,
        ), violations

    @classmethod
    def evaluate(
        cls,
        pools: Sequence[LiquidityPool],
        measurements: Sequence[EqualsMeasurement] = (),
        *,
        booster_read_sites: int = 0,
    ) -> RuleEvaluation:
        """TARGET-006's telemetry over one scan's output.

        NOT_APPLICABLE when the classifier considered no pair: a scan with fewer than two
        same-side swings carries no evidence about the ranking in either direction, and
        recording that is not the same as passing.
        """
        conformance, violations = cls.conformance(pools, measurements)
        conditions = cls.boost_conditions(booster_read_sites)

        values: dict[str, Any] = {
            **conformance.as_dict(),
            "tiers_checked": list(EQUALS_TIERS),
            "pairs_classified": len(measurements),
            "conditions": {c.name: c.state for c in conditions},
            "unreadable_conditions": {
                c.name: (c.missing_producer or c.unread_producer)
                for c in conditions
                if c.state in ("NOT_EVALUABLE", "NOT_READ")
            },
            **cls.declared_parameters(),
        }

        provenance: dict[str, Any] = {
            "pools_by_tier": from_primitive("liquidity_pools[]", "equals_class"),
            "measurements_by_tier": from_primitive(
                "equals_measurements[]", "equals_class"
            ),
            "boosted_pools": from_primitive("liquidity_pools[]", "boosters"),
            "diff_pct_range_by_tier": from_primitive(
                "equals_measurements[]", "equals_diff_pct"
            ),
            "tiers_checked": derived("TARGET-006 statement's three named tiers"),
            "pairs_classified": derived("len(PRIM-003.equals_classification output)"),
            "conditions": derived(
                "TARGET-006's two non-classification requirements, each with its "
                "evaluability; NOT_READ names a producer that exists and is uncalled"
            ),
            "unreadable_conditions": derived(
                "conditions whose state is NOT_EVALUABLE or NOT_READ, with the producer named"
            ),
        }
        for key in DECLARED_RELATIVE_EQUALS.as_values():
            provenance[key] = derived(f"TARGET-006 declared parameter {key}")

        if violations:
            values["violations"] = violations
            return cls.evaluation("FAIL", values=values, value_provenance=provenance)

        # THE SHARED INVARIANT: no rule reaches a verdict while a condition is unreadable.
        # Routed through `base.quorum_blocked` rather than derived inline — two inline
        # copies are SUPPOSED to differ in exactly the place a mistake would appear, so a
        # reviewer reading them side by side cannot tell a correct opposite from a wrong one.
        #
        # THIS IS THE PATH TAKEN TODAY, EVERY TIME. Both of TARGET-006's non-classification
        # requirements are unreadable — the boost has no consumer and TARGET-007 is OPEN —
        # so a PASS here would claim conformance to a three-part rule on the one part that
        # can be read, with the denominator silently shrinking to the readable subset.
        blocked = quorum_blocked(conditions, default_outcome=CLASSIFY_ONLY)
        if blocked is not None:
            unreadable, default_ranking = blocked
            values["unreadable_inputs"] = unreadable
            values["ranking_outcome"] = default_ranking
            values["not_applicable_reason"] = (
                "the tier classification conforms and is reported above, but TARGET-006's "
                "ranking half cannot be read: "
                + "; ".join(f"{k} <- {v}" for k, v in sorted(unreadable.items()))
                + ". Reported as NOT_APPLICABLE rather than PASS because a rule that scores "
                "its readable conditions and stops has shrunk its own denominator."
            )
            provenance["unreadable_inputs"] = derived(
                "base.quorum_blocked over TARGET-006's condition readings"
            )
            provenance["ranking_outcome"] = derived(
                f"TARGET-006's own blocked-state default, {CLASSIFY_ONLY}: its closing "
                "clause forbids an equal from becoming the active destination, so applying "
                "no boost is the conservative direction FOR THIS RULE"
            )
            provenance["not_applicable_reason"] = derived(
                "conditions whose state is NOT_EVALUABLE or NOT_READ"
            )
            return cls.evaluation(
                "NOT_APPLICABLE", values=values, value_provenance=provenance
            )

        if not measurements and not any(
            p.pool_class == "EQUAL_HIGHS_LOWS" for p in pools
        ):
            values["not_applicable_reason"] = (
                "the classifier considered no swing pair in this scan, so nothing here "
                "carries evidence about the equals ranking. Reported rather than passed."
            )
            provenance["not_applicable_reason"] = derived(
                "pairs_classified == 0 and no EQUAL_HIGHS_LOWS pool present"
            )
            return cls.evaluation(
                "NOT_APPLICABLE", values=values, value_provenance=provenance
            )

        return cls.evaluation("PASS", values=values, value_provenance=provenance)
