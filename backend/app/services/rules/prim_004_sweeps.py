"""PRIM-004 — sweep events, and the reaction TARGET-005 demands before a pool is consumed (M3).

    Emit a sweep event whenever price runs through a marked pool: the excursion beyond the
    level with its penetration measured, plus the post-sweep reaction that TARGET-005 requires
    before the pool may be called consumed. Carry the three documented degradations […]

THE RULE THIS PRIMITIVE EXISTS TO ENFORCE IS TARGET-005, AND IT IS COUNTERINTUITIVE

    "A liquidity level is not considered cleared solely because price wicks through it or
    closes beyond it. The sweep itself is only the first step. The engine must evaluate the
    market reaction after the sweep." … "Market structure always has higher priority than
    wick penetration."

So a body close beyond a level does NOT clear it. That is the opposite of the break-validity
rule (ENTRY-003), where a body close is exactly what makes a break real, and the registry
flags the scope split explicitly because the two are so easily conflated. Here, clearance is
a structural question: the pool becomes CONSUMED only when a break event afterwards turns
AGAINST the direction of the run. Until then it is TESTED_NOT_CONSUMED, and it is still a
live objective.

That is also why nothing here uses a reaction *window*. The first break after the sweep
answers the question — opposite direction means the sweep did its work, same direction means
price simply carried on through and the level was never the destination. A window would be a
number the corpus does not contain.

PENETRATION IS MEASURED; ITS BASIS IS DECLARED
TARGET-005 calibrates a weak sweep at "≤ ~1%" and the registry records, in the rule's own
`values`, that the source never says one percent *of what*: `"pct_of_what": "UNSTATED — level
price? swing range? never said"`. The schema therefore makes `penetration_pct_basis`
mandatory. We use LEVEL_PRICE and say so on every record, so a later ruling can recompute
stored history instead of discarding it.

THE THREE DEGRADATIONS, AND THE ONE THAT NEEDS A NUMBER WE DO NOT HAVE
  (b) TINY-WICK INSUFFICIENCY → `weak_sweep`, from TARGET-005's ~1%. Built.
  (c) DEGRADED SWEEP → `degraded_by_prior_breakout`: a prior close beyond the level before
      the final poke. Purely structural, no threshold. Built.
  (a) LIQUIDITY SWEEP FAIL → "price comes extremely close to the LIQ1 point but it was never
      hunted". "Extremely close" is not a number anywhere in the corpus, so a failed sweep is
      emitted ONLY when the caller declares `near_miss_pct`. Without it, no failed sweeps are
      reported — silence is honest; a guessed threshold would manufacture events.

ENGINEERED-LIQUIDITY BUILD IS NOT BUILT
"A cluster of small, closely spaced swings… with shrinking candles just before the thrust"
needs three thresholds the corpus fixes none of. See `COVERAGE_NOTE`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_001_swings import Bar
from app.services.rules.prim_003_liquidity import LiquidityPool
from app.services.telemetry.ny_time import iso_ny

WickOrClose = Literal["WICK_ONLY", "BODY_CLOSE_BEYOND"]
PctBasis = Literal["LEVEL_PRICE", "SWING_RANGE", "OTHER"]

#: TARGET-005 `values.weak_sweep_penetration_pct`. A registry constant, not an engine choice.
WEAK_SWEEP_PENETRATION_PCT = 1.0

#: The basis we measure `penetration_pct` against. An engine choice, declared on every record
#: because the doctrine leaves it unstated.
PENETRATION_PCT_BASIS: PctBasis = "LEVEL_PRICE"


@dataclass
class SweepEvent:
    """One run through a marked pool, in the contract's shape."""

    id: str
    pool_id: str
    bar_time: datetime
    penetration_abs: float
    penetration_pct: float
    wick_or_close: WickOrClose
    penetration_pct_basis: PctBasis = PENETRATION_PCT_BASIS
    weak_sweep: bool = False
    degraded_by_prior_breakout: bool = False
    sweep_failed: bool = False
    structural_reaction: str | None = None
    reaction_break_ids: list[str] = field(default_factory=list)
    #: Index of the bar at the excursion's deepest point. Not emitted.
    bar_index: int = -1
    #: TARGET-005 verdict for this excursion: did structure turn against the run? Kept as a
    #: field rather than re-derived from `structural_reaction`, because a state machine that
    #: greps its own prose breaks the moment the wording is edited.
    cleared: bool = False

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "pool_id": self.pool_id,
            "bar_time": iso_ny(self.bar_time),
            "penetration_abs": self.penetration_abs,
            "penetration_pct": self.penetration_pct,
            "penetration_pct_basis": self.penetration_pct_basis,
            "wick_or_close": self.wick_or_close,
            "weak_sweep": self.weak_sweep,
            "degraded_by_prior_breakout": self.degraded_by_prior_breakout,
            "sweep_failed": self.sweep_failed,
        }
        if self.structural_reaction is not None:
            out["structural_reaction"] = self.structural_reaction
        if self.reaction_break_ids:
            out["reaction_break_ids"] = list(self.reaction_break_ids)
        return out


