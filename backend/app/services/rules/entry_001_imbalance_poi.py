"""ENTRY-001 — entry is ALWAYS from an inefficiency; imbalance is the primary POI (T-0019).

The registry entry:

    "We always take entries from imbalances no matter what, we do not use OBs or BBs to
    enter." After the aligned MSB, "i need imbalances to make entries or BPR or a gap, any
    kind of inefficiency will do the job". The trader's canonical criteria list confirms
    this as a PRECEDENCE RULE, not a preference: "Imbalances (primary POI)". Preference
    order within inefficiencies: super BPR > BPR > plain imbalance; collisions with OB/BB
    UPGRADE the entry but never replace the imbalance as the trigger.
    output: entry_poi{type, price_band, sub_rank} + colliding_blocks[] (upgrade evidence only)

WHY AN ORDER BLOCK IS EXCLUDED RATHER THAN RANKED LAST, and it is the whole rule
A version that ranks OB/BB *below* imbalances satisfies the word "precedence" and violates
the statement, because with no imbalance present the best-ranked candidate is then an order
block and an entry is taken on it. **The trader's sentence is a prohibition — "we do not use
OBs or BBs to enter" — so blocks are not candidates at all.** They enter this rule only
through `colliding_blocks`, which is evidence attached to an entry the imbalance already
justified.

THE PRECEDENCE ORDER IS IMPLEMENTED AND ITS OUTCOME IS NOT ASSERTED OVER LIVE DATA
`super BPR > BPR > plain imbalance` is ranked here, deterministically, over whatever
candidates the caller supplies.

**T-0020 HAS LANDED (2026-08-15) and the prohibition this paragraph used to carry is
DISCHARGED.** It read: this rule must not be tested against which type PRIM-002 classifies a
band as, because the promotion scan had no time bound, the SUPER_BPR share grew with the
corpus, and the same band ranked differently depending on how much history the caller
passed. The scan is now causal, direction-constrained and bounded by a declared lookback,
and over a committed 999-bar corpus **every band the backtest's 250-bar window and a
999-bar window both see is classified identically**. So the ordering CAN now be asserted
over detected bars, and `test_t0019_entry_decision.py` asserts it.

The tests here still hand this rule an explicit candidate list, which remains the right
shape for a ranking rule — but that is now a choice about what this rule owns, not a
prohibition imposed by a defect upstream.

FILL STATE IS RECORDED AND NOT FILTERED ON, DELIBERATELY
The registry names fill state as an input and says nothing about how it gates entry. "An
imbalance stays extremely reactive until it is fully filled" is a reactivity claim, not an
admissibility threshold. Excluding filled imbalances would be an invented rule wearing this
rule's id, so every candidate's `fill_state` and `fill_fraction` travel on the record and a
later ruling can be applied to stored history instead of invalidating it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_002_imbalances import Imbalance
from app.services.telemetry.records import RuleEvaluation, derived, from_record

#: The precedence order inside the inefficiency family, from the statement itself
#: ("super BPR > BPR > plain imbalance"). Lower number wins. This is DOCTRINE, quoted, not an
#: engine choice — which is why it is a constant here and not a declared parameter.
SUB_RANK: dict[str, int] = {
    "SUPER_BPR": 1,
    "BPR": 2,
    # "any kind of inefficiency will do the job" — the three plain types are one rank. The
    # statement orders super BPR and BPR explicitly and says nothing separating FVG from a
    # volume imbalance or a gap, so inventing an order between them would be doctrine we made
    # up. Ties break on formation order, which is a fact rather than a preference.
    "FVG": 3,
    "VOLUME_IMBALANCE": 3,
    "GAP": 3,
}

#: The types that may be an entry POI. Every key of SUB_RANK, by construction — an
#: inefficiency type that gained a rank but not admissibility would be silently unenterable.
ADMISSIBLE_TYPES = frozenset(SUB_RANK)

#: NOT candidates. Named so the prohibition is greppable and so the record can say what was
#: seen and refused rather than only what was chosen.
BLOCK_KINDS = ("ORDER_BLOCK", "BREAKER_BLOCK")


@dataclass(frozen=True)
class Block:
    """An OB or BB zone. Upgrade evidence only — never an entry trigger."""

    kind: str
    price_high: float
    price_low: float
    id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "price_high": self.price_high,
            "price_low": self.price_low,
        }


@dataclass(frozen=True)
class EntryPOI:
    """The chosen entry object, in the registry's shape."""

    type: str
    price_high: float
    price_low: float
    sub_rank: int
    imbalance_id: str
    fill_state: str
    fill_fraction: float
    colliding_blocks: list[Block] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            # The contract's word is `price_band`, and a band is two numbers. PRIM-006 is
            # explicit about why a single price is never enough.
            "price_band": {"high": self.price_high, "low": self.price_low},
            "sub_rank": self.sub_rank,
            "imbalance_id": self.imbalance_id,
            "fill_state": self.fill_state,
            "fill_fraction": round(self.fill_fraction, 6),
        }


