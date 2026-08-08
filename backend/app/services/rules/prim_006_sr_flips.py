"""PRIM-006 — support/resistance flips are ZONES, never lines (M3).

    A support/resistance flip is a level or zone broken one way then retested from the other
    side and holding — break → retest → go. The images are explicit that these are ZONES, not
    thin lines, and that a stop placed at a flip zone must cover the WHOLE zone.

WHY "NEVER A LINE" IS A RISK RULE, NOT A DRAWING PREFERENCE
A flip zone is a stop anchor. Modelling it as a single price puts the stop at the edge of the
area that is actually defending, so the stop sits inside the noise it was meant to survive —
and because the stop distance sets position size, a zone collapsed to a line does not produce
a slightly wrong stop, it produces a systematically oversized position. Hence `price_high` and
`price_low` are both required by the schema and there is no single-price constructor here.

THE ZONE IS MEASURED, NOT PARAMETERISED
The obvious way to build a zone is to pick a width — 0.1%, half an ATR — and wrap the level in
it. That width would be invented; nothing in the corpus states one. So the zone is bounded by
two prices the market printed: the broken level, and the extreme the retest actually reached
before turning away. A zone built that way is exactly as wide as the defence that formed it,
and needs no threshold at all.

WHAT COUNTS AS A RETEST THAT HELD
Price returns to the level from the other side and does not CLOSE back through it. The close
is what makes this decidable without a tolerance: a wick back through the old level is the
retest, and a close back through means the flip failed and the level went back to being what
it was. This is ENTRY-003's body-close convention for break validity — which TARGET-005
explicitly leaves untouched when it overrides the *clearance* rule.

TWO ORIGINS, BECAUSE THE CONTRACT NAMES TWO MECHANISMS
  BROKEN_LEVEL     — a swing level consumed by a break, then defended from the far side.
  FAILED_IMBALANCE — GRADE-038: "FAILED IMBALANCES can turn into Support or Resistance areas!"
                     The zone is the imbalance's own band, which is already a zone.

The purpose test that decides whether an imbalance FAILED is GRADE-038's, not this rule's. So
`from_failed_imbalances` takes imbalances already carrying `purpose_verdict == "FAIL"` and
never computes the verdict itself — implementing another rule's judgement inside this one is
how a single id ends up owning two behaviours, which `base.py` exists to prevent.

THE SAME OBJECT APPEARS IN TWO ROLES
GATE-038 lists S/R flip areas as one of the three amplifier classes, and amplifiers "never
create a trade by themselves". A flip zone in this inventory is therefore evidence, never a
trigger — nothing here may be read as an entry reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_001_swings import Bar, Swing
from app.services.rules.prim_002_imbalances import Imbalance

FlipOrigin = Literal["FAILED_IMBALANCE", "BROKEN_LEVEL"]


@dataclass
class SRFlip:
    """A flip zone, in the contract's shape. Two prices, always."""

    id: str
    tf: str
    price_high: float
    price_low: float
    origin: FlipOrigin
    touch_count: int = 0
    quality_factors: list[str] = field(default_factory=list)
    #: The level the zone formed around, and the break that made it. Not emitted.
    level: float = 0.0
    source_id: str | None = None

    def __post_init__(self) -> None:
        if self.price_high < self.price_low:
            raise ValueError(
                f"{self.id}: price_high {self.price_high} is below price_low "
                f"{self.price_low} — a flip zone is an interval, and an inverted one would "
                "silently become an empty stop cushion."
            )

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "tf": self.tf,
            "price_high": self.price_high,
            "price_low": self.price_low,
            "origin": self.origin,
            "touch_count": self.touch_count,
        }
        if self.quality_factors:
            out["quality_factors"] = list(self.quality_factors)
        return out


