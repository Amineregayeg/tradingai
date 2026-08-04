"""PRIM-001 — the swing-point series, with strong/weak classification (M3).

    Detect the swing-point series per timeframe; these are the atoms of the whole system —
    "Liquidity starts with swing points like swing highs and swing lows where the stop
    losses are placed". […] Every detected swing must be emitted with its price, bar,
    timeframe and strong/weak classification, because every liquidity level, structure box
    and stop anchor downstream is derived from one.

WHY THIS IS THE FIRST PRIMITIVE
Everything else in the contract is defined in terms of swings. Liquidity pools are swing
levels; structure boxes are bounded by them; every stop anchor in the ladder is one. A swing
series that is subtly wrong does not produce a wrong swing — it produces a wrong risk
percentage, because the box grade it feeds keys the 3x3 matrix.

STRENGTH IS DEFINED BY BREAKS, NOT BY SHAPE
This is the part most easily got wrong. The doctrine does not say a "strong low" is a deeper
low; it says strength is *conferred by a break*:

    "Every single time a new break of structure happens in the trend direction, we just
    create a strong low and a possible weak high… When the buyers push the price and take
    out a weak high, a strong low is confirmed"

So classification cannot be computed from the swing alone. It requires the break series
(PRIM-005), which is why `classify_strength` takes breaks as an input and why an unbroken
series is legitimately all UNCONFIRMED rather than defaulting to WEAK. Defaulting would
manufacture confirmation that the market never gave.

WHAT THE FRACTAL WINDOW IS, AND IS NOT
A swing needs *some* window to be identifiable at all, and the doctrine fixes none. It is
therefore an engine choice, declared and stamped, not a number attributed to the trader.
It is deliberately NOT called a "candle count" gate: the banned-input list rejects candle
counts as a *decision* input — using bars to identify a fractal is arithmetic, not doctrine.

WHAT NO TEST HERE CAN TELL YOU
Whether these are the swings the trader would have marked. Nothing in the conformance suite
tests detector quality, and a systematically wrong swing series scores 100% CONFORMANT while
mis-grading every box. That gap closes only with readiness gate 7 — a human replaying
records against the charts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.telemetry.ny_time import iso_ny

SwingKind = Literal["HIGH", "LOW"]
Strength = Literal["STRONG", "WEAK", "UNCONFIRMED"]

#: Bars either side that a swing must exceed. Engine choice — the doctrine fixes none.
DEFAULT_FRACTAL_WINDOW = 2


@dataclass(frozen=True)
class Bar:
    """One completed candle. Deliberately minimal — a primitive should not need an engine."""

    time: datetime
    high: float
    low: float


@dataclass
class Swing:
    """A detected swing point, in the contract's shape."""

    id: str
    tf: str
    bar_time: datetime
    price: float
    kind: SwingKind
    strength: Strength = "UNCONFIRMED"
    combo_tfs: list[str] | None = None
    #: Index into the bar series. Not emitted — used to order swings against breaks.
    bar_index: int = -1

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "tf": self.tf,
            "bar_time": iso_ny(self.bar_time),
            "price": self.price,
            "kind": self.kind,
            "strength": self.strength,
        }
        if self.combo_tfs:
            out["combo_tfs"] = list(self.combo_tfs)
        return out


class SwingPoints(RuleImplementation):
    """PRIM-001: the swing series, per timeframe, with strength."""

    RULE_ID = "PRIM-001"

    @staticmethod
    def detect(
        bars: Sequence[Bar],
        *,
        tf: str,
        window: int = DEFAULT_FRACTAL_WINDOW,
    ) -> list[Swing]:
        """Fractal swings: a high exceeding `window` bars either side, and the mirror.

        Strictly greater on both sides. Allowing equality would emit two swings for a
        double top, and equal highs are a liquidity pool in their own right (PRIM-003) —
        conflating the two would double-count the same level in two inventories.

        The last `window` bars can never be confirmed, because confirmation needs bars to
        the right that do not exist yet. They are omitted rather than guessed: emitting an
        unconfirmed swing at the hard right edge is how look-ahead enters a system that
        believes it is causal.
        """
        if window < 1:
            raise ValueError("window must be >= 1 — a swing needs bars either side")

        swings: list[Swing] = []
        for i in range(window, len(bars) - window):
            left = bars[i - window : i]
            right = bars[i + 1 : i + 1 + window]
            bar = bars[i]

            if all(bar.high > b.high for b in left) and all(bar.high > b.high for b in right):
                swings.append(
                    Swing(id=f"sw-{tf}-{i}-H", tf=tf, bar_time=bar.time,
                          price=bar.high, kind="HIGH", bar_index=i)
                )
            if all(bar.low < b.low for b in left) and all(bar.low < b.low for b in right):
                swings.append(
                    Swing(id=f"sw-{tf}-{i}-L", tf=tf, bar_time=bar.time,
                          price=bar.low, kind="LOW", bar_index=i)
                )
        return swings

    @staticmethod
    def classify_strength(swings: Sequence[Swing], breaks: Sequence[Any]) -> None:
        """Apply the doctrine's strength rule, in place.

        Two movements, mirrored:

          * a swing that has been **taken out** by a break is WEAK — the liquidity above or
            below it is gone;
          * the opposing swing **protected** by that break is STRONG — "when the buyers push
            the price and take out a weak high, a strong low is confirmed".

        Everything else stays UNCONFIRMED. That is a real state, not a placeholder: an
        unbroken series genuinely has no confirmed strength, and calling it WEAK by default
        would invent confirmation the market never gave.
        """
        by_id = {s.id: s for s in swings}

        for brk in breaks:
            consumed = by_id.get(getattr(brk, "consumed_swing_id", None))
            if consumed is None:
                continue

            # The swing whose liquidity was taken.
            consumed.strength = "WEAK"

            # The protected swing is the one price moved AWAY from to make the break —
            # the most recent opposite-kind swing before the BREAKING BAR, not before the
            # swing that was consumed.
            #
            # "when the buyers push the price and take out a weak high, a strong low is
            # confirmed": the confirmed low is the one the push started from. Looking
            # before the consumed high instead finds a low from the previous leg, which is
            # a different swing and often none at all.
            opposite: SwingKind = "LOW" if consumed.kind == "HIGH" else "HIGH"
            break_bar = getattr(brk, "bar_index", -1)
            candidates = [
                s for s in swings
                if s.kind == opposite and s.bar_index < break_bar
            ]
            if candidates:
                max(candidates, key=lambda s: s.bar_index).strength = "STRONG"

    @staticmethod
    def mark_combo(series_by_tf: dict[str, Sequence[Swing]], *, tolerance: float) -> None:
        """Tag swings that are strong on several timeframes at once.

        "every single TF will have their own strong highs and lows"; one strong across
        several is a COMBO and "is repeatedly defended". Carried because the contract asks
        for `combo_tfs`, and because a combo swing is a materially better stop anchor than a
        single-timeframe one.

        `tolerance` is an absolute price distance and is an engine choice — the doctrine
        gives no figure for "the same level on two timeframes". It must therefore be
        declared, never presented as doctrine.
        """
        flat = [(tf, s) for tf, series in series_by_tf.items() for s in series if s.strength == "STRONG"]
        for tf, swing in flat:
            others = sorted(
                {
                    other_tf
                    for other_tf, other in flat
                    if other_tf != tf
                    and other.kind == swing.kind
                    and abs(other.price - swing.price) <= tolerance
                }
            )
            if others:
                swing.combo_tfs = others
