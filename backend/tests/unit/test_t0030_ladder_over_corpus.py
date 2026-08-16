"""T-0030's corpus measurements — the setup denominator, `1b-i`, and the target sweep.

WHICH ASSERTIONS READ WHAT, because they mean different things when they go red:

    the MEASURED block below reads `tests/fixtures/btcusdtp_5m_1500.csv`, PINNED. Nothing
    fetches, the market cannot move under it, so a red run is unambiguously a defect.

    the SWEEP-INSTRUMENT tests read constructed setups only. They exist to prove the
    verdict machinery can return each of its answers — a verdict function that always says
    REPORTABLE would pass every corpus assertion in this file.

THE SLOW HALF IS DELIBERATELY HERE AND NOT IN `test_t0030_stop_flags.py`. Extraction runs
the five primitive detectors over an 863-bar window per decision bar; at step 12 that is 54
windows and tens of seconds. The conformance suite stays fast and fails for a different
reason than a measurement does.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.rules.gate_027_stop_ladder import (
    LadderInputs, StopCandidate, StopCandidateLadder,
)
from app.services.rules.prim_001_swings import Bar
from app.services.rules.stop_ladder_corpus import (
    CORPUS_BARS, DECLARED_ENTRY_PLACEMENT, FLATNESS_THRESHOLD, STEP_BARS, Interval, Setup,
    distinct_setups, extract_setups, inversion_report, observed_target_range,
    target_sensitivity_sweep, windows,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "btcusdtp_5m_1500.csv"
T0 = datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc)

#: MEASURED on the pinned fixture at STEP 12, 2026-08-17. Recorded so a change in these
#: shows up as a change rather than as a differently-worded pass — T-0017's convention.
#:
#: STEP 12 IS THE TEST'S STEP, NOT THE REPORT'S. The headline denominator is measured at
#: STEP 1 (every decision bar with an 863-bar lookback) and is in the work report; step 12
#: is the same instrument sampled every twelfth bar, chosen here because 54 windows is
#: seconds and 638 is minutes. Both numbers state their step, because "n setups" measured at
#: two different steps are two different quantities.
MEASURED_STEP_12 = {
    "windows": 54,
    "setups": 49,
    "distinct": 49,
    "no_poi_at_the_decision_price": 5,
}


def _bars() -> list[Bar]:
    out: list[Bar] = []
    with FIXTURE.open() as fh:
        for row in csv.DictReader(fh):
            out.append(Bar(
                time=datetime.fromisoformat(row["time"]),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
            ))
    return out


@pytest.fixture(scope="module")
def bars() -> list[Bar]:
    return _bars()


@pytest.fixture(scope="module")
def setups(bars: list[Bar]) -> list[Setup]:
    """Extracted once per module — the detectors are the expensive part, not the assertions."""
    return extract_setups(bars, step_bars=STEP_BARS, placement="MID")


# ===========================================================================
# The claim that rescues criterion 7a, turned from asserted into measured
# ===========================================================================
def test_the_ladder_does_not_depend_on_the_target():
    """THE LOAD-BEARING STRUCTURAL CLAIM OF THIS WHOLE TASK, measured rather than read.

    `rr` needs a target and nothing produces one, so every rr-derived rate is unmeasurable.
    `1b-i` survives ONLY because it reads cushion — and that is worth nothing unless the
    ladder itself is target-free. Three wildly different targets, same ladder.

    FAILING INPUT, stated in advance and the Manager's too: make any locator read
    `inputs.target` — e.g. filter `_deepest_swing`'s pool by `s.price < inputs.target`. The
    three ladders then differ and this fails. A reading-based check would not have caught
    it: the Manager's first grep reported 4 target references in all four locators because
    a `sed` range never terminated, and four identical counts was the tell.
    """
    from app.services.rules.prim_001_swings import Swing
    from app.services.rules.prim_005_breaks import BreakEvent

    def ladder_for(target: float) -> list[tuple[int, bool, float | None]]:
        inputs = LadderInputs(
            entry=100.0, target=target, direction="LONG",
            search_window_from=T0, search_window_to=T0,
            msb=BreakEvent(id="MSB-1", tf="5m", bar_time=T0, type="MSB", scale="MAJOR",
                           consumed_swing_id="S-0", break_price=99.0, bar_index=5),
            swings=[Swing(id="S-1", tf="5m", bar_time=T0, price=70.0, kind="LOW",
                          bar_index=9)],
            breaks=[BreakEvent(id="BRK-1", tf="5m", bar_time=T0, type="MSB", scale="MINOR",
                               consumed_swing_id="S-1", break_price=97.0, bar_index=11)],
        )
        return [(c.rung, c.locatable, c.stop_price) for c in StopCandidateLadder.build(inputs)]

    near, mid, far = ladder_for(101.0), ladder_for(130.0), ladder_for(10_000.0)
    assert near == mid == far, (
        "the ladder must be identical under any target — this is the claim that makes the "
        "inversion rate measurable at all"
    )
    # control: the same helper DOES respond to something it should respond to, so the
    # equality above is a property of the target and not of a frozen helper.
    assert ladder_for(130.0) != [(r, loc, p) for r, loc, p in mid if r != 1] , (
        "control: the comparison is capable of returning unequal"
    )


def test_the_shadow_setup_predicate_has_not_drifted():
    """CRITERION 1's producer is `shadow.py:680`, and this file must not hold a second one.

    The predicate is READ AS TEXT rather than imported, so no edge from these measurements
    into `live/` is created (criterion 12). The cost is that it can drift silently, which is
    what this closes.

    FAILING INPUT: change `shadow.py`'s line to `bool(imbalances) or bool(breaks)`. The
    must-hit below stops matching and this fails, which is correct — the denominator would
    then mean something else and the report's `n` would be measuring a different quantity.
    """
    shadow = (
        Path(__file__).resolve().parents[2] / "app" / "services" / "live" / "shadow.py"
    ).read_text()
    must_hit = "setup_in_play = bool(imbalances) and bool(breaks)"
    assert must_hit in shadow, (
        "the existing entry path's setup predicate has changed; T-0030's denominator is "
        "defined as this line and must be re-derived rather than silently kept"
    )
    assert "setup_in_play = bool(imbalances) or bool(breaks)" not in shadow, (
        "control: the must-miss variant is genuinely absent, so the match above is a read "
        "and not a substring that would hit either way"
    )
    assert "zzz_predicate_that_is_not_there" not in shadow, "control: absent token"


# ===========================================================================
# CRITERION 1 — the denominator, and both of its units
# ===========================================================================
def test_the_windowing_is_the_existing_one_and_yields_54(bars: list[Bar]):
    """REUSE, NOT REBUILD. Same constants as `validate_over_corpora()`, same 54.

    The arithmetic is re-derived from the fixture length rather than read from the
    constant, exactly as T-0017 does, so a wrong constant cannot agree with itself.

    FAILING INPUT: change CORPUS_BARS or STEP_BARS. Both sides move apart and this fails.
    """
    assert len(bars) == 1500
    assert len(list(windows(bars))) == len(range(0, 1500 - CORPUS_BARS + 1, STEP_BARS))
    assert len(list(windows(bars))) == MEASURED_STEP_12["windows"]


def test_the_setup_count_is_not_the_window_count(setups: list[Setup]):
    """THE UNIT COLLISION, PINNED. `n` must be a measurement, not a restatement of 54.

    Calling ENTRY-001 WITHOUT `at_price` returns a POI on every window and yields exactly
    54 setups — n equal to the window count BY CONSTRUCTION. That is `54 corpora` vs `54
    setups` (B122) arriving on the very number the entry is about. Supplying the location,
    as ENTRY-001's own docstring requires, 5 windows carry no POI at the decision price.

    FAILING INPUT: drop `at_price` from the extractor's ENTRY-001 call. The count becomes
    54, equal to the window count, and both assertions below fail.
    """
    assert len(setups) == MEASURED_STEP_12["setups"]
    assert len(setups) != MEASURED_STEP_12["windows"], (
        "if these are ever equal the denominator has collapsed into the window count and "
        "no comparison in the report can catch it, because there is only one figure"
    )
    assert (
        MEASURED_STEP_12["windows"] - len(setups)
        == MEASURED_STEP_12["no_poi_at_the_decision_price"]
    )


def test_distinct_setups_deduplicate_on_the_engines_own_object_identity(setups):
    """DECISION BARS ARE NOT SETUPS — the ruling's requirement (d), second half.

    At step 12 every window happens to select a different POI, so dedup changes nothing
    HERE; the reduction appears at step 1, where consecutive bars re-select one inventory.
    This asserts the mechanism rather than the reduction, because the mechanism is what
    would silently stop working.

    FAILING INPUT: dedup on `decision_index` instead of `imbalance_id`. The constructed
    pair below then survives as two setups and this fails.
    """
    assert len(distinct_setups(setups)) == MEASURED_STEP_12["distinct"]

    shared = setups[0]
    twin = Setup(
        decision_index=shared.decision_index + 1, entry=shared.entry,
        direction=shared.direction, imbalance_id=shared.imbalance_id,
        poi_high=shared.poi_high, poi_low=shared.poi_low, msb_id=shared.msb_id,
        ladder=shared.ladder,
    )
    assert len(distinct_setups([shared, twin])) == 1, (
        "two decision bars selecting the SAME imbalance are one setup seen twice"
    )


def test_the_entry_placement_is_declared_and_not_hardcoded():
    """The ruling's requirement (d), first half. A third placement choice, declared.

    FAILING INPUT: set `ratified=True`, or drop the authority. Either makes an engine
    choice read as a trader ruling — the asymmetry GATE-027 already avoids twice.
    """
    assert DECLARED_ENTRY_PLACEMENT.ratified is False
    assert DECLARED_ENTRY_PLACEMENT.authority.startswith("ENGINEERING")
    assert DECLARED_ENTRY_PLACEMENT.value == "MID"
    assert "FAR_EDGE" in str(DECLARED_ENTRY_PLACEMENT.competing)


def test_cushion_order_is_shift_invariant_so_the_placement_channel_is_membership_only():
    """THE STATED CHANNEL. A three-way agreement without one looks like a coincidence.

    Moving entry by `d` adds `d` to every cushion on the stop side, so the ORDER of cushions
    cannot change. The only way the placement choice can move the inversion rate is by
    changing WHICH anchors pass `is_on_stop_side` — set membership, not ordering.

    FAILING INPUT: this is a claim about arithmetic, so the failing input is a cushion
    definition that is not a distance from entry — e.g. keying cushion on the stop price
    itself. The shifted order below then differs from the unshifted one.
    """
    stops = [70.0, 85.0, 90.0, 97.0]
    for entry in (100.0, 100.5, 101.0):
        cushions = [abs(entry - s) for s in stops]
        assert cushions == sorted(cushions, reverse=True), (
            "order is preserved under any entry above every stop — the shift-invariance "
            "the report cites"
        )
    # and the membership channel is real: at entry 88 two of the four stops are no longer
    # below entry at all, which is exactly how the three placements can disagree.
    assert sum(1 for s in stops if s < 88.0) == 2


# ===========================================================================
# CRITERION 7a — the measurement itself, and its units
# ===========================================================================
def test_the_inversion_rate_carries_its_unit_denominator_and_interval(setups):
    """CRITERION 7c and 2a. A figure without unit, denominator and interval is disputable.

    FAILING INPUT: return a bare float from `inversion_report`. Every accessor below
    disappears and this fails at the first one.
    """
    report = inversion_report(setups, placement="MID")
    assert report.setups_considered == len(setups)
    for interval in (report.pairs, report.setups_with_inversion):
        assert interval.numerator_unit and interval.denominator_unit
        assert interval.wilson is not None
        summary = interval.summary()
        assert "95% CI" in summary and interval.denominator_unit in summary
    assert report.pairs.successes > 0, (
        "GATE-027 asserts cushion-monotonicity IN PROSE; this corpus contains inversions, "
        "so the prose claim is FALSE on real data and the flag is reachable"
    )


def test_rung_two_never_locates_because_no_declared_momentum_width_exists(setups):
    """A FINDING, PINNED: the plan's PRIMARY split is rungs 1,2,3,5 and rung 2 cannot fire.

    `is_momentum_imbalance` is set only when a `momentum_min_width` is supplied, and nothing
    in `app/` supplies one — `evaluate_layout` defaults it to None and `shadow.py` never
    passes it. So the measurable ladder is rungs 1, 3 and 5, and rung 4 has no producer.

    FAILING INPUT: pass a `momentum_min_width` in the extractor. Rung 2 starts locating and
    this fails — correctly, because the measurement would then be of a ladder the engine
    does not run.
    """
    report = inversion_report(setups, placement="MID")
    assert 2 not in report.rung_locatable_counts, (
        "rung 2 must never locate under production settings"
    )
    assert 4 not in report.rung_locatable_counts, "rung 4 has no producer at all"
    assert {1, 3, 5} >= set(report.rung_locatable_counts), (
        f"only rungs 1, 3 and 5 can locate; saw {sorted(report.rung_locatable_counts)}"
    )


def test_a_wilson_interval_is_computed_and_not_stubbed():
    """The interval is the mechanism that stops `n` hiding behind a percentage (B124).

    Checked against two hand-verifiable properties rather than a recomputation of the same
    formula: it must contain the point estimate, and it must NARROW as `n` grows at a fixed
    rate. A stub returning (0, 1) satisfies neither.

    FAILING INPUT: return `(0.0, 1.0)` from `wilson`. The narrowing assertion fails.
    """
    small = Interval(successes=2, trials=6, numerator_unit="x", denominator_unit="y")
    large = Interval(successes=200, trials=600, numerator_unit="x", denominator_unit="y")
    for interval in (small, large):
        low, high = interval.wilson  # type: ignore[misc]
        assert low <= interval.rate <= high  # type: ignore[operator]
    small_width = small.wilson[1] - small.wilson[0]      # type: ignore[index]
    large_width = large.wilson[1] - large.wilson[0]      # type: ignore[index]
    assert large_width < small_width / 5, (
        "a real interval narrows with n; ten times the data must not give the same width"
    )
    assert "2 of 6" in small.summary(), "n travels inside the number"

    empty = Interval(successes=0, trials=0, numerator_unit="x", denominator_unit="SETUPS")
    assert empty.rate is None and empty.wilson is None, (
        "a rate over zero trials is not a rate, and 0.0 would read as 'none of them'"
    )
    assert "UNMEASURED" in empty.summary()


# ===========================================================================
# CRITERIA 4b / 7b — the sweep, and the instrument that judges it
# ===========================================================================
def _setup_with(cushions: list[float], *, entry: float = 100.0, index: int = 0,
                distances: tuple[float, ...] = (10.0, 60.0)) -> Setup:
    """A setup whose ladder sits at the given cushions below entry."""
    ladder = tuple(
        StopCandidate(
            rung=rung, anchor=f"A{rung}", locatable=True, stop_price=entry - cushion,
            anchor_object_id=f"OBJ-{rung}", _entry=entry,
        )
        for rung, cushion in enumerate(cushions, start=1)
    )
    return Setup(
        decision_index=index, entry=entry, direction="LONG",
        imbalance_id=f"IMB-{index}", poi_high=entry + 1, poi_low=entry - 1,
        msb_id="MSB-1", ladder=ladder, candidate_target_distances=distances,
    )


def test_the_sweep_reports_target_dependent_when_the_rate_crosses_fifty_percent():
    """THE MUST-HIT ARM. B127's criterion must be able to return TARGET_DEPENDENT.

    NAMED FAILING INPUT for the sweep as a whole, which B127 requirement 3 demands: a
    corpus of setups with three well-separated cushions, so that at a small target only the
    tightest rung clears 2R (nothing wider to pass over, no flag) while at a large target
    several clear it and a tighter one sits nearer 3R (flag). That input is constructed
    here, and it makes the sweep cross 50%.

    FAILING INPUT for THIS test: a verdict function hardwired to REPORTABLE. It fails here
    and passes every corpus assertion in the file, which is why this arm exists.
    """
    # Cushions 30 and 20. The flag fires only while the TIGHTER rung sits nearer 3R than
    # the wider one, i.e. |R/30 - 3| > |R/20 - 3|, which holds for 60 <= R < 72 and for no
    # other target. Solving it: 3 - R/30 = R/20 - 3 gives R = 72. So the rate is 1.0 inside
    # a narrow band of the range and 0.0 outside it — a crossing by construction, derived
    # rather than found by trying corpora until one straddled.
    #
    # The range starts at 40 = 2 x the tightest cushion so that EVERY row admits a
    # candidate. Starting lower produces leading rows with no selection at all, whose rr is
    # None on both, and requirement 7 correctly calls those adjacent duplicates — which
    # would return INERT before flatness was ever consulted.
    corpus = [
        _setup_with([30.0, 20.0], index=i, distances=(40.0, 120.0)) for i in range(10)
    ]
    result = target_sensitivity_sweep(corpus, flag="TIGHTER_THAN_NECESSARY", steps=25)
    rates = [r.rate.rate for r in result.rows if r.rate.rate is not None]
    assert min(rates) < FLATNESS_THRESHOLD < max(rates), (
        f"the constructed corpus must straddle 50%; got {min(rates)}-{max(rates)}"
    )
    assert not result.duplicate_adjacent_rows, (
        "this arm must reach the flatness test, so it must not trip inertness first"
    )
    assert result.verdict == "TARGET_DEPENDENT"
    assert "UNMEASURED" in result.figure_name()


def test_the_sweep_reports_inert_when_nothing_moves_between_adjacent_rows():
    """B127 REQUIREMENT 7, THE THIRD PIN. Identical rr on adjacent rows is one experiment.

    A single-rung ladder cannot change selection or admission across most of the range, and
    a range with only one distinct distance collapses to duplicate rows.

    FAILING INPUT: check flatness BEFORE inertness. This corpus is perfectly flat, so it
    would return REPORTABLE — which is the exact laundering B127 requirement 6 was written
    for and requirement 7 closed.
    """
    # A single-rung ladder at cushion 25, swept from 10 to 100. Below R = 50 nothing clears
    # 2R, so the first four rows have no selection and no rr at all — four different targets
    # producing one identical experiment. Above it the rate is flat at 0.0. The whole table
    # is on one side of 50% and would read REPORTABLE under the second pin.
    corpus = [_setup_with([25.0], index=i, distances=(10.0, 100.0)) for i in range(10)]
    result = target_sensitivity_sweep(corpus, flag="TIGHTER_THAN_NECESSARY", steps=8)
    rates = [r.rate.rate for r in result.rows if r.rate.rate is not None]
    assert rates and len(set(rates)) == 1, "the measured rows are perfectly flat"
    assert all(r < FLATNESS_THRESHOLD for r in rates), (
        "and they are all on ONE SIDE of 50%, which is what would have passed"
    )
    assert result.duplicate_adjacent_rows, "the duplicate adjacent rows must be reported"
    assert result.verdict == "INERT", (
        "a flat rate from a sweep that could not move must NOT be reportable"
    )
    assert "UNMEASURED" in result.figure_name()


def test_a_reportable_sweep_must_have_moved_and_carries_its_range_in_the_figure_name():
    """THE MUST-NOT-FIRE ARM plus B127 requirement 5. Not every sweep is UNMEASURED.

    Without this arm, a verdict function hardwired to UNMEASURED would pass every other
    assertion here — the mirror of the previous test, and the pair is what makes either one
    evidence.

    FAILING INPUT: return the bare rate from `figure_name()`. The range disappears from the
    name, which is `54 corpora` -> `54 setups`: a real number carried out of the scope that
    made it real.
    """
    # Cushions 60/30/10 over targets 20..120. Admission and selection both move — rungs
    # enter the accepted set as the target grows — and the widest accepted candidate is
    # always the one nearest 3R, so the flag never fires and the rate is flat at 0% on ONE
    # SIDE of 50%. This is the genuinely-robust case, and it must come out REPORTABLE.
    corpus = [
        _setup_with([60.0, 30.0, 10.0], index=i, distances=(20.0, 120.0)) for i in range(10)
    ]
    result = target_sensitivity_sweep(corpus, flag="TIGHTER_THAN_NECESSARY", steps=9)
    assert result.verdict == "REPORTABLE", f"{result.verdict} — {result.reason}"
    assert result.selection_changed_on_setups and result.admission_changed_on_setups, (
        "REPORTABLE requires the sweep to have MOVED, and this records what moved"
    )
    assert not result.duplicate_adjacent_rows
    name = result.figure_name()
    assert "across targets in [" in name and "price units from entry" in name, (
        "the range is part of the name; a bare rate must not be quotable"
    )
    assert result.rr_span is not None and result.rr_span[0] < result.rr_span[1], (
        "rr must vary across the range or the sweep proved nothing"
    )


def test_the_swept_range_is_measured_from_the_corpus_and_not_pinned(setups):
    """B127 REQUIREMENT 4. The range is a measurement a reviewer can recompute.

    FAILING INPUT: hardcode the range inside the sweep. `observed_target_range` then stops
    being what the sweep uses, and the equality below fails.
    """
    low, high = observed_target_range(setups)
    assert 0.0 < low < high, "the observed distances must bound a real interval"
    result = target_sensitivity_sweep(setups[:6], flag="TIGHTER_THAN_NECESSARY", steps=5)
    expected = observed_target_range(setups[:6])
    assert (result.reward_min, result.reward_max) == expected
    assert "measured over the setups themselves" in result.range_derivation


def test_the_sweep_uses_the_real_rules_and_not_a_reimplementation():
    """A sweep that re-derives selection could disagree with the engine silently.

    FAILING INPUT: replace the selector call with a local `min()` that omits the tie-break.
    On the tie-carrying corpus below the two disagree, and the assertion fails.
    """
    from app.services.rules.gate_027_stop_ladder import ClosestTo3RSelector, RewardFloor

    setup = _setup_with([30.0, 15.0], distances=(45.0, 45.0))
    inputs = LadderInputs(entry=100.0, target=145.0, direction="LONG",
                          search_window_from=T0, search_window_to=T0)
    table = RewardFloor.table(inputs, list(setup.ladder))
    selected = ClosestTo3RSelector.select(table)
    assert selected is not None
    result = target_sensitivity_sweep(
        [setup], flag="TIGHTER_THAN_NECESSARY", steps=2, reward_range=(45.0, 45.0),
    )
    # the range is degenerate on purpose: the sweep must report EMPTY rather than invent a
    # spread, and the engine's own selector is what priced the row above.
    assert result.verdict == "EMPTY"
    assert selected.rr == pytest.approx(45.0 / 15.0)


# ===========================================================================
# CRITERION 7a's SECONDARY — the labelled proxy, and the instrument behind it
# ===========================================================================
def test_the_proxy_does_not_depend_on_the_synthesized_volume(bars: list[Bar]):
    """THE INSTRUMENT, CHECKED BEFORE THE MEASUREMENT THAT USES IT.

    `detect_order_blocks()` needs a `volume` column and the pinned fixture has none, so one
    is synthesized. **A synthesized input that changed what was detected would make the whole
    secondary measurement an artefact of the synthesis** — and it would not error; it would
    return a different, well-formed set of order blocks.

    Three unrelated volume series over the same window must give the SAME order-block set.

    FAILING INPUT: a detector whose geometry reads volume — e.g. one filtering blocks by
    `OBVolume` above a threshold. The three sets then differ and this fails. The control
    below proves the comparison can return unequal, so agreement is a result and not a
    property of an empty list.
    """
    import numpy as np
    import pandas as pd

    from app.services.ict.detector import ICTDetector

    window = bars[:863]
    base = pd.DataFrame({
        "open": [b.open for b in window], "high": [b.high for b in window],
        "low": [b.low for b in window], "close": [b.close for b in window],
    })
    detector = ICTDetector()

    def blocks(volume):
        frame = base.copy()
        frame["volume"] = volume
        return sorted(
            (b["candle_index"], round(b["price_high"], 4), round(b["price_low"], 4),
             str(b["direction"]))
            for b in detector.detect_order_blocks(frame)
        )

    constant = blocks(1.0)
    random = blocks(np.random.default_rng(0).uniform(1.0, 100.0, len(base)))
    as_range = blocks((base["high"] - base["low"]).values + 1.0)

    assert constant, "the detector found nothing at all — the instrument, not the answer"
    assert constant == random == as_range, (
        "the detected order blocks must not depend on the synthesized volume"
    )
    assert constant != constant[:-1], "control: the comparison can return unequal"


def test_the_proxy_is_labelled_and_the_primary_ladder_is_left_alone(bars: list[Bar]):
    """PERMITTED FOR MEASUREMENT, FORBIDDEN FOR SELECTION — so the anchor says which it is.

    The proxy rung is named `ORDER_BLOCK_ICT_PROXY`, never `ORDER_BLOCK`, and the primary
    setup is a separate object that still carries the producer gap.

    FAILING INPUT: name the proxy rung `ORDER_BLOCK`, or mutate the setup in place instead
    of returning a copy. The first fails the label assertions; the second fails the primary
    assertions, because the two reports would then be computed from one ladder.
    """
    from app.services.rules.stop_ladder_corpus import (
        ORDER_BLOCK_PROXY_ANCHOR, extract_setup, with_order_block_proxy,
    )

    window = bars[:863]
    primary = extract_setup(window, decision_index=862, placement="MID")
    assert primary is not None
    secondary = with_order_block_proxy(primary, window)

    rung_4_primary = next(c for c in primary.ladder if c.rung == 4)
    assert rung_4_primary.anchor == "ORDER_BLOCK"
    assert rung_4_primary.locatable is False
    assert rung_4_primary.missing_producer == "order_block_detector", (
        "the PRIMARY ladder must still carry the producer gap, untouched"
    )

    rung_4_secondary = next(c for c in secondary.ladder if c.rung == 4)
    assert rung_4_secondary.anchor == ORDER_BLOCK_PROXY_ANCHOR != "ORDER_BLOCK", (
        "a number computed from this rung is about the PROXY, and the name must say so"
    )
    assert rung_4_secondary.locatable is True and rung_4_secondary.stop_price is not None

    # the other four rungs are the same objects — only rung 4 was replaced
    assert [c for c in primary.ladder if c.rung != 4] == [
        c for c in secondary.ladder if c.rung != 4
    ]


def test_the_proxy_rung_never_reaches_the_engines_ladder_builder():
    """The grant is for MEASUREMENT. `StopCandidateLadder` must never emit a proxy rung.

    FAILING INPUT: have `StopCandidateLadder.build` call `order_block_proxy_anchor`. The
    AST scan below then finds the call and this fails — which is the same guard T-0025a
    already applies to the detector itself, extended to the wrapper this task added.
    """
    import ast
    import inspect

    from app.services.rules import gate_027_stop_ladder

    tree = ast.parse(inspect.getsource(gate_027_stop_ladder))
    called = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    assert "order_block_proxy_anchor" not in called
    assert "detect_order_blocks" not in called
    # CONTROL, both arms: the scan must be able to see a call that IS there, and must not
    # see one that is not. Without the must-hit, an empty `called` would pass the two
    # assertions above while proving nothing.
    assert "risk_reward" in called, "control must-HIT: the module does call risk_reward"
    assert "zzz_absent_call_t0030" not in called, "control must-MISS"


def test_the_secondary_measurement_adds_rung_four_and_is_reported_apart(bars: list[Bar]):
    """CRITERION 7a's SECONDARY, at step 12. Reported BESIDE the primary, never instead.

    MEASURED at step 12, 2026-08-17 — the step-1 figures are in the work report:

        PRIMARY    rungs 1,3,5      11 of  67 pairs (16.4%)   10 of 49 setups (20.4%)
        SECONDARY  + proxy rung 4   20 of 170 pairs (11.8%)   10 of 49 setups (20.4%)

    THE TWO PAIR RATES ARE NOT COMPARABLE AND THE TEST SAYS SO BY ASSERTING BOTH
    DENOMINATORS. Adding a rung adds pairs, so the pooled pair rate moves even when nothing
    about the ladder's behaviour changed — which is exactly what happened: the SETUP-level
    rate is IDENTICAL, so the proxy rung introduced no newly-inverted setup.

    FAILING INPUT: report the secondary alone, or average the two. Both are forbidden by the
    plan, and the assertions below pin each number to its own rung set and denominator.
    """
    from app.services.rules.stop_ladder_corpus import (
        distinct_setups, extract_setups_with_proxy,
    )

    primary, secondary = extract_setups_with_proxy(bars, step_bars=STEP_BARS, placement="MID")
    p_report = inversion_report(distinct_setups(primary), placement="MID")
    s_report = inversion_report(distinct_setups(secondary), placement="MID")

    assert 4 not in p_report.rung_locatable_counts, "the PRIMARY must not contain rung 4"
    assert s_report.rung_locatable_counts[4] == 47, "the proxy located on 47 of 49 setups"

    assert (p_report.pairs.successes, p_report.pairs.trials) == (11, 67)
    assert (s_report.pairs.successes, s_report.pairs.trials) == (20, 170)

    assert p_report.setups_with_inversion.successes == 10
    assert s_report.setups_with_inversion.successes == 10, (
        "the proxy rung introduced NO newly-inverted setup — the setup-level rate is the "
        "one that is comparable across the two rung sets, and it did not move"
    )
    assert p_report.setups_usable == s_report.setups_usable == 49


def test_both_halves_of_the_extraction_choice_are_declared_not_just_one():
    """THE ASYMMETRY THIS MODULE WAS ABOUT TO REPEAT, closed and pinned.

    Two engine choices sit on the SAME ENTRY-001 call, one line apart: WHICH PRICE is "the
    location" (`at_price`), and WHERE IN THE POI BAND the scalar entry sits. Declaring one
    and hardcoding the other is worse than either alone — a reader who finds one declaration
    reasonably infers the undeclared one is doctrine. GATE-027 was caught on exactly this and
    now declares both of its placements; this module declares both of its own.

    FAILING INPUT: delete `DECLARED_ENTRY_LOCATION` and inline `window[-1].close` at the call
    site. The import fails and this test cannot even collect — which is the point: the
    constant is the single source, and `extract_setup` raises rather than silently keeping the
    old reading if the declaration changes to one it does not implement.
    """
    from app.services.rules.stop_ladder_corpus import DECLARED_ENTRY_LOCATION

    for declared in (DECLARED_ENTRY_LOCATION, DECLARED_ENTRY_PLACEMENT):
        assert declared.ratified is False
        assert declared.authority.startswith("ENGINEERING")
        assert declared.competing, "the option not taken is recorded"
        assert declared.source, "the argument for the value is recorded"

    assert DECLARED_ENTRY_LOCATION.value == "DECISION_BAR_CLOSE"
    assert "54" in DECLARED_ENTRY_LOCATION.source, (
        "the declaration records the measured consequence — omitting at_price makes n equal "
        "the window count by construction"
    )
