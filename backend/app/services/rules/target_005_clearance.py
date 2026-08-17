"""TARGET-005 — clearance is structural, and this module CHECKS that rather than deciding it.

    "A liquidity level is not considered cleared solely because price wicks through it or
    closes beyond it. The sweep itself is only the first step. The engine must evaluate the
    market reaction after the sweep." … "A wick through the level is sufficient to mark the
    liquidity as tested, but not necessarily consumed." … "Market structure always has
    higher priority than wick penetration."

## THIS RULE HAS NO MECHANISM OF ITS OWN, DELIBERATELY

`PRIM-004` already enforces TARGET-005 and says so eleven times in its own prose —
`prim_004_sweeps.py:7` is literally "THE RULE THIS PRIMITIVE EXISTS TO ENFORCE IS
TARGET-005", and `:314` carries the doctrine sentence over `_apply_state`. Nothing claimed
the rule *id*, which is why the coverage tool reported it unimplemented and why this file
exists.

**So the id is claimed here and the mechanism is NOT rebuilt.** Two code paths computing
clearance is the same-claim-two-homes failure, and the copy nothing checks is the one that
rots. Everything below READS `PRIM-004`'s emitted output:

    LiquidityPool.state          UNTESTED / TESTED_NOT_CONSUMED / CONSUMED
    SweepEvent.cleared           the per-excursion verdict
    SweepEvent.structural_reaction / .reaction_break_ids     the evidence for it
    SweepEvent.penetration_pct / .weak_sweep / .wick_or_close

**THE ONE-GREP TEST FOR WHETHER THAT PROMISE HELD:** every clearance key in this rule's
`values` carries `from_primitive(...)` provenance naming the emitted object it was read off.
A key that had been recomputed here could only carry `derived(...)`. A conformance rule that
recomputes the states in order to assert them has re-implemented clearance with extra steps,
and the provenance is where that shows.

## WHAT A CONFORMANCE RULE CAN STILL GET WRONG, AND WHAT IS DONE ABOUT IT

**Asserting a property no case in the corpus exercises.** Collapsing `tested` and `consumed`
into one boolean passes every fixture in which the two happen to agree, so the checks below
count DIVERGENT cases and a report with none is a FAIL, not a pass: the doctrine sentence
names a case and the evidence must contain it.

## THE PERCENTAGE ANNOTATES; IT DOES NOT GATE — AND THAT IS A PROBE, NOT A CLAIM

`weak_sweep_penetration_pct` is his, self-labelled *"approximate calibration values … should
only be used as supporting information"*. `penetration_removal_probe` re-runs `PRIM-004`
with the VALUE varied across the decision path and compares `PRIM-004`'s own verdicts. It
varies the value rather than deleting the symbol, and the distinction is not pedantic:
**deleting the symbol raises `NameError`, and must, because TARGET-005's own `output` field
requires `penetration_pct` to be measured and the ~1% band to be reported.** A rule that
mandates a measurement cannot be checked by removing the measurement.

**A removal probe over a corpus that straddles nothing proves nothing** — unchanged verdicts
are guaranteed when no input sits near the boundary, and the probe would then pass a correct
and an incorrect implementation alike. So `RemovalProbe.discriminating_cases` counts the
cases where the constant, IF it gated, WOULD force the opposite verdict, and a probe with
none of those is reported as `INDETERMINATE` rather than as a pass.

## TWO PERCENTAGES, TWO AUTHORITIES, AND THEY ARE NOT THE SAME AUTHORITY

`1.0` is HIS, hedged by him. `LEVEL_PRICE` — the answer to *one percent of what* — is OURS:
the registry records `"pct_of_what": "UNSTATED — level price? swing range? never said"`. The
declared-parameter carrier therefore stamps the value's authority and the DENOMINATOR's
authority separately. Flattening them into one `_authority` field would publish our
denominator under his name, which is the one thing this loop refuses.

## AND SINGLE-VS-CUMULATIVE IS UNSTATED TOO — the registry says so and asks for both

TARGET-005's notes: *"Single-vs-cumulative is unspecified: emit BOTH a per-bar maximum and
an episode maximum, and declare which the flag reads. [ENGINEERING]"* `PRIM-004` emits one
`penetration_pct` per EXCURSION and a pool is usually hunted more than once, so the two
quantities are different and the difference is not academic: measured over the pinned
corpus, **76,171 of 238,040 swept (window, pool) pairs contain an excursion whose weak/strong
class disagrees with the episode maximum's.** Both are emitted here, read off the events, and
`PENETRATION_EPISODE_BASIS` declares which one `weak_sweep` reads.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_003_liquidity import LiquidityPool
from app.services.rules.prim_004_sweeps import (
    PENETRATION_PCT_BASIS, WEAK_SWEEP_PENETRATION_PCT, SweepEvent,
)
from app.services.telemetry.records import RuleEvaluation, derived, from_primitive

#: The states TARGET-005's `output` field names. Read from the pool, never assigned here.
TESTED = "TESTED_NOT_CONSUMED"
CONSUMED = "CONSUMED"
UNTESTED = "UNTESTED"


@dataclass(frozen=True)
class DeclaredPercentage:
    """A percentage plus the denominator nobody stated, each with its own authority.

    Its own type rather than a shared carrier, matching `DeclaredWindow` (GATE-038),
    `DeclaredEngineering` (GATE-029) and `DeclaredQuorum` (GRADE-031): the reason is recorded
    at `gate_029_stop_flags.py:120` — these belong to the rules that carry them, and a
    project-wide bag of declared values detaches the choice from the rule it constrains.

    **`measured_from_authority` IS A SEPARATE FIELD AND THAT IS THE POINT.** GATE-038's
    registry precedent — `amplifier_edge_tolerance_pct` / `_ratified` / `_authority` /
    `_measured_from` at `RULE_REGISTRY.json:992-995` — carries ONE authority because both its
    number and its `NEAREST_EDGE` basis are engineering. Here the number is the trader's and
    the basis is ours, so one field would have to lie about one of them.
    """

    #: Stem, not the full key: `as_values()` appends `_pct` and the sibling suffixes, so the
    #: registry's four-field shape is produced rather than restated.
    name: str
    pct: float
    #: WHO fixed the number.
    authority: str
    source: str
    #: The denominator — TARGET-005's `pct_of_what`, TARGET-006's unstated basis.
    measured_from: str
    measured_from_authority: str
    measured_from_source: str
    ratified: bool = False

    def as_values(self) -> dict[str, Any]:
        return {
            f"{self.name}_pct": self.pct,
            f"{self.name}_ratified": self.ratified,
            f"{self.name}_authority": self.authority,
            f"{self.name}_source": self.source,
            f"{self.name}_measured_from": self.measured_from,
            f"{self.name}_measured_from_authority": self.measured_from_authority,
            f"{self.name}_measured_from_source": self.measured_from_source,
        }


#: HIS number, OUR denominator. Unratified because he hedged the number himself and because
#: nobody has ever ruled on the denominator.
#:
#: **BOTH FIELDS ARE READ FROM `PRIM-004`, NOT RETYPED, AND THAT IS DELIBERATE.** This rule
#: exists because the same claim living in two places is how one copy rots. A carrier that
#: restated `1.0` and `"LEVEL_PRICE"` as literals would be a second home for exactly the two
#: values this module was written to stop duplicating — and it would keep passing after
#: someone changed `PRIM-004`. The declaration here adds the AUTHORITY and the RATIFICATION
#: that `PRIM-004` has no field for; the value and the basis stay its.
DECLARED_WEAK_SWEEP = DeclaredPercentage(
    name="weak_sweep_penetration",
    pct=WEAK_SWEEP_PENETRATION_PCT,
    authority="TRADER, self-labelled provisional",
    source=(
        "TARGET-005 values.weak_sweep_penetration_pct = 1.0. His hedge, in his own words "
        "(answers Q6): the ~1% figures are 'approximate calibration values and should only "
        "be used as supporting information'. The registry also records that the figure "
        "appears in NO workspace page and in NONE of the chart images, so no corpus exists "
        "to calibrate it against — it is declared, never fitted."
    ),
    measured_from=PENETRATION_PCT_BASIS,
    measured_from_authority="ENGINEERING",
    measured_from_source=(
        "TARGET-005 values.pct_of_what = 'UNSTATED — level price? swing range? never said'. "
        "PRIM-004 measures `pen / abs(level) * 100` (prim_004_sweeps.py:260) and declares "
        "the basis on every record as `penetration_pct_basis`. Stamped so a later ruling can "
        "recompute stored history instead of discarding it. "
        "AND THE DENOMINATOR IS ALREADY OBSERVABLE, which corrects the reason this "
        "declaration was asked for: test_primitives_inventory.py:379-382 pins "
        "penetration_abs, penetration_pct, penetration_pct_basis AND the weak_sweep flag the "
        "percentage produces, so a changed basis fails a test that predates this rule. The "
        "declaration is right because the choice is OURS and unratified — not because "
        "nobody could watch it."
    ),
)

#: WHICH maximum the `weak_sweep` flag reads, since the doctrine never says.
#:
#: **THE REQUIREMENT HAS TWO HALVES AND THEY ARE SEPARABLE.** *"Emit BOTH a per-bar maximum
#: and an episode maximum, AND declare which the flag reads."* A record carrying one maximum
#: plus a declaration naming it has satisfied the second half and not the first, and it reads
#: as complete because the declaration is the visible half. Both are emitted, per pool, at
#: `penetration_pct_per_bar_max` and `penetration_pct_episode_max`.
#:
#: **WHAT "EPISODE" MEANS IS ITSELF UNSTATED, so the reading is declared rather than assumed.**
#: The registry names the axis "single-vs-cumulative" and defines neither end. PRIM-004
#: measures each contiguous run at its deepest bar, so WITHIN one excursion the per-bar
#: maximum and the excursion maximum are arithmetically the same number and no choice exists.
#: The choice appears one level up: a pool is usually hunted repeatedly, and the maximum
#: ACROSS a pool's excursions is a different number. That is the reading taken here — episode
#: = the pool's whole hunting history — and it is the reading under which the two quantities
#: are distinguishable at all.
PENETRATION_EPISODE_BASIS = DeclaredPercentage(
    name="penetration_episode",
    pct=float("nan"),
    authority="ENGINEERING",
    source=(
        "TARGET-005 notes: 'Single-vs-cumulative is unspecified: emit BOTH a per-bar maximum "
        "and an episode maximum, and declare which the flag reads. [ENGINEERING]'. There is "
        "no percentage to declare here — the choice is WHICH quantity, so `_pct` is NaN and "
        "`_measured_from` carries the answer. BOTH maxima are emitted per pool; this "
        "parameter declares only which one the shipped `weak_sweep` flag consults."
    ),
    measured_from="PER_BAR_MAXIMUM_WITHIN_ONE_EXCURSION",
    measured_from_authority="ENGINEERING",
    measured_from_source=(
        "PRIM-004._excursion measures at the run's deepest bar (prim_004_sweeps.py:255-260) "
        "and `weak_sweep` reads that value (:273), so the shipped flag is per-excursion. "
        "MEASURED CONSEQUENCE, not a hypothetical: over 54 windows of 863 bars at step 12 on "
        "tests/fixtures/btcusdtp_5m_1500.csv, 76,171 of 238,040 swept (window, pool) pairs "
        "contain at least one excursion whose weak/strong class differs from the class the "
        "episode maximum would carry — 32%. The un-emitted quantity is the one a later "
        "ruling would need to re-partition stored history without re-running the market."
    ),
)

#: Values the removal probe sweeps through. Spread deliberately wide — below every observed
#: penetration, through the shipped 1.0, and past the largest — so that a constant which
#: gated ANYTHING could not hold its verdicts still across the whole range.
REMOVAL_PROBE_VALUES: tuple[float, ...] = (
    0.0, 0.001, 0.5, 1.0, 2.0, 100.0, 1e9, float("inf"), float("-inf"),
)


@dataclass(frozen=True)
class ClearanceObservation:
    """One pool's clearance facts, every one of them READ off an emitted object.

    Nothing here recomputes a verdict. `episode_max_pct` is a maximum OVER emitted
    `penetration_pct` values, which is a summary of PRIM-004's measurements rather than a
    second measurement of the same thing.
    """

    pool_id: str
    #: `LiquidityPool.state` — PRIM-004's `_apply_state` wrote it.
    state: str
    excursions: int
    #: `SweepEvent.penetration_pct`, one per excursion, in emission order.
    penetration_pcts: tuple[float, ...]
    #: `SweepEvent.weak_sweep`, the annotation the ~1% produces.
    weak_flags: tuple[bool, ...]
    #: `SweepEvent.cleared`, the per-excursion TARGET-005 verdict.
    cleared_flags: tuple[bool, ...]
    #: `SweepEvent.wick_or_close`.
    wick_or_close: tuple[str, ...]
    #: Whether each excursion named structural evidence.
    reaction_present: tuple[bool, ...]
    #: Whether each excursion named the break ids behind that evidence.
    reaction_break_ids_present: tuple[bool, ...]

    @property
    def per_bar_max_pcts(self) -> tuple[float, ...]:
        """The per-bar maximum of each excursion — PRIM-004's emitted value, unaltered.

        Named rather than aliased silently: within one contiguous run, the deepest BAR is the
        deepest point of the run, so this is the per-bar maximum and the excursion maximum at
        once. The two quantities only separate at the pool level, below.
        """
        return self.penetration_pcts

    @property
    def episode_max_pct(self) -> float:
        """The pool's deepest penetration across ALL its excursions."""
        return max(self.penetration_pcts) if self.penetration_pcts else 0.0

    @property
    def swept(self) -> bool:
        return self.excursions > 0

    @property
    def divergent(self) -> bool:
        """Wicked through and NOT consumed — the case the doctrine sentence describes."""
        return self.swept and self.state == TESTED

    @property
    def body_closed_beyond(self) -> bool:
        return any(w == "BODY_CLOSE_BEYOND" for w in self.wick_or_close)

    @property
    def episode_class_disagrees(self) -> bool:
        """Does any excursion's weak/strong class differ from the episode maximum's?

        Reads the FLAG PRIM-004 emitted for each excursion against the class the episode
        maximum would carry under the same declared band. This is the single-vs-cumulative
        ambiguity made countable; it decides nothing.
        """
        if not self.penetration_pcts:
            return False
        episode_weak = self.episode_max_pct <= DECLARED_WEAK_SWEEP.pct
        return any(flag != episode_weak for flag in self.weak_flags)

    def as_dict(self) -> dict[str, Any]:
        """BOTH maxima on the record, which is the half of the requirement a declaration hides.

        `penetration_pct_per_bar_max` is a list because PRIM-004 emits one per excursion and
        collapsing it here would destroy exactly the quantity the second field exists to be
        compared against.
        """
        return {
            "pool_id": self.pool_id,
            "state": self.state,
            "excursions": self.excursions,
            "penetration_pct_per_bar_max": list(self.per_bar_max_pcts),
            "penetration_pct_episode_max": self.episode_max_pct,
            "weak_sweep_flags": list(self.weak_flags),
            "weak_sweep_reads": PENETRATION_EPISODE_BASIS.measured_from,
            "episode_class_disagrees": self.episode_class_disagrees,
        }


