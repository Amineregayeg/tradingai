"""EXIT-004 — a target is a NAMED OBJECT, never a bare number (T-0023).

The registry entry:

    "Where is my Profit Target? — Unfilled or half filled Imbalances — Equal Highs/Lows
    because they are a form of Liquidity and Market makers hunt them." Real TPs are set at
    marked liquidity points, not at whatever a tool defaults to: "i never set my targets
    like this… this liquidity point can be a great target for me". On a magic-aligned setup
    the target class should be present on all aligned assets ("three assets riding towards
    their imbalances is crazy effective"). Telemetry must name the object the target sits
    on, so a target that corresponds to no detected primitive is visible as an unexplained
    decision.
    output: target_object{type, id, price} — never a bare number.

THE DEFECT THIS RULE EXISTS TO FORBID IS A FLOAT. A target of `118400.0` is unauditable: it
cannot be checked against the inventory, it cannot be attributed to a primitive, and it is
exactly what a charting tool's default produces. So a `TargetObject` cannot be constructed
without an id and a type, and the price is derived from the object rather than supplied
beside it.

## THE ENUM IS NARROWER THAN THE VOCABULARY FEEDING IT, AND ONE MAPPING IS A TRAP

`TELEMETRY_SCHEMA.json` constrains `target_object_type` to five values. `PRIM-003` classifies
pools into seven, of which it BUILDS four. The two sets overlap without nesting:

    PRIM-003 builds            faithful target_object_type?
    SWING_LEVEL                NO  — no such value; collapses to LIQUIDITY_POOL
    INSTITUTIONAL_CANDLESTICK  NO  — and the obvious mapping is WRONG. See below.
    EQUAL_HIGHS_LOWS           yes
    SESSION_LEVEL              yes

**`INSTITUTIONAL_CANDLESTICK` MUST NOT MAP TO `INSTITUTIONAL_LEVEL`.** The names differ by one
word and the objects are different: `INSTITUTIONAL_LEVEL` is a monthly/weekly/daily **deep-V
swing extreme** — the thing `TARGET-007` is OPEN about, because *"a 'Deep-V' is not defined by
a fixed retracement percentage or ATR value"* — while `INSTITUTIONAL_CANDLESTICK` is
**PDH/PDL, PWH/PWL, PMH/PML and the Monday range**. Mapping one onto the other would file
every previous-day-high target as a deep-V extreme: a **silent misattribution**, and strictly
worse than the generic bucket, because it produces a confident wrong class instead of a
visibly imprecise one. A test asserts this mapping does not happen, because it is the mistake
a future edit makes while thinking it is tightening the code.

**Half-filled imbalances map to `UNFILLED_IMBALANCE`,** which loses a distinction `PRIM-002`
makes (`FillState` has `HALF_FILLED` and even carries `fill_fraction`). The statement names
*"unfilled or half filled"* as targets both; the enum has one value for the pair. Recorded,
not widened.

**Both are `B77`'s shape — a contract enum lossier than the vocabulary feeding it — and the
remedy is to SET the field, never omit it.** `target_object_type` is NOT in the schema's
`required` list, so omitting would validate — and would make *"no faithful value exists"*
indistinguishable from *"nobody populated this"*, which is this register's default failure.
So the widened value is emitted, with `type_is_widened` beside it as a self-attestation.

**The true class is NOT copied into the record, and `target_object_id` is why.** It is the
pool's own id, and `trade_execution` requires `setup_evaluation_id`, whose
`primitives.liquidity_pools[]` carries `{id, tf, class, price, state}` — so the class is
recoverable by a join guaranteed to resolve. A second copy is the same claim in two homes,
and the copy nothing checks is the one that goes stale. **The honest cost: a
`trade_execution` read ALONE cannot tell you the pool class.** That is real, and the remedy
is the join rather than a duplicate.

## WHAT IS NOT IMPLEMENTED, AND IT IS HALF THE STATEMENT

The aligned-asset claim — *"on a magic-aligned setup the target class should be present on all
aligned assets"* — is a CROSS-ASSET assertion. It needs the correlate panels and GATE-002's
disturbance state, and it is not implemented here. `COVERAGE_NOTE` says so, because
`rules/__init__.py` warns that implemented means registered, not finished.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_002_imbalances import Imbalance
from app.services.rules.prim_003_liquidity import LiquidityPool
from app.services.telemetry.records import RuleEvaluation, derived, from_primitive

#: The schema's five. Mirrored here so a drift between code and contract is a test failure
#: rather than a record that silently fails validation at the store boundary.
TargetObjectType = Literal[
    "LIQUIDITY_POOL",
    "UNFILLED_IMBALANCE",
    "EQUAL_HIGHS_LOWS",
    "INSTITUTIONAL_LEVEL",
    "SESSION_LEVEL",
]

TARGET_OBJECT_TYPES: tuple[str, ...] = (
    "LIQUIDITY_POOL",
    "UNFILLED_IMBALANCE",
    "EQUAL_HIGHS_LOWS",
    "INSTITUTIONAL_LEVEL",
    "SESSION_LEVEL",
)

#: PRIM-003 pool class -> target_object_type. Explicit for every class PRIM-003 KNOWS, built
#: or not, so a class becoming buildable later does not silently fall through a default.
#:
#: The two `LIQUIDITY_POOL` entries among the BUILT classes are the lossy ones. They are
#: written out rather than left to a fallback precisely so that the loss is visible in the
#: table a reader checks, instead of being an absence they have to notice.
POOL_CLASS_TO_TARGET_TYPE: dict[str, str] = {
    # -- built by PRIM-003 ----------------------------------------------------------
    "SWING_LEVEL": "LIQUIDITY_POOL",              # LOSSY: no swing value in the enum
    "EQUAL_HIGHS_LOWS": "EQUAL_HIGHS_LOWS",
    "INSTITUTIONAL_CANDLESTICK": "LIQUIDITY_POOL",  # LOSSY, and NOT INSTITUTIONAL_LEVEL
    "SESSION_LEVEL": "SESSION_LEVEL",
    # -- classified by PRIM-003, not built (each needs a number Salim declined to fix) --
    "PARABOLIC_COMPRESSED": "LIQUIDITY_POOL",     # LOSSY
    "INSTITUTIONAL_LEVEL": "INSTITUTIONAL_LEVEL",  # the genuine deep-V extreme
    "DIAGONAL_POOL": "LIQUIDITY_POOL",            # LOSSY
}

#: The classes whose mapping DISCARDS information, named so the record can flag itself and a
#: test can assert the set has not silently grown.
LOSSY_POOL_CLASSES: tuple[str, ...] = (
    "SWING_LEVEL",
    "INSTITUTIONAL_CANDLESTICK",
    "PARABOLIC_COMPRESSED",
    "DIAGONAL_POOL",
)

#: PRIM-002 fill states that EXIT-004 admits as a target. "Unfilled or half filled" — a fully
#: filled imbalance has been consumed and is not an objective.
TARGETABLE_FILL_STATES: tuple[str, ...] = ("UNFILLED", "HALF_FILLED")


class NotATargetObject(ValueError):
    """A target was supplied as a price with no object behind it.

    The one thing EXIT-004 exists to refuse. Raised rather than recorded because there is
    nothing to record: a bare number names no primitive, so a telemetry entry for it would
    be the unexplained decision the statement is trying to make visible.
    """


@dataclass(frozen=True)
class TargetObject:
    """`target_object{type, id, price}` — the contract's shape, plus its own provenance.

    `price` is NOT independently supplied. It is read off the object, because a price passed
    beside an id can disagree with it, and the disagreement is unrecoverable later: the
    record would name an object and carry a number that is not on it.
    """

    object_id: str
    object_type: str
    price: float
    #: What the object REALLY is, when `object_type` had to be widened to fit the enum.
    #: Always populated, so a reader never has to infer whether widening occurred.
    source_class: str
    tf: str
    lossy: bool = False
    #: Only for imbalances: the fill state the enum cannot express.
    fill_state_at_selection: str | None = None

    def __post_init__(self) -> None:
        if not self.object_id:
            raise NotATargetObject(
                "a target object with no id is a bare number wearing a dataclass — "
                "EXIT-004's whole requirement is that telemetry names the object"
            )
        if self.object_type not in TARGET_OBJECT_TYPES:
            raise ValueError(
                f"{self.object_type!r} is not one of the schema's target_object_type "
                f"values {TARGET_OBJECT_TYPES}"
            )

    def as_dict(self) -> dict[str, Any]:
        """The schema's `trade_execution.target` shape.

        `target_object_type` is EMITTED even when it is the widened value. Omitting it would
        validate — it is not in the schema's `required` list — and would make "no faithful
        value exists" read identically to "nobody populated this field".

        THE TRUE CLASS IS DELIBERATELY **NOT** EMITTED HERE, AND `object_id` IS WHY.
        `target_object_id` is the pool's or imbalance's own id, and `trade_execution`
        requires `setup_evaluation_id`, whose `primitives.liquidity_pools[]` carries
        `{id, tf, class, price, state}`. So the class is recoverable by a join that is
        guaranteed to resolve. Copying it here would be the same claim in two homes, and the
        copy nothing checks is the one that goes stale.

        **The honest cost, stated rather than papered over: a `trade_execution` read ALONE
        cannot tell you the pool class.** That is a real limit of this shape and the remedy
        is the join, not a duplicate.

        `fill_state_at_selection` IS emitted, and it is not the same kind of thing. **The
        test is whether the source can CHANGE.** A pool's class is immutable, so a stored
        copy can only ever drift from the truth. An imbalance's fill state ADVANCES as price
        approaches it — by settle time the join returns `FULLY_FILLED` and is correct and
        useless. So "it was HALF_FILLED when we chose it" is not a second copy of a fact; it
        is **the only copy of a different fact**, and no later read can recover it.

        **The field is named `_at_selection` for that reason.** A bare `fill_state` invites
        exactly the misreading the join would then contradict; the name carries the warning.
        """
        out: dict[str, Any] = {
            "price": self.price,
            "target_object_id": self.object_id,
            "target_object_type": self.object_type,
        }
        if self.lossy:
            # A self-attestation, not a copy of the class: it says the mapping widened,
            # which a conformance reader can act on without resolving the join.
            out["type_is_widened"] = True
        if self.fill_state_at_selection is not None:
            out["fill_state_at_selection"] = self.fill_state_at_selection
        return out


class TargetIsANamedObject(RuleImplementation):
    """EXIT-004: targets are liquidity points and unfilled imbalances, never tool defaults."""

    RULE_ID = "EXIT-004"

    COVERAGE_NOTE = (
        "PARTIAL, AND THE UNBUILT HALF IS NAMED. Implemented: a target is a named object "
        "carrying {type, id, price}, built from a PRIM-003 pool or a PRIM-002 unfilled/"
        "half-filled imbalance, with a bare price refused at construction. NOT implemented: "
        "the aligned-asset claim — 'on a magic-aligned setup the target class should be "
        "present on all aligned assets' — which is a CROSS-ASSET assertion needing the "
        "correlate panels and GATE-002's disturbance state. Two mappings are LOSSY because "
        "the schema's five-value target_object_type is narrower than PRIM-003's seven pool "
        "classes: SWING_LEVEL and INSTITUTIONAL_CANDLESTICK both widen to LIQUIDITY_POOL, "
        "and HALF_FILLED imbalances widen to UNFILLED_IMBALANCE. INSTITUTIONAL_CANDLESTICK "
        "is deliberately NOT mapped to INSTITUTIONAL_LEVEL — they are different objects "
        "(PDH/PDL vs deep-V swing extremes) and that mapping would be a silent "
        "misattribution. The true class is always carried as source_class."
    )

    @classmethod
    def from_pool(cls, pool: LiquidityPool) -> TargetObject:
        """Build a target object from a PRIM-003 liquidity pool."""
        if pool.price is None:
            raise NotATargetObject(
                f"pool {pool.id} has no price, so it cannot be a target — an objective "
                "the engine cannot put a number on is not one it can trade towards"
            )
        mapped = POOL_CLASS_TO_TARGET_TYPE.get(pool.pool_class)
        if mapped is None:
            # A pool class PRIM-003 knows and this table does not. Refused rather than
            # defaulted: a silent fallback to LIQUIDITY_POOL would absorb a genuinely new
            # class without anyone deciding what it should map to.
            raise ValueError(
                f"pool class {pool.pool_class!r} has no entry in "
                "POOL_CLASS_TO_TARGET_TYPE. Add one deliberately — a default would hide a "
                "new class inside the generic bucket."
            )
        return TargetObject(
            object_id=pool.id,
            object_type=mapped,
            price=float(pool.price),
            source_class=pool.pool_class,
            tf=pool.tf,
            lossy=pool.pool_class in LOSSY_POOL_CLASSES,
        )

    @classmethod
    def from_imbalance(cls, imb: Imbalance) -> TargetObject:
        """Build a target object from a PRIM-002 unfilled or half-filled imbalance.

        The price is the band's far edge in the direction of travel — a bullish imbalance is
        a destination reached at its high. Taking the midpoint would invent a fill
        assumption the statement does not make.
        """
        if imb.fill_state not in TARGETABLE_FILL_STATES:
            raise NotATargetObject(
                f"imbalance {imb.id} is {imb.fill_state}; EXIT-004 names 'unfilled or half "
                "filled' imbalances as targets, and a consumed one is not an objective"
            )
        price = imb.price_high if imb.direction == "BULLISH" else imb.price_low
        return TargetObject(
            object_id=imb.id,
            object_type="UNFILLED_IMBALANCE",
            price=float(price),
            source_class=f"IMBALANCE_{imb.type}",
            tf=imb.tf,
            # HALF_FILLED has no distinct enum value. The statement admits both, so this is
            # a target either way — but the record must not claim it was untouched.
            lossy=imb.fill_state == "HALF_FILLED",
            fill_state_at_selection=imb.fill_state,
        )

    @classmethod
    def evaluate(cls, target: TargetObject | None) -> RuleEvaluation:
        """PASS when the target names an object; FAIL when there is none.

        NOT_APPLICABLE is not offered. A setup being evaluated for entry either has a target
        or does not, and "no target" is a FAIL of this rule rather than an inability to
        judge it — the whole statement is that a trade without a named objective should be
        visible as an unexplained decision.
        """
        if target is None:
            return cls.evaluation(
                "FAIL",
                values={
                    "target_object": None,
                    "violations": [
                        "no target object — a target that names no detected primitive is "
                        "the unexplained decision EXIT-004 exists to surface"
                    ],
                    "aligned_asset_claim_evaluated": False,
                },
                value_provenance={
                    "target_object": derived("EXIT-004 target selection"),
                    "violations": derived("EXIT-004 conformance check"),
                    "aligned_asset_claim_evaluated": derived(
                        "NOT IMPLEMENTED — needs the correlate panels and GATE-002"
                    ),
                },
            )

        values: dict[str, Any] = {
            "target_object": target.as_dict(),
            "target_object_type": target.object_type,
            "source_class": target.source_class,
            "type_is_widened": target.lossy,
            "admissible_types": list(TARGET_OBJECT_TYPES),
            # Emitted as a literal False on every record: a claim the engine makes about
            # itself, which a conformance test can read without inspecting the source.
            "aligned_asset_claim_evaluated": False,
        }
        provenance: dict[str, Any] = {
            "target_object": from_primitive(target.object_id, "price"),
            "target_object_type": derived(
                "POOL_CLASS_TO_TARGET_TYPE[source_class], or UNFILLED_IMBALANCE for a "
                "PRIM-002 imbalance"
            ),
            "source_class": from_primitive(target.object_id, "class"),
            "type_is_widened": derived(
                "the schema's target_object_type is narrower than PRIM-003's pool classes"
            ),
            "admissible_types": derived("TELEMETRY_SCHEMA target_object_type enum"),
            "aligned_asset_claim_evaluated": derived(
                "NOT IMPLEMENTED — the aligned-asset half of EXIT-004 needs the correlate "
                "panels and GATE-002's disturbance state"
            ),
        }
        return cls.evaluation("PASS", values=values, value_provenance=provenance)
