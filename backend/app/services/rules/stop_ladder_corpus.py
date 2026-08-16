"""T-0030's corpus measurements: the setup denominator and the monotonicity inversion rate.

GATE-027's statement asserts the ladder "is cushion-monotonic" IN PROSE. Nothing has ever
measured it, and two things downstream depend on the claim being true: GATE-028's tie-break
is UNOBSERVABLE on a monotonic ladder (the larger stop is always the earlier rung, so
`min()`'s list-order accident coincides with the correct answer), and GATE-030's flag is
reachable only through the selector. `1b-i` is the measurement.

WHAT THIS REUSES RATHER THAN REBUILDS
`validate_over_corpora()` at `consolidation.py:270` already windows a pinned fixture into
863-bar corpora at step 12 — 54 of them over `btcusdtp_5m_1500.csv`, green in
`test_t0017_threshold_over_corpora.py`. The same windowing is used here, with the same
defaults, for the same reason: a second windowing structure would be a second thing to keep
honest, and the plan says reuse it.

    "54 CORPORA"   T-0017's sliding windows. REAL, and it is the instrument.
    "54 SETUPS"    NOT THE SAME QUANTITY, and nothing here may report it as one.

THE DENOMINATOR IS NOT THE WINDOW COUNT, AND THAT IS THE WHOLE UNIT HAZARD (B122). One
decision bar per window would make the setup count equal the window count by construction,
and a reader seeing `n = 54` could not tell which quantity it was. So the decision bars are
counted at STEP 1 over the same 863-bar lookback, and setups are then deduplicated by the
ENGINE'S OWN OBJECT IDENTITY — the `imbalance_id` ENTRY-001 selected — because consecutive
bars re-select the same POI and counting bars would inflate `n` by the dwell time of an
inventory rather than by the number of setups in it.

WHAT A SETUP IS, IN ONE SENTENCE, AND IT IS NOT OURS
A setup is a decision bar at which the existing entry path's own predicate holds —
`setup_in_play = bool(imbalances) and bool(breaks)` at `shadow.py:680`, "A setup is 'in
play' only if the primitives produced something to judge" — and at which ENTRY-001 returns
an entry POI. `test_shadow_setup_predicate_has_not_drifted` reads that line out of
`shadow.py` and fails if it changes, so this file cannot quietly hold a second definition.

NOTHING HERE IS IMPORTED BY `live/`. The dependency runs one way: this module reads the
shadow path's predicate as TEXT, in a test, precisely so that no import edge is created.

WHY THE TARGET NEVER APPEARS IN THIS FILE
`rr` needs a target and NOTHING IN THE ENGINE PRODUCES ONE — `InstitutionalDestination` is
constructed nowhere in `app/`, TARGET-001's own docstring says "AN INPUT — nothing in the
engine produces one", and `shadow.py:692` says a TAKE "additionally requires
`stop_evaluation`, `target_selection` and `entry_criteria`, none of which exists before M6".
So every rate that consumes `rr` is UNMEASURABLE over this corpus without the measuring seat
supplying the missing number, which would put our choice inside every figure.

The inversion rate does not consume `rr`. It reads CUSHION — `|entry - stop|` — and none of
GATE-027's four locators reads `inputs.target`; `test_the_ladder_does_not_depend_on_the_target`
pins that by varying the target and asserting an identical ladder. That is why `1b-i` is
deliverable here and `4b` and `6-i` are reported as UNMEASURED with their reason.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Literal, Sequence

from app.services.rules.entry_001_imbalance_poi import ImbalanceIsTheOnlyEntryPOI
from app.services.rules.gate_027_stop_ladder import (
    ClosestTo3RSelector, LadderInputs, RewardFloor, StopCandidate, StopCandidateLadder,
)
from app.services.rules.gate_029_stop_flags import (
    DegenerateRunner, DeclaredEngineering, RRAboveAcceptableBand, TighterThanNecessary,
)
from app.services.rules.prim_001_swings import Bar, SwingPoints
from app.services.rules.prim_002_imbalances import ImbalanceInventory
from app.services.rules.prim_003_liquidity import LiquidityPools
from app.services.rules.prim_004_sweeps import SweepEvents
from app.services.rules.prim_005_breaks import BreakEvents

#: The T-0017 windowing, mirrored rather than re-derived. `validate_over_corpora()` carries
#: these as its own defaults and `test_t0017_threshold_over_corpora.py` asserts the 54.
CORPUS_BARS: int = 863
STEP_BARS: int = 12

#: A placeholder search window for the re-pricing done during the sweep. `RewardFloor.table`
#: needs one only to stamp `search_evidence` on a rung it cannot price; the sweep re-prices
#: rungs whose anchors were already located, so nothing reads it. Fixed rather than "now" so
#: a sweep is reproducible.
T_SENTINEL = datetime(1970, 1, 1, tzinfo=timezone.utc)

EntryPlacement = Literal["MID", "FAR_EDGE", "NEAR_EDGE"]

#: OURS. Unratified. THE ENTRY PATH PRODUCES A BAND AND THE LADDER CONSUMES A SCALAR.
#:
#: `EntryPOI` carries `price_band {high, low}` — PRIM-006's zones-are-never-lines, applied
#: to the POI — while `LadderInputs.entry` is one float. Something must pick a point, and
#: nothing in the doctrine picks it. This is the same class of choice GATE-027 already
#: declares twice (`DECLARED_SWEEP_PLACEMENT`, `DECLARED_IMBALANCE_EDGE`), and leaving it
#: hardcoded while those two are declared would be the asymmetry Review already caught on
#: that module: one declaration makes the undeclared ones look settled.
#:
#: MID is operative because it is the only choice invariant under swapping which edge is
#: called "near" — the two edges are the two competing readings and neither has an argument
#: the other lacks. The inversion rate is reported under ALL THREE (criterion 7a's report),
#: so the choice is visible as a sensitivity rather than buried as a default.
DECLARED_ENTRY_PLACEMENT = DeclaredEngineering(
    name="setup_entry_placement_in_poi_band",
    value="MID",
    authority="ENGINEERING — this engine, T-0030. Not ratified by Salim.",
    source=(
        "ENTRY-001 emits price_band{high,low} and never a single entry price; "
        "LadderInputs.entry is a scalar. No doctrine picks a point in the band. MID is "
        "declared because it is invariant under relabelling the edges, and the inversion "
        "rate is reported under MID, FAR_EDGE and NEAR_EDGE so the dependence is measured. "
        "Cushion ORDER is shift-invariant — moving entry by d adds d to every cushion on "
        "the stop side — so the only channel by which this choice can change the answer is "
        "set MEMBERSHIP via is_on_stop_side, which is why the three numbers can differ at "
        "all."
    ),
    competing="FAR_EDGE / NEAR_EDGE, the two band edges",
)

#: OURS. Unratified. THE SECOND HALF OF THE SAME ASYMMETRY, AND IT WAS NEARLY LEFT UNDECLARED.
#:
#: `ENTRY-001.select` takes an `at_price` and its docstring calls that "the location". Which
#: price IS the location is stated nowhere: this uses the DECISION BAR'S CLOSE, because that
#: is the price the engine has when it decides, and `shadow.py` evaluates at bar close.
#:
#: DECLARING THE PLACEMENT AND NOT THIS WOULD HAVE BEEN THE EXACT ASYMMETRY GATE-027 WAS
#: CAUGHT ON — "declaring one and hardcoding the other is worse than either choice alone",
#: because a reader who finds one declaration reasonably infers the undeclared ones are
#: doctrine. Both choices sit on the same call, one line apart.
#:
#: THE CONSEQUENCE IS MEASURED AND IT IS LARGE. Omitting `at_price` entirely returns a POI on
#: every window and makes `n` equal the WINDOW COUNT by construction — exactly 54 at step 12,
#: which is B122's collision landing on the number B122 is about. With the close supplied, 49
#: of 54 windows carry a POI and 5 do not. So this is not a tidy-up: it is the difference
#: between a denominator that is measured and one that is a restatement.
DECLARED_ENTRY_LOCATION = DeclaredEngineering(
    name="setup_entry_location_price",
    value="DECISION_BAR_CLOSE",
    authority="ENGINEERING — this engine, T-0030. Not ratified by Salim.",
    source=(
        "ENTRY-001.select's `at_price` is documented as 'the location' and nothing states "
        "which price that is. The decision bar's close is used because it is the price the "
        "engine holds at the moment it decides, and shadow.py evaluates on bar close. "
        "Measured: omitting at_price makes the setup count equal the window count by "
        "construction (54 of 54 at step 12); supplying the close gives 49 of 54."
    ),
    competing=(
        "the POI band's own midpoint, or omitting at_price entirely — the latter is what "
        "produces the window-count collision and is the reason this is declared rather than "
        "chosen quietly"
    ),
)


@dataclass(frozen=True)
class Setup:
    """One decision bar at which the existing entry path produced something to judge.

    `ladder` is GATE-027's, built by GATE-027's own producer. Nothing here re-implements
    anchor location — a second ladder would be a second thing that can disagree with the
    engine, and the measurement would then be about this file.
    """

    decision_index: int
    entry: float
    direction: str
    imbalance_id: str
    poi_high: float
    poi_low: float
    msb_id: str | None
    ladder: tuple[StopCandidate, ...]
    #: Distances from entry to the objects a target could BE — unresolved liquidity pools
    #: and unfilled imbalances lying in the trade direction. NOT a target and never used as
    #: one: this is the observed distribution B127 requires the swept range to be derived
    #: from, so the range is a measurement a reviewer can recompute.
    candidate_target_distances: tuple[float, ...] = ()

    @property
    def locatable(self) -> tuple[StopCandidate, ...]:
        return tuple(c for c in self.ladder if c.locatable and c.cushion is not None)


@dataclass(frozen=True)
class Interval:
    """A 95% Wilson interval, carried WITH its numerator and denominator.

    THE INTERVAL IS THE POINT AND IT IS STRONGER THAN THE FLOOR. `n` travels inside the
    number and cannot be hidden behind a percentage: "33% (2 of 6, 95% CI 6-76%)" refuses to
    be read as "33%". B124's second mechanism, and it is why every rate in this module
    returns one of these rather than a float.
    """

    successes: int
    trials: int
    #: What is being counted, and of what. A rate with no unit is B122's defect.
    numerator_unit: str
    denominator_unit: str

    @property
    def rate(self) -> float | None:
        """None, not 0.0, when nothing was counted. A rate over zero trials is not a rate."""
        return None if self.trials == 0 else self.successes / self.trials

    @property
    def wilson(self) -> tuple[float, float] | None:
        """The 95% Wilson score interval. None when there is nothing to bound."""
        if self.trials == 0:
            return None
        z = 1.959963984540054  # two-sided 95%
        n = float(self.trials)
        p = self.successes / n
        denom = 1.0 + z * z / n
        centre = (p + z * z / (2.0 * n)) / denom
        half = (z / denom) * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
        return (max(0.0, centre - half), min(1.0, centre + half))

    def summary(self) -> str:
        """The figure with its unit, denominator and interval attached — criterion 7c."""
        if self.trials == 0:
            return (
                f"UNMEASURED: 0 {self.denominator_unit} — a rate over zero trials is not a "
                "rate and is reported as its denominator"
            )
        lo, hi = self.wilson  # type: ignore[misc]
        return (
            f"{self.rate * 100:.1f}% ({self.successes} of {self.trials} "  # type: ignore[operator]
            f"{self.denominator_unit}, 95% CI {lo * 100:.1f}-{hi * 100:.1f}%) "
            f"[{self.numerator_unit}]"
        )

    def as_dict(self) -> dict[str, Any]:
        lo_hi = self.wilson
        return {
            "successes": self.successes,
            "trials": self.trials,
            "rate": self.rate,
            "ci95_low": None if lo_hi is None else lo_hi[0],
            "ci95_high": None if lo_hi is None else lo_hi[1],
            "numerator_unit": self.numerator_unit,
            "denominator_unit": self.denominator_unit,
            "summary": self.summary(),
        }


def windows(
    bars: Sequence[Bar], *, corpus_bars: int = CORPUS_BARS, step_bars: int = STEP_BARS,
) -> Iterator[tuple[int, Sequence[Bar]]]:
    """The T-0017 sliding windows, yielding `(decision_index, window)`.

    The decision bar is the window's LAST bar, so every primitive detected inside the window
    lies at or before it — the causality `evaluate_layout`'s `as_of_index` enforces, obtained
    here by construction instead.

    THE WINDOWS OVERLAP HEAVILY (863 bars, step 12) and are a RESAMPLING STRUCTURE, not
    independent samples. Any spread computed across them must say so.
    """
    for start in range(0, max(0, len(bars) - corpus_bars) + 1, step_bars):
        window = bars[start:start + corpus_bars]
        if len(window) < corpus_bars:
            break
        yield start + corpus_bars - 1, window


def _entry_price(high: float, low: float, direction: str, placement: EntryPlacement) -> float:
    """A point in the POI band, under the declared placement.

    FAR/NEAR are relative to the trade, not to the chart: on a LONG the stop sits below, so
    the FAR edge of the POI is its low. Defining them by chart position instead would make
    the same word mean opposite things on longs and shorts.
    """
    if placement == "MID":
        return (high + low) / 2.0
    if placement == "FAR_EDGE":
        return low if direction == "LONG" else high
    return high if direction == "LONG" else low


def extract_setup(
    window: Sequence[Bar],
    *,
    tf: str = "5m",
    decision_index: int,
    placement: EntryPlacement = "MID",
) -> Setup | None:
    """The setup at this window's right edge, or None when the entry path produces none.

    Every producer here is an existing one, called with its own signature:
    PRIM-001 swings, PRIM-002 imbalances, PRIM-005 breaks, PRIM-003 pools, PRIM-004 sweeps,
    ENTRY-001's selection, and GATE-027's ladder builder.

    `momentum_min_width` IS NOT SUPPLIED, AND THAT IS FAITHFUL RATHER THAN LAZY. Nothing in
    `app/` supplies one — `evaluate_layout` defaults it to None and `shadow.py` never passes
    it — so `is_momentum_imbalance` is None on every imbalance and RUNG 2 CANNOT LOCATE IN
    PRODUCTION. Supplying a width here would measure a ladder the engine does not run.
    """
    swings = SwingPoints.detect(window, tf=tf)
    breaks = BreakEvents.detect(window, swings, tf=tf)
    imbalances = ImbalanceInventory.detect(window, tf=tf)
    # `setup_in_play` — shadow.py:680, the existing entry path's own predicate.
    if not (imbalances and breaks):
        return None

    msb = breaks[-1]
    direction = "LONG" if msb.direction == "UP" else "SHORT"
    # `at_price` IS THE ENTRY LOCATION AND OMITTING IT PRODUCES THE UNIT COLLISION EXACTLY.
    #
    # ENTRY-001.select's own docstring: "the entry POI, or None when no inefficiency is
    # available AT THE LOCATION". Called without `at_price` it ranks every imbalance in the
    # lookback and returns the best-ranked one anywhere in it — which for this fixture is
    # the oldest surviving super-BPR, an artefact of where the window's LEFT edge fell.
    #
    # MEASURED, because the difference is not cosmetic: over the 54 windows at step 12,
    # `at_price=None` returns a POI on EVERY window and yields exactly 54 setups — n equal
    # to the window count BY CONSTRUCTION, which is B122's "one count wearing two
    # quantities" arriving on the very number the entry is about. With the location
    # supplied, 49 windows carry a POI at the decision bar's close and 5 do not, so `n` is
    # a measurement rather than a restatement of the denominator above it.
    # The location price, READ FROM THE DECLARATION rather than inlined, so the constant is
    # the single source. Only the declared reading is implemented: changing the declaration
    # without implementing the new reading raises here instead of silently doing the old
    # thing, which is the failure mode a declared parameter exists to prevent.
    if DECLARED_ENTRY_LOCATION.value != "DECISION_BAR_CLOSE":
        raise NotImplementedError(
            f"{DECLARED_ENTRY_LOCATION.name} is declared "
            f"{DECLARED_ENTRY_LOCATION.value!r} and only DECISION_BAR_CLOSE is implemented"
        )
    poi = ImbalanceIsTheOnlyEntryPOI.select(imbalances, at_price=window[-1].close)
    if poi is None:
        return None

    entry = _entry_price(poi.price_high, poi.price_low, direction, placement)
    pools = LiquidityPools.detect(window, swings, tf=tf)
    sweeps = SweepEvents.detect(pools, window, breaks, tf=tf)

    # The target is a REQUIRED field on LadderInputs and no engine producer exists for it.
    # A sentinel one bar-range away from entry is passed so the ladder can be built at all;
    # NOTHING IN THIS MODULE READS rr, and `test_the_ladder_does_not_depend_on_the_target`
    # proves the ladder is identical whatever this value is. It is deliberately not a
    # plausible target — a plausible one would invite a later reader to compute rr from it.
    span = max(b.high for b in window) - min(b.low for b in window)
    sentinel_target = entry + span if direction == "LONG" else entry - span

    try:
        inputs = LadderInputs(
            entry=entry,
            target=sentinel_target,
            direction=direction,  # type: ignore[arg-type]
            search_window_from=window[0].time,
            search_window_to=window[-1].time,
            swings=swings,
            imbalances=imbalances,
            sweeps=sweeps,
            pools=pools,
            breaks=breaks,
            msb=msb,
        )
    except ValueError:
        # A degenerate window where the sentinel lands on the wrong side of entry. Skipped
        # and NOT counted as a setup, rather than nudged into validity.
        return None

    return Setup(
        decision_index=decision_index,
        entry=entry,
        direction=direction,
        imbalance_id=poi.imbalance_id,
        poi_high=poi.price_high,
        poi_low=poi.price_low,
        msb_id=msb.id,
        ladder=tuple(StopCandidateLadder.build(inputs)),
        candidate_target_distances=candidate_target_distances(
            entry, direction, pools, imbalances
        ),
    )


def candidate_target_distances(
    entry: float, direction: str, pools: Sequence[Any], imbalances: Sequence[Any],
) -> tuple[float, ...]:
    """How far the objects a target could BE actually sit from entry.

    TARGET-001's candidates are `Objective`s wrapping "a liquidity pool or unfilled
    imbalance", and TARGET-003 orders them by distance. Neither can run here — the
    destination that selects among them has no producer — but the DISTANCES exist and are
    observable, and B127 requires the swept range to come from them rather than from a
    number this seat picked.

    THIS IS NOT A TARGET AND MUST NEVER BECOME ONE. It is the support of a distribution: it
    says where a target COULD lie, not which one is right. Choosing among these is exactly
    the level-1 decision TARGET-001 owns and cannot make.
    """
    out: list[float] = []
    for pool in pools:
        price = getattr(pool, "price", None)
        if price is None or getattr(pool, "state", None) in ("CONSUMED",):
            continue
        distance = price - entry if direction == "LONG" else entry - price
        if distance > 0:
            out.append(distance)
    for imbalance in imbalances:
        if getattr(imbalance, "fill_state", None) == "FILLED":
            continue
        edge = imbalance.price_high if direction == "LONG" else imbalance.price_low
        distance = edge - entry if direction == "LONG" else entry - edge
        if distance > 0:
            out.append(distance)
    return tuple(sorted(out))


def extract_setups(
    bars: Sequence[Bar],
    *,
    tf: str = "5m",
    corpus_bars: int = CORPUS_BARS,
    step_bars: int = STEP_BARS,
    placement: EntryPlacement = "MID",
) -> list[Setup]:
    """One extraction attempt per window. Returns the setups the entry path produced."""
    out: list[Setup] = []
    for decision_index, window in windows(
        bars, corpus_bars=corpus_bars, step_bars=step_bars
    ):
        setup = extract_setup(
            window, tf=tf, decision_index=decision_index, placement=placement
        )
        if setup is not None:
            out.append(setup)
    return out


def distinct_setups(setups: Sequence[Setup]) -> list[Setup]:
    """Deduplicated by the ENGINE'S OWN object identity: the selected `imbalance_id`.

    DECISION BARS ARE NOT SETUPS. Consecutive bars re-select the same POI, so counting bars
    measures how long an inventory persisted rather than how many setups it contained —
    B122's unit hazard one level down, and the reason this function exists rather than a
    `len()` at the call site. The first bar at which a POI is selected is kept, because a
    setup is first decidable when it first appears.
    """
    seen: set[str] = set()
    out: list[Setup] = []
    for setup in setups:
        if setup.imbalance_id in seen:
            continue
        seen.add(setup.imbalance_id)
        out.append(setup)
    return out


@dataclass(frozen=True)
class InversionReport:
    """`1b-i` — is the ladder cushion-monotonic, measured rather than asserted.

    PAIRS AND SETUPS ARE REPORTED SEPARATELY (1b-v). A setup with only two locatable rungs
    contributes one trivially-ordered pair, and pooling those with richer setups inflates
    the rate. Ties are non-strict and are counted apart for the same reason: "not an
    inversion" and "not a strict ordering" are different facts.
    """

    setups_considered: int
    setups_usable: int
    pairs: Interval
    setups_with_inversion: Interval
    tied_pairs: int
    rungs_locatable_histogram: dict[int, int]
    #: Which rungs ever located at all. Rung 4 has no producer; rung 2 needs a declared
    #: momentum width that nothing supplies.
    rung_locatable_counts: dict[int, int]
    placement: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "setups_considered": self.setups_considered,
            "setups_usable_for_monotonicity": self.setups_usable,
            "inverted_pairs": self.pairs.as_dict(),
            "setups_with_at_least_one_inversion": self.setups_with_inversion.as_dict(),
            "tied_pairs": self.tied_pairs,
            "rungs_locatable_histogram": dict(self.rungs_locatable_histogram),
            "rung_locatable_counts": dict(self.rung_locatable_counts),
            "entry_placement": self.placement,
        }


def inversion_report(
    setups: Sequence[Setup], *, placement: str = "MID",
) -> InversionReport:
    """Count pairs where a LATER rung carries a LARGER cushion than an EARLIER one.

    GATE-027's claim is that the ladder is cushion-monotonic — "the first options provide
    more room for natural pullbacks, while the later options progressively reduce that
    cushion" — so cushion should fall as the rung index rises. A pair `(i, j)` with `i < j`
    and `cushion_j > cushion_i` STRICTLY is an inversion. Equal cushions are ties and are
    counted apart.

    ONE INVERSION ANYWHERE FALSIFIES THE PROSE CLAIM, which is why the setup-level rate is
    reported alongside the pair-level one: a single badly-behaved setup and a uniformly
    badly-behaved corpus produce very different pair rates and the same boolean.
    """
    usable = 0
    inverted_pairs = 0
    total_pairs = 0
    tied = 0
    setups_inverted = 0
    histogram: dict[int, int] = {}
    per_rung: dict[int, int] = {}

    for setup in setups:
        located = setup.locatable
        histogram[len(located)] = histogram.get(len(located), 0) + 1
        for candidate in located:
            per_rung[candidate.rung] = per_rung.get(candidate.rung, 0) + 1
        if len(located) < 2:
            continue
        usable += 1
        this_setup_inverted = False
        for a_index in range(len(located)):
            for b_index in range(a_index + 1, len(located)):
                earlier, later = located[a_index], located[b_index]
                assert earlier.cushion is not None and later.cushion is not None
                total_pairs += 1
                if later.cushion > earlier.cushion:
                    inverted_pairs += 1
                    this_setup_inverted = True
                elif later.cushion == earlier.cushion:
                    tied += 1
        if this_setup_inverted:
            setups_inverted += 1

    return InversionReport(
        setups_considered=len(setups),
        setups_usable=usable,
        pairs=Interval(
            successes=inverted_pairs,
            trials=total_pairs,
            numerator_unit="rung PAIRS where a later rung had the larger cushion",
            denominator_unit="comparable rung PAIRS",
        ),
        setups_with_inversion=Interval(
            successes=setups_inverted,
            trials=usable,
            numerator_unit="SETUPS carrying at least one inversion",
            denominator_unit="SETUPS with >= 2 locatable rungs",
        ),
        tied_pairs=tied,
        rungs_locatable_histogram=dict(sorted(histogram.items())),
        rung_locatable_counts=dict(sorted(per_rung.items())),
        placement=placement,
    )



# ===========================================================================
# The target sensitivity sweep — criteria 4b and 7b, against B127's pinned criterion
# ===========================================================================
#: B127's flatness criterion, read from `git show bc2413c:KNOWN_ISSUES.md` — THE SECOND PIN.
#: The first, `4a2ed17`, is superseded rather than edited, per the entry's own rule that a
#: revision gets a new pinned commit. The 50% is unchanged between them; three requirements
#: were added, and one of them (inertness) changes what this code does.
#:
#:     "The swept firing rate is REPORTABLE iff it stays on ONE SIDE OF 50% across the whole
#:      declared target range. If the range straddles 50%, the rate is TARGET-DEPENDENT and
#:      reports as UNMEASURED."
#:
#: 50% because criterion 4b exists to answer ONE question — does the flag fire on most
#: setups (noise) or not (signal) — so that is where the answer changes. Not this seat's
#: number to move: disagreement argues with the 50% in a new pinned commit.
FLATNESS_THRESHOLD: float = 0.5


@dataclass(frozen=True)
class SweepRow:
    """One target, and what the flag did across the corpus at that target."""

    reward: float
    setups_with_a_selection: int
    fired: int
    rate: Interval
    #: The selected stop's rr across the corpus at this target. B127's inertness check reads
    #: these: if rr barely varies, flatness is a property of the sweep, not of the rate.
    min_selected_rr: float | None
    max_selected_rr: float | None
    accepted_candidates: int
    #: Which rung won, per setup. A sweep in which this never changes moved nothing.
    selected_rungs: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "reward": self.reward,
            "setups_with_a_selection": self.setups_with_a_selection,
            "fired": self.fired,
            "rate": self.rate.as_dict(),
            "min_selected_rr": self.min_selected_rr,
            "max_selected_rr": self.max_selected_rr,
            "accepted_candidates": self.accepted_candidates,
        }


@dataclass(frozen=True)
class SweepResult:
    """A TABLE of firing rate against target, and B127's verdict computed over it.

    THE VERDICT IS NOT A JUDGEMENT ABOUT WHETHER THE SPREAD "LOOKS FLAT". That judgement is
    the mental state B124 removed from the measuring seat and B127 removed a second time —
    the rule was fixed, in a commit that predates this run, by the seat that does not
    measure.

    TWO WAYS TO FAIL, AND THE SECOND IS THE ONE NEITHER SEAT NAMED FIRST:

        the rate crosses 50% inside the range     -> TARGET_DEPENDENT. The answer is an
                                                     artefact of a number nobody produces.
        nothing in the sweep ever moved           -> INERT. A flat line produced by a sweep
                                                     that could not have moved it proves
                                                     nothing, and it is INDISTINGUISHABLE
                                                     from robustness in the output.

    Both report UNMEASURED. Only a sweep that MOVED and did not CROSS is reportable.
    """

    flag: str
    rows: tuple[SweepRow, ...]
    reward_min: float
    reward_max: float
    range_derivation: str
    verdict: Literal["REPORTABLE", "TARGET_DEPENDENT", "INERT", "EMPTY"]
    reason: str
    #: What moved, so a reader can check the sweep was live rather than trust that it was.
    rr_span: tuple[float, float] | None
    selection_changed_on_setups: int
    admission_changed_on_setups: int
    #: B127 requirement 7 — adjacent rows whose selected rr is IDENTICAL. Any such pair is
    #: two targets that are one experiment, and its presence makes the sweep INERT.
    duplicate_adjacent_rows: tuple[tuple[float, float], ...] = ()

    def figure_name(self) -> str:
        """THE RANGE IS PART OF THE NAME, NOT A CAVEAT BESIDE IT — B127 requirement 5.

        "the rate is 12%" and "across targets in [a, b], the rate is 12%" differ by a clause,
        and the clause disappears on the first requote — which is `54 corpora` -> `54 setups`
        exactly. So the reportable figure is only ever produced WITH its range attached, and
        there is no accessor on this object that returns the bare number.
        """
        if self.verdict != "REPORTABLE":
            return (
                f"{self.flag}: UNMEASURED ({self.verdict}) — {self.reason}"
            )
        rates = [r.rate.rate for r in self.rows if r.rate.rate is not None]
        return (
            f"across targets in [{self.reward_min:.2f}, {self.reward_max:.2f}] price units "
            f"from entry, {self.flag} fires on {min(rates):.1%}-{max(rates):.1%} of setups "
            f"with a selected stop"
        )

    def table_text(self) -> str:
        lines = [
            f"{self.flag} firing rate vs target reward (price units from entry)",
            f"  range [{self.reward_min:.2f}, {self.reward_max:.2f}] — {self.range_derivation}",
            "   reward   fired /  sel     rate        95% CI        rr min-max   accepted",
        ]
        for row in self.rows:
            interval = row.rate.wilson
            ci = "         —" if interval is None else (
                f"  {interval[0] * 100:5.1f}-{interval[1] * 100:5.1f}%"
            )
            rate = "     —" if row.rate.rate is None else f"{row.rate.rate * 100:5.1f}%"
            rr = (
                "        —" if row.min_selected_rr is None
                else f"  {row.min_selected_rr:5.2f}-{row.max_selected_rr:5.2f}"
            )
            lines.append(
                f"  {row.reward:8.2f} {row.fired:5d} / {row.setups_with_a_selection:4d}"
                f"  {rate}{ci}{rr}  {row.accepted_candidates:6d}"
            )
        lines.append(
            f"  MOVED: rr span {self.rr_span}, selection changed on "
            f"{self.selection_changed_on_setups} setups, admission changed on "
            f"{self.admission_changed_on_setups}, adjacent rows with IDENTICAL rr: "
            f"{len(self.duplicate_adjacent_rows)}"
        )
        lines.append(f"  VERDICT: {self.verdict} — {self.reason}")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "flag": self.flag,
            "reward_min": self.reward_min,
            "reward_max": self.reward_max,
            "range_derivation": self.range_derivation,
            "verdict": self.verdict,
            "reason": self.reason,
            "figure_name": self.figure_name(),
            "rr_span": list(self.rr_span) if self.rr_span else None,
            "selection_changed_on_setups": self.selection_changed_on_setups,
            "admission_changed_on_setups": self.admission_changed_on_setups,
            "duplicate_adjacent_rows": [list(p) for p in self.duplicate_adjacent_rows],
            "rows": [r.as_dict() for r in self.rows],
            "flatness_threshold": FLATNESS_THRESHOLD,
            "flatness_criterion_pin": "git show bc2413c:KNOWN_ISSUES.md (B127, second pin)",
        }


def observed_target_range(setups: Sequence[Setup]) -> tuple[float, float]:
    """The min and max distance to an object a target could BE, across the corpus.

    B127 requirement 4: the range is MEASURED FROM THE CORPUS, not pinned. The Manager
    proposed pinning it and Review refused on this entry's own reasoning — nobody can derive
    a plausible-target range without the data, so a pinned one would move the arbitrariness
    rather than remove it.

    Returns `(0.0, 0.0)` when no setup carries a candidate objective at all, which is a real
    outcome and reports as EMPTY rather than as a default interval.
    """
    distances = [d for setup in setups for d in setup.candidate_target_distances]
    return (min(distances), max(distances)) if distances else (0.0, 0.0)


def target_sensitivity_sweep(
    setups: Sequence[Setup],
    *,
    flag: str = "TIGHTER_THAN_NECESSARY",
    steps: int = 25,
    eps: float | None = None,
    reward_range: tuple[float, float] | None = None,
) -> SweepResult:
    """Sweep the unproduced target across its observed range and report rate against it.

    NO TARGET IS CHOSEN. Every row is a different target, the table carries all of them, and
    B127's criterion — pinned before this ran — decides whether the rate is reportable at
    all. A single row would be the fitted number this exists to refuse.

    THE RULES ARE THE REAL ONES: `RewardFloor.table` prices the stored ladder against the
    row's target, `ClosestTo3RSelector.select` chooses, and the flag classes evaluate. A
    re-derivation here could disagree with the engine, and the sweep would then be a
    measurement of this function.
    """
    low, high = reward_range if reward_range is not None else observed_target_range(setups)
    derivation = (
        "min and max distance from entry to a candidate objective — unresolved liquidity "
        "pools (PRIM-003) and unfilled imbalances (PRIM-002) in the trade direction, the "
        "objects TARGET-001 selects among — measured over the setups themselves"
    )
    if high <= 0.0 or high <= low:
        return SweepResult(
            flag=flag, rows=(), reward_min=low, reward_max=high,
            range_derivation=derivation, verdict="EMPTY",
            reason="no setup carries a candidate objective, so there is no range to sweep",
            rr_span=None, selection_changed_on_setups=0, admission_changed_on_setups=0,
        )

    rows: list[SweepRow] = []
    selection_history: dict[int, set[int]] = {}
    admission_history: dict[int, set[tuple[bool, ...]]] = {}
    all_rrs: list[float] = []

    for step in range(steps):
        reward = low + (high - low) * step / max(1, steps - 1)
        fired = 0
        selections = 0
        accepted_total = 0
        rrs: list[float] = []
        rungs: list[int] = []
        for index, setup in enumerate(setups):
            target = (
                setup.entry + reward if setup.direction == "LONG" else setup.entry - reward
            )
            inputs = LadderInputs(
                entry=setup.entry, target=target,
                direction=setup.direction,  # type: ignore[arg-type]
                search_window_from=T_SENTINEL, search_window_to=T_SENTINEL,
            )
            table = RewardFloor.table(inputs, list(setup.ladder))
            accepted_total += sum(1 for c in table if c.accepted)
            admission_history.setdefault(index, set()).add(
                tuple(c.accepted for c in table)
            )
            selected = ClosestTo3RSelector.select(table)
            if selected is None:
                continue
            selections += 1
            selection_history.setdefault(index, set()).add(selected.rung)
            rungs.append(selected.rung)
            if selected.rr is not None:
                rrs.append(selected.rr)
            if flag == "TIGHTER_THAN_NECESSARY":
                fired += bool(TighterThanNecessary.wider_survivors(table, selected))
            elif flag == "DEGENERATE_RUNNER":
                fired += bool(DegenerateRunner.flags(selected.rr, eps=eps))
            elif flag == "RR_ABOVE_ACCEPTABLE_BAND":
                fired += bool(RRAboveAcceptableBand.flags(selected.rr))
            else:
                raise ValueError(f"unknown flag {flag!r}")
        all_rrs.extend(rrs)
        rows.append(SweepRow(
            reward=reward,
            setups_with_a_selection=selections,
            fired=fired,
            rate=Interval(
                successes=fired, trials=selections,
                numerator_unit=f"SETUPS where {flag} fired",
                denominator_unit="SETUPS with a selected stop at this target",
            ),
            min_selected_rr=min(rrs) if rrs else None,
            max_selected_rr=max(rrs) if rrs else None,
            accepted_candidates=accepted_total,
            selected_rungs=tuple(rungs),
        ))

    selection_changed = sum(1 for v in selection_history.values() if len(v) > 1)
    admission_changed = sum(1 for v in admission_history.values() if len(v) > 1)
    rr_span = (min(all_rrs), max(all_rrs)) if all_rrs else None
    measured = [r.rate.rate for r in rows if r.rate.rate is not None]

    # B127 REQUIREMENT 7, THE THIRD PIN: `rr` must DIFFER between every adjacent pair of
    # rows. Requirement 6 asked whether the sweep moved SOMEWHERE, which lets an active
    # extreme launder an inert middle — the reported figure can come from an interval in
    # which nothing changed. Identical rr on consecutive rows means those two targets are
    # ONE EXPERIMENT RUN TWICE, and the check is per-row precisely so there is no aggregate
    # left to be inert about.
    duplicate_adjacent = [
        (rows[i].reward, rows[i + 1].reward)
        for i in range(len(rows) - 1)
        if (rows[i].min_selected_rr, rows[i].max_selected_rr)
        == (rows[i + 1].min_selected_rr, rows[i + 1].max_selected_rr)
    ]

    # INERTNESS IS CHECKED BEFORE FLATNESS, because a flat line from a sweep that could not
    # move is indistinguishable from robustness and reads as the flattering answer.
    if not measured:
        verdict: Literal["REPORTABLE", "TARGET_DEPENDENT", "INERT", "EMPTY"] = "EMPTY"
        reason = "no row produced a selection, so there is no rate to judge"
    elif duplicate_adjacent:
        verdict = "INERT"
        reason = (
            f"{len(duplicate_adjacent)} adjacent row pair(s) carry IDENTICAL selected rr "
            f"— e.g. rewards {duplicate_adjacent[0][0]:.2f} and "
            f"{duplicate_adjacent[0][1]:.2f} — so those targets are one experiment run "
            "twice and the interval between them cannot support a point-by-point claim "
            "(B127 requirement 7)"
        )
    elif selection_changed == 0 and admission_changed == 0:
        verdict = "INERT"
        reason = (
            "no candidate crossed the 2R floor and no selected rung changed anywhere in "
            f"the range; selected rr spanned {rr_span}. The sweep could not have moved the "
            "rate, so its flatness is a property of the sweep and not of the rate"
        )
    elif all(r < FLATNESS_THRESHOLD for r in measured):
        verdict = "REPORTABLE"
        reason = (
            f"every row sits below {FLATNESS_THRESHOLD:.0%} (max {max(measured):.1%}) and "
            f"the sweep moved: admission changed on {admission_changed} setups, selection "
            f"on {selection_changed}"
        )
    elif all(r > FLATNESS_THRESHOLD for r in measured):
        verdict = "REPORTABLE"
        reason = (
            f"every row sits above {FLATNESS_THRESHOLD:.0%} (min {min(measured):.1%}) and "
            f"the sweep moved: admission changed on {admission_changed} setups, selection "
            f"on {selection_changed}"
        )
    else:
        verdict = "TARGET_DEPENDENT"
        reason = (
            f"the swept rate spans {min(measured):.1%}-{max(measured):.1%} and touches or "
            f"crosses {FLATNESS_THRESHOLD:.0%}, so the answer is an artefact of a target "
            "nobody produces"
        )

    return SweepResult(
        flag=flag, rows=tuple(rows), reward_min=low, reward_max=high,
        range_derivation=derivation, verdict=verdict, reason=reason,
        rr_span=rr_span, selection_changed_on_setups=selection_changed,
        admission_changed_on_setups=admission_changed,
        duplicate_adjacent_rows=tuple(duplicate_adjacent),
    )


# ===========================================================================
# Criterion 7a's SECONDARY measurement — rung 4 via an EXPLICITLY LABELLED PROXY
# ===========================================================================
#: The anchor name the proxy rung carries. DELIBERATELY NOT `ORDER_BLOCK`.
#:
#: `GATE-027`'s rung 4 is a contract-side order block and NOTHING PRODUCES ONE — six PRIM
#: rules and none emits them, which is why `StopCandidateLadder` emits rung 4 with
#: `missing_producer` and declares `CANNOT_FIRE_WITHOUT`. `detect_order_blocks()` at
#: `ict/detector.py:192` is the PRE-CONTRACT ICT strategy, and adopting its semantics as
#: doctrine is the move `TARGET-001` refuses.
#:
#: The plan grants it for MEASUREMENT and forbids it for SELECTION, so the name says which
#: it is. A number computed from this rung is about the PROXY and not about a contract-side
#: order block, and the two must never be reported as one figure or averaged into one.
ORDER_BLOCK_PROXY_ANCHOR = "ORDER_BLOCK_ICT_PROXY"

#: The volume column the ICT detector requires and the fixture does not have.
#:
#: MEASURED, NOT ASSUMED, because a synthesized input that changed what was detected would
#: make the whole secondary measurement an artefact of the synthesis. The detected order
#: block SET is IDENTICAL under three unrelated volume series — constant 1.0, uniform random,
#: and per-bar high-low range — over the first 863-bar window: 7 order blocks, same indices,
#: same edges, same directions. Volume reaches only `OBVolume` -> `confidence`, which this
#: measurement never reads. `test_the_proxy_does_not_depend_on_the_synthesized_volume` pins it.
PROXY_SYNTHETIC_VOLUME: float = 1.0


def order_block_proxy_anchor(
    window: Sequence[Bar], entry: float, direction: str,
) -> tuple[float, str] | None:
    """The deepest ICT order-block edge on the stop side. A PROXY. Never for selection.

    "Deepest" matches what rungs 2 and 3 already do for zone anchors — `max` by distance
    from entry — so the proxy rung is placed by the same rule as its neighbours rather than
    by a new one invented for it.
    """
    import pandas as pd

    from app.services.ict.detector import ICTDetector

    frame = pd.DataFrame({
        "open": [b.open for b in window],
        "high": [b.high for b in window],
        "low": [b.low for b in window],
        "close": [b.close for b in window],
        "volume": [PROXY_SYNTHETIC_VOLUME] * len(window),
    })
    blocks = ICTDetector().detect_order_blocks(frame)
    edges: list[tuple[float, str]] = []
    for index, block in enumerate(blocks):
        # A zone, so it has two edges; the far one clears the whole object, which is
        # PRIM-006's rule applied to the proxy exactly as GATE-027 applies it to rung 2.
        edge = block["price_low"] if direction == "LONG" else block["price_high"]
        on_stop_side = edge < entry if direction == "LONG" else edge > entry
        if on_stop_side:
            edges.append((float(edge), f"ICT-OB-{block.get('candle_index', index)}"))
    if not edges:
        return None
    return max(edges, key=lambda pair: abs(entry - pair[0]))


def with_order_block_proxy(setup: Setup, window: Sequence[Bar]) -> Setup:
    """A copy of `setup` whose rung 4 carries the PROXY instead of the producer gap.

    Returns a NEW Setup rather than mutating: the primary ladder must stay exactly what
    `GATE-027` built, so that the primary and secondary numbers are computed from two
    distinct objects and cannot silently become one.
    """
    found = order_block_proxy_anchor(window, setup.entry, setup.direction)
    if found is None:
        return setup
    price, object_id = found
    ladder = tuple(
        StopCandidate(
            rung=c.rung, anchor=ORDER_BLOCK_PROXY_ANCHOR, locatable=True,
            stop_price=price, anchor_object_id=object_id, _entry=setup.entry,
        )
        if c.anchor == "ORDER_BLOCK" else c
        for c in setup.ladder
    )
    return Setup(
        decision_index=setup.decision_index, entry=setup.entry,
        direction=setup.direction, imbalance_id=setup.imbalance_id,
        poi_high=setup.poi_high, poi_low=setup.poi_low, msb_id=setup.msb_id,
        ladder=ladder, candidate_target_distances=setup.candidate_target_distances,
    )


def extract_setups_with_proxy(
    bars: Sequence[Bar],
    *,
    tf: str = "5m",
    corpus_bars: int = CORPUS_BARS,
    step_bars: int = STEP_BARS,
    placement: EntryPlacement = "MID",
) -> tuple[list[Setup], list[Setup]]:
    """Both ladders from ONE pass: `(primary, secondary)`.

    Returned as a pair so a caller cannot accidentally hold only the proxied one — the plan
    forbids reporting the secondary alone, and returning them together makes that the
    default rather than a rule to remember.
    """
    primary: list[Setup] = []
    secondary: list[Setup] = []
    for decision_index, window in windows(
        bars, corpus_bars=corpus_bars, step_bars=step_bars
    ):
        setup = extract_setup(
            window, tf=tf, decision_index=decision_index, placement=placement
        )
        if setup is None:
            continue
        primary.append(setup)
        secondary.append(with_order_block_proxy(setup, window))
    return primary, secondary