@dataclass(frozen=True)
class RemovalProbe:
    """Criterion 2's removal test, RUN. The verdict is `outcome`, not `identical` alone."""

    values_tried: tuple[float, ...]
    #: How many events the annotation flagged at each value. This moving is what proves the
    #: instrument is live; a probe where it never moved tested nothing.
    weak_sweep_counts: tuple[int, ...]
    #: Did every `SweepEvent.cleared` and every `LiquidityPool.state` hold still?
    verdicts_identical: bool
    #: Events where `weak_sweep` and `cleared` point OPPOSITE ways, so a gating
    #: implementation would have been forced to a different verdict than the shipped one.
    discriminating_cases: int
    baseline_events: int

    @property
    def instrument_moved(self) -> bool:
        return len(set(self.weak_sweep_counts)) > 1

    @property
    def outcome(self) -> str:
        """PASS / FAIL / INDETERMINATE — and the third is not a soft pass.

        INDETERMINATE is the answer T-0018's `1c` and T-0023's criterion 4 both name: a check
        that cannot discriminate because the FIXTURE cannot tell the two implementations
        apart. Reporting it as PASS is how a vacuous test survives review.
        """
        if not self.verdicts_identical:
            return "FAIL"
        if not self.instrument_moved:
            return "INDETERMINATE"
        if self.discriminating_cases == 0:
            return "INDETERMINATE"
        return "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "values_tried": list(self.values_tried),
            "weak_sweep_counts": list(self.weak_sweep_counts),
            "verdicts_identical": self.verdicts_identical,
            "instrument_moved": self.instrument_moved,
            "discriminating_cases": self.discriminating_cases,
            "baseline_events": self.baseline_events,
            "outcome": self.outcome,
        }


