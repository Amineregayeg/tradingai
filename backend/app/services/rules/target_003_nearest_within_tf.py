"""TARGET-003 — nearest wins WITHIN one direction and one timeframe; size ranks ACROSS them.

The registry entry:

    "If multiple liquidity pools are in the same direction… and on the same timeframe, the
    engine should target the closest one first"; "the engine should not automatically choose
    the one with the largest swing or the largest liquidity cluster"; "Institutions will
    normally consume the nearest available liquidity before continuing toward more distant
    liquidity." This settles the long-standing ambiguity between 024's Rule 2 ("highest
    amount of liquidity") and B8's "deep V… always save much higher amount of liquidity":
    SIZE IS NOT A SAME-TF SELECTOR. Size still ranks ACROSS timeframes; it never beats
    proximity WITHIN one. Agrees with the pixels at §9.B IM13 ("1D+1D LIQ > 1D LIQ. However
    1D+1D area is NOT our concern at the moment").
    output: selected pool + the rejected pools with the distance that beat their size.

## THIS RULE OWNS TWO OF THE THREE LEVELS, AND COLLAPSING THEM IS THE DEFECT

    LEVEL 1   WHICH OBJECTIVE       TARGET-001   distance BARRED    (not this module)
    LEVEL 2   ACROSS timeframes     TARGET-003   SIZE RANKS
    LEVEL 3   within one dir + TF   TARGET-003   PROXIMITY wins, size is NOT the tie-break

**"IGNORE SIZE ENTIRELY" IS THE WRONG IMPLEMENTATION AND IT IS THE ONE THAT LOOKS SAFE.** It
satisfies every same-timeframe test — size never breaks a tie because size is never read —
and it VIOLATES the rule, because size is the cross-timeframe ranker. It is also the
conservative-looking choice, which this register records as the direction that attracts less
scrutiny. The pixels are explicit that both halves hold at once: *"1D+1D LIQ > 1D LIQ"*
(bigger ranks higher across timeframes) *"However 1D+1D area is NOT our concern at the
moment"* (and still loses to the nearer objective within one).

So the two levels are implemented as two functions with different orderings, and the tests
pair them: **the same large pool must WIN across timeframes and LOSE within one.** A single
sort cannot produce both results, which is what makes the separation checkable rather than
asserted.

## WHY THE REJECTED POOLS ARE CARRIED

The statement's output is *"selected pool + the rejected pools with the distance that beat
their size"*. A selection recorded alone is unauditable — "the nearest was chosen" is only
checkable against the alternatives it beat, and specifically against a LARGER one it beat,
since that is the case the rule exists to decide. So every rejection carries both numbers and
the reason, and a rejection where the loser was larger is flagged
`size_lost_to_proximity=True`: that flag firing is the evidence the tie-break went the
doctrinal way rather than the intuitive one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.target_001_concerning_objective import Objective
from app.services.telemetry.records import RuleEvaluation, derived


@dataclass(frozen=True)
class RejectedPool:
    """One candidate that lost, and the comparison that beat it."""

    id: str
    distance: float
    size: float | None
    reason: str
    #: True when a LARGER pool lost to a nearer one. The doctrinal case, flagged so the
    #: telemetry shows the tie-break actually operating rather than merely occurring.
    size_lost_to_proximity: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "distance": self.distance,
            "size": self.size,
            "reason": self.reason,
            "size_lost_to_proximity": self.size_lost_to_proximity,
        }


def _distance(o: Objective) -> float:
    if o.distance is None:
        raise ValueError(
            f"candidate {o.target.object_id} has no distance; TARGET-003's ordering is a "
            "distance question and a missing one cannot be defaulted — a default would "
            "silently sort it first or last"
        )
    return o.distance


def _size(o: Objective) -> float:
    #: 0.0 for an unsized pool. NOT None-as-infinity: an unsized pool must not outrank a
    #: measured one, and treating absence as "biggest" is how a detector gap becomes a
    #: preference.
    return o.size if o.size is not None else 0.0


def rank_across_timeframes(candidates: Sequence[Objective]) -> list[Objective]:
    """LEVEL 2 — size ranks ACROSS timeframes. Bigger first.

    *"Size still ranks ACROSS timeframes."* Distance is NOT the ordering here, and that is
    the half an "ignore size entirely" implementation gets wrong while passing every
    same-timeframe test.

    Ties break on distance, nearer first — a secondary key rather than a coin toss, so the
    ordering is deterministic and a reader can predict it.
    """
    return sorted(candidates, key=lambda o: (-_size(o), _distance(o)))


def select_within_tf(
    candidates: Sequence[Objective],
) -> tuple[Objective | None, list[RejectedPool]]:
    """LEVEL 3 — within one direction and one timeframe, the NEAREST wins.

    Size is not consulted for the selection at all. It is READ, but only to report whether a
    larger pool lost — which is the telemetry the statement asks for, not an input to the
    decision. Reading a value to record it and reading it to decide are different acts, and
    only the second is forbidden.
    """
    if not candidates:
        return None, []
    ordered = sorted(candidates, key=_distance)
    winner = ordered[0]
    rejected = [
        RejectedPool(
            id=o.target.object_id,
            distance=_distance(o),
            size=o.size,
            reason=(
                f"a nearer candidate at {_distance(winner)} was selected first; "
                "institutions consume the nearest available liquidity before continuing"
            ),
            size_lost_to_proximity=_size(o) > _size(winner),
        )
        for o in ordered[1:]
    ]
    return winner, rejected


class NearestWithinTimeframe(RuleImplementation):
    """TARGET-003: proximity within one dir+TF, size across timeframes."""

    RULE_ID = "TARGET-003"

    COVERAGE_NOTE = (
        "IMPLEMENTS TWO ORDERING LEVELS AND DELIBERATELY NOT THE THIRD. Within one direction "
        "and one timeframe the NEAREST candidate wins and size is never an input to the "
        "selection — it is read only to report that a larger pool lost, which is the "
        "telemetry the statement requires. ACROSS timeframes size RANKS, because 'size still "
        "ranks across timeframes; it never beats proximity within one' — an implementation "
        "that ignores size entirely passes every same-TF test and violates the rule. WHICH "
        "objective the trade is about is TARGET-001's level 1 and is not decided here; this "
        "rule only orders candidates it is given. Unsized pools count as size 0.0, never as "
        "unbounded, so a detector gap cannot become a preference."
    )

    @classmethod
    def evaluate(
        cls,
        candidates: Sequence[Objective],
        *,
        same_timeframe: bool = True,
    ) -> RuleEvaluation:
        """PASS with the selection and every rejection; NOT_APPLICABLE on an empty set.

        `same_timeframe` selects the LEVEL, and it is an explicit argument rather than
        something inferred from the candidates' `tf` fields. Inferring it would make the two
        levels indistinguishable to a reader of the record — and would silently switch
        ordering rules when a fixture happened to mix timeframes, which is the collapse this
        rule's whole structure exists to prevent.
        """
        values: dict[str, Any] = {
            "candidates_considered": len(candidates),
            "level": "WITHIN_TF_PROXIMITY" if same_timeframe else "ACROSS_TF_SIZE",
            "size_is_tie_break": False,
        }
        provenance: dict[str, Any] = {
            "candidates_considered": derived("len(candidates supplied to TARGET-003)"),
            "level": derived("same_timeframe flag — level 3 when true, level 2 when false"),
            "size_is_tie_break": derived(
                "structural claim: within one TF, size is never an input to the selection"
            ),
        }

        if not candidates:
            # ZERO IS A DISTINCT OUTCOME, not a quiet pass (B84). An ordering rule over an
            # empty candidate set has ordered nothing, and saying PASS would be a green row
            # that means the inventory was empty.
            values["not_applicable_reason"] = (
                "no candidates supplied — an ordering rule over an empty set has decided "
                "nothing, and reporting PASS would make an empty inventory look like a "
                "working selection"
            )
            provenance["not_applicable_reason"] = derived("len(candidates) == 0")
            return cls.evaluation(
                "NOT_APPLICABLE", values=values, value_provenance=provenance
            )

        if not same_timeframe:
            ordered = rank_across_timeframes(candidates)
            values["ranking"] = [
                {"id": o.target.object_id, "tf": o.target.tf, "size": o.size,
                 "distance": o.distance}
                for o in ordered
            ]
            values["selected"] = ordered[0].target.object_id
            values["size_ranks_here"] = True
            provenance["ranking"] = derived(
                "sorted by size DESC, distance ASC as the tie-break — TARGET-003: 'size "
                "still ranks across timeframes'"
            )
            provenance["selected"] = derived("first of the across-timeframe ranking")
            provenance["size_ranks_here"] = derived(
                "level 2: across timeframes, size is the ranker"
            )
            return cls.evaluation("PASS", values=values, value_provenance=provenance)

        winner, rejected = select_within_tf(candidates)
        assert winner is not None  # non-empty checked above
        values["selected"] = winner.target.object_id
        values["selected_distance"] = _distance(winner)
        values["selected_size"] = winner.size
        values["rejected_pools"] = [r.as_dict() for r in rejected]
        # The doctrinal case, counted: a LARGER pool lost to a nearer one. If this is always
        # zero across a corpus, the tie-break has never actually been exercised and the rule
        # is passing without deciding anything.
        values["larger_pools_rejected"] = sum(
            1 for r in rejected if r.size_lost_to_proximity
        )
        values["size_ranks_here"] = False
        provenance["selected"] = derived("argmin(distance) among same-direction same-TF")
        provenance["selected_distance"] = derived("candidate distance from entry")
        provenance["selected_size"] = derived(
            "RECORDED, not used — size is not a same-TF selector"
        )
        provenance["rejected_pools"] = derived(
            "every non-selected candidate with the distance that beat it — TARGET-003's "
            "declared output"
        )
        provenance["larger_pools_rejected"] = derived(
            "count of rejections where the loser was LARGER than the winner"
        )
        provenance["size_ranks_here"] = derived(
            "level 3: within one TF, size never beats proximity"
        )
        return cls.evaluation("PASS", values=values, value_provenance=provenance)
