"""PRIM-005 — break events, MSB vs BOS discriminated by GEOMETRY (M3).

    Discriminator, from the images: SAME candle quality, DIFFERENT location — an MSB breaks
    the last swing AGAINST the trend; a BOS breaks the prior swing WITH it. Do NOT
    disambiguate by acronym expansion: MSB now expands to "Market Structure Break" and BOS
    is glossed "break of structure", so the two expansions have collapsed and only the
    geometry separates them.

THE WHOLE RULE IS THAT ONE WORD: LOCATION
The candles look the same. What separates the two is whether the break runs with the
prevailing leg or against it. An implementation that reaches for candle size, expansion, or
the label in a screenshot is not implementing this rule — it is implementing a resemblance
to it, and the registry says so explicitly.

    MSB  — breaks the last swing AGAINST the trend  → the trend is being challenged
    BOS  — breaks the prior swing WITH the trend    → the trend is being confirmed

DIRECTION HAS TO COME FROM SOMEWHERE, AND IT COMES FROM THE BREAKS
Trend is not an input we are given; it is the running consequence of previous breaks. So
this walks the series forward, carrying the leg direction, and each break both classifies
against the current direction and updates it. That ordering is why breaks cannot be
classified independently of one another, and why a break detected out of order would
mislabel every break after it.

The first break has no prevailing direction. It is emitted as a BOS — a trend cannot be
"challenged" before one exists — and flagged with `validity_criteria_met: ["FIRST_LEG"]`
so the assumption is visible in telemetry rather than buried here.

SCALE, AND WHAT IS NOT DECIDED HERE
`scale ∈ {MAIN, INTERNAL, MICRO}` distinguishes the HTF break from substructure and from
the reversal-feasibility trigger. Scale is a property of *which timeframe you are looking
at*, not of the geometry, so it is passed in by the caller that knows which series this is.
Guessing it from bar counts would be inventing doctrine.

`fake_msb` is GRADE-008, which is OPEN — the trader declined to fix the detection windows.
It is therefore left unset here rather than approximated. A False would be a claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_001_swings import Bar, Swing
from app.services.telemetry.ny_time import iso_ny

BreakType = Literal["MSB", "BOS"]
BreakScale = Literal["MAIN", "INTERNAL", "MICRO"]
Direction = Literal["UP", "DOWN"]


@dataclass
class BreakEvent:
    """A structure break, in the contract's shape."""

    id: str
    tf: str
    bar_time: datetime
    type: BreakType
    scale: BreakScale
    consumed_swing_id: str
    break_price: float
    direction: Direction | None = None
    valid: bool | None = None
    validity_criteria_met: list[str] | None = None
    #: GRADE-008 is OPEN. Left None — a False would be a claim we cannot support.
    fake_msb: bool | None = None
    #: Index of the bar that did the breaking. Not emitted — used by PRIM-001 to find the
    #: swing this break confirmed, which is the one price moved AWAY from.
    bar_index: int = -1

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "tf": self.tf,
            "bar_time": iso_ny(self.bar_time),
            "type": self.type,
            "scale": self.scale,
            "consumed_swing_id": self.consumed_swing_id,
            "break_price": self.break_price,
        }
        for key, value in (
            ("direction", self.direction),
            ("valid", self.valid),
            ("validity_criteria_met", self.validity_criteria_met),
            ("fake_msb", self.fake_msb),
        ):
            if value is not None:
                out[key] = value
        return out


class BreakEvents(RuleImplementation):
    """PRIM-005: break events, typed by geometry."""

    RULE_ID = "PRIM-005"

    @staticmethod
    def detect(
        bars: Sequence[Bar],
        swings: Sequence[Swing],
        *,
        tf: str,
        scale: BreakScale = "MAIN",
    ) -> list[BreakEvent]:
        """Walk the bars, emitting a break each time a swing's level is consumed.

        A swing is consumed when a LATER bar trades beyond it — above a swing high, below a
        swing low. Only bars strictly after the swing's own bar are considered, which is
        what keeps this causal: a swing cannot be broken by the candle that formed it, and
        allowing it would let a single bar both create and consume its own level.

        Each swing is consumed at most once. The second run through a level is a different
        object — a re-test, or an engineered-liquidity build (PRIM-004) — and emitting it as
        another break would double-count the structure.
        """
        ordered = sorted(swings, key=lambda s: s.bar_index)
        consumed: set[str] = set()
        breaks: list[BreakEvent] = []
        direction: Direction | None = None

        for i, bar in enumerate(bars):
            for swing in ordered:
                if swing.id in consumed or swing.bar_index >= i:
                    continue

                if swing.kind == "HIGH" and bar.high > swing.price:
                    broke: Direction = "UP"
                    price = swing.price
                elif swing.kind == "LOW" and bar.low < swing.price:
                    broke = "DOWN"
                    price = swing.price
                else:
                    continue

                # THE RULE. Same candle, different location: with the leg or against it.
                if direction is None:
                    break_type: BreakType = "BOS"
                    criteria = ["FIRST_LEG"]
                elif broke == direction:
                    break_type = "BOS"
                    criteria = ["WITH_TREND"]
                else:
                    break_type = "MSB"
                    criteria = ["AGAINST_TREND"]

                consumed.add(swing.id)
                breaks.append(
                    BreakEvent(
                        id=f"brk-{tf}-{i}-{swing.id}",
                        tf=tf,
                        bar_time=bar.time,
                        type=break_type,
                        scale=scale,
                        consumed_swing_id=swing.id,
                        break_price=price,
                        direction=broke,
                        validity_criteria_met=criteria,
                        bar_index=i,
                    )
                )
                # The break sets the leg for everything after it.
                direction = broke

        return breaks
