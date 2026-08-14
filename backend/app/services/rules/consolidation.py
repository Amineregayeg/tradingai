"""A consolidation/range detector — OURS, because the registry does not define one.

WHY THIS IS NOT A RULE MODULE
GRADE-035's `inputs` name *"the consolidation/overlap detector"* and **no such detector
exists anywhere** — not in the registry, not in the rules package, not under
`app/services/`. The only `overlap` in the codebase is PRIM-002's BPR overlap, which is two
opposite-direction imbalances overlapping in price: a different object entirely. So this is
a primitive the contract assumes and never specifies, and it carries **no `RULE_ID`**,
because claiming one would assert the registry defines a rule it does not.

THE DEFINITION IS OURS AND UNRATIFIED, AND THAT IS THE WHOLE HAZARD
No source states what a consolidation is. Measured on real Binance perpetual bars with a
12-bar window, one parameter moves the detector across the entire range of possible
behaviour:

    k     1H (~30d, relayed)   5m (863 bars, MEASURED HERE)
    2.0        0.6%                     0.1%
    3.0       25.1%                    19.7%   <- DECLARED
    4.0       68.2%                    57.6%
    5.0       90.1%                    86.3%

The 5m column was measured by this module against live `fapi` bars, not taken on report.
An earlier measurement of "the same" 3-day corpus, hours apart, gave 17.0% at k=3.0 —
2.7 points adrift, because a rolling 3-day window is a different corpus every hour. That
divergence is why `measured_span` records the exact window and not "~3 days".

**No structural change — one number.** At `k = 5.0` nine windows in ten are "consolidation"
and GRADE-035 permits essentially every reversal; at `k = 2.0` it fires on nothing and every
reversal is refused. **Both ends are a detector that has stopped discriminating**, and the
low end is the more dangerous one to review, because "not permissive" reads as conservative.

**AND A FIXTURE PAIR CANNOT BOUND THIS.** A genuine-consolidation fixture is tighter than a
trend fixture *by construction*, so every setting in that table passes a discriminates-a-
range-from-a-trend test. The fixtures prove the detector discriminates; they say nothing
about where the boundary sits, and the boundary is the rule. Nobody would notice `3.0`
versus `4.0` in review, and that is 20% versus 58% of all market conditions.

So the threshold is a declared parameter that **carries its own measured rate**, and the
detector reports the rate it achieves on a corpus so the declaration is checkable rather
than decorative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.rules.prim_001_swings import Bar

#: Bars per window. 12 at 5m is an hour — long enough that a single wick cannot define the
#: range, short enough to sit inside the post-sweep window GRADE-035 cares about.
WINDOW_BARS = 12


@dataclass(frozen=True)
class ConsolidationThreshold:
    """`k` in `span <= k * average_bar_range`, with the evidence for choosing it attached.

    THE MEASURED RATE TRAVELS WITH THE VALUE. A bare `k` is unfalsifiable: nobody reading
    `4.0` can tell whether that is strict or permissive without re-running the measurement,
    and the difference between two plausible-looking values is most of the market.
    """

    k: float
    #: Fraction of windows this k calls consolidation, on the corpus named below.
    measured_rate_pct: float
    measured_tf: str
    measured_bars: int
    measured_span: str
    #: FALSE. Nobody has ruled on what a consolidation is.
    ratified: bool = False
    rationale: str = ""
    #: The bounds this rate must stay inside. A ceiling alone lets the detector satisfy it
    #: by never firing, which refuses every reversal instead of permitting every one.
    rate_ceiling_pct: float = 35.0
    rate_floor_pct: float = 5.0
    #: WHY THE RATE MAY NOT BE TREATED AS A PROPERTY OF THE MARKET.
    corpus_caveat: str = ""

    def rate_is_within_bounds(self) -> bool:
        return self.rate_floor_pct <= self.measured_rate_pct <= self.rate_ceiling_pct


#: THE DECLARED THRESHOLD. Ours, unratified, and measured at the timeframe the engine runs.
DECLARED_THRESHOLD = ConsolidationThreshold(
    k=3.0,
    measured_rate_pct=19.7,
    measured_tf="5m",
    measured_bars=863,
    measured_span="2026-08-11 16:10 -> 2026-08-14 16:00 UTC, 852 windows",
    rationale=(
        "OURS, NOT SALIM'S — no source defines a consolidation. k=3.0 measured 19.7% at "
        "5m over 852 windows, inside a 5-35% band. k=4.0 gives 57.6%, making the "
        "prerequisite true more often than not — it stops discriminating; k=2.0 gives "
        "0.1%, which fires on almost nothing and refuses every reversal. Chosen for the "
        "RATE it produces, not for the number itself."
    ),
    corpus_caveat=(
        "MEASURED ON THREE DAYS, 863 bars, entirely post-ENTRY_TF-switch and one market "
        "regime. Enough to measure a rate; NOT enough to claim it is representative. "
        "RE-MEASURE if ENTRY_TF changes — the 1H rate for this same k is ~25%, five "
        "points adrift, so a ceiling declared against the wrong timeframe is loose. "
        "AND THE CAVEAT IS EMPIRICAL, NOT RHETORICAL: two independent measurements of "
        "'the same' 3-day 5m corpus, taken hours apart, gave 17.0% and 19.7% for this k. "
        "A rolling window is a different corpus every hour, so a rate quoted without its "
        "window is not reproducible."
    ),
)


@dataclass(frozen=True)
class ConsolidationWindow:
    """A range, as a BAND. Never a single price.

    PRIM-006 is explicit that a flip carries two prices because a level is a zone, and a
    range is the same object: collapsing it to a midpoint discards the thing that makes it
    a range.
    """

    tf: str
    start: Bar
    end: Bar
    price_high: float
    price_low: float
    span: float
    average_bar_range: float
    k_used: float
    is_consolidation: bool

    @property
    def ratio(self) -> float:
        """`span / average_bar_range` — the raw measurement, before the threshold."""
        return self.span / self.average_bar_range if self.average_bar_range else 0.0


def detect_window(
    bars: Sequence[Bar], *, tf: str, threshold: ConsolidationThreshold
) -> ConsolidationWindow | None:
    """Measure the most recent `WINDOW_BARS` bars. `None` if there are too few.

    Returning `None` rather than a not-consolidation verdict is deliberate: "we have not
    got enough bars to say" and "we looked and it is trending" are different facts, and
    this project has spent a day on what happens when those are collapsed.
    """
    if len(bars) < WINDOW_BARS:
        return None
    window = list(bars[-WINDOW_BARS:])
    high = max(b.high for b in window)
    low = min(b.low for b in window)
    span = high - low
    ranges = [b.high - b.low for b in window]
    avg = sum(ranges) / len(ranges)
    return ConsolidationWindow(
        tf=tf,
        start=window[0],
        end=window[-1],
        price_high=high,
        price_low=low,
        span=span,
        average_bar_range=avg,
        k_used=threshold.k,
        is_consolidation=bool(avg) and span <= threshold.k * avg,
    )


def detection_rate_pct(
    bars: Sequence[Bar], *, tf: str, threshold: ConsolidationThreshold
) -> tuple[float, int]:
    """Fraction of rolling windows called consolidation, and how many windows were measured.

    **This is what makes the declared threshold checkable.** Without it the value is
    invisible: `k = 4.0` and `k = 3.0` look equally reasonable in a diff and differ by most
    of the market.
    """
    windows = 0
    hits = 0
    for end in range(WINDOW_BARS, len(bars) + 1):
        w = detect_window(bars[:end], tf=tf, threshold=threshold)
        if w is None:
            continue
        windows += 1
        hits += 1 if w.is_consolidation else 0
    return (100.0 * hits / windows if windows else 0.0), windows
