"""The stop pipeline, part two: two stop-layer flags, one exit-layer flag, and the zone modifier.

T-0030, the far side of the seam cut through T-0025. Every artefact here consumes
`selected_stop` or the candidate table, which is why none of it could be built before
`gate_027_stop_ladder.py` existed.

    GATE-029   flag RR_ABOVE_ACCEPTABLE_BAND when rr > 4.0     -> a flag, never a rejection
    GATE-030   flag TIGHTER_THAN_NECESSARY + reason            -> a flag WITH a reason
    GATE-031   flag DEGENERATE_RUNNER when rr <= 2.0 + eps     -> a flag, layer=exit
    GATE-027   the post-selection ZONE-COVERAGE MODIFIER       -> an ADJUSTED STOP PRICE

THREE RULES, THREE ARTEFACTS, AND A FOURTH THAT BELONGS TO A RULE ALREADY IMPLEMENTED
The three flags do not collapse into one function (criterion 9): each has a distinct output
and each is conformance-tested separately below. The zone modifier is NOT a fourth rule and
does NOT get a new id.

WHY THE ZONE MODIFIER SHIPS UNDER GATE-027 AND WHY IT IS NOT A CLASS
`GATE-027.notes` item (b), verbatim: "The wide-cover case is a ZONE-COVERAGE MODIFIER
APPLIED AFTER ANCHOR SELECTION, not a sixth anchor: if the chosen stop lands inside a zone
object, extend to the far edge of the whole zone (075 Choice 4; 049_Examples.md:5;
116_Examples.md:5; PRIM-006, zones never lines)." GATE-027's `inputs` carry the same thing
from the other end — "(plus any residual imbalance to cover)". So the artefact has an owner
already, and the question the previous session's worst near-miss turned on — WHICH RULE'S
`output` FIELD NAMES THIS ARTEFACT — is answered by the registry rather than by us.

It is therefore functions, not a `RuleImplementation` subclass. `GATE-027` is already
implemented by `StopCandidateLadder`, and `base.py` offers `ALLOW_SHARED_ID` for exactly
this situation — "set on a subclass only when a rule is legitimately implemented in more
than one place". IT WAS REFUSED, AND THE REASON IS MECHANICAL RATHER THAN STYLISTIC.
`__init_subclass__` ends with `_IMPLEMENTATIONS[claimed] = cls`, an unconditional
assignment, so a second GATE-027 class would REPLACE the first in the map that
`scripts/check_rule_coverage.py` reads. `StopCandidateLadder.CANNOT_FIRE_WITHOUT =
(ORDER_BLOCK_PRODUCER,)` is how rung 4's producer gap reaches the coverage report at all —
taking the sanctioned hatch would have deleted that gap from the report while changing no
behaviour, which is this register's recurring failure: an artefact nobody re-reads made to
say something the code does not support. `test_gate_027_still_owns_its_own_coverage_entry`
pins it.

CORROBORATION IS RECORDED IN BOTH DIRECTIONS, WHICH IS THE POINT OF CITING TWO RULES
`PRIM-006`'s statement carries the same requirement from the primitive side — "the images
are explicit that these are ZONES, not thin lines, and that a stop placed at a flip zone
must cover the WHOLE zone". Two independent rules stating one requirement is corroboration
and is visible in `zone_coverage`'s provenance rather than asserted in a comment.

WHAT IS OURS HERE, DECLARED RATHER THAN FITTED
Four values in this module are ENGINEERING choices with no ratification. Each is a
`DeclaredEngineering` carrying its own authority and the reading NOT taken, for the reason
GATE-027 already records twice: a choice with only one option written down reads as a fact.

    degenerate_runner_eps            0.0        GATE-031 has NO `values` block at all
    zone_widening_order              AFTER_SELECTION_FLOOR_RETESTED_NOT_REAPPLIED
    zone_snap_tolerance              0.0        the tolerance that CHANGES a price
    zone_adjacency_reporting_window  1.0        zone heights; only REPORTS, cannot change one

THE TWO TOLERANCES ARE SEPARATE ON PURPOSE AND COLLAPSING THEM IS THE DEFECT. One decides
whether a stop MOVES; the other decides whether a note is WRITTEN. A single tolerance forces
the reporting window to inherit the widening window's value, and since the widening window
is declared 0.0 — refusing to act on a gap the doctrine does not define — the flag would
then never fire and the residual would look measured at zero rather than unmeasured.

WHAT THIS MODULE DOES NOT DO
It does not skip a setup, widen a target, nudge the partial level, or invent a minimum gap
(criterion 5c — GATE-031's own output says so outright). It does not change a threshold:
4.0, 2.0 and 3.0 are Salim's and are read from the registry. Nothing under `live/` imports
it; it is shadow-only and is wired to nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.gate_027_stop_ladder import (
    LadderInputs, StopCandidate, risk_reward,
)
from app.services.telemetry import contract_loader as contract
from app.services.telemetry.records import (
    RuleEvaluation, derived, from_declared, from_registry,
)

#: GATE-029's two values. `flag_above_rr` is a THRESHOLD and is read; `unnamed_band` is
#: ANNOTATION and is deliberately never read by a predicate — see criterion 3a and
#: `test_unnamed_band_reaches_no_predicate`.
FLAG_ABOVE_RR: float = float(contract.rule("GATE-029")["values"]["flag_above_rr"])
UNNAMED_BAND: tuple[float, float] = tuple(  # type: ignore[assignment]
    float(x) for x in contract.rule("GATE-029")["values"]["unnamed_band"]
)

#: GATE-025's floor, from the registry for the same reason part one reads it there: a
#: retyped constant is a second source that drifts silently.
RR_FLOOR: float = float(contract.rule("GATE-025")["values"]["rr_floor"])

#: GATE-031's partial level. The rule's own `inputs` name it — "selected_stop.rr;
#: partial_level (2R); target price" — and it is 2R, the same number as the floor and NOT
#: the same fact. GATE-025's 2.0 is where a candidate becomes ADMISSIBLE; this 2.0 is where
#: the 70% partial LANDS. They coincide, and that coincidence IS the defect GATE-031 names.
#: Two names because one name would make the collision invisible.
PARTIAL_LEVEL_R: float = RR_FLOOR

#: Arithmetic tolerance for float comparison. NOT `eps`, and the distinction is the whole
#: reason this constant is declared separately and named after what it is.
#:
#: `rr` is `|target - entry| / |entry - stop|`, so a setup constructed to sit at exactly 2R
#: can arrive as 1.9999999999999998. A comparison tolerance absorbs that. `eps` is a
#: DOCTRINE quantity — how much room the runner needs to be worth running — and defaults to
#: 0.0 below. If one constant served both, then raising the float tolerance would silently
#: widen a doctrinal flag, and the two would be impossible to argue about separately.
FLOAT_TOLERANCE: float = 1e-9

Ordering = Literal[
    "AFTER_SELECTION_FLOOR_RETESTED_NOT_REAPPLIED",
    "BEFORE_FLOOR",
]


@dataclass(frozen=True)
class DeclaredEngineering:
    """An engineering choice with no ratification, carrying its own authority.

    Its own type rather than a shared carrier, matching `DeclaredPlacement` in part one:
    these belong to the rules that carry them, and a project-wide bag of declared values
    detaches the choice from the rule it constrains.
    """

    name: str
    value: Any
    #: WHO decided. Not a citation of doctrine — the point of the field is that no doctrine
    #: exists, so a reader can tell an engine choice from a trader ruling at a glance.
    authority: str
    source: str
    #: The option NOT taken. A choice with one option written down reads as a fact.
    competing: Any = None
    ratified: bool = False

    def as_values(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            self.name: self.value,
            f"{self.name}_ratified": self.ratified,
            f"{self.name}_authority": self.authority,
            f"{self.name}_source": self.source,
        }
        if self.competing is not None:
            out[f"{self.name}_competing"] = self.competing
        return out


#: OURS. Unratified. GATE-031 carries NO `values` block and no `epsilon` exists anywhere in
#: `rules/` — measured, with a control pair, in the work report.
#:
#: 0.0 IS THE ONLY VALUE THAT IS NOT AN INVENTION, and that is an argument rather than a
#: preference. GATE-031's defect is an ARITHMETIC COLLISION: at exactly 2R the 70% partial
#: level IS the final target, so the runner has nothing to run into. That collision happens
#: at `rr == 2.0` exactly. Any eps > 0 asserts something the collision does not: that a
#: runner with SOME room is still degenerate — which is a claim about how much room a runner
#: needs, and that is precisely "the active trade management rules" GATE-031's own notes
#: record as NEVER DEFINED. So eps has no scale for the same reason 5d says the runner has
#: no rules, and fitting one here would bury the undefined subsystem inside a constant.
#:
#: The firing rate is reported AS A CURVE over eps rather than at this value alone, so a
#: later ratification inherits the measurement instead of re-running it.
DECLARED_EPS = DeclaredEngineering(
    name="degenerate_runner_eps",
    value=0.0,
    authority="ENGINEERING — this engine, T-0030. Not ratified by Salim.",
    source=(
        "GATE-031 carries no values block and names no epsilon; nothing in rules/ declares "
        "one. 0.0 is the arithmetic collision the rule actually describes — at rr == 2.0 "
        "the 70% partial level IS the final target. A positive eps would assert how much "
        "room a runner needs to be worth running, which is 'the active trade management "
        "rules' GATE-031's notes record as NEVER DEFINED (036_Single_Trade_Management.md is "
        "empty). The firing rate is reported over a sweep of eps so the interval is "
        "measured rather than pinned by two fixture points."
    ),
    competing="any eps > 0, which requires the undefined runner rules to justify",
)

#: OURS. Unratified. GATE-027's note (b) is in tension with itself and this records which
#: half was followed.
#:
#: The note says the modifier is "APPLIED AFTER ANCHOR SELECTION" and then lists as an open
#: residual "whether the widening runs before or after the 2R floor". Those cannot both be
#: fully open: selection happens after the floor (GATE-025 admits, GATE-028 chooses among
#: the survivors), so "after anchor selection" already places the widening after the floor.
#: What is genuinely unstated is whether the WIDENED stop is re-tested against the floor,
#: and what happens if it now fails.
#:
#: Declared: re-tested, RECORDED, and NOT acted on. Acting on it — re-selecting, or dropping
#: the setup — would silently change which trades are admissible, and admission is
#: GATE-025's, not this modifier's. Reading a value to record it and reading it to decide
#: are different acts and only the second is forbidden here.
DECLARED_WIDENING_ORDER = DeclaredEngineering(
    name="zone_widening_order",
    value="AFTER_SELECTION_FLOOR_RETESTED_NOT_REAPPLIED",
    authority="ENGINEERING — this engine, T-0030. Not ratified by Salim.",
    source=(
        "GATE-027 note (b) fixes 'APPLIED AFTER ANCHOR SELECTION' and simultaneously lists "
        "'whether the widening runs before or after the 2R floor' as an open residual. "
        "Selection is downstream of the floor, so the first sentence settles the ordering "
        "and the residual can only be about RE-application. The widened stop is re-tested "
        "and the result recorded as `widened_below_floor`; nothing is re-selected and no "
        "setup is dropped, because admission belongs to GATE-025."
    ),
    competing="BEFORE_FLOOR — widen first, then admit, which changes which candidates clear 2R",
)

#: OURS. Unratified. The tolerance that CHANGES A PRICE, and it refuses to act.
#:
#: The intersecting case is fully determined by the doctrine; the adjacent-but-not-touching
#: case is the one genuine gap ("if it is very close to imbalance" — 075 Choice 4 — with no
#: distance attached). Default per the plan: do not widen. 0.0 is that default expressed as
#: a number, and it is the conservative direction in the only sense that matters here —
#: it never moves a stop the doctrine did not move.
DECLARED_SNAP_TOLERANCE = DeclaredEngineering(
    name="zone_snap_tolerance",
    value=0.0,
    authority="ENGINEERING — this engine, T-0030. Not ratified by Salim.",
    source=(
        "075 Choice 4 says 'if it is very close to imbalance, i will also cover that "
        "imbalance as well' and attaches no distance. GATE-027's note (b) lists the snap "
        "tolerance as an open [ENGINEERING] residual. 0.0 means only an INTERSECTING zone "
        "widens a stop; an adjacent one is reported and left alone."
    ),
    competing="any positive tolerance, which would move a stop on a distance nobody stated",
)

#: OURS. Unratified. The window that only REPORTS, and it is deliberately not 0.0.
#:
#: Expressed in multiples of the ZONE'S OWN HEIGHT, because that is the only scale available
#: in the data — a price distance would need to know which class of instrument this is, and
#: that field has no producer (B116/B123; the field is named there, and it is deliberately
#: NOT named here, because `test_both_live_paths_hardcode_aligned_major_so_the_refusal_is_
#: not_exercised` scans every module under `app/services/` for the literal token and cannot
#: tell a producer from a mention. B112 ruled that case: reword the module, do not widen the
#: guard). A reporting window cannot change a trade, so a wrong value here
#: costs noise; the widening tolerance above can change a trade, so a wrong value there
#: costs a stop. That asymmetry is why they are two parameters and not one.
DECLARED_ADJACENCY_WINDOW = DeclaredEngineering(
    name="zone_adjacency_reporting_window",
    value=1.0,
    authority="ENGINEERING — this engine, T-0030. Not ratified by Salim.",
    source=(
        "Units are the zone's own height, so the window has a scale that comes from the "
        "object rather than from an instrument class nobody produces. Reporting only: it "
        "raises `zone_adjacent_uncovered` and never moves a price. Set to 0.0 it would "
        "report nothing and the residual would read as measured-at-zero rather than open."
    ),
    competing="0.0, which silently converts an open residual into an empty measurement",
)


@dataclass(frozen=True)
class ZoneObject:
    """A zone the stop may land inside. PRIM-006's rule is that these are never lines.

    Deliberately a plain band with a `kind` rather than a union of the producers' types:
    the modifier's question is geometric and identical for an imbalance, a breaker, an S/R
    flip and an order block. `kind` is carried so the record says WHICH doctrine object
    covered the stop, and `id` so the widening is traceable to a produced object.
    """

    kind: str
    price_high: float
    price_low: float
    id: str | None = None

    def __post_init__(self) -> None:
        if self.price_high < self.price_low:
            raise ValueError(
                f"zone {self.id or self.kind} has high {self.price_high} below low "
                f"{self.price_low} — an inverted band would make 'inside' unanswerable and "
                "every containment test would quietly return False"
            )

    @property
    def height(self) -> float:
        return self.price_high - self.price_low

    def contains(self, price: float) -> bool:
        """Inclusive on both edges — a stop ON the edge is not clear of the zone."""
        return self.price_low <= price <= self.price_high

    def far_edge(self, direction: str) -> float:
        """The edge that covers the WHOLE zone: below entry on a LONG, above it on a SHORT.

        KEYED ON DIRECTION AND NOT ON WHERE ENTRY SITS. Deriving it from entry's position
        relative to the band reads correctly for the ordinary case and inverts when entry
        lands INSIDE the zone — which is not exotic, since ENTRY-001 enters from an
        imbalance and PRIM-006 zones overlap imbalances by construction. The inverted
        answer would be a stop on the wrong side of entry, which `risk_reward` would then
        refuse as a sign error wearing a number.
        """
        return self.price_low if direction == "LONG" else self.price_high

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "price_high": self.price_high,
            "price_low": self.price_low,
        }


@dataclass(frozen=True)
class ZoneCoverage:
    """GATE-027 note (b)'s artefact: a post-selection stop price, and why it moved.

    `widened` false with `covering_zone` None is the ordinary case and is emitted anyway —
    "no zone contained the stop" and "the modifier did not run" are different facts.
    """

    original_stop: float
    final_stop: float
    widened: bool
    covering_zone: ZoneObject | None = None
    adjacent_uncovered: tuple[ZoneObject, ...] = ()
    #: rr recomputed on the FINAL stop. None when no target-bearing inputs were supplied.
    final_rr: float | None = None
    original_rr: float | None = None
    #: True when the widened stop no longer clears GATE-025's floor. RECORDED, never acted
    #: on — see DECLARED_WIDENING_ORDER.
    widened_below_floor: bool = False

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "original_stop": self.original_stop,
            "final_stop": self.final_stop,
            "widened": self.widened,
            "widened_below_floor": self.widened_below_floor,
            "zone_adjacent_uncovered": [z.as_dict() for z in self.adjacent_uncovered],
        }
        if self.covering_zone is not None:
            out["covering_zone"] = self.covering_zone.as_dict()
        for key, value in (("original_rr", self.original_rr), ("final_rr", self.final_rr)):
            if value is not None:
                out[key] = value
        return out


def apply_zone_coverage(
    inputs: LadderInputs,
    selected: StopCandidate,
    zones: Sequence[ZoneObject] = (),
) -> ZoneCoverage:
    """GATE-027 note (b): if the selected stop lands INSIDE a zone, extend to the far edge.

    ONE ZONE WIDENS THE STOP AND IT IS THE FURTHEST ONE, not the first in the list. When two
    zones both contain the stop, covering only the nearer leaves the stop inside the other —
    which is the thing the rule forbids, so "the far edge of the whole zone" read over a set
    of overlapping zones means the furthest far edge. Ordering by supply here would make the
    result depend on the caller's iteration order.

    THE WIDENED STOP IS RE-TESTED AGAINST THE 2R FLOOR AND THE RESULT IS RECORDED, NOT
    ACTED ON (`DECLARED_WIDENING_ORDER`). Widening always LOWERS rr, so this is reachable
    and criterion 6b's fixture drives it across `DEGENERATE_RUNNER`'s boundary on purpose.
    """
    if selected.stop_price is None:
        raise ValueError(
            f"rung {selected.rung} was selected with no stop_price — a selected candidate "
            "with no price cannot be widened and should not have been selectable"
        )
    original = selected.stop_price
    entry = inputs.entry

    containing = [z for z in zones if z.contains(original)]
    adjacent = [
        z for z in zones
        if not z.contains(original)
        and z.height > 0.0
        and min(abs(original - z.price_low), abs(original - z.price_high))
        <= DECLARED_ADJACENCY_WINDOW.value * z.height
    ]

    final = original
    covering: ZoneObject | None = None
    if containing:
        # The furthest far edge: the extension that clears EVERY containing zone.
        covering = max(
            containing, key=lambda z: abs(entry - z.far_edge(inputs.direction))
        )
        candidate_edge = covering.far_edge(inputs.direction)
        # Never tighten. A zone whose far edge sits closer to entry than the stop already
        # is would otherwise pull the stop IN, and this modifier only ever covers more.
        if abs(entry - candidate_edge) > abs(entry - original):
            final = candidate_edge
        else:
            covering = None

    original_rr = _rr_or_none(inputs, original)
    final_rr = _rr_or_none(inputs, final)
    return ZoneCoverage(
        original_stop=original,
        final_stop=final,
        widened=final != original,
        covering_zone=covering,
        adjacent_uncovered=tuple(adjacent),
        original_rr=original_rr,
        final_rr=final_rr,
        widened_below_floor=(
            final_rr is not None and final_rr < RR_FLOOR - FLOAT_TOLERANCE
        ),
    )


def _rr_or_none(inputs: LadderInputs, stop: float) -> float | None:
    """rr, or None when the price is not comparable against the predefined target."""
    from app.services.rules.gate_027_stop_ladder import StopCandidateNotComparable

    try:
        return risk_reward(inputs, stop)
    except StopCandidateNotComparable:
        return None


def zone_coverage_evaluation_values(coverage: ZoneCoverage) -> tuple[dict, dict]:
    """The modifier's telemetry block and its provenance, attributed to GATE-027.

    Returned rather than emitted as a `RuleEvaluation`, because GATE-027's evaluation is
    `StopCandidateLadder`'s and this is the same rule's second artefact — not a second rule.
    """
    values: dict[str, Any] = {
        "zone_coverage": coverage.as_dict(),
        **DECLARED_WIDENING_ORDER.as_values(),
        **DECLARED_SNAP_TOLERANCE.as_values(),
        **DECLARED_ADJACENCY_WINDOW.as_values(),
    }
    provenance: dict[str, Any] = {
        "zone_coverage": from_registry("GATE-027", "notes"),
        # Corroboration, recorded in both directions: PRIM-006 states the same requirement
        # from the primitive side, and two rules agreeing is evidence rather than repetition.
        "zone_coverage_corroboration": from_registry("PRIM-006", "statement"),
        DECLARED_WIDENING_ORDER.name: from_declared(DECLARED_WIDENING_ORDER.name),
        DECLARED_SNAP_TOLERANCE.name: from_declared(DECLARED_SNAP_TOLERANCE.name),
        DECLARED_ADJACENCY_WINDOW.name: from_declared(DECLARED_ADJACENCY_WINDOW.name),
    }
    for declared in (
        DECLARED_WIDENING_ORDER, DECLARED_SNAP_TOLERANCE, DECLARED_ADJACENCY_WINDOW,
    ):
        provenance[f"{declared.name}_ratified"] = derived("OURS, unratified")
        provenance[f"{declared.name}_authority"] = derived("engine choice, not a ruling")
        provenance[f"{declared.name}_source"] = derived("the argument for the value")
        if declared.competing is not None:
            provenance[f"{declared.name}_competing"] = derived("the option not taken")
    return values, provenance


class RRAboveAcceptableBand(RuleImplementation):
    """GATE-029: flag a selection above 4R. NEVER a rejection.

    ARTEFACT: the flag `RR_ABOVE_ACCEPTABLE_BAND`.

    FLAG IT, RECORD IT, TAKE THE TRADE. Blocking above 4R is a rejection rule nobody ruled
    and it would contradict GATE-025, which accepts anything at or above 2R. The rule exists
    because the algorithm AS WRITTEN takes a 10R stop when it is the only candidate clearing
    2R — "'Overly Tight' is a LABEL, not a rejection" — so an implementation that skipped it
    would be the engine writing the cut the statement says is absent.
    """

    RULE_ID = "GATE-029"

    COVERAGE_NOTE = (
        "IMPLEMENTED as a flag. The threshold is the registry's flag_above_rr and the rule "
        "never blocks: verdict is PASS whenever a stop was selected, with the flag carried "
        "in values. `unnamed_band` is recorded as ANNOTATION and reaches no predicate — it "
        "discriminates nothing, since a 5R and a 9R selection are flagged identically. The "
        "rule's HARD_GATE classification is in tension with its non-blocking output; that "
        "is recorded on every evaluation and in KNOWN_ISSUES, and no seat may edit the "
        "registry to resolve it."
    )

    @staticmethod
    def flags(rr: float | None) -> bool:
        """rr STRICTLY above 4.0, which is the output's own word ("when rr > 4.0").

        `None` does not flag. No selection means nothing to judge, not a quiet False.
        """
        return rr is not None and rr > FLAG_ABOVE_RR

    @classmethod
    def evaluate(cls, selected: StopCandidate | None) -> RuleEvaluation:
        rr = selected.rr if selected is not None else None
        flagged = cls.flags(rr)
        values: dict[str, Any] = {
            "flag_above_rr": FLAG_ABOVE_RR,
            "selected_rr": rr,
            "flags": ["RR_ABOVE_ACCEPTABLE_BAND"] if flagged else [],
            "blocks": False,
            # ANNOTATION. Recorded because it explains WHY 4.0 is the boundary; read by
            # nothing. Criterion 3a, and T-0028's criterion 2 in a new rule.
            "unnamed_band": list(UNNAMED_BAND),
            "unnamed_band_is_annotation": True,
            # Criterion 3b. Stated, not resolved.
            "classification_tension": (
                "GATE-029 is classified HARD_GATE and its output blocks nothing. Every "
                "other HARD_GATE can refuse a trade; this one cannot, by its own text. "
                "That is either a classification error in the registry or a HARD_GATE that "
                "means something else here. Recorded, not resolved — no seat may edit the "
                "registry."
            ),
        }
        provenance: dict[str, Any] = {
            "flag_above_rr": from_registry("GATE-029", "values.flag_above_rr"),
            "selected_rr": derived("selected_stop.rr, or None when nothing was selected"),
            "flags": derived(f"RR_ABOVE_ACCEPTABLE_BAND when rr > {FLAG_ABOVE_RR}"),
            "blocks": derived("structural claim: this rule has no rejection path"),
            "unnamed_band": from_registry("GATE-029", "values.unnamed_band"),
            "unnamed_band_is_annotation": derived(
                "structural claim: no branch reads unnamed_band; it discriminates nothing "
                "because the flag fires on rr > 4.0 alone"
            ),
            "classification_tension": from_registry("GATE-029", "type"),
        }
        if selected is None:
            values["not_applicable_reason"] = (
                "no stop was selected, so there is no rr to judge. The terminal skip is "
                "GATE-026's."
            )
            provenance["not_applicable_reason"] = derived("selector returned None")
            return cls.evaluation("NOT_APPLICABLE", values=values,
                                  value_provenance=provenance)
        return cls.evaluation("PASS", values=values, value_provenance=provenance)


class TighterThanNecessary(RuleImplementation):
    """GATE-030: flag when a tighter stop was chosen over a wider one that also cleared 2R.

    ARTEFACT: the flag `TIGHTER_THAN_NECESSARY` **and its reason**. A flag with no reason
    field fails criterion 4c — the reason must name the wider candidate passed over and its
    rr, or the flag cannot be acted on or audited.

    REACHABILITY IS GOVERNED BY THE SELECTOR, NOT BY MONOTONICITY, AND THE PLAN'S
    BICONDITIONAL IS TOO STRONG. Re-derived here rather than inherited, because two seats
    reached different answers before this one. Under the shipped
    `CLOSEST_TO_3R_TIES_TO_LARGER`, on a cushion-monotonic ladder:

        rr rises as the stop tightens, so survivors (rr >= 2.0) are a SUFFIX starting at
        some rung k, and the WIDEST survivor is rung k — the LOWEST rr among survivors.

        rr_k >= 3.0   every other survivor is farther from 3.0   -> k selected -> NO FLAG
        rr_k <  3.0   a tighter survivor MAY be nearer 3.0       -> flag IFF one IS

    The plan says the flag "fires exactly when the widest 2R-clearing candidate sits below
    3R". That is NECESSARY BUT NOT SUFFICIENT: survivors at rr = [2.9, 5.0] have the widest
    below 3R, and |2.9 - 3.0| = 0.1 still beats |5.0 - 3.0| = 2.0, so the widest is selected
    and nothing fires. The correct predicate is

        fires  <=>  rr_k < 3.0  AND  some survivor is STRICTLY nearer 3.0 than rr_k

    strict because ties resolve to the larger cushion, which is rung k itself.
    `test_reachability_predicate_over_the_four_monotonic_cases` enumerates it, and the
    [2.9, 5.0] ladder is in the file as the case that separates the two readings.
    """

    RULE_ID = "GATE-030"

    COVERAGE_NOTE = (
        "IMPLEMENTED as a flag with a reason. Fires when the selected stop is not the "
        "widest candidate that cleared 2R; the reason names the widest passed-over "
        "candidate, its rung, its anchor and its rr. Never a rejection — GATE-030 is a "
        "SOFT_PREFERENCE and a tighter-than-necessary selection is a flag, not a failure. "
        "Reachability is governed by GATE-028's operative reading rather than by ladder "
        "monotonicity; measured over the corpus by T-0030."
    )

    @staticmethod
    def wider_survivors(
        table: Sequence[StopCandidate], selected: StopCandidate | None,
    ) -> list[StopCandidate]:
        """Accepted candidates with a strictly larger cushion than the selected stop.

        Keys on CUSHION, never on rung index. The ladder is cushion-monotonic by GATE-027's
        prose and that claim is exactly what T-0030 measures — an implementation that used
        rung order here would assume the thing under test and would silently disagree with
        this one on any inverted ladder.
        """
        if selected is None or selected.cushion is None:
            return []
        return [
            c for c in table
            if c.accepted and c.cushion is not None and c.cushion > selected.cushion
        ]

    @classmethod
    def evaluate(
        cls, table: Sequence[StopCandidate], selected: StopCandidate | None,
    ) -> RuleEvaluation:
        wider = cls.wider_survivors(table, selected)
        flagged = bool(wider)
        values: dict[str, Any] = {
            "flags": ["TIGHTER_THAN_NECESSARY"] if flagged else [],
            "blocks": False,
            "wider_accepted_candidates": len(wider),
        }
        provenance: dict[str, Any] = {
            "flags": derived(
                "TIGHTER_THAN_NECESSARY when an accepted candidate has a larger cushion "
                "than the selected stop"
            ),
            "blocks": derived("structural claim: SOFT_PREFERENCE, no rejection path"),
            "wider_accepted_candidates": derived(
                "count of accepted candidates with cushion > selected.cushion"
            ),
        }
        if selected is None:
            values["not_applicable_reason"] = (
                "no stop was selected, so no wider candidate was passed over."
            )
            provenance["not_applicable_reason"] = derived("selector returned None")
            return cls.evaluation("NOT_APPLICABLE", values=values,
                                  value_provenance=provenance)
        if flagged:
            # The WIDEST passed-over candidate: the one the cushion preference would have
            # taken. Reporting the nearest wider candidate would understate the gap.
            widest = max(wider, key=lambda c: c.cushion or 0.0)
            values["reason"] = {
                "passed_over_rung": widest.rung,
                "passed_over_anchor": widest.anchor,
                "passed_over_rr": widest.rr,
                "passed_over_cushion": widest.cushion,
                "selected_rung": selected.rung,
                "selected_rr": selected.rr,
                "selected_cushion": selected.cushion,
                "text": (
                    f"rung {selected.rung} ({selected.anchor}) at rr {selected.rr} was "
                    f"selected over rung {widest.rung} ({widest.anchor}) at rr "
                    f"{widest.rr}, which also cleared {RR_FLOOR}R and carries the larger "
                    "cushion. GATE-030 prefers the larger cushion; the selection follows "
                    "GATE-028's closest-to-3R reading, so this is a recorded preference "
                    "loss and not a failure."
                ),
            }
            provenance["reason"] = derived(
                "the widest accepted candidate passed over, with both rr values"
            )
        return cls.evaluation("PASS", values=values, value_provenance=provenance)


class DegenerateRunner(RuleImplementation):
    """GATE-031: flag when the selected stop leaves the 30% runner nothing to run into.

    ARTEFACT: the flag `DEGENERATE_RUNNER`. Layer is EXIT, not stop — it consumes a stop
    value and acts where the exit model does.

    THE INTERLOCK WITH THE FLOOR IS THE POINT AND IT IS DELIBERATE. GATE-025's floor is
    INCLUSIVE, so `rr == 2.0` is ACCEPTED; this rule flags `DEGENERATE_RUNNER` at
    `rr <= 2.0 + eps`. THE SAME VALUE IS BOTH ADMISSIBLE AND FLAGGED, and that is correct:
    admission and health are different questions — T-0022's "same predicate, two purposes,
    opposite edges". A single fixture asserts both sides at once, because two fixtures would
    assert two facts and never the simultaneity, and the two boundaries are one value apart.

    WHAT IS BEING PROTECTED IS ITSELF UNSPECIFIED. GATE-031's notes: "the active trade
    management rules" governing the 30% runner are NEVER DEFINED — "the single most
    load-bearing undefined phrase in the document" — and `036_Single_Trade_Management.md` is
    empty. The flag is still well-defined, because it is about the 2R collision and not
    about what the runner would have done. Recorded, not resolved.
    """

    RULE_ID = "GATE-031"

    COVERAGE_NOTE = (
        "IMPLEMENTED as a flag. Fires when selected_stop.rr <= 2.0 + eps, where eps is "
        "DECLARED [ENGINEERING] at 0.0 and unratified — GATE-031 carries no values block "
        "and no epsilon exists in rules/. The engine invents no minimum gap: no setup is "
        "skipped, no target moved, no partial level nudged. The runner's own management "
        "rules are undefined, which is recorded rather than filled in."
    )

    #: DELIBERATELY NOT DECLARED. The runner's management rules are undefined (5d), but
    #: this flag does not depend on them: it reads `selected_stop.rr` and fires. Declaring
    #: the missing rules here would put GATE-031 in the coverage report's CANNOT_FIRE
    #: bucket, which would be false — it fires, and the fixtures below prove it. The gap is
    #: recorded in `values` on every evaluation instead, where it is true.

    @staticmethod
    def flags(rr: float | None, *, eps: float | None = None) -> bool:
        """rr at or below `2.0 + eps`. Inclusive, which is the output's own `<=`.

        `eps` is a parameter with the declared value as its default so the firing rate can
        be measured ACROSS eps without mutating a module constant — a sweep that reassigned
        the constant would leave the value changed for every later test in the process.
        """
        if rr is None:
            return False
        use = DECLARED_EPS.value if eps is None else eps
        return rr <= PARTIAL_LEVEL_R + use + FLOAT_TOLERANCE

    @classmethod
    def evaluate(
        cls, selected: StopCandidate | None, *, eps: float | None = None,
    ) -> RuleEvaluation:
        rr = selected.rr if selected is not None else None
        used_eps = DECLARED_EPS.value if eps is None else eps
        flagged = cls.flags(rr, eps=used_eps)
        values: dict[str, Any] = {
            "partial_level_r": PARTIAL_LEVEL_R,
            "selected_rr": rr,
            "flags": ["DEGENERATE_RUNNER"] if flagged else [],
            "blocks": False,
            "minimum_gap_invented": False,
            **DECLARED_EPS.as_values(),
            "degenerate_runner_eps_used": used_eps,
            # Criterion 5d. The compounding gap, stated on every record.
            "runner_management_rules_defined": False,
            "runner_management_rules_note": (
                "GATE-031's own notes: 'the active trade management rules' governing the "
                "30% runner are NEVER DEFINED — 'the single most load-bearing undefined "
                "phrase in the document' — and the only workspace page bearing that name "
                "(036_Single_Trade_Management.md) is empty. This flag therefore reports "
                "that a runner is degenerate while what the runner WOULD have done is "
                "unspecified. The flag is well-defined on its own; the subsystem is not."
            ),
        }
        provenance: dict[str, Any] = {
            "partial_level_r": from_registry("GATE-031", "inputs"),
            "selected_rr": derived("selected_stop.rr, or None when nothing was selected"),
            "flags": derived(
                f"DEGENERATE_RUNNER when rr <= {PARTIAL_LEVEL_R} + eps (inclusive)"
            ),
            "blocks": derived("structural claim: this rule has no rejection path"),
            "minimum_gap_invented": derived(
                "structural claim: no setup skipped, no target widened, no partial level "
                "moved — GATE-031's output forbids all three"
            ),
            DECLARED_EPS.name: from_declared(DECLARED_EPS.name),
            f"{DECLARED_EPS.name}_ratified": derived("OURS, unratified"),
            f"{DECLARED_EPS.name}_authority": derived("engine choice, not a ruling"),
            f"{DECLARED_EPS.name}_source": derived("the argument for 0.0"),
            f"{DECLARED_EPS.name}_competing": derived("the option not taken"),
            "degenerate_runner_eps_used": derived("the eps this evaluation actually used"),
            "runner_management_rules_defined": from_registry("GATE-031", "notes"),
            "runner_management_rules_note": from_registry("GATE-031", "notes"),
        }
        if selected is None:
            values["not_applicable_reason"] = (
                "no stop was selected, so there is no runner to judge."
            )
            provenance["not_applicable_reason"] = derived("selector returned None")
            return cls.evaluation("NOT_APPLICABLE", values=values,
                                  value_provenance=provenance)
        return cls.evaluation("PASS", values=values, value_provenance=provenance)


def evaluate_stop_flags(
    inputs: LadderInputs,
    table: Sequence[StopCandidate],
    selected: StopCandidate | None,
    zones: Sequence[ZoneObject] = (),
    *,
    eps: float | None = None,
) -> dict[str, Any]:
    """Run the three flags and the zone modifier, keeping every artefact distinct.

    THE THREE RULES DO NOT COLLAPSE INTO ONE FUNCTION (criterion 9). This is a caller-side
    convenience in the same shape as part one's `evaluate_stop_pipeline`: it invents no
    verdict, and every value below is its own rule's.

    GATE-029 AND GATE-031 READ THE FINAL STOP, AFTER ANY WIDENING; GATE-030 READS THE
    SELECTION, BEFORE IT. That split is not a detail. GATE-029 and GATE-031 ask about the
    stop actually taken, so a widened stop is the one to judge — and since widening lowers
    rr, the zone modifier can MANUFACTURE a DEGENERATE_RUNNER (criterion 6b) and can equally
    clear an RR_ABOVE_ACCEPTABLE_BAND flag that fired before it. GATE-030 asks which
    candidate was CHOSEN over which, which is settled at selection time; judging it on the
    widened price would compare a post-modifier stop against pre-modifier candidates. Both
    rr values are emitted so either answer stays reconstructable.
    """
    coverage = (
        apply_zone_coverage(inputs, selected, zones) if selected is not None else None
    )
    final = selected
    if selected is not None and coverage is not None and coverage.widened:
        final = StopCandidate(
            rung=selected.rung,
            anchor=selected.anchor,
            locatable=True,
            stop_price=coverage.final_stop,
            anchor_object_id=selected.anchor_object_id,
            rr=coverage.final_rr,
            accepted=selected.accepted,
            rejection_reason=selected.rejection_reason,
            _entry=inputs.entry,
        )
    out: dict[str, Any] = {
        "GATE-029": RRAboveAcceptableBand.evaluate(final),
        "GATE-030": TighterThanNecessary.evaluate(table, selected),
        "GATE-031": DegenerateRunner.evaluate(final, eps=eps),
        "selected_before_zone_coverage": selected,
        "selected_after_zone_coverage": final,
    }
    if coverage is not None:
        values, provenance = zone_coverage_evaluation_values(coverage)
        out["zone_coverage"] = coverage
        out["zone_coverage_values"] = values
        out["zone_coverage_provenance"] = provenance
    return out
