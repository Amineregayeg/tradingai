"""PRIM-003 — the liquidity-pool inventory (M3).

    Detect and carry, each with a taken/untaken flag and a timeframe tag: (1) swing-point
    levels; (2) equal highs/lows — perfect and relative, per TARGET-006 […]; (3) parabolic /
    compressed liquidity; (4) institutional levels — monthly / weekly / daily deep-V swing
    extremes; (5) institutional candlesticks — PDH/PDL, PWH/PWL, PMH/PML and the Monday
    range, each with high, low and EQ midline; (6) session levels — Asia and London range
    highs/lows, and their EQ as a reverse-trade target. […] Only "fresh not hunted liquidity
    levels" count as objectives.

WHAT THIS IS FOR
Liquidity pools are the engine's *destinations*. TARGET-001 selects the next unresolved
objective from this inventory, TARGET-008 requires the target to be fixed BEFORE the stop is
chosen, and GATE-025's 2R floor is measured against it. An engine with no pool inventory
cannot compute a reward-to-risk at all, which is why every stop rule downstream is currently
unreachable.

FOUR OF THE SEVEN CLASSES ARE BUILT HERE. THREE ARE NOT, DELIBERATELY.

  built      SWING_LEVEL · EQUAL_HIGHS_LOWS · INSTITUTIONAL_CANDLESTICK · SESSION_LEVEL
  not built  PARABOLIC_COMPRESSED · INSTITUTIONAL_LEVEL · DIAGONAL_POOL

The three left out are not an oversight and not a to-do list. Each needs a number the trader
declined to fix:

  * PARABOLIC_COMPRESSED — "compact trends in LTFs, these areas will be very tight". No
    definition of tight exists anywhere in the corpus.
  * INSTITUTIONAL_LEVEL — these are deep-V swing extremes, and TARGET-007 is OPEN precisely
    because "a 'Deep-V' is not defined by a fixed retracement percentage or ATR value". It
    also warns the printed 5-tier list must NOT be transcribed as an ordering.
  * DIAGONAL_POOL — trendline pools along a staircase. The geometry is drawn by hand in the
    corpus and never specified.

Inventing thresholds for these would produce pools the trader never marked, and TARGET-001
would then chase them as objectives — an engine off-doctrine at its destination layer while
scoring 100% conformant. `COVERAGE_NOTE` states the gap so `check_rule_coverage.py` reports
it rather than showing PRIM-003 as a solid tick.

STATE IS NOT SET HERE
Every pool is born UNTESTED. Advancing to TESTED_NOT_CONSUMED or CONSUMED is PRIM-004's job,
because TARGET-005 makes clearance a question about the *reaction* after a sweep, not about
this level's own geometry: "a wick through the level is sufficient to mark the liquidity as
tested, but not necessarily consumed".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal, Sequence

from app.services.rules.base import RuleImplementation
from app.services.rules.prim_001_swings import Bar, Swing
from app.services.telemetry.ny_time import to_ny

PoolClass = Literal[
    "SWING_LEVEL",
    "EQUAL_HIGHS_LOWS",
    "PARABOLIC_COMPRESSED",
    "INSTITUTIONAL_LEVEL",
    "INSTITUTIONAL_CANDLESTICK",
    "SESSION_LEVEL",
    "DIAGONAL_POOL",
]
PoolState = Literal["UNTESTED", "TESTED_NOT_CONSUMED", "CONSUMED"]
EqualsClass = Literal["PERFECT", "RELATIVE", "SEPARATE_POOLS"]
Side = Literal["HIGH", "LOW", "MID"]

#: TARGET-006, verbatim from the registry `values`. Above this the two levels are SEPARATE
#: pools and are not equals at all — the threshold is a classifier, never a filter.
RELATIVE_EQUALS_MAX_DIFF_PCT = 0.3

#: GATE-024 `values`, in NY local time. Asia wraps midnight; London does not.
ASIA_NY = (20, 0)
ASIA_END_NY = (0, 0)
LONDON_NY = (2, 0)
LONDON_END_NY = (5, 0)


@dataclass
class LiquidityPool:
    """One pool of resting liquidity, in the contract's shape."""

    id: str
    tf: str
    pool_class: PoolClass
    state: PoolState = "UNTESTED"
    price: float | None = None
    label: str | None = None
    equals_class: EqualsClass | None = None
    equals_diff_pct: float | None = None
    boosters: list[str] = field(default_factory=list)
    #: Which way price must run to hunt this pool. Not in the schema — needed by PRIM-004,
    #: which cannot know whether trading above or below the level is the sweep.
    side: Side = "HIGH"
    #: First bar index at which the pool exists. Not emitted; keeps the sweep scan causal —
    #: a pool cannot be swept by price that printed before it was marked.
    formed_index: int = -1

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "tf": self.tf,
            "class": self.pool_class,
            "state": self.state,
        }
        for key, value in (
            ("price", self.price),
            ("label", self.label),
            ("equals_class", self.equals_class),
            ("equals_diff_pct", self.equals_diff_pct),
        ):
            if value is not None:
                out[key] = value
        if self.boosters:
            out["boosters"] = list(self.boosters)
        return out


