"""PRIM-002 — the imbalance inventory, with fill state (M3).

    Detect all four named inefficiency types and carry each with its fill state. Types: fair
    value gap ("classic imbalances"); volume imbalance ("the empty space between candle
    bodies with only wicks"); gap ("the large voids between candlesticks… gaps and volume
    imbalances are the same thing the only difference is the wicks"); BPR — the boxed OVERLAP
    of a minimum of two opposite-direction imbalances, extended right, with ≥3 overlapping
    gaps = SUPER BPR.

WHY THIS PRIMITIVE DECIDES WHETHER THE ENGINE IS ON-DOCTRINE AT ALL
ENTRY-001 is a precedence rule, not a preference: "we always take entries from imbalances no
matter what, we do not use OBs or BBs to enter". Every admissible entry object in the whole
contract comes out of this inventory. The engine we have today detects FVGs only, so three of
the four documented inefficiency types are entries the strategy permits and ours cannot see.

THE ONE LINE THAT SEPARATES A GAP FROM A VOLUME IMBALANCE
"gaps and volume imbalances are the same thing the only difference is the wicks." So:

    bodies apart, wicks apart   → GAP
    bodies apart, wicks overlap → VOLUME_IMBALANCE

That is the entire discriminator, and it is why `Bar` had to grow a body. Detecting these off
wicks alone would collapse the two classes into one and silently drop a documented type.

FILL STATE, AND THE ONE MAPPING WE HAD TO CHOOSE
The contract's fill states come from the image captions and the enum is fixed at four:
UNFILLED · HALF_FILLED · FULLY_FILLED · FULLY_FILLED_AND_VIOLATED. There is no PARTIAL. So
any penetration short of the far edge maps to HALF_FILLED, which is the contract's only
partial state — and `fill_fraction` carries the measured number alongside it, so a later
ruling that cuts the boundary somewhere else can be applied to stored history instead of
invalidating it. The mapping is an engine choice; the measurement is not.

"An imbalance stays extremely reactive until it is fully filled", so the fraction is the
field downstream rules should read, not the label.

WHAT IS DELIBERATELY NOT DECIDED HERE
`is_momentum_imbalance` needs a size threshold — "the large gaps left behind by impulsive
moves". The doctrine fixes no number. It is therefore left **unset** unless the caller passes
a declared `momentum_min_width`, exactly as PRIM-005 leaves `fake_msb` unset for OPEN
GRADE-008. A False would be a claim.

`purpose_verdict` / `target_cleared_at_failure` / `mutated_to_sr_flip` are GRADE-038 and
PRIM-006, not this rule. They are carried on the dataclass so the record can be completed by
the rule that owns them, and are never populated here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_001_swings import Bar
from app.services.telemetry.ny_time import iso_ny

ImbalanceType = Literal["FVG", "VOLUME_IMBALANCE", "GAP", "BPR", "SUPER_BPR"]
FillState = Literal["UNFILLED", "HALF_FILLED", "FULLY_FILLED", "FULLY_FILLED_AND_VIOLATED"]
Direction = Literal["BULLISH", "BEARISH"]

#: ≥ this many overlapping imbalances promotes a BPR to a SUPER BPR. From the statement
#: ("a minimum of two" for BPR, "≥3 overlapping gaps = SUPER BPR"), not an engine choice.
SUPER_BPR_MIN_OVERLAP = 3


@dataclass
class Imbalance:
    """One inefficiency, in the contract's shape."""

    id: str
    tf: str
    bar_time: datetime
    price_high: float
    price_low: float
    type: ImbalanceType
    direction: Direction
    fill_state: FillState = "UNFILLED"
    test_count: int = 0
    #: Measured penetration as a fraction of the band's width. Carried because the four-state
    #: enum cannot express it and every downstream reactivity judgement wants the number.
    fill_fraction: float = 0.0
    #: None means "not assessed" — no declared momentum threshold was supplied.
    is_momentum_imbalance: bool | None = None
    #: GRADE-038 territory. Owned by that rule; never set here.
    purpose_verdict: Literal["PASS", "FAIL", "PENDING"] | None = None
    target_cleared_at_failure: bool | None = None
    #: PRIM-006 territory.
    mutated_to_sr_flip: bool | None = None
    #: Index of the last bar forming the imbalance. Not emitted — used to bound the fill scan.
    formed_index: int = -1
    #: Ids of the imbalances a BPR was cut from. Not emitted; used by tests and by GRADE-038.
    component_ids: list[str] = field(default_factory=list)

    @property
    def width(self) -> float:
        return self.price_high - self.price_low

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "tf": self.tf,
            "bar_time": iso_ny(self.bar_time),
            "price_high": self.price_high,
            "price_low": self.price_low,
            "type": self.type,
            "fill_state": self.fill_state,
            "test_count": self.test_count,
            "direction": self.direction,
            "fill_fraction": round(self.fill_fraction, 6),
        }
        for key, value in (
            ("is_momentum_imbalance", self.is_momentum_imbalance),
            ("purpose_verdict", self.purpose_verdict),
            ("target_cleared_at_failure", self.target_cleared_at_failure),
            ("mutated_to_sr_flip", self.mutated_to_sr_flip),
        ):
            if value is not None:
                out[key] = value
        return out


