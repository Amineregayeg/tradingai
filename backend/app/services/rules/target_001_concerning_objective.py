"""TARGET-001 — the concerning liquidity is the next UNRESOLVED OBJECTIVE, not the closest.

The registry entry, an OVERRIDE:

    "The concerning liquidity is therefore not simply the closest liquidity. It is the next
    unresolved objective that supports the active institutional destination"; "Distance
    alone never determines the destination". The concept "is not determined by a fixed
    distance, percentage, or ATR threshold"; the engine "should not ask: 'Is liquidity
    within X% or Y × ATR?'". Proximity survives ONLY as an ordering input among
    same-direction, same-timeframe candidates. [059, 085, §9.B IM10 and 0613] are all
    superseded as the SELECTION RULE and survive only as inputs.
    output: concerning_objective{id, price, tf, type, why_selected} — the 'why' must name
    the institutional destination it supports, not a distance.
    banned_inputs: fixed_pct_distance, atr_multiple_distance

## THIS LOOKS LIKE IT CONTRADICTS TARGET-003 AND IT DOES NOT

    TARGET-001   "NOT simply the closest liquidity"; "distance alone never determines"
    TARGET-003   "the engine should target the CLOSEST one first"

**Read cold, one says distance does not decide and the other says nearest wins.** The
reconciliation is not an interpretation — **TARGET-001 states the carve-out itself and hands
it to TARGET-003**, and TARGET-003 then adds a level:

    LEVEL 1   WHICH OBJECTIVE       TARGET-001   distance is BARRED as an input
    LEVEL 2   ACROSS timeframes     TARGET-003   SIZE RANKS
    LEVEL 3   within one dir + TF   TARGET-003   proximity wins, size is NOT the tie-break

*"Proximity survives ONLY as an ordering input among same-direction, same-timeframe
candidates"* — TARGET-001 delegates. *"SIZE IS NOT A SAME-TF SELECTOR. Size still ranks
ACROSS timeframes; it never beats proximity WITHIN one"* — TARGET-003 occupies the carve-out
and names a middle level.

**So distance is barred from the objective decision and mandated for the within-pool
ordering. An implementation using distance in the first, or size in the third, is wrong in
opposite directions — and BOTH pass a test that only checks a target came out.** This module
owns level 1 and nothing else; `target_003_nearest_within_tf.py` owns levels 2 and 3.

## THE ACTIVE INSTITUTIONAL DESTINATION HAS NO PRODUCER, AND IT IS TAKEN AS AN INPUT

Measured before building: **nothing in this repository mentions `institutional_destination`,
`active_destination` or any spelling of it.** No rule computes one. So TARGET-001 consumes an
input the engine cannot supply, and this implementation takes it as a parameter rather than
inferring one from price — which is what the plan requires and what honesty requires, since
inferring a destination from distance is the exact prohibition above, wearing a different
name.

**`CANNOT_FIRE_WITHOUT` is declared accordingly.** Registering this rule must not inflate
effective coverage: implemented and unable to fire is what the coverage report has a separate
bucket for, and putting it there is the difference between 40 implemented / 39 effective and
a figure that claims a decision the engine cannot make.

## WHY `why_selected` IS THE HARD PART

The registry says the `why` **must name the institutional destination it supports, not a
distance**. So `why_selected: "nearest unresolved high"` is a FAILING output even though it
is TRUE — it is a distance answer to a structural question. This is the criterion a lazy
implementation satisfies with any non-empty string, so `why_selected` is **derived from the
destination object** and never templated: it names the destination's id and label, and a
test asserts that two different destinations produce two DIFFERENT strings. A hardcoded
destination-shaped constant passes every check except that one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.exit_004_target_object import TargetObject
from app.services.telemetry.records import RuleEvaluation, derived, from_primitive

#: Declared in the registry. Checked, never assumed — and `present` is COMPUTED rather than
#: hardcoded to `[]`, which is the defect T-0019 fixed and this is the first rule since with
#: real banned inputs to check.
BANNED_INPUTS: tuple[str, ...] = ("fixed_pct_distance", "atr_multiple_distance")

#: Substrings that betray a distance answer to a structural question. Used ONLY to reject a
#: `why_selected`, never to build one — a checker that also generated the string would agree
#: with itself by construction.
DISTANCE_WORDS: tuple[str, ...] = (
    "closest", "nearest", "distance", "atr", "percent", "%", "pips", "points away",
    "far", "near",
)


@dataclass(frozen=True)
class InstitutionalDestination:
    """The active institutional destination. **AN INPUT — nothing in the engine produces one.**

    Carried as an object rather than a string so `why_selected` can be DERIVED from its
    identity. A string destination would make a templated `why` indistinguishable from a
    derived one, which is precisely the hole criterion 2-i exists to close.
    """

    id: str
    label: str
    #: Which way the destination lies. Objectives that do not support it are not candidates.
    direction: str
    tf: str

    def __post_init__(self) -> None:
        if self.direction not in ("BULLISH", "BEARISH"):
            raise ValueError(f"direction must be BULLISH or BEARISH, got {self.direction!r}")
        if not self.id or not self.label:
            raise ValueError(
                "a destination with no id or no label cannot be named in why_selected, and "
                "naming it is the whole requirement"
            )


@dataclass(frozen=True)
class Objective:
    """A candidate objective: a liquidity pool or unfilled imbalance, plus its state.

    `supports_destination` IS AN INPUT, NOT A COMPUTATION. Whether an objective supports the
    active institutional destination is a structural judgement the corpus does not reduce to
    a formula, and deriving it here from position or distance would be the banned reasoning
    under a new name. It is supplied, and the record says it was supplied.
    """

    target: TargetObject
    resolved: bool
    supports_destination: bool
    #: Distance from entry. CARRIED for TARGET-003's ordering and DELIBERATELY UNUSED here.
    distance: float | None = None
    size: float | None = None
    direction: str = "BULLISH"


@dataclass(frozen=True)
class ConcerningObjective:
    """`concerning_objective{id, price, tf, type, why_selected}`."""

    id: str
    price: float
    tf: str
    type: str
    why_selected: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "price": self.price,
            "tf": self.tf,
            "type": self.type,
            "why_selected": self.why_selected,
        }


def why_names_a_destination(why: str) -> bool:
    """A TRIPWIRE ON TEXT THIS MODULE DERIVED. **Not a validator of text supplied to it.**

    Does `why_selected` name a destination rather than answer with a distance?

    A NEGATIVE CHECK PLUS A LENGTH FLOOR IS NOT ENOUGH ON ITS OWN, and the module docstring
    says why: a constant string passes both. The load-bearing assertion is the one in the
    test — two destinations must produce two DIFFERENT strings. This function catches the
    other failure, a `why` that is derived but phrased as a distance.

    ITS SCOPE IS RECORDED HERE BECAUSE THE CHECK IS LEXICAL AND THE PROPERTY IS SEMANTIC
    (B98, found by Review). `DISTANCE_WORDS` holds the bare substrings `"far"` and `"near"`,
    and those are distance words in *"the far one"* and STRUCTURAL words in *"the far side of
    the flip zone"* — standard SMC vocabulary for a location, the same object `GATE-027`'s
    notes discuss at `§9.J IM79/IM86`. Measured false positives:

        rejected   "the far edge of the daily order block"      structural, wrongly refused
        rejected   "the far side of the H4 flip zone"           structural, wrongly refused
        rejected   "the nearest unresolved high"                CORRECT — a distance answer
        accepted   "the weekly equal highs at 112.5"
        accepted   "sell-side liquidity under the Monday low"

    **LENGTHENING THE LIST CANNOT FIX THIS.** The same token is correct in one sentence and
    wrong in another, so no lexical rule separates them.

    **The defect a false positive would cause is not a rejected string — it is that the
    rejection is INDISTINGUISHABLE FROM A REAL TARGET-001 VIOLATION**: same value, same FAIL,
    same message, and a reader goes hunting for a distance-based selector that does not
    exist.

    **What holds today: the ONLY call site is on the `why` this module derives from the
    destination object, which never produces that vocabulary.** So the check is sound where
    it is used. It is exported for tests, and a caller passing HUMAN-WRITTEN or
    ANOTHER-RULE'S text — `TARGET-007` and the `GATE-027` ladder work both plausibly would —
    is outside what it can answer. **Do not make it a gate on supplied text without
    replacing the lexical test.**
    """
    lowered = why.lower()
    return bool(why.strip()) and not any(w in lowered for w in DISTANCE_WORDS)


class ConcerningLiquidityIsStructural(RuleImplementation):
    """TARGET-001: the next unresolved objective supporting the active destination."""

    RULE_ID = "TARGET-001"

    #: The destination has NO producer anywhere under app/. Declared so the coverage report
    #: puts this rule in the "implemented but CANNOT FIRE" bucket rather than counting it as
    #: a decision the engine can make. Named as the missing DATA rather than a rule id
    #: because no registry rule produces it — B44's case: the rule knows, the graph does not.
    CANNOT_FIRE_WITHOUT = ("active_institutional_destination",)

    COVERAGE_NOTE = (
        "IMPLEMENTED AND UNABLE TO FIRE. The selection logic, the banned-input check and the "
        "why_selected derivation are all real and tested, but 'the active institutional "
        "destination' HAS NO PRODUCER — measured, zero mentions anywhere under app/ — so the "
        "rule consumes an input the engine cannot supply and is taken as a parameter here. "
        "Inferring one from price would be the banned distance reasoning under another name. "
        "This rule owns LEVEL 1 only (which objective); TARGET-003 owns the ordering levels. "
        "Distance is carried on every candidate and is deliberately never read here."
    )

    @classmethod
    def banned_input_check(cls, present: Sequence[str] = ()) -> dict[str, Any]:
        """Same shape as GATE-002/GATE-037, so all conformance surfaces read alike."""
        return {"checked": list(BANNED_INPUTS), "present": list(present)}

    @classmethod
    def _present_banned_inputs(cls, supplied: dict[str, Any] | None) -> list[str]:
        """COMPUTED, never hardcoded to `[]`.

        An enumeration that always reports nothing present is the defect T-0019 fixed: it
        passes identically whether the inputs are absent or nobody looked. So this reads the
        actual keys handed to the selector.
        """
        if not supplied:
            return []
        return sorted(k for k in supplied if k in BANNED_INPUTS)

    @classmethod
    def select(
        cls,
        candidates: Sequence[Objective],
        destination: InstitutionalDestination,
    ) -> Objective | None:
        """Level 1: which objective is this trade about?

        THE NEXT UNRESOLVED OBJECTIVE THAT SUPPORTS THE DESTINATION. `distance` is present on
        every candidate and is not read — deliberately, and the test proves it by making the
        closer candidate the wrong one.

        "Next" is resolved by ORDER OF SUPPLY, not by proximity. The caller presents
        candidates in the sequence price would encounter them, which is a structural fact
        about the inventory rather than a measurement; sorting by distance here is precisely
        the prohibited move.
        """
        for c in candidates:
            if c.resolved:
                continue          # "only fresh not hunted liquidity levels count"
            if not c.supports_destination:
                continue          # supporting the destination is the selector
            return c
        return None

    @classmethod
    def evaluate(
        cls,
        candidates: Sequence[Objective],
        destination: InstitutionalDestination | None,
        *,
        supplied_inputs: dict[str, Any] | None = None,
    ) -> RuleEvaluation:
        """TARGET-001's telemetry.

        NOT_APPLICABLE when no destination was supplied — which is the LIVE case today, since
        nothing produces one. Silence is not a pass: a rule that could not be evaluated is
        recorded with its reason, never PASS.
        """
        present = cls._present_banned_inputs(supplied_inputs)
        # Reported on EVERY record, including the count of candidates considered, so an
        # empty candidate list is a distinct outcome rather than a quiet pass (B84).
        values: dict[str, Any] = {
            "candidates_considered": len(candidates),
            "unresolved_candidates": sum(1 for c in candidates if not c.resolved),
            "destination_supported_candidates": sum(
                1 for c in candidates if c.supports_destination and not c.resolved
            ),
            "banned_inputs_present": present,
            "distance_used_in_selection": False,
        }
        provenance: dict[str, Any] = {
            "candidates_considered": derived("len(candidates supplied to TARGET-001)"),
            "unresolved_candidates": derived("candidates with resolved == False"),
            "destination_supported_candidates": derived(
                "unresolved candidates with supports_destination == True"
            ),
            "banned_inputs_present": derived(
                "keys of the supplied input map intersected with TARGET-001.banned_inputs"
            ),
            "distance_used_in_selection": derived(
                "structural claim: TARGET-001 never reads Objective.distance"
            ),
        }

        if present:
            values["violations"] = [
                f"banned input {k!r} was supplied to the objective decision — TARGET-001 "
                "forbids asking 'is liquidity within X% or Y x ATR?'"
                for k in present
            ]
            provenance["violations"] = derived("TARGET-001 banned-input conformance check")
            return cls.evaluation(
                "FAIL", values=values, value_provenance=provenance,
                banned_input_check=cls.banned_input_check(present),
            )

        if destination is None:
            values["not_applicable_reason"] = (
                "no active institutional destination was supplied, and NOTHING IN THE "
                "ENGINE PRODUCES ONE. TARGET-001 cannot select an objective without the "
                "structure it is selecting in support of; inferring one from price would be "
                "the banned distance reasoning under another name."
            )
            values["missing_producer"] = "active_institutional_destination"
            provenance["not_applicable_reason"] = derived("destination input was None")
            provenance["missing_producer"] = derived(
                "no implementation anywhere under app/ produces an institutional destination"
            )
            return cls.evaluation(
                "NOT_APPLICABLE", values=values, value_provenance=provenance,
                banned_input_check=cls.banned_input_check(present),
            )

        chosen = cls.select(candidates, destination)
        values["destination"] = {
            "id": destination.id,
            "label": destination.label,
            "direction": destination.direction,
            "tf": destination.tf,
        }
        provenance["destination"] = derived(
            "SUPPLIED — no producer exists; see CANNOT_FIRE_WITHOUT"
        )

        if chosen is None:
            values["concerning_objective"] = None
            values["not_applicable_reason"] = (
                "no unresolved objective supports the active destination — every candidate "
                "was already resolved or points elsewhere"
            )
            provenance["concerning_objective"] = derived("TARGET-001 selection")
            provenance["not_applicable_reason"] = derived("selection returned nothing")
            return cls.evaluation(
                "NOT_APPLICABLE", values=values, value_provenance=provenance,
                banned_input_check=cls.banned_input_check(present),
            )

        # DERIVED FROM THE DESTINATION'S IDENTITY, never templated. Two destinations must
        # produce two different strings, which is the only assertion that separates derived
        # from constant — see the module docstring.
        why = (
            f"supports the active institutional destination {destination.label} "
            f"({destination.id}) on {destination.tf}; the next unresolved objective in that "
            f"structure"
        )
        objective = ConcerningObjective(
            id=chosen.target.object_id,
            price=chosen.target.price,
            tf=chosen.target.tf,
            type=chosen.target.object_type,
            why_selected=why,
        )
        values["concerning_objective"] = objective.as_dict()
        values["why_names_a_destination"] = why_names_a_destination(why)
        provenance["concerning_objective"] = from_primitive(
            chosen.target.object_id, "price"
        )
        provenance["why_names_a_destination"] = derived(
            "why_selected contains no distance vocabulary and is derived from the "
            "destination's id and label"
        )
        return cls.evaluation(
            "PASS", values=values, value_provenance=provenance,
            banned_input_check=cls.banned_input_check(present),
        )