def observe(
    pools: Sequence[LiquidityPool], sweeps: Sequence[SweepEvent]
) -> list[ClearanceObservation]:
    """Read PRIM-004's output into one observation per pool. No verdict is computed here.

    `sweep_failed` events are excluded: a failed sweep is an approach that never crossed the
    level, so it is not a penetration and `_apply_state` does not count it either.
    """
    by_pool: dict[str, list[SweepEvent]] = {}
    for e in sweeps:
        if e.sweep_failed:
            continue
        by_pool.setdefault(e.pool_id, []).append(e)

    out: list[ClearanceObservation] = []
    for pool in pools:
        events = by_pool.get(pool.id, [])
        out.append(ClearanceObservation(
            pool_id=pool.id,
            state=pool.state,
            excursions=len(events),
            penetration_pcts=tuple(e.penetration_pct for e in events),
            weak_flags=tuple(e.weak_sweep for e in events),
            cleared_flags=tuple(e.cleared for e in events),
            wick_or_close=tuple(e.wick_or_close for e in events),
            reaction_present=tuple(e.structural_reaction is not None for e in events),
            reaction_break_ids_present=tuple(bool(e.reaction_break_ids) for e in events),
        ))
    return out


def penetration_removal_probe(
    rerun: Callable[[float], tuple[Sequence[LiquidityPool], Sequence[SweepEvent]]],
    *,
    values: Sequence[float] = REMOVAL_PROBE_VALUES,
) -> RemovalProbe:
    """Vary the VALUE in the decision path and compare PRIM-004's own verdicts.

    `rerun(value)` must set `prim_004_sweeps.WEAK_SWEEP_PENETRATION_PCT` to `value`, re-run
    the detection chain and return `(pools, sweeps)`. The caller owns the patching because
    the corpus and the windowing belong to the caller; this function owns the comparison.

    **What would make this FAIL, named before it is run:** any single value at which a
    `cleared` flag or a `pool.state` differs from the baseline. What would make it
    INDETERMINATE: a `weak_sweep` count that never moves (the constant is inert in the
    fixture, not proven non-gating), or zero discriminating cases (nothing in the fixture
    could have told a gating implementation from this one).
    """
    baseline_pools, baseline_sweeps = rerun(DECLARED_WEAK_SWEEP.pct)
    base_cleared = {e.id: e.cleared for e in baseline_sweeps}
    base_state = {p.id: p.state for p in baseline_pools}

    discriminating = sum(
        1 for e in baseline_sweeps
        if not e.sweep_failed and (e.weak_sweep != (not e.cleared))
    )

    counts: list[int] = []
    identical = True
    for value in values:
        pools, sweeps = rerun(value)
        counts.append(sum(1 for e in sweeps if not e.sweep_failed and e.weak_sweep))
        if {e.id: e.cleared for e in sweeps} != base_cleared:
            identical = False
        if {p.id: p.state for p in pools} != base_state:
            identical = False

    return RemovalProbe(
        values_tried=tuple(values),
        weak_sweep_counts=tuple(counts),
        verdicts_identical=identical,
        discriminating_cases=discriminating,
        baseline_events=sum(1 for e in baseline_sweeps if not e.sweep_failed),
    )


