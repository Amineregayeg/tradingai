"""PRIM-007 — the Order Block: the last opposite-colour candle before the impulse that broke structure.

**`T-0029`'s refusal is DISCHARGED, and only because Salim defined the object.** That task built a
question rather than a producer, on the ground that *"NO rule defines an order block"*. He answered in
round 3 and `T-0045` registered the id, so this module implements a DEFINITION rather than filling a
gap with a plausible detector.

    definition  [DOCTRINE]  the LAST opposite-colour candle immediately preceding the impulse that
                            produced the aligned MSB / i-MSB — "the small red candle of the
                            'Engulfing Pattern' before the big green"; mirror for bearish
    stop point  [RULING]    THE WICK EXTREME. Round 3, and it is the reason the box's wick bounds
                            are the anchor even though his slides draw both
    failure     [DOCTRINE]  FAILED only on a BODY CLOSE through the box. A WICK through is not a
                            flip -- which is the same fact as the stop sitting beyond the wick
    becomes     [DOCTRINE]  a FAILED order block is a Breaker candidate for PRIM-006 (origin
                            FAILED_OB) -- "Breaker Block = Failed Order Block"
    multi       [DOCTRINE]  when several same-colour candles precede the impulse, box only the LAST;
                            do NOT merge into a zone by default, but LOG the merged extreme

## WHAT THIS MODULE REFUSES TO DO, AND WHY IT MATTERS MORE THAN WHAT IT DOES

`detect_order_blocks()` already exists at `ict/detector.py:192` — the PRE-CONTRACT ICT strategy — and
`stop_ladder_corpus.py` is allowed to call it as a PROXY under the name `ORDER_BLOCK_ICT_PROXY`,
*"granted for MEASUREMENT and forbidden for SELECTION"*. **Nothing here imports it.** Wrapping it
would have produced a working rung 4 in an afternoon and would have installed a third party's
semantics as Salim's doctrine, which is `TARGET-001`'s refusal and `GATE-014`'s shape.

> **The pack says so itself: *"The third-party detector's 94.5% hit rate is not evidence about this
> definition."*** A hit rate against ITS OWN definition says nothing about whether it found HIS object.

`test_t0046_order_blocks.py` measures the two against each other on the pinned corpus **and expects
them to DISAGREE.** *Exact agreement would be evidence that this module reimplemented ICT rather than
the ruling* — the one outcome that cannot be read as success.

## THE BOX CARRIES BOTH EXTREMES BECAUSE HIS OWN SLIDES DISAGREE

His material draws the box wick-to-wick in some places and body-only in others — **inside a single
chart of his own (`Putting_All_Together/0445`)**. The pack's instruction is to record the ambiguity
rather than resolve it, so every block carries `wick_high/low` AND `body_high/low`, `box_bounds`
declares which is in force (`WICK_TO_WICK`, per the stop ruling), and the alternative remains
computable from stored history. *Emitting one extreme would decide a question he left open, by
omission, and no later reader could tell it had been decided.*

## `ob_grade` IS DELIBERATELY INCOMPLETE, AND SAYS SO BY ABSENCE

The 7-point checklist (IM58/IM59) grades an order block's QUALITY and **never touches box grading or
risk %** — two different "Super" scales, which the pack is explicit about. Of its seven, this module
can honestly evaluate only those computable from the objects it is handed. **The rest are OMITTED,
not set to `False`.** *A `False` would say "we checked and it does not hold"; absence says "not
checked", and `B166` is this session's evidence that collapsing those two is how a schema starts
lying.*
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_001_swings import Bar
from app.services.rules.prim_005_breaks import BreakEvent
from app.services.telemetry.records import derived, from_registry
from app.services.telemetry.ny_time import iso_ny

OrderBlockState = Literal["UNTESTED", "TESTED", "FAILED"]
OrderBlockDirection = Literal["DEMAND", "SUPPLY"]

@dataclass(frozen=True)
class _DeclaredWalkBound:
    """An engineering choice of THIS rule's, carrying its own authority.

    Its own type rather than an import of `GATE-029`'s `DeclaredEngineering`, and for that type's
    own stated reason: *"these belong to the rules that carry them, and a project-wide bag of
    declared values detaches the choice from the rule it constrains."*
    """

    name: str
    value: Any
    #: WHO decided. The point of the field is that NO doctrine exists here, so a reader can tell
    #: an engine choice from a trader ruling at a glance.
    authority: str
    source: str
    #: The option NOT taken. A choice with one option written down reads as a fact.
    competing: Any = None
    ratified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            self.name: self.value,
            f"{self.name}_ratified": self.ratified,
            f"{self.name}_authority": self.authority,
            f"{self.name}_source": self.source,
            f"{self.name}_competing": self.competing,
        }


#: Registry value, not ours. `PRIM-007.values.anchor_point_for_stop`, trader ruling round 3.
ANCHOR_POINT_FOR_STOP = "WICK_EXTREME"
#: Registry value. Both extremes are stored regardless; this says which one is IN FORCE.
BOX_BOUNDS_DEFAULT = "WICK_TO_WICK"
#: Registry value. Several same-colour candles before the impulse -> box the LAST one only.
MULTI_CANDLE_POLICY = "LAST_CANDLE_ONLY"
#: Registry value. A wick through the box is not a flip.
FAILURE_TEST = "BODY_CLOSE_THROUGH"

#: [ENGINEERING] How far back the walk may go before giving up.
#:
#: The ruling gives the walk ("step back one candle at a time, stop at the FIRST opposite-colour
#: candle met") and the bound ("rung 1's swing bar"), and says nothing about what to do when the
#: caller supplies no swing bound. Without a cap the walk would run to the start of the series and
#: return a candle from an unrelated leg, which is worse than returning nothing.
DECLARED_WALK_BACK_CAP = _DeclaredWalkBound(
    name="order_block_walk_back_cap",
    value=50,
    authority="ENGINEERING. The ruling bounds the walk at rung 1's swing bar and is SILENT on the "
              "unbounded case. Consulted ONLY when the caller supplies no swing bound; when one is "
              "supplied the swing wins and this is never read.",
    source="PRIM-007 statement, round 3 — 'bound = rung 1's swing bar'; the no-bound case is ours",
    competing="walk to the start of the series (returns a candle from an unrelated leg), or refuse "
              "without a bound (loses every block on a caller that has no rung-1 swing yet)",
)


@dataclass(frozen=True)
class OrderBlock:
    """One order block, in the contract's shape (`TELEMETRY_SCHEMA` `$defs/order_block`)."""

    id: str
    tf: str
    origin_candle_ts: datetime
    direction: OrderBlockDirection
    wick_high: float
    wick_low: float
    body_high: float
    body_low: float
    state: OrderBlockState = "UNTESTED"
    linked_break_id: str | None = None
    #: True when the walk found no opposite-colour candle and fell back to the impulse origin.
    #: NOT a defect and NOT the same object — a reader must be able to exclude these.
    ob_at_origin: bool = False
    #: The merged extreme of the same-colour run, when there was one. LOGGED, NEVER SELECTED:
    #: `MULTI_CANDLE_POLICY` is LAST_CANDLE_ONLY and merging is the alternative he did not take.
    merged_alternative: tuple[float, float] | None = None
    ob_grade: dict[str, bool] = field(default_factory=dict)
    #: Index of the origin candle in the series it was found in. Not emitted.
    bar_index: int = -1

    @property
    def box_high(self) -> float:
        """The box's upper bound UNDER THE DECLARED BOUNDS. Both extremes stay stored."""
        return self.wick_high if BOX_BOUNDS_DEFAULT == "WICK_TO_WICK" else self.body_high

    @property
    def box_low(self) -> float:
        return self.wick_low if BOX_BOUNDS_DEFAULT == "WICK_TO_WICK" else self.body_low

    @property
    def stop_anchor(self) -> float:
        """The price rung 4 anchors on — the WICK extreme, trader ruling round 3.

        DEMAND (a long's block) anchors on the wick LOW; SUPPLY on the wick HIGH. The stop
        itself sits BEYOND this by `stop_beyond_anchor_margin`, which is GATE-027's to apply
        and is deliberately not added here: one declared margin, shared with rung 2, applied at
        the point the stop price is formed.
        """
        return self.wick_low if self.direction == "DEMAND" else self.wick_high

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "tf": self.tf,
            "origin_candle_ts": iso_ny(self.origin_candle_ts),
            "direction": self.direction,
            "wick_high": self.wick_high,
            "wick_low": self.wick_low,
            "body_high": self.body_high,
            "body_low": self.body_low,
            "box_high": self.box_high,
            "box_low": self.box_low,
            "box_bounds": BOX_BOUNDS_DEFAULT,
            "state": self.state,
        }
        if self.linked_break_id is not None:
            out["linked_break_id"] = self.linked_break_id
        if self.ob_at_origin:
            out["ob_at_origin"] = True
        if self.merged_alternative is not None:
            out["merged_alternative"] = list(self.merged_alternative)
        # OMITTED WHEN EMPTY, never emitted as a dict of False. See the module docstring.
        if self.ob_grade:
            out["ob_grade"] = dict(self.ob_grade)
        return out


