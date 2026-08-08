"""GRADE-001 — structure box construction, and GRADE-009's choice of WHICH box (M4).

    A structure box exists only once a break event (MSB or BOS) has printed. Construct it
    from the price of the swing that was broken back to that swing, ending at the breaking
    candle […] The box's extreme (low for an up-leg, high for a down-leg) IS the Strong Low /
    Strong High. […] No box ⇒ no box grade ⇒ the risk matrix cannot be looked up and no trade
    may be sized.

THE LAST SENTENCE IS THE LOAD-BEARING ONE
Everything about position size runs through this object. The box grade keys the 3×3 matrix,
so a box built on the wrong swing does not produce a slightly different box — it produces a
different risk percentage on a real order. That is why construction is its own rule with its
own id, separate from the grading, and why "no box" is a first-class answer rather than a
default grade.

WHY THE BOX IS BUILT FROM THE BREAK, NOT FROM THE PULLBACK
A box cannot exist before the break that creates it. The break names the swing it consumed
(PRIM-005 carries `consumed_swing_id` for exactly this), and that swing plus the breaking
candle bound the box in time. The opposite extreme inside that span is the box's own extreme,
and the doctrine says plainly what it is: the Strong Low for an up-leg, the Strong High for a
down-leg. That is the same object PRIM-001 marks STRONG when a break confirms it, reached
from the other direction — the two must agree, and a test here pins that.

EITHER BREAK TYPE MAY CREATE A BOX
"the slide labels the box-birth break 'MSB / BoS'". So no filtering on break type at
construction; `birth_break_type` is recorded and the graders may read it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_001_swings import Bar, Swing
from app.services.telemetry.ny_time import iso_ny

BoxDirection = Literal["UP", "DOWN"]
BirthBreak = Literal["MSB", "BOS"]
BoxScope = Literal["ENTRY_BOX_EXEC_TF", "DESTINATION_BOX"]


@dataclass
class StructureBox:
    """One structure box, in the contract's shape."""

    id: str
    tf: str
    direction: BoxDirection
    swing_bar: datetime
    break_bar: datetime
    box_high: float
    box_low: float
    strong_swing_price: float
    birth_break_type: BirthBreak
    #: Index span. Not emitted — the graders need it to scan only inside the box.
    swing_index: int = -1
    break_index: int = -1
    consumed_swing_id: str = ""
    birth_break_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tf": self.tf,
            "direction": self.direction,
            "swing_bar": iso_ny(self.swing_bar),
            "break_bar": iso_ny(self.break_bar),
            "box_high": self.box_high,
            "box_low": self.box_low,
            "strong_swing_price": self.strong_swing_price,
            "birth_break_type": self.birth_break_type,
        }


class StructureBoxes(RuleImplementation):
    """GRADE-001: the box, or nothing."""

    RULE_ID = "GRADE-001"

    @staticmethod
    def construct(
        bars: Sequence[Bar],
        swings: Sequence[Swing],
        breaks: Sequence[Any],
        *,
        tf: str,
    ) -> list[StructureBox]:
        """One box per break, bounded by the consumed swing and the breaking candle.

        Returns an empty list when no break has printed. That is the contract's "no box"
        state and it must stay distinguishable from a box that graded badly: one means the
        engine may not size a trade at all, the other means it may size a small one.
        """
        by_id = {s.id: s for s in swings}
        boxes: list[StructureBox] = []

        for brk in breaks:
            swing = by_id.get(getattr(brk, "consumed_swing_id", None))
            break_index = getattr(brk, "bar_index", -1)
            direction = getattr(brk, "direction", None)
            if swing is None or break_index < 0 or direction not in ("UP", "DOWN"):
                continue
            if swing.bar_index < 0 or swing.bar_index >= break_index:
                # A swing cannot be consumed by a candle at or before its own. PRIM-005
                # already enforces this; re-checking here keeps the box honest if it is
                # ever handed breaks from another source.
                continue

            span = bars[swing.bar_index:break_index + 1]
            if not span:
                continue

            if direction == "UP":
                # Up-leg. The broken swing high CAPS the box — the breaking candle's
                # excursion beyond it is the break, not part of the box, and folding it in
                # would move box_high on every setup by however far the break ran.
                # The deepest low inside the span is the Strong Low the push started from.
                box_high = swing.price
                box_low = min(b.low for b in span)
                strong = box_low
            else:
                box_low = swing.price
                box_high = max(b.high for b in span)
                strong = box_high

            boxes.append(StructureBox(
                id=f"box-{tf}-{swing.id}-{break_index}",
                tf=tf,
                direction=direction,
                swing_bar=bars[swing.bar_index].time,
                break_bar=bars[break_index].time,
                box_high=box_high,
                box_low=box_low,
                strong_swing_price=strong,
                birth_break_type=getattr(brk, "type", "BOS"),
                swing_index=swing.bar_index,
                break_index=break_index,
                consumed_swing_id=swing.id,
                birth_break_id=getattr(brk, "id", ""),
            ))
        return boxes

    @staticmethod
    def latest(boxes: Sequence[StructureBox], *, as_of_index: int) -> StructureBox | None:
        """The most recent box whose break had already printed at `as_of_index`.

        The look-ahead guard for everything downstream: a box whose birth break prints on or
        after the decision bar has not happened yet, and grading it is GRADE-007's early
        entry.
        """
        eligible = [b for b in boxes if 0 <= b.break_index < as_of_index]
        return max(eligible, key=lambda b: b.break_index) if eligible else None


class BoxScopeDeclaration(RuleImplementation):
    """GRADE-009: which box the grade refers to — declared, not assumed.

        The grade that keys the risk table is not bound to a specific box anywhere in the
        source. […] The engine must pick one — the entry box on the execution timeframe is
        the reading most consistent with 023 Step 6 — declare the choice in telemetry, and
        flag it as unratified rather than silently assuming it.

    This class exists to make the choice a recorded artefact rather than an implicit
    property of whichever box the code happened to reach for. It carries no geometry.
    """

    RULE_ID = "GRADE-009"

    #: The declared reading. Also stamped into `DeclaredParameters.box_scope`, which is where
    #: conformance reads it from; this constant is the single place it is decided.
    SCOPE: BoxScope = "ENTRY_BOX_EXEC_TF"

    #: The trader has not ratified this. It must stay visible as an engine choice, because
    #: the alternative reading (the box at the destination) would key a different matrix cell
    #: and therefore a different position size on the same setup.
    RATIFIED = False

    COVERAGE_NOTE = (
        "A declared choice, not a detector: box_scope = ENTRY_BOX_EXEC_TF, flagged "
        "unratified. The source leaves it open in three separate places and never says "
        "whether the grade means the entry box or the destination box."
    )

    @classmethod
    def evaluation(cls, **_: Any):  # type: ignore[override]
        return super().evaluation(
            "FLAG" if not cls.RATIFIED else "PASS",
            values={"box_scope": cls.SCOPE, "ratified_by_trader": cls.RATIFIED},
            value_provenance={
                "box_scope": {"source": "DECLARED_PARAMETER", "field": "box_scope"},
                "ratified_by_trader": {"source": "DECLARED_PARAMETER", "field": "box_scope"},
            },
        )