class ClearanceIsStructural(RuleImplementation):
    """TARGET-005: structure outranks penetration. Checked over PRIM-004's output."""

    RULE_ID = "TARGET-005"

    #: NOT DECLARED, and the omission is the finding. Criterion 7 of the plan carried a
    #: `CANNOT_FIRE_WITHOUT` disposition for "the post-sweep structural reaction"; the
    #: producer EXISTS — `SweepEvents._reaction` at `prim_004_sweeps.py:280`, called at
    #: `:268` — so declaring one would put a firing rule in the cannot-fire bucket and
    #: understate coverage in the opposite direction to the usual error.
    CANNOT_FIRE_WITHOUT = ()

    COVERAGE_NOTE = (
        "CONFORMANCE ONLY, and that is the whole design. The clearance MECHANISM lives in "
        "PRIM-004 (prim_004_sweeps.py:7 — 'THE RULE THIS PRIMITIVE EXISTS TO ENFORCE IS "
        "TARGET-005'), which was built to this rule before the id was claimed. This module "
        "claims the id, READS the emitted state, and asserts the properties the rule "
        "demands: the two states are separate and both occur, a divergent case exists, a "
        "CONSUMED pool names structural evidence, and the ~1% annotates without gating. It "
        "computes no clearance verdict of its own — every clearance key in `values` carries "
        "from_primitive provenance naming the object it was read off. NOT WIRED — nothing "
        "under app/services/live/ imports THIS module, measured with prim_004_sweeps as the "
        "must-hit arm. Stated that way rather than as 'nothing under live/ imports it', "
        "which is B142's false form: live/shadow.py imports ELEVEN rule modules and "
        "PRIM-004 is one of them. This task did not change PRIM-004."
    )

    @classmethod
    def declared_parameters(cls) -> dict[str, Any]:
        """Both declarations, in the registry's four-field shape plus the basis authority."""
        return {**DECLARED_WEAK_SWEEP.as_values(), **PENETRATION_EPISODE_BASIS.as_values()}

    @classmethod
    def conformance(
        cls, observations: Sequence[ClearanceObservation]
    ) -> tuple[dict[str, Any], list[str]]:
        """The properties TARGET-005 demands, over a set of observations.

        Returns `(values, violations)`. A violation is a case where the emitted output
        contradicts the rule — not a case the corpus failed to contain, which is reported as
        a count so an empty corpus is visible rather than silently conformant.
        """
        swept = [o for o in observations if o.swept]
        divergent = [o for o in swept if o.divergent]
        consumed = [o for o in swept if o.state == CONSUMED]

        values: dict[str, Any] = {
            "pools_observed": len(observations),
            "pools_swept": len(swept),
            "pools_untested": sum(1 for o in observations if o.state == UNTESTED),
            "pools_tested_not_consumed": len(divergent),
            "pools_consumed": len(consumed),
            "divergent_cases": len(divergent),
            "body_close_beyond_not_consumed": sum(
                1 for o in divergent if o.body_closed_beyond
            ),
            "episode_class_disagreements": sum(
                1 for o in swept if o.episode_class_disagrees
            ),
            # BOTH maxima, per swept pool. The registry asks for two quantities and a
            # declaration of which the flag reads; a summary count of disagreements is the
            # declaration's evidence, not the emission.
            "penetration_maxima": [o.as_dict() for o in swept],
        }

        violations: list[str] = []

        # THE OVERRIDE ITSELF: nothing may be CONSUMED without structural evidence.
        for o in consumed:
            cleared_with_evidence = [
                i for i, c in enumerate(o.cleared_flags)
                if c and o.reaction_present[i] and o.reaction_break_ids_present[i]
            ]
            if not cleared_with_evidence:
                violations.append(
                    f"{o.pool_id} is CONSUMED but no excursion carries a structural "
                    "reaction with the break ids behind it — TARGET-005 requires the "
                    "market reaction after the sweep, not the sweep"
                )

        # A cleared excursion that names no evidence is the same failure one level down.
        for o in swept:
            for i, c in enumerate(o.cleared_flags):
                if c and not (o.reaction_present[i] and o.reaction_break_ids_present[i]):
                    violations.append(
                        f"{o.pool_id} excursion {i} reports cleared with no structural "
                        "reaction recorded"
                    )

        # A pool that was swept must not still read UNTESTED.
        for o in swept:
            if o.state == UNTESTED:
                violations.append(
                    f"{o.pool_id} has {o.excursions} excursion(s) and still reads UNTESTED — "
                    "a wick through the level is sufficient to mark it TESTED"
                )

        return values, violations

    @classmethod
    def evaluate(
        cls,
        pools: Sequence[LiquidityPool],
        sweeps: Sequence[SweepEvent],
        *,
        removal: RemovalProbe | None = None,
    ) -> RuleEvaluation:
        """TARGET-005's telemetry over one scan's output.

        NOT_APPLICABLE when no pool was swept: silence is not a pass, and a scan with no
        excursions carries no evidence about clearance in either direction.
        """
        observations = observe(pools, sweeps)
        values, violations = cls.conformance(observations)
        values.update(cls.declared_parameters())

        provenance: dict[str, Any] = {
            "pools_observed": derived("len(pools supplied to TARGET-005)"),
            "pools_swept": derived("pools with >= 1 non-failed SweepEvent"),
            "pools_untested": from_primitive("liquidity_pools[]", "state"),
            "pools_tested_not_consumed": from_primitive("liquidity_pools[]", "state"),
            "pools_consumed": from_primitive("liquidity_pools[]", "state"),
            "divergent_cases": derived(
                "swept pools whose PRIM-004 state is TESTED_NOT_CONSUMED"
            ),
            "body_close_beyond_not_consumed": from_primitive(
                "sweep_events[]", "wick_or_close"
            ),
            "episode_class_disagreements": derived(
                "swept pools where an emitted weak_sweep flag differs from the class the "
                "episode maximum would carry under the same declared band"
            ),
            "penetration_maxima": from_primitive("sweep_events[]", "penetration_pct"),
        }
        for key in DECLARED_WEAK_SWEEP.as_values():
            provenance[key] = derived(f"TARGET-005 declared parameter {key}")
        for key in PENETRATION_EPISODE_BASIS.as_values():
            provenance[key] = derived(f"TARGET-005 declared parameter {key}")

        if removal is not None:
            values["penetration_removal_probe"] = removal.as_dict()
            values["penetration_gates_clearance"] = not removal.verdicts_identical
            provenance["penetration_removal_probe"] = derived(
                "PRIM-004 re-run with weak_sweep_penetration_pct varied across the decision "
                "path; every emitted cleared flag and pool state compared to the baseline"
            )
            provenance["penetration_gates_clearance"] = derived(
                "penetration_removal_probe.verdicts_identical inverted"
            )

        if violations:
            values["violations"] = violations
            return cls.evaluation("FAIL", values=values, value_provenance=provenance)

        if not any(o.swept for o in observations):
            values["not_applicable_reason"] = (
                "no pool was swept in this scan, so nothing here carries evidence about "
                "clearance. Reported rather than passed: a scan with no excursions and a "
                "scan whose excursions all conformed are different facts."
            )
            provenance["not_applicable_reason"] = derived("pools_swept == 0")
            return cls.evaluation(
                "NOT_APPLICABLE", values=values, value_provenance=provenance
            )

        if removal is not None and removal.outcome != "PASS":
            values["indeterminate_reason"] = (
                f"the removal probe returned {removal.outcome}: instrument_moved="
                f"{removal.instrument_moved}, discriminating_cases="
                f"{removal.discriminating_cases}. Unchanged verdicts over a corpus that "
                "straddles nothing would pass a correct and an incorrect implementation "
                "alike, so this is not reported as conformance."
            )
            provenance["indeterminate_reason"] = derived("RemovalProbe.outcome != PASS")
            return cls.evaluation(
                "NOT_APPLICABLE", values=values, value_provenance=provenance
            )

        return cls.evaluation("PASS", values=values, value_provenance=provenance)