class ImbalanceInventory(RuleImplementation):
    """PRIM-002: the four inefficiency types, BPR overlaps, and fill state."""

    RULE_ID = "PRIM-002"

    COVERAGE_NOTE = (
        "FVG, VOLUME_IMBALANCE, GAP, BPR and SUPER_BPR are detected with fill state and "
        "test count. `is_momentum_imbalance` is only assessed when the caller supplies a "
        "declared momentum_min_width — the doctrine fixes no size for 'large'."
    )

    # -- detection ---------------------------------------------------------------------
    @staticmethod
    def detect(
        bars: Sequence[Bar],
        *,
        tf: str,
        momentum_min_width: float | None = None,
    ) -> list[Imbalance]:
        """The full inventory over `bars`, fill state resolved against later price action.

        Ordered by formation. BPRs are appended after the simple types because a BPR is cut
        from them and cannot exist before they do.
        """
        simple = (
            ImbalanceInventory._fvgs(bars, tf=tf)
            + ImbalanceInventory._two_bar(bars, tf=tf)
        )
        simple.sort(key=lambda imb: (imb.formed_index, imb.id))
        found = simple + ImbalanceInventory._bprs(simple, bars, tf=tf)

        for imb in found:
            ImbalanceInventory._resolve_fill(imb, bars)
            if momentum_min_width is not None:
                # "the large gaps left behind by impulsive moves and NEVER FILLED" — both
                # halves are required, so a filled gap is not a momentum imbalance however
                # wide it was.
                imb.is_momentum_imbalance = (
                    imb.width >= momentum_min_width and imb.fill_state == "UNFILLED"
                )
        return found

    @staticmethod
    def _fvgs(bars: Sequence[Bar], *, tf: str) -> list[Imbalance]:
        """Classic three-bar imbalance: bar i-1 and bar i+1 do not overlap at all."""
        out: list[Imbalance] = []
        for i in range(1, len(bars) - 1):
            before, after = bars[i - 1], bars[i + 1]
            if after.low > before.high:
                out.append(Imbalance(
                    id=f"imb-{tf}-{i}-FVG-B", tf=tf, bar_time=bars[i + 1].time,
                    price_high=after.low, price_low=before.high,
                    type="FVG", direction="BULLISH", formed_index=i + 1,
                ))
            elif after.high < before.low:
                out.append(Imbalance(
                    id=f"imb-{tf}-{i}-FVG-S", tf=tf, bar_time=bars[i + 1].time,
                    price_high=before.low, price_low=after.high,
                    type="FVG", direction="BEARISH", formed_index=i + 1,
                ))
        return out

    @staticmethod
    def _two_bar(bars: Sequence[Bar], *, tf: str) -> list[Imbalance]:
        """GAP and VOLUME_IMBALANCE — separated only by whether the WICKS overlap."""
        out: list[Imbalance] = []
        for i in range(1, len(bars)):
            prev, cur = bars[i - 1], bars[i]

            if cur.body_low > prev.body_high:                    # bodies apart, upward
                wicks_apart = cur.low > prev.high
                out.append(Imbalance(
                    id=f"imb-{tf}-{i}-{'GAP' if wicks_apart else 'VI'}-B", tf=tf,
                    bar_time=cur.time,
                    price_high=cur.low if wicks_apart else cur.body_low,
                    price_low=prev.high if wicks_apart else prev.body_high,
                    type="GAP" if wicks_apart else "VOLUME_IMBALANCE",
                    direction="BULLISH", formed_index=i,
                ))
            elif cur.body_high < prev.body_low:                  # bodies apart, downward
                wicks_apart = cur.high < prev.low
                out.append(Imbalance(
                    id=f"imb-{tf}-{i}-{'GAP' if wicks_apart else 'VI'}-S", tf=tf,
                    bar_time=cur.time,
                    price_high=prev.low if wicks_apart else prev.body_low,
                    price_low=cur.high if wicks_apart else cur.body_high,
                    type="GAP" if wicks_apart else "VOLUME_IMBALANCE",
                    direction="BEARISH", formed_index=i,
                ))
        return out

    @staticmethod
    def _bprs(simple: Sequence[Imbalance], bars: Sequence[Bar], *, tf: str) -> list[Imbalance]:
        """The boxed OVERLAP of at least two OPPOSITE-direction imbalances.

        Opposite direction is the whole point — a BPR is where a buy-side and a sell-side
        inefficiency occupy the same prices, so the band is contested from both ends.
        Overlapping two same-direction gaps is just a wider gap and is not a BPR.

        The promotion to SUPER_BPR counts every imbalance covering the intersection, not
        just the pair that produced it: "≥3 overlapping gaps = SUPER BPR".
        """
        out: list[Imbalance] = []
        seen: set[tuple[float, float]] = set()

        for a_idx, a in enumerate(simple):
            for b in simple[a_idx + 1:]:
                if a.direction == b.direction:
                    continue
                lo = max(a.price_low, b.price_low)
                hi = min(a.price_high, b.price_high)
                if hi <= lo:
                    continue
                if (lo, hi) in seen:
                    continue
                seen.add((lo, hi))

                covering = [
                    imb for imb in simple
                    if imb.price_low <= lo and imb.price_high >= hi
                ]
                is_super = len(covering) >= SUPER_BPR_MIN_OVERLAP
                # "extended right": the BPR exists from the moment its LAST component
                # printed, and the later component is what dates it.
                formed = max(a.formed_index, b.formed_index)
                out.append(Imbalance(
                    id=f"imb-{tf}-{formed}-{'SBPR' if is_super else 'BPR'}-"
                       f"{len(out)}",
                    tf=tf, bar_time=bars[formed].time,
                    price_high=hi, price_low=lo,
                    type="SUPER_BPR" if is_super else "BPR",
                    # A BPR is contested from both sides. The direction recorded is that of
                    # the LATER component — the side that most recently claimed the band.
                    direction=(a if a.formed_index >= b.formed_index else b).direction,
                    formed_index=formed,
                    component_ids=sorted(imb.id for imb in covering) if is_super
                    else sorted([a.id, b.id]),
                ))
        return out

    # -- fill state --------------------------------------------------------------------
    @staticmethod
    def _resolve_fill(imb: Imbalance, bars: Sequence[Bar]) -> None:
        """Walk the bars after formation and record how far price came back into the band.

        Direction matters. A bullish imbalance was left behind by an up-move, so it fills
        from its TOP edge downward; a bearish one fills from its bottom edge upward. Measuring
        both from the same edge would report a bullish gap as fully filled the instant price
        traded anywhere near it.
        """
        width = imb.width
        if width <= 0:
            imb.fill_state = "FULLY_FILLED"
            imb.fill_fraction = 1.0
            return

        deepest = 0.0
        violated = False
        inside = False
        tests = 0

        for bar in bars[imb.formed_index + 1:]:
            if imb.direction == "BULLISH":
                reach = imb.price_high - bar.low
                closed_beyond = bar.close is not None and bar.close < imb.price_low
                touching = bar.low <= imb.price_high and bar.high >= imb.price_low
            else:
                reach = bar.high - imb.price_low
                closed_beyond = bar.close is not None and bar.close > imb.price_high
                touching = bar.high >= imb.price_low and bar.low <= imb.price_high

            deepest = max(deepest, reach)
            violated = violated or closed_beyond

            # A test is an ENTRY into the band, not a bar spent inside it — otherwise a slow
            # grind through the zone would count as thirty tests. "First-vs-second test" is
            # about how many times price came back.
            if touching and not inside:
                tests += 1
            inside = touching

        imb.fill_fraction = max(0.0, min(deepest / width, 1.0))
        imb.test_count = tests

        if violated:
            imb.fill_state = "FULLY_FILLED_AND_VIOLATED"
        elif deepest >= width:
            imb.fill_state = "FULLY_FILLED"
        elif deepest > 0:
            imb.fill_state = "HALF_FILLED"
        else:
            imb.fill_state = "UNFILLED"