def _overlaps(a_high: float, a_low: float, b_high: float, b_low: float) -> bool:
    return a_low <= b_high and b_low <= a_high


class ImbalanceIsTheOnlyEntryPOI(RuleImplementation):
    """ENTRY-001: only an inefficiency may be entered on; OB/BB are upgrade evidence."""

    RULE_ID = "ENTRY-001"

    COVERAGE_NOTE = (
        "The precedence order (super BPR > BPR > plain imbalance) is implemented and is "
        "quoted doctrine. The classification upstream WAS unstable — PRIM-002's promotion "
        "had no time bound, so the share grew with the caller's lookback and the shadow "
        "and the backtest disagreed — and T-0020 fixed it on 2026-08-15: the scan is now "
        "causal, direction-constrained and bounded by a DECLARED lookback that is ours "
        "and unratified. Fill state is RECORDED and not filtered on — the statement makes "
        "no admissibility claim about it, and excluding filled imbalances would be an "
        "invented rule wearing this id."
    )

    @classmethod
    def select(
        cls,
        candidates: Sequence[Imbalance] = (),
        blocks: Sequence[Block] = (),
        *,
        at_price: float | None = None,
    ) -> EntryPOI | None:
        """The entry POI, or None when no inefficiency is available at the location.

        `None` IS A REAL ANSWER AND MUST NOT BE FILLED IN. With only an order block at the
        entry location the honest result is no entry POI — not a downgraded one, not a
        block-shaped one. That is the whole prohibition.
        """
        admissible = [
            imb for imb in candidates
            if imb.type in ADMISSIBLE_TYPES
            and (at_price is None or imb.price_low <= at_price <= imb.price_high)
        ]
        if not admissible:
            return None

        # Deterministic: rank first, then formation order, then id. Ties are broken on facts
        # rather than on a preference the statement does not express.
        best = min(
            admissible,
            key=lambda imb: (SUB_RANK[imb.type], imb.formed_index, imb.id),
        )
        colliding = [
            b for b in blocks
            if _overlaps(best.price_high, best.price_low, b.price_high, b.price_low)
        ]
        return EntryPOI(
            type=best.type,
            price_high=best.price_high,
            price_low=best.price_low,
            sub_rank=SUB_RANK[best.type],
            imbalance_id=best.id,
            fill_state=best.fill_state,
            fill_fraction=best.fill_fraction,
            colliding_blocks=list(colliding),
        )

    @classmethod
    def evaluate(
        cls,
        candidates: Sequence[Imbalance] = (),
        blocks: Sequence[Block] = (),
        *,
        at_price: float | None = None,
    ) -> RuleEvaluation:
        """PASS when an inefficiency is available to enter on, FAIL when none is.

        FAIL RATHER THAN NOT_APPLICABLE, and the distinction is load-bearing here. This rule
        CAN be evaluated on every bar — its inputs exist and were read. "No imbalance at the
        entry location" is the rule working and refusing, not the rule being unable to speak.
        NOT_APPLICABLE would say the engine could not tell, which is the absent-versus-empty
        collapse this project keeps rebuilding.
        """
        poi = cls.select(candidates, blocks, at_price=at_price)
        refused = [
            b.as_dict() for b in blocks
            if at_price is None or b.price_low <= at_price <= b.price_high
        ]

        values: dict[str, Any] = {
            "entry_poi": poi.as_dict() if poi is not None else None,
            "colliding_blocks": [b.as_dict() for b in (poi.colliding_blocks if poi else [])],
            # WHAT WAS SEEN AND REFUSED. Without it, "no entry POI" reads the same whether
            # the location was empty or held an order block the rule correctly declined —
            # and those have different meanings to anyone auditing a skipped setup.
            "blocks_at_location_not_eligible": refused,
            "candidates_considered": len(candidates),
            "admissible_candidates": sum(
                1 for imb in candidates if imb.type in ADMISSIBLE_TYPES
            ),
            "block_kinds_never_eligible": list(BLOCK_KINDS),
            "sub_rank_order": dict(SUB_RANK),
        }
        provenance: dict[str, Any] = {
            "entry_poi": from_record("primitives.imbalances"),
            "colliding_blocks": derived(
                "OB/BB zones whose band overlaps the chosen POI — upgrade evidence only"
            ),
            "blocks_at_location_not_eligible": derived(
                "OB/BB zones at the entry location that this rule refused as triggers"
            ),
            "candidates_considered": derived("count of inefficiency objects supplied"),
            "admissible_candidates": derived(
                "count of supplied objects whose type is in ADMISSIBLE_TYPES"
            ),
            "block_kinds_never_eligible": derived(
                "ENTRY-001 statement — 'we do not use OBs or BBs to enter'"
            ),
            "sub_rank_order": derived(
                "ENTRY-001 statement — 'super BPR > BPR > plain imbalance'"
            ),
        }
        return cls.evaluation(
            "PASS" if poi is not None else "FAIL",
            values=values,
            value_provenance=provenance,
        )