@dataclass(frozen=True)
class EqualsMeasurement:
    """One swing pair's TARGET-006 tier and the difference that produced it.

    NOT A POOL, DELIBERATELY. `TELEMETRY_SCHEMA.json:550` asks for the measured difference
    *"even when the class is SEPARATE_POOLS"*, and the two levels in that tier are already in
    the inventory as swing levels — so what was missing was a RECORD, not an object. Emitting
    a pool here would double-count the liquidity and break
    `test_equals_are_ranked_by_target_006_and_separate_pools_emit_nothing`, which has asserted
    the count difference since before TARGET-006 was claimed.
    """

    id: str
    tf: str
    equals_class: EqualsClass
    equals_diff_pct: float
    #: HIGH or LOW — which side of the market the pair rests on.
    kind: str
    side: Side
    #: The outer of the two levels: the one a sweep has to clear. Carried so a consumer of
    #: the SEPARATE_POOLS tier can locate the pair without re-reading the swings.
    outer_price: float
    swing_ids: tuple[str, str]
    formed_index: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tf": self.tf,
            "equals_class": self.equals_class,
            "equals_diff_pct": self.equals_diff_pct,
            "swing_ids": list(self.swing_ids),
        }


class LiquidityPools(RuleImplementation):
    """PRIM-003: the pool inventory, four of the seven classes."""

    RULE_ID = "PRIM-003"

    COVERAGE_NOTE = (
        "PARTIAL. Built: SWING_LEVEL, EQUAL_HIGHS_LOWS (TARGET-006), "
        "INSTITUTIONAL_CANDLESTICK (PDH/PDL/PWH/PWL/PMH/PML + Monday range), SESSION_LEVEL "
        "(GATE-024 Asia/London). Not built: PARABOLIC_COMPRESSED, INSTITUTIONAL_LEVEL and "
        "DIAGONAL_POOL — each needs a number the trader declined to fix (TARGET-007 is OPEN "
        "for exactly this reason). Do not read PRIM-003 as complete."
    )

    #: Machine-readable form of the note above, so a caller can assert on it.
    UNBUILT_CLASSES = ("PARABOLIC_COMPRESSED", "INSTITUTIONAL_LEVEL", "DIAGONAL_POOL")

    # -- swing levels ------------------------------------------------------------------
    @staticmethod
    def from_swings(swings: Sequence[Swing], *, tf: str) -> list[LiquidityPool]:
        """Class 1. "Liquidity starts with swing points… where the stop losses are placed."

        Every swing is a pool. No filtering by strength: a WEAK swing is one whose liquidity
        has already been taken, which is a *state*, and dropping it here would delete the
        evidence PRIM-004 needs to say so.
        """
        return [
            LiquidityPool(
                id=f"lq-{tf}-swing-{s.id}", tf=tf, pool_class="SWING_LEVEL",
                price=s.price, side="HIGH" if s.kind == "HIGH" else "LOW",
                formed_index=s.bar_index,
            )
            for s in swings
        ]

    # -- equal highs / lows ------------------------------------------------------------
    @staticmethod
    def equals_classification(
        swings: Sequence[Swing], *, tf: str
    ) -> list["EqualsMeasurement"]:
        """Every swing pair's TARGET-006 tier, INCLUDING the one that emits no pool.

        THE THIRD TIER WAS A TYPE VALUE WITH NO DATA BEHIND IT. `EqualsClass` has always
        listed `SEPARATE_POOLS`, `TELEMETRY_SCHEMA.json:544` has always allowed it, and
        `:550` says outright *"the measured difference that produced equals_class. Record it
        even when the class is SEPARATE_POOLS."* Nothing ever assigned it: the classifier
        reached the `> 0.30%` branch, `continue`d, and the measurement went nowhere. Over 54
        windows of the pinned 5m fixture that discarded 519,046 measured differences spanning
        0.3000% to 3.2893% — the majority tier, unrecorded.

        **THIS CHANGES THE RECORD AND NOT THE PAIRING.** `equal_highs_lows` still emits
        nothing above the threshold, because `continue` was the correct BEHAVIOUR: the two
        levels are already in the inventory as swing levels and a third object would
        double-count the same liquidity. The defect was evidentiary — the classifier
        considered the pairing, rejected it, and left no trace that it had looked.

        So this returns the classification for ALL pairs and `equal_highs_lows` builds pools
        from the two tiers that have them. ONE classifier, still: the tier boundary is
        decided here and nowhere else.
        """
        out: list[EqualsMeasurement] = []
        for kind, side in (("HIGH", "HIGH"), ("LOW", "LOW")):
            same = sorted(
                (s for s in swings if s.kind == kind), key=lambda s: s.bar_index
            )
            for i, a in enumerate(same):
                for b in same[i + 1:]:
                    mean = (a.price + b.price) / 2
                    if mean == 0:
                        continue
                    diff_pct = abs(a.price - b.price) / abs(mean) * 100
                    if a.price == b.price:
                        eq_class: EqualsClass = "PERFECT"
                    elif diff_pct <= RELATIVE_EQUALS_MAX_DIFF_PCT:
                        eq_class = "RELATIVE"
                    else:
                        eq_class = "SEPARATE_POOLS"
                    out.append(EqualsMeasurement(
                        id=f"eqm-{tf}-{a.id}-{b.id}", tf=tf,
                        equals_class=eq_class, equals_diff_pct=round(diff_pct, 6),
                        kind=kind, side=side,  # type: ignore[arg-type]
                        outer_price=(
                            max(a.price, b.price) if kind == "HIGH"
                            else min(a.price, b.price)
                        ),
                        swing_ids=(a.id, b.id),
                        formed_index=max(a.bar_index, b.bar_index),
                    ))
        return out

    @staticmethod
    def equal_highs_lows(swings: Sequence[Swing], *, tf: str) -> list[LiquidityPool]:
        """Class 2, ranked by TARGET-006: perfect > relative (≤0.30%) > separate pools.

        Above 0.30% the two levels are SEPARATE pools and no equals pool is emitted — they
        are already in the inventory as swing levels, and emitting a third object would
        double-count the same liquidity. **The measurement behind that rejection is no
        longer thrown away** — `equals_classification` returns it — but the pool inventory is
        byte-for-byte what it was, because the schema asked for a record and not an object.

        BASIS. TARGET-006 says "price difference ≤ 0.30%" and never says of what. The measured
        difference is carried in `equals_diff_pct` against the mean of the two levels, and the
        basis is stated here rather than left for an auditor to infer — the same problem the
        schema forces PRIM-004 to declare for `penetration_pct`.

        A relative equal is a QUALITY BOOSTER, never a destination selector, so the pool
        carries `boosters: ["EQUALS"]` and nothing here promotes it to a target.
        """
        return [
            LiquidityPool(
                id=f"lq-{tf}-eq-{m.swing_ids[0]}-{m.swing_ids[1]}", tf=tf,
                pool_class="EQUAL_HIGHS_LOWS",
                # The pool sits at the level price is actually resting against: the outer of
                # the two, which is the one a sweep has to clear.
                price=m.outer_price,
                label=f"EQ{m.kind[0]}", side=m.side,
                equals_class=m.equals_class, equals_diff_pct=m.equals_diff_pct,
                boosters=["EQUALS"],
                formed_index=m.formed_index,
            )
            for m in LiquidityPools.equals_classification(swings, tf=tf)
            if m.equals_class != "SEPARATE_POOLS"
        ]

    # -- institutional candlesticks ----------------------------------------------------
    @staticmethod
    def institutional_candlesticks(bars: Sequence[Bar], *, tf: str) -> list[LiquidityPool]:
        """Class 5: PDH/PDL, PWH/PWL, PMH/PML and the Monday range, each with an EQ midline.

        PERIODS ARE CUT IN NEW YORK LOCAL TIME, not UTC. GATE-023 is not a formatting rule —
        "previous day's high" means the previous NY session's high, and cutting on UTC
        midnight moves the boundary by four or five hours and produces a different level for
        a third of the year.

        Only COMPLETED periods are emitted. The current day's high is not the PDH, and
        emitting the running period would hand downstream rules a level that changes under
        them mid-decision.
        """
        if not bars:
            return []

        pools: list[LiquidityPool] = []
        for prefix, keyfn in (
            ("PD", lambda d: d),
            ("PW", lambda d: d - timedelta(days=d.weekday())),   # Monday of that week
            ("PM", lambda d: d.replace(day=1)),
        ):
            groups = LiquidityPools._group(bars, keyfn)
            # every group except the last, which is still forming
            for key, (lo_i, hi_i) in list(groups.items())[:-1]:
                pools += LiquidityPools._range_pools(
                    bars, lo_i, hi_i, tf=tf, prefix=prefix, key=str(key),
                )

        # The Monday range, called out separately by the contract: it is the week's opening
        # balance and is hunted as its own object, not merely as part of PW. Grouped over the
        # ORIGINAL index space so `formed_index` stays comparable with every other pool.
        mondays: dict[date, tuple[int, int]] = {}
        for i, bar in enumerate(bars):
            ny = to_ny(bar.time)
            if ny.weekday() != 0:
                continue
            lo, hi = mondays.get(ny.date(), (i, i))
            mondays[ny.date()] = (min(lo, i), max(hi, i))
        for key, (lo_i, hi_i) in list(sorted(mondays.items()))[:-1]:
            pools += LiquidityPools._range_pools(
                bars, lo_i, hi_i, tf=tf, prefix="MDAY", key=key.isoformat(),
            )
        return pools

    # -- session levels ----------------------------------------------------------------
    @staticmethod
    def session_levels(bars: Sequence[Bar], *, tf: str) -> list[LiquidityPool]:
        """Class 6: Asia and London range high/low, and the EQ as a reverse-trade target.

        Windows are GATE-024's, in NY local time: Asia 20:00–00:00, London 02:00–05:00.
        Asia wraps midnight, so a session is keyed by the date it STARTED — otherwise the
        four hours either side of midnight become two different Asia sessions.

        GATE-024 is ADVISORY and says so for a reason: these supply levels, never entry
        permission. Nothing here gates anything.
        """
        pools: list[LiquidityPool] = []
        for name, start, end in (
            ("ASIA", ASIA_NY, ASIA_END_NY),
            ("LONDON", LONDON_NY, LONDON_END_NY),
        ):
            buckets: dict[date, list[int]] = {}
            for i, bar in enumerate(bars):
                ny = to_ny(bar.time)
                minutes = ny.hour * 60 + ny.minute
                lo = start[0] * 60 + start[1]
                hi = end[0] * 60 + end[1]
                if lo < hi:
                    inside, session_date = lo <= minutes < hi, ny.date()
                else:
                    # wraps midnight: 20:00–24:00 belongs to that date, 00:00 is the edge
                    inside = minutes >= lo
                    session_date = ny.date()
                if inside:
                    buckets.setdefault(session_date, []).append(i)

            # drop the newest bucket — it may still be open
            for session_date, idxs in list(sorted(buckets.items()))[:-1]:
                pools += LiquidityPools._range_pools(
                    bars, min(idxs), max(idxs), tf=tf, prefix=name,
                    key=session_date.isoformat(), pool_class="SESSION_LEVEL",
                    # The schema's own label vocabulary: PDH/PWL for institutional
                    # candlesticks, ASIA_HIGH/LONDON_LOW for sessions. Labels are a join key
                    # for anyone reading the records, so they follow the contract's spelling
                    # rather than ours.
                    sep="_", high="HIGH", low="LOW", eq="EQ",
                )
        return pools

    # -- helpers -----------------------------------------------------------------------
    @staticmethod
    def _group(bars: Sequence[Bar], keyfn) -> dict[Any, tuple[int, int]]:
        """Contiguous index span per NY-local period key, insertion-ordered."""
        spans: dict[Any, tuple[int, int]] = {}
        for i, bar in enumerate(bars):
            key = keyfn(to_ny(bar.time).date())
            lo, hi = spans.get(key, (i, i))
            spans[key] = (min(lo, i), max(hi, i))
        return spans

    @staticmethod
    def _range_pools(
        bars: Sequence[Bar], lo_i: int, hi_i: int, *, tf: str, prefix: str, key: str,
        pool_class: PoolClass = "INSTITUTIONAL_CANDLESTICK",
        sep: str = "", high: str = "H", low: str = "L", eq: str = "EQ",
    ) -> list[LiquidityPool]:
        """High, low and EQ midline for one completed period."""
        window = bars[lo_i:hi_i + 1]
        if not window:
            return []
        top = max(b.high for b in window)
        bottom = min(b.low for b in window)
        formed = hi_i

        def pool(suffix: str, price: float, side: Side) -> LiquidityPool:
            label = f"{prefix}{sep}{suffix}"
            return LiquidityPool(id=f"lq-{tf}-{label}-{key}", tf=tf, pool_class=pool_class,
                                 price=price, label=label, side=side, formed_index=formed)

        return [
            pool(high, top, "HIGH"),
            pool(low, bottom, "LOW"),
            # The EQ midline. Carried because the contract names it for every institutional
            # candlestick and calls the session EQ a reverse-trade target — NOT because of
            # premium/discount, which GATE-037 forbids as an entry filter. It is a level.
            pool(eq, (top + bottom) / 2, "MID"),
        ]

    # -- the whole inventory -----------------------------------------------------------
    @staticmethod
    def detect(
        bars: Sequence[Bar], swings: Sequence[Swing], *, tf: str,
    ) -> list[LiquidityPool]:
        """Every pool class this rule builds, in one call."""
        return (
            LiquidityPools.from_swings(swings, tf=tf)
            + LiquidityPools.equal_highs_lows(swings, tf=tf)
            + LiquidityPools.institutional_candlesticks(bars, tf=tf)
            + LiquidityPools.session_levels(bars, tf=tf)
        )