class SRFlipZones(RuleImplementation):
    """PRIM-006: flip zones from broken levels and from failed imbalances."""

    RULE_ID = "PRIM-006"

    COVERAGE_NOTE = (
        "Both documented origins are built: BROKEN_LEVEL (break → retest → hold, zone bounded "
        "by the level and the retest extreme) and FAILED_IMBALANCE (GRADE-038 mutation). The "
        "reactive-level test — 'check if there are a lot of reactions to that price level' — "
        "is served by touch_count; no threshold on it is applied, because none exists."
    )

    # -- broken levels -----------------------------------------------------------------
    @staticmethod
    def from_broken_levels(
        bars: Sequence[Bar],
        swings: Sequence[Swing],
        breaks: Sequence[Any],
        *,
        tf: str,
    ) -> list[SRFlip]:
        """break → retest → go, one zone per level that was broken and then defended.

        The side flips with the break. A swing HIGH taken out by an upward break becomes
        SUPPORT: price must now come back DOWN to it and hold above. The mirror for a low.
        """
        by_id = {s.id: s for s in swings}
        flips: list[SRFlip] = []

        for brk in breaks:
            swing = by_id.get(getattr(brk, "consumed_swing_id", None))
            break_index = getattr(brk, "bar_index", -1)
            if swing is None or break_index < 0:
                continue

            level = swing.price
            # After an UP break of a high, the level defends from below.
            defends_from_below = getattr(brk, "direction", None) == "UP"

            touches = 0
            extreme: float | None = None
            failed = False

            for bar in bars[break_index + 1:]:
                if defends_from_below:
                    returned = bar.low <= level
                    broke_back = bar.close is not None and bar.close < level
                else:
                    returned = bar.high >= level
                    broke_back = bar.close is not None and bar.close > level

                if broke_back:
                    # The flip did not hold. The level is not a flip zone; it is just a level
                    # again, and recording it as one would put a stop behind a wall that is
                    # no longer there.
                    failed = True
                    break
                if returned:
                    touches += 1
                    reach = bar.low if defends_from_below else bar.high
                    extreme = reach if extreme is None else (
                        min(extreme, reach) if defends_from_below else max(extreme, reach)
                    )

            if failed or touches == 0 or extreme is None:
                continue

            flips.append(SRFlip(
                id=f"flip-{tf}-{swing.id}-{break_index}", tf=tf,
                price_high=max(level, extreme), price_low=min(level, extreme),
                origin="BROKEN_LEVEL", touch_count=touches, level=level,
                source_id=swing.id,
                quality_factors=(["MULTI_TOUCH"] if touches > 1 else []),
            ))
        return flips

    # -- failed imbalances -------------------------------------------------------------
    @staticmethod
    def from_failed_imbalances(
        imbalances: Sequence[Imbalance], bars: Sequence[Bar], *, tf: str
    ) -> list[SRFlip]:
        """GRADE-038's mutation: "FAILED IMBALANCES can turn into Support or Resistance areas!"

        The zone is the imbalance's own band — already two prices, so nothing has to be
        invented to widen it. Only imbalances the purpose test has already FAILED are
        considered; `purpose_verdict` is GRADE-038's field and is never set here.

        `mutated_to_sr_flip` is written back onto the imbalance, because the schema carries
        that flag on the imbalance and an auditor reading the two inventories should not have
        to join them by price to discover they are the same object.
        """
        flips: list[SRFlip] = []
        for imb in imbalances:
            if imb.purpose_verdict != "FAIL":
                continue

            # A failed bullish imbalance was overrun downward, so the band now caps price from
            # above; the mirror for a bearish one. Either way the defence is the whole band.
            touches = 0
            inside = False
            for bar in bars[imb.formed_index + 1:]:
                touching = bar.high >= imb.price_low and bar.low <= imb.price_high
                if touching and not inside:
                    touches += 1
                inside = touching

            imb.mutated_to_sr_flip = True
            flips.append(SRFlip(
                id=f"flip-{tf}-{imb.id}", tf=tf,
                price_high=imb.price_high, price_low=imb.price_low,
                origin="FAILED_IMBALANCE", touch_count=touches, level=imb.price_low,
                source_id=imb.id,
                quality_factors=(["MULTI_TOUCH"] if touches > 1 else []),
            ))
        return flips

    @staticmethod
    def detect(
        bars: Sequence[Bar],
        swings: Sequence[Swing],
        breaks: Sequence[Any],
        imbalances: Sequence[Imbalance] = (),
        *,
        tf: str,
    ) -> list[SRFlip]:
        """Both origins, in one call."""
        return (
            SRFlipZones.from_broken_levels(bars, swings, breaks, tf=tf)
            + SRFlipZones.from_failed_imbalances(imbalances, bars, tf=tf)
        )