class SweepEvents(RuleImplementation):
    """PRIM-004: sweeps, their degradations, and TARGET-005 clearance."""

    RULE_ID = "PRIM-004"

    COVERAGE_NOTE = (
        "Sweeps, penetration (basis LEVEL_PRICE, declared), weak/degraded classification and "
        "TARGET-005 structural clearance are built. LIQUIDITY SWEEP FAIL is emitted only when "
        "the caller declares near_miss_pct. ENGINEERED-LIQUIDITY build is not built — it "
        "needs three thresholds the corpus fixes none of."
    )

    @staticmethod
    def detect(
        pools: Sequence[LiquidityPool],
        bars: Sequence[Bar],
        breaks: Sequence[Any] = (),
        *,
        tf: str,
        near_miss_pct: float | None = None,
    ) -> list[SweepEvent]:
        """Emit every sweep, and advance each pool's state in place.

        `breaks` are PRIM-005 events; they are what makes clearance decidable. Passing none
        is legitimate — every swept pool then rests at TESTED_NOT_CONSUMED, which is the
        honest answer when no structural evidence exists yet, not a degraded one.

        Pools whose `side` is MID (the EQ midlines) are skipped. An EQ is a reference level
        and a reverse-trade target, not resting liquidity on one side of the market, so
        "running through it" has no hunting direction to measure penetration against.
        """
        events: list[SweepEvent] = []
        for pool in pools:
            if pool.price is None or pool.side == "MID":
                continue
            events += SweepEvents._for_pool(
                pool, bars, breaks, tf=tf, near_miss_pct=near_miss_pct
            )
        return events

    # ----------------------------------------------------------------------------------
    @staticmethod
    def _for_pool(
        pool: LiquidityPool,
        bars: Sequence[Bar],
        breaks: Sequence[Any],
        *,
        tf: str,
        near_miss_pct: float | None,
    ) -> list[SweepEvent]:
        level = float(pool.price)  # type: ignore[arg-type]
        if level == 0:
            return []
        hunting_up = pool.side == "HIGH"
        start = pool.formed_index + 1

        events: list[SweepEvent] = []
        prior_close_beyond = False
        run: list[int] = []          # indices of the current contiguous excursion
        closest_gap_pct: float | None = None

        def beyond(bar: Bar) -> bool:
            return bar.high > level if hunting_up else bar.low < level

        def closed_beyond(bar: Bar) -> bool:
            if bar.close is None:
                return False
            return bar.close > level if hunting_up else bar.close < level

        for i in range(start, len(bars)):
            bar = bars[i]
            if beyond(bar):
                run.append(i)
                continue

            # not beyond: close the excursion if one was open
            if run:
                events.append(SweepEvents._excursion(
                    pool, bars, run, level, hunting_up, tf=tf,
                    degraded=prior_close_beyond, breaks=breaks, seq=len(events),
                ))
                # A close beyond the level, once it has happened, degrades every LATER poke:
                # "this is not the ideal sweep, it has BO and new highs over level before
                # sweep".
                prior_close_beyond = prior_close_beyond or any(
                    closed_beyond(bars[j]) for j in run
                )
                run = []
            else:
                gap = (level - bar.high) if hunting_up else (bar.low - level)
                if gap >= 0:
                    pct = gap / abs(level) * 100
                    closest_gap_pct = pct if closest_gap_pct is None else min(closest_gap_pct, pct)

        if run:
            events.append(SweepEvents._excursion(
                pool, bars, run, level, hunting_up, tf=tf,
                degraded=prior_close_beyond, breaks=breaks, seq=len(events),
            ))

        # (a) LIQUIDITY SWEEP FAIL — only with a declared threshold.
        if (
            not events
            and near_miss_pct is not None
            and closest_gap_pct is not None
            and closest_gap_pct <= near_miss_pct
        ):
            nearest = min(
                range(start, len(bars)),
                key=lambda i: (level - bars[i].high) if hunting_up else (bars[i].low - level),
                default=None,
            )
            if nearest is not None:
                events.append(SweepEvent(
                    id=f"swp-{tf}-{pool.id}-fail", pool_id=pool.id,
                    bar_time=bars[nearest].time,
                    penetration_abs=0.0, penetration_pct=0.0,
                    wick_or_close="WICK_ONLY", sweep_failed=True,
                    structural_reaction="approach without crossing — the level was never hunted",
                    bar_index=nearest,
                ))

        SweepEvents._apply_state(pool, events)
        return events

    @staticmethod
    def _excursion(
        pool: LiquidityPool,
        bars: Sequence[Bar],
        run: Sequence[int],
        level: float,
        hunting_up: bool,
        *,
        tf: str,
        degraded: bool,
        breaks: Sequence[Any],
        seq: int,
    ) -> SweepEvent:
        """One contiguous run beyond the level, measured at its deepest bar.

        A run is one sweep, not one per bar. Three bars spent above a swing high is a single
        excursion through that liquidity; emitting three events would triple-count the same
        hunt and make any later count of "how often is this level run" meaningless.
        """
        deepest_i = max(
            run, key=lambda i: (bars[i].high - level) if hunting_up else (level - bars[i].low)
        )
        bar = bars[deepest_i]
        pen = (bar.high - level) if hunting_up else (level - bar.low)
        pen_pct = pen / abs(level) * 100

        body_beyond = any(
            bars[i].close is not None
            and (bars[i].close > level if hunting_up else bars[i].close < level)
            for i in run
        )

        reaction, break_ids, cleared = SweepEvents._reaction(breaks, deepest_i, hunting_up)
        return SweepEvent(
            id=f"swp-{tf}-{pool.id}-{seq}", pool_id=pool.id, bar_time=bar.time,
            penetration_abs=round(pen, 10), penetration_pct=round(pen_pct, 10),
            wick_or_close="BODY_CLOSE_BEYOND" if body_beyond else "WICK_ONLY",
            weak_sweep=pen_pct <= WEAK_SWEEP_PENETRATION_PCT,
            degraded_by_prior_breakout=degraded,
            structural_reaction=reaction, reaction_break_ids=break_ids,
            bar_index=deepest_i, cleared=cleared,
        )

    @staticmethod
    def _reaction(
        breaks: Sequence[Any], sweep_index: int, hunting_up: bool
    ) -> tuple[str | None, list[str], bool]:
        """The FIRST break after the sweep decides whether the level was consumed.

        Opposite to the run → the sweep did its work and the liquidity is gone. Same as the
        run → price carried straight on and this level was never the destination; the pool is
        tested, not consumed. No break yet → no verdict, which is a real state and not a
        failure.
        """
        after = sorted(
            (b for b in breaks if getattr(b, "bar_index", -1) > sweep_index),
            key=lambda b: b.bar_index,
        )
        if not after:
            return None, [], False
        first = after[0]
        turned = (first.direction == "DOWN") if hunting_up else (first.direction == "UP")
        if turned:
            return (
                f"{first.type} {first.direction} after the sweep — structure turned against "
                "the run (TARGET-005 clearance)",
                [first.id],
                True,
            )
        return (
            f"{first.type} {first.direction} after the sweep — structure continued through "
            "the level, so it was passed rather than hunted",
            [first.id],
            False,
        )

    @staticmethod
    def _apply_state(pool: LiquidityPool, events: Sequence[SweepEvent]) -> None:
        """TARGET-005 in one place: a wick marks TESTED; only a reaction makes it CONSUMED."""
        real = [e for e in events if not e.sweep_failed]
        if not real:
            return
        pool.state = "CONSUMED" if any(e.cleared for e in real) else "TESTED_NOT_CONSUMED"