def _is_opposite_colour(bar: Bar, impulse: Literal["UP", "DOWN"]) -> bool | None:
    """Is this candle the opposite colour to the impulse? `None` when it has no body.

    A DOJI COUNTS AS SAME-COLOUR — his words — so it does not stop the walk. That is not a
    rounding decision: a doji is where a body-less definition would silently pick a different
    candle, and the ruling names the case.

    `None` for a bar carrying no open/close, because a body-less bar cannot answer the question
    and guessing from the wick would detect a different object. PRIM-002 refuses the same way.
    """
    if bar.open is None or bar.close is None:
        return None
    if bar.close == bar.open:
        return False  # doji: same-colour by ruling
    return (bar.close < bar.open) if impulse == "UP" else (bar.close > bar.open)


class OrderBlocks(RuleImplementation):
    """PRIM-007: order blocks, walked back from the break that consumed structure."""

    RULE_ID = "PRIM-007"

    COVERAGE_NOTE = (
        "Implements Salim's round-3 definition, NOT the pre-contract ICT detector at "
        "ict/detector.py:192 -- nothing here imports app.services.ict, and the corpus test "
        "measures the two against each other EXPECTING DISAGREEMENT, because exact agreement "
        "would be evidence this reimplemented ICT rather than the ruling. Both box extremes are "
        "stored because his own slides are split wick-to-wick vs body-only inside a single chart "
        "(0445); the WICK is anchored per the stop ruling and the alternative stays computable. "
        "ob_grade's unevaluable criteria are OMITTED, never set to False -- absence means NOT "
        "CHECKED. The walk-back cap is DECLARED ENGINEERING and is consulted only when the caller "
        "supplies no rung-1 swing bound. State is UNTESTED/TESTED/FAILED with FAILED requiring a "
        "BODY close through: a wick through is not a flip, which is the same fact as the stop "
        "sitting beyond the wick."
    )

    @staticmethod
    def detect(
        bars: Sequence[Bar],
        breaks: Sequence[BreakEvent],
        *,
        tf: str,
        swing_bound_index: int | None = None,
    ) -> list[OrderBlock]:
        """One order block per break, walked back from the candle that did the breaking.

        `swing_bound_index` is rung 1's swing bar — the ruling's bound. When it is None the
        declared cap applies instead, and that substitution is recorded on the block itself by
        nothing at all: it changes only how far the walk looked, never what it means to find a
        candle. What DOES change meaning is finding nothing, which is `ob_at_origin`.
        """
        out: list[OrderBlock] = []
        for event in breaks:
            if event.bar_index is None or event.bar_index < 0 or event.bar_index >= len(bars):
                continue
            impulse: Literal["UP", "DOWN"] = "UP" if event.direction == "UP" else "DOWN"
            block = OrderBlocks._walk_back(
                bars, event, impulse=impulse, tf=tf, swing_bound_index=swing_bound_index
            )
            if block is not None:
                out.append(block)
        return out

    @staticmethod
    def _walk_back(
        bars: Sequence[Bar],
        event: BreakEvent,
        *,
        impulse: Literal["UP", "DOWN"],
        tf: str,
        swing_bound_index: int | None,
    ) -> OrderBlock | None:
        start = event.bar_index
        floor = (
            max(0, swing_bound_index)
            if swing_bound_index is not None
            else max(0, start - int(DECLARED_WALK_BACK_CAP.value))
        )

        origin_index: int | None = None
        run_highs: list[float] = []
        run_lows: list[float] = []
        for index in range(start - 1, floor - 1, -1):
            opposite = _is_opposite_colour(bars[index], impulse)
            if opposite is None:
                # A body-less bar cannot answer, so the walk stops rather than stepping over it
                # and returning a candle chosen by a question nobody could ask.
                break
            if opposite:
                origin_index = index
                break
            run_highs.append(bars[index].high)
            run_lows.append(bars[index].low)

        at_origin = origin_index is None
        if at_origin:
            # No opposite-colour candle inside the bound. The ruling's fallback: use the impulse
            # origin and SAY SO, so a reader can exclude these rather than treat them as found.
            origin_index = max(floor, start - 1)
            if origin_index >= start:
                return None

        bar = bars[origin_index]
        if bar.open is None or bar.close is None:
            return None

        direction: OrderBlockDirection = "DEMAND" if impulse == "UP" else "SUPPLY"
        merged: tuple[float, float] | None = None
        if run_highs and run_lows:
            merged = (max([bar.high, *run_highs]), min([bar.low, *run_lows]))

        return OrderBlock(
            id=f"OB-{tf}-{origin_index}",
            tf=tf,
            origin_candle_ts=bar.time,
            direction=direction,
            wick_high=bar.high,
            wick_low=bar.low,
            body_high=max(bar.open, bar.close),
            body_low=min(bar.open, bar.close),
            state=OrderBlocks.state_of(bars, origin_index, bar, direction),
            linked_break_id=event.id,
            ob_at_origin=at_origin,
            merged_alternative=merged,
            bar_index=origin_index,
        )

    @staticmethod
    def state_of(
        bars: Sequence[Bar], origin_index: int, origin: Bar, direction: OrderBlockDirection
    ) -> OrderBlockState:
        """UNTESTED until price returns into the box; FAILED only on a BODY CLOSE through it.

        > **A wick through is not a flip.** That is the doctrine, and it is the same fact as the
        > stop sitting beyond the wick — a definition that failed on wicks would flip the block on
        > exactly the excursions the stop is placed to survive.

        Order matters: FAILED is checked before TESTED, because the bar that closes through has
        also entered the box, and reporting it as a test would lose the flip.
        """
        if origin.open is None or origin.close is None:
            return "UNTESTED"
        high, low = origin.high, origin.low
        body_high, body_low = max(origin.open, origin.close), min(origin.open, origin.close)
        tested = False
        left_the_box = False
        for later in bars[origin_index + 1:]:
            close = later.close
            if close is not None:
                through = close < low if direction == "DEMAND" else close > high
                if through:
                    return "FAILED"
            inside = later.low <= high and later.high >= low
            if not inside:
                left_the_box = True
                continue
            # A TEST IS A RETURN, NOT THE DEPARTURE. The impulse candle emerges FROM the block
            # and necessarily overlaps it, so counting contact from bar one would mark every
            # block TESTED at birth and make `first_test` meaningless — the block would be
            # "tested" by the move that created it. Price must leave before it can come back.
            if left_the_box:
                tested = True
        return "TESTED" if tested else "UNTESTED"

    @classmethod
    def evaluate(cls, blocks: Sequence[OrderBlock] = ()) -> Any:
        """The inventory, as a rule evaluation. Reports; decides nothing.

        `NOT_APPLICABLE` on an empty inventory is deliberate: PASS would be a verdict about a
        chart with no order blocks, and a primitive that reports PASS for "nothing found" is the
        collapse this cluster refuses everywhere else.
        """
        values: dict[str, Any] = {
            "order_blocks": [b.as_dict() for b in blocks],
            "order_blocks_found": len(blocks),
            "anchor_point_for_stop": ANCHOR_POINT_FOR_STOP,
            "box_bounds_default": BOX_BOUNDS_DEFAULT,
            "multi_candle_policy": MULTI_CANDLE_POLICY,
            "failure_test": FAILURE_TEST,
            "walk_back_cap": DECLARED_WALK_BACK_CAP.as_dict(),
            "at_origin_count": sum(1 for b in blocks if b.ob_at_origin),
            "failed_count": sum(1 for b in blocks if b.state == "FAILED"),
        }
        provenance = {
            "order_blocks": derived("PRIM-007's walk back from each break's candle"),
            "order_blocks_found": derived("inventory size — a denominator, published always"),
            "anchor_point_for_stop": from_registry("PRIM-007", "values.anchor_point_for_stop"),
            "box_bounds_default": from_registry("PRIM-007", "values.box_bounds_default"),
            "multi_candle_policy": from_registry("PRIM-007", "values.multi_candle_policy"),
            "failure_test": from_registry("PRIM-007", "values.failure_test"),
            "walk_back_cap": derived("ENGINEERING — declared, unratified, competing recorded"),
            "at_origin_count": derived("blocks where NO opposite-colour candle was found"),
            "failed_count": derived("body-closed-through — PRIM-006 Breaker candidates"),
        }
        return cls.evaluation(
            "NOT_APPLICABLE" if not blocks else "PASS",
            values=values,
            value_provenance=provenance,
        )
