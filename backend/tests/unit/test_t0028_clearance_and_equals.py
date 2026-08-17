"""T-0028 — TARGET-005 and TARGET-006, both CONFORMANCE rules over primitives.

WHICH ASSERTIONS READ WHAT, because they go red for different reasons:

    the CONSTRUCTED tests build bars and swings by hand. They exist to prove each verdict
    the machinery can return IS returnable — a conformance function that always says PASS
    would satisfy every corpus assertion in this file.

    the CORPUS block reads `tests/fixtures/btcusdtp_5m_1500.csv`, PINNED, through the same
    T-0017 windowing `stop_ladder_corpus.py` already uses. Nothing fetches, so a red run
    there is unambiguously a defect rather than a market that moved.

THE ONE-GREP PROMISE THIS FILE ENFORCES
Both rules claim ids whose mechanisms live in PRIM-003 and PRIM-004. A conformance rule that
RECOMPUTES the states in order to assert them has re-implemented them with extra steps, so
`test_the_clearance_values_are_read_from_the_primitive_not_recomputed` and its TARGET-006
twin assert that every clearance/tier key carries PRIMITIVE_FIELD provenance. That is the
check the Manager and Review both asked to be held to, made mechanical.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.rules import prim_004_sweeps as P4
from app.services.rules.prim_001_swings import Bar, Swing, SwingPoints
from app.services.rules.prim_003_liquidity import (
    RELATIVE_EQUALS_MAX_DIFF_PCT, LiquidityPool, LiquidityPools,
)
from app.services.rules.prim_004_sweeps import SweepEvents
from app.services.rules.prim_005_breaks import BreakEvents
from app.services.rules.stop_ladder_corpus import CORPUS_BARS, STEP_BARS, windows
from app.services.rules.target_005_clearance import (
    CONSUMED, DECLARED_WEAK_SWEEP, PENETRATION_EPISODE_BASIS, TESTED,
    ClearanceIsStructural, observe, penetration_removal_probe,
)
from app.services.rules.target_006_equals_ranking import (
    DECLARED_RELATIVE_EQUALS, EQUALS_TIERS, EqualsRanking,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "btcusdtp_5m_1500.csv"
T0 = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)

#: MEASURED on the pinned fixture at STEP 12, 2026-08-17, by the probe in the work report.
#: Recorded so a change shows up as a change rather than as a differently-worded pass —
#: T-0017's convention, and T-0030's.
#:
#: THE UNIT IS A (window, pool) PAIR, NOT A DISTINCT POOL. Windows overlap by 851 of 863
#: bars, so the same level is re-observed many times. Naming the unit here because B122's
#: hazard is one count wearing two quantities, and "238,040 pools" would be exactly that.
MEASURED_STEP_12 = {
    "windows": 54,
    "swept_window_pool_pairs": 238040,
    "divergent_window_pool_pairs": 10103,
    "consumed_window_pool_pairs": 227937,
    "real_sweep_events": 1345028,
    "episode_class_disagreements": 76171,
    "equals_pairs_perfect": 312,
    "equals_pairs_relative": 263771,
    "equals_pairs_separate": 519046,
}


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------
def candles(rows: list[tuple[float, float, float, float]]) -> list[Bar]:
    return [
        Bar(time=T0 + timedelta(hours=i), open=o, high=h, low=lo, close=c)
        for i, (o, h, lo, c) in enumerate(rows)
    ]


def swing(price: float, kind: str, idx: int, sid: str | None = None) -> Swing:
    return Swing(
        id=sid or f"sw-{kind}-{idx}", tf="1H", bar_time=T0 + timedelta(hours=idx),
        price=price, kind=kind, bar_index=idx,
    )


def pool_at(price: float, side: str = "HIGH", pid: str = "lq-1") -> LiquidityPool:
    return LiquidityPool(
        id=pid, tf="1H", pool_class="SWING_LEVEL", price=price, side=side, formed_index=0,
    )


class _Break:
    """A PRIM-005 break in the shape `SweepEvents._reaction` reads."""

    def __init__(self, bid: str, bar_index: int, direction: str, btype: str = "MSB"):
        self.id, self.bar_index, self.direction, self.type = bid, bar_index, direction, btype


@pytest.fixture(scope="module")
def bars() -> list[Bar]:
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
def corpus(bars: list[Bar]):
    """One pass of the REAL chain per window, in stop_ladder_corpus's own call order."""
    out = []
    for di, w in windows(bars, corpus_bars=CORPUS_BARS, step_bars=STEP_BARS):
        swings = SwingPoints.detect(w, tf="5m")
        breaks = BreakEvents.detect(w, swings, tf="5m")
        pools = LiquidityPools.detect(w, swings, tf="5m")
        sweeps = SweepEvents.detect(pools, w, breaks, tf="5m")
        out.append((di, w, swings, breaks, pools, sweeps))
    return out


# ===========================================================================
# TARGET-005 — criterion 1: tested and consumed are SEPARATE states
# ===========================================================================
def test_a_wick_beyond_the_level_marks_tested_and_not_consumed():
    """"A wick through the level is sufficient to mark the liquidity as TESTED, but not
    necessarily CONSUMED." No break follows, so there is no reaction to judge."""
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99.5, 100), (100, 100, 99, 99.5)])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars_, tf="1H")

    assert pool.state == TESTED
    assert sweeps and sweeps[0].cleared is False
    obs = observe([pool], sweeps)[0]
    assert obs.divergent is True


def test_a_body_close_beyond_the_level_still_does_not_clear_it():
    """THE OVERRIDE, and it is the counterintuitive half: "not considered cleared solely
    because price wicks through it OR CLOSES BEYOND IT"."""
    bars_ = candles([(100, 100, 99, 100), (100, 102, 100, 101.5), (101, 101, 99, 99)])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars_, tf="1H")

    assert sweeps[0].wick_or_close == "BODY_CLOSE_BEYOND"
    assert sweeps[0].cleared is False
    assert pool.state == TESTED, "a close beyond is still only TESTED without a reaction"


def test_a_structural_reaction_against_the_run_is_what_consumes_the_level():
    """The other direction, or the split is a distinction the corpus never exercises."""
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99.5, 100), (100, 100, 99, 99.5)])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect(
        [pool], bars_, [_Break("bk-1", 2, "DOWN")], tf="1H"
    )

    assert sweeps[0].cleared is True
    assert pool.state == CONSUMED
    assert sweeps[0].reaction_break_ids == ["bk-1"]


def test_a_break_continuing_through_the_level_does_not_consume_it():
    """Same direction as the run: price carried on, so the level was never the destination."""
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99.5, 100), (100, 100, 99, 99.5)])
    pool = pool_at(100.0)
    SweepEvents.detect([pool], bars_, [_Break("bk-1", 2, "UP")], tf="1H")

    assert pool.state == TESTED


# --- criterion 1a: both directions, or the rule is a percentage with extra steps ---
def test_a_five_percent_penetration_with_no_reaction_is_not_consumed():
    """The mutation criterion 1a names. 5% is five times the declared weak band."""
    bars_ = candles([(100, 100, 99, 100), (100, 105, 100, 104), (104, 104, 99, 99)])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars_, tf="1H")

    assert sweeps[0].penetration_pct == pytest.approx(5.0)
    assert sweeps[0].weak_sweep is False
    assert sweeps[0].cleared is False, "structure outranks penetration, in this direction"
    assert pool.state == TESTED


def test_a_sub_one_percent_penetration_with_a_reaction_reaches_consumed():
    """THE CONVERSE, and without it the rule is 'a bigger number clears' wearing a hedge."""
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99.5, 100), (100, 100, 99, 99.5)])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars_, [_Break("bk-1", 2, "DOWN")], tf="1H")

    assert sweeps[0].penetration_pct == pytest.approx(0.5)
    assert sweeps[0].weak_sweep is True, "inside the declared band"
    assert sweeps[0].cleared is True, "and consumed anyway — structure decided"
    assert pool.state == CONSUMED


def test_the_conformance_check_fails_a_consumed_pool_with_no_structural_evidence():
    """THE MUTATION THAT MATTERS: a checker that only counts states passes this."""
    pool = pool_at(100.0)
    pool.state = CONSUMED
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99.5, 100), (100, 100, 99, 99.5)])
    sweeps = SweepEvents.detect([pool], bars_, tf="1H")
    pool.state = CONSUMED          # forced back: PRIM-004 correctly said TESTED

    _, violations = ClearanceIsStructural.conformance(observe([pool], sweeps))

    assert violations, "CONSUMED with no reaction must be a violation, not a silent pass"
    assert "structural reaction" in violations[0]


# ===========================================================================
# criterion 1a-i — the corpus must CONTAIN the divergent case, not merely permit it
# ===========================================================================
def test_both_states_occur_over_the_corpus_and_divergent_cases_are_present(corpus):
    """Collapsing tested and consumed into one boolean passes every fixture in which the two
    happen to AGREE. The requirement is a non-zero count of cases where they do not."""
    swept = divergent = consumed = 0
    for _, _, _, _, pools, sweeps in corpus:
        for o in observe(pools, sweeps):
            if not o.swept:
                continue
            swept += 1
            divergent += o.divergent
            consumed += o.state == CONSUMED

    assert swept == MEASURED_STEP_12["swept_window_pool_pairs"]
    assert divergent == MEASURED_STEP_12["divergent_window_pool_pairs"]
    assert consumed == MEASURED_STEP_12["consumed_window_pool_pairs"]
    assert divergent > 0, (
        "the doctrine sentence NAMES a wick that is tested and not consumed; a corpus "
        "without one cannot tell a two-state implementation from a one-boolean one"
    )
    assert consumed > 0, "and both states must occur, or the split is untested"


# ===========================================================================
# criterion 2 — the ~1% annotates and does not gate. RUN, not asserted.
# ===========================================================================
def test_the_removal_probe_finds_the_percentage_gates_no_clearance_verdict(corpus, bars):
    """CRITERION 2's removal test, over the corpus, varying the VALUE in the decision path.

    NOT the symbol. Deleting `WEAK_SWEEP_PENETRATION_PCT` raises `NameError` at
    `prim_004_sweeps.py:273` — measured — because TARGET-005's own `output` field requires
    `penetration_pct` and the ~1% band to be reported. A rule that mandates a measurement
    cannot be checked by removing the measurement, so criterion 2-i's second bullet was
    withdrawn and its first governs.

    WHAT WOULD MAKE THIS FAIL, named before it runs: any value at which one `cleared` flag
    or one `pool.state` differs from the baseline.
    """
    original = P4.WEAK_SWEEP_PENETRATION_PCT

    def rerun(value: float):
        P4.WEAK_SWEEP_PENETRATION_PCT = value
        all_pools: list[LiquidityPool] = []
        all_sweeps = []
        for _, w, swings, breaks, _, _ in corpus:
            pools = LiquidityPools.detect(w, swings, tf="5m")
            all_sweeps += SweepEvents.detect(pools, w, breaks, tf="5m")
            all_pools += pools
        return all_pools, all_sweeps

    try:
        probe = penetration_removal_probe(rerun)
    finally:
        P4.WEAK_SWEEP_PENETRATION_PCT = original

    assert probe.verdicts_identical is True
    assert probe.instrument_moved is True, (
        "if the weak_sweep count never moved, the constant is inert in this fixture and "
        "the probe has proven nothing about whether it gates"
    )
    assert probe.discriminating_cases > 0
    assert probe.outcome == "PASS"


def test_the_corpus_contains_cases_a_gating_implementation_would_decide_differently(corpus):
    """CRITERION 2-i's REAL hole, closed by measurement rather than by argument.

    Unchanged verdicts are GUARANTEED when no input sits near the boundary — the probe would
    then pass a correct and an incorrect implementation alike. So the fixture must contain
    cases where the constant, IF it gated, WOULD flip the verdict.
    """
    weak_and_cleared = strong_and_not = total = 0
    for _, _, _, _, _, sweeps in corpus:
        for e in sweeps:
            if e.sweep_failed:
                continue
            total += 1
            weak_and_cleared += e.weak_sweep and e.cleared
            strong_and_not += (not e.weak_sweep) and (not e.cleared)

    assert total == MEASURED_STEP_12["real_sweep_events"]
    assert weak_and_cleared > 0, (
        "a weak sweep that cleared anyway — a gating implementation MUST call this "
        "not-cleared, so its presence is what makes the removal probe discriminate"
    )
    assert strong_and_not > 0, "and the converse, or only one direction is exercised"


def test_deleting_the_symbol_raises_and_that_is_correct_behaviour():
    """Criterion 2-i's WITHDRAWN bullet, pinned so nobody reinstates it from the prose.

    The bullet scored `NameError` as FAIL — "a constant whose removal breaks the import is
    by definition read". It IS read, at the ANNOTATION line, and it must be: the rule's
    `output` field requires the penetration and the band. Read-anywhere and
    read-in-the-decision-path are the distinction the first bullet draws.
    """
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99.5, 100), (100, 100, 99, 99.5)])
    saved = P4.WEAK_SWEEP_PENETRATION_PCT
    del P4.WEAK_SWEEP_PENETRATION_PCT
    try:
        with pytest.raises(NameError):
            SweepEvents.detect([pool_at(100.0)], bars_, tf="1H")
    finally:
        P4.WEAK_SWEEP_PENETRATION_PCT = saved


# ===========================================================================
# criterion 3 — the declared parameters, and the premise that turned out false
# ===========================================================================
def test_the_declared_percentage_carries_the_registry_four_field_shape():
    values = ClearanceIsStructural.declared_parameters()

    for suffix in ("_pct", "_ratified", "_authority", "_measured_from"):
        assert f"weak_sweep_penetration{suffix}" in values
    assert values["weak_sweep_penetration_pct"] == P4.WEAK_SWEEP_PENETRATION_PCT
    assert values["weak_sweep_penetration_ratified"] is False
    assert values["weak_sweep_penetration_measured_from"] == P4.PENETRATION_PCT_BASIS


def test_the_value_and_its_denominator_carry_SEPARATE_authorities():
    """HIS number, OUR denominator. One `_authority` field would publish ours under his name,
    and that is the one thing this loop refuses."""
    values = ClearanceIsStructural.declared_parameters()

    assert "TRADER" in values["weak_sweep_penetration_authority"]
    assert values["weak_sweep_penetration_measured_from_authority"] == "ENGINEERING"
    assert (
        values["weak_sweep_penetration_authority"]
        != values["weak_sweep_penetration_measured_from_authority"]
    )


def test_the_declared_values_are_read_from_the_primitive_and_not_restated():
    """A carrier that retyped 1.0 and LEVEL_PRICE would be a second home for the two values
    this module exists to stop duplicating — and it would keep agreeing with itself."""
    assert DECLARED_WEAK_SWEEP.pct is P4.WEAK_SWEEP_PENETRATION_PCT
    assert DECLARED_WEAK_SWEEP.measured_from is P4.PENETRATION_PCT_BASIS
    assert DECLARED_RELATIVE_EQUALS.pct is RELATIVE_EQUALS_MAX_DIFF_PCT


def test_the_denominator_is_observable_which_is_what_criterion_3_denied():
    """Criterion 3-ii declared the basis unratified BECAUSE "no test can detect a wrong
    choice". A test does, and it predates this task: `test_primitives_inventory.py:379-382`
    pins penetration_abs, penetration_pct, penetration_pct_basis AND the derived weak_sweep.

    The ACTION survives and the JUSTIFICATION does not — the basis is ours and unratified,
    which is reason enough. Pinned here so the false premise cannot be cited later as fact.
    """
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99, 100.2), (100, 100, 99, 99)])
    sweep = SweepEvents.detect([pool_at(100.0)], bars_, tf="1H")[0]

    assert sweep.penetration_pct_basis == "LEVEL_PRICE"
    assert sweep.penetration_pct == pytest.approx(0.5)


# --- the [ENGINEERING] requirement the plan never mentioned -----------------
def test_both_maxima_are_emitted_and_the_flag_declares_which_it_reads():
    """TARGET-005's notes: "emit BOTH a per-bar maximum and an episode maximum, AND declare
    which the flag reads."

    TWO HALVES, AND THEY ARE SEPARABLE. A record with one maximum plus a declaration naming
    it satisfies the second half and not the first, and reads as complete because the
    declaration is the visible half. Both are asserted here.
    """
    bars_ = candles([
        (100, 100, 99, 100),
        (100, 100.5, 99.5, 100),      # excursion 1 — 0.5%, weak
        (100, 100, 99, 99.5),
        (100, 102.6, 99.5, 100),      # excursion 2 — 2.6%, not weak
        (100, 100, 99, 99.5),
    ])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars_, tf="1H")
    obs = observe([pool], sweeps)[0]

    assert obs.excursions == 2
    record = obs.as_dict()
    assert len(record["penetration_pct_per_bar_max"]) == 2
    assert record["penetration_pct_episode_max"] == pytest.approx(2.6)
    assert record["penetration_pct_episode_max"] != record["penetration_pct_per_bar_max"][0]
    assert record["weak_sweep_reads"] == PENETRATION_EPISODE_BASIS.measured_from
    assert record["episode_class_disagrees"] is True, (
        "excursion 1 is weak and the episode maximum is not — this is the 32% of swept "
        "pools where the unstated single-vs-cumulative axis changes the published class"
    )


def test_the_episode_disagreement_rate_is_measured_over_the_corpus(corpus):
    disagreements = sum(
        1 for _, _, _, _, pools, sweeps in corpus
        for o in observe(pools, sweeps) if o.swept and o.episode_class_disagrees
    )
    assert disagreements == MEASURED_STEP_12["episode_class_disagreements"]
    assert disagreements > 0, "a zero here would make the declaration unfalsifiable"


# ===========================================================================
# criterion 4 — the scope split. What CAN be pinned, and what cannot.
# ===========================================================================
def test_break_validity_is_untouched_while_clearance_varies_underneath_it():
    """"§2 A12 / §9.J IM80's body-close test for BREAK VALIDITY is untouched (ENTRY-003);
    what is overridden is clearance." Two rules, one candlestick fact, opposite conclusions.

    AIMED AT PRIM-005 RATHER THAN AT ENTRY-003, AND THE REASON IS STATED RATHER THAN GLOSSED:
    `grep RULE_ID = "ENTRY-003"` returns NO FILE — the rule has no implementation, so
    "assert ENTRY-003's behaviour is unaffected" cannot be written as posed. What exists is
    PRIM-005's `valid` / `validity_criteria_met`, and that IS pinnable: it is asserted
    identical while the clearance constant sweeps across its whole range.
    """
    # The series `test_a_break_with_the_trend_is_a_bos_and_against_it_is_an_msb` uses, so the
    # baseline is a break set known to be non-empty by an existing passing test rather than
    # by whatever this file happened to construct.
    bars_ = [
        Bar(time=T0 + timedelta(hours=i), high=h, low=lo)
        for i, (h, lo) in enumerate(zip(
            [10, 12, 20, 14, 16, 24, 18, 15, 12, 11, 12, 13],
            [8, 9, 15, 9, 11, 19, 13, 10, 4, 5, 6, 7],
        ))
    ]
    swings = SwingPoints.detect(bars_, tf="1H", window=2)
    baseline = [
        (b.id, b.valid, tuple(b.validity_criteria_met or ()))
        for b in BreakEvents.detect(bars_, swings, tf="1H")
    ]

    saved = P4.WEAK_SWEEP_PENETRATION_PCT
    try:
        for value in (0.0, 1.0, 100.0):
            P4.WEAK_SWEEP_PENETRATION_PCT = value
            after = [
                (b.id, b.valid, tuple(b.validity_criteria_met or ()))
                for b in BreakEvents.detect(bars_, swings, tf="1H")
            ]
            assert after == baseline, (
                "break validity moved when the clearance constant did — the two scopes "
                "have been collapsed, which K-17 forbids"
            )
    finally:
        P4.WEAK_SWEEP_PENETRATION_PCT = saved

    assert baseline, "a vacuous baseline would pass this whatever happened"


# ===========================================================================
# TARGET-006 — criterion 5: three tiers, and the third is a SEPARATION
# ===========================================================================
@pytest.mark.parametrize(
    "second, tier, pools_expected",
    [
        (100.0, "PERFECT", 1),
        (100.2, "RELATIVE", 1),        # 0.1998% — inside 0.30%
        (101.0, "SEPARATE_POOLS", 0),  # 0.995% — two distinct pools
    ],
)
def test_the_three_tiers_classify_and_the_third_emits_no_pool(second, tier, pools_expected):
    """The third tier is a SEPARATION, not a degradation: `> 0.30%` does not mean
    "poor-quality equals", it means TWO DISTINCT POOLS. The objects returned differ in COUNT.
    """
    swings = [swing(100.0, "HIGH", 2), swing(second, "HIGH", 6)]

    pools = LiquidityPools.equal_highs_lows(swings, tf="1H")
    measurements = LiquidityPools.equals_classification(swings, tf="1H")

    assert len(pools) == pools_expected
    assert [m.equals_class for m in measurements] == [tier]


def test_the_separate_pools_tier_now_records_its_measured_difference():
    """`TELEMETRY_SCHEMA.json:550` — "the measured difference that produced equals_class.
    Record it even when the class is SEPARATE_POOLS."

    IT WAS A TYPE VALUE WITH NO DATA BEHIND IT: declared in `EqualsClass`, allowed by the
    schema, named in the rule's `output`, and assigned NOWHERE in the repository. The
    classifier reached the `> 0.30%` branch and `continue`d.
    """
    swings = [swing(100.0, "HIGH", 2), swing(101.0, "HIGH", 6)]

    [m] = LiquidityPools.equals_classification(swings, tf="1H")

    assert m.equals_class == "SEPARATE_POOLS"
    assert m.equals_diff_pct == pytest.approx(0.995, abs=1e-3)
    assert m.as_dict()["equals_diff_pct"] == m.equals_diff_pct


def test_the_extension_changed_the_record_and_not_the_pairing():
    """The behavioural half of the approved change, asserted rather than described.

    `continue` was the correct BEHAVIOUR — the two levels are already inventoried as swing
    levels and a third object would double-count. So the pool inventory must be identical
    to what it was, and only the measurement is new.
    """
    swings = [
        swing(100.0, "HIGH", 2), swing(100.2, "HIGH", 6), swing(101.0, "HIGH", 9),
        swing(99.0, "LOW", 3), swing(99.0, "LOW", 7),
    ]

    pools = LiquidityPools.equal_highs_lows(swings, tf="1H")
    measurements = LiquidityPools.equals_classification(swings, tf="1H")

    assert all(p.equals_class in ("PERFECT", "RELATIVE") for p in pools)
    assert len(pools) < len(measurements), "the discarded tier is real and is now recorded"
    assert len(pools) == sum(
        1 for m in measurements if m.equals_class != "SEPARATE_POOLS"
    )


def test_one_classifier_decides_the_tier_boundary(monkeypatch):
    """SAME-CLAIM-TWO-HOMES, checked by moving the threshold and watching BOTH follow.

    If `equal_highs_lows` held its own copy of the comparison, this would pass for the
    measurements and fail for the pools — which is exactly how the copy nothing checks rots.
    """
    swings = [swing(100.0, "HIGH", 2), swing(101.0, "HIGH", 6)]
    assert LiquidityPools.equal_highs_lows(swings, tf="1H") == []

    monkeypatch.setattr(
        "app.services.rules.prim_003_liquidity.RELATIVE_EQUALS_MAX_DIFF_PCT", 5.0
    )
    pools = LiquidityPools.equal_highs_lows(swings, tf="1H")
    [m] = LiquidityPools.equals_classification(swings, tf="1H")

    assert m.equals_class == "RELATIVE"
    assert len(pools) == 1 and pools[0].equals_class == "RELATIVE"


def test_the_conformance_check_fails_an_equals_pool_classed_separate_pools():
    """The mutation: a pool object carrying the third tier means the classifier emitted an
    equals object for two levels that are not equals."""
    bad = LiquidityPool(
        id="lq-bad", tf="1H", pool_class="EQUAL_HIGHS_LOWS", price=100.0,
        equals_class="SEPARATE_POOLS", equals_diff_pct=0.9, boosters=["EQUALS"],
    )

    _, violations = EqualsRanking.conformance([bad])

    assert violations and "double-counts" in violations[0]


def test_the_conformance_check_fails_a_relative_pool_outside_the_declared_band():
    bad = LiquidityPool(
        id="lq-bad", tf="1H", pool_class="EQUAL_HIGHS_LOWS", price=100.0,
        equals_class="RELATIVE", equals_diff_pct=0.9, boosters=["EQUALS"],
    )

    _, violations = EqualsRanking.conformance([bad])

    assert violations and "outside the declared" in violations[0]


# --- criterion 5a / 6: declared, and honest about what is not built ---------
def test_the_relative_equals_threshold_is_declared_unratified_with_its_denominator():
    values = EqualsRanking.declared_parameters()

    assert values["relative_equals_max_diff_pct"] == RELATIVE_EQUALS_MAX_DIFF_PCT
    assert values["relative_equals_max_diff_ratified"] is False
    assert values["relative_equals_max_diff_measured_from"] == "MEAN_OF_THE_PAIR"
    assert "initial calibration value" in values["relative_equals_max_diff_source"]


def test_the_quality_boost_is_reported_as_unread_rather_than_as_working():
    """CRITERION 6, and the honest answer is that half of it is not built.

    "A relative equal only strengthens the QUALITY of a liquidity target; it does not
    automatically make it the active destination." The second half holds today — but it
    holds because `boosters` has ZERO read sites outside `prim_003_liquidity.py`, not
    because anything refuses to select on it. NOT_READ names a producer that EXISTS and is
    uncalled; reporting it as TRUE would make a wiring gap read as a working check.
    """
    conditions = {c.name: c for c in EqualsRanking.boost_conditions(booster_read_sites=0)}

    boost = conditions["quality_boost_applied_to_target"]
    assert boost.state == "NOT_READ"
    assert "boosters" in boost.unread_producer

    v_shaped = conditions["equals_outrank_v_shaped_liquidity"]
    assert v_shaped.state == "NOT_EVALUABLE"
    assert "TARGET-007 is OPEN" in v_shaped.missing_producer


def test_the_boost_condition_reports_true_the_day_something_reads_it():
    """The measured input is supplied, not assumed, so this rule needs no edit when the
    consumer lands — which is what stops the note going stale silently."""
    conditions = {c.name: c for c in EqualsRanking.boost_conditions(booster_read_sites=3)}

    assert conditions["quality_boost_applied_to_target"].state == "TRUE"


def test_equals_do_not_override_target_001s_objective_selection():
    """"it does not automatically make it the active destination" — so the boost must not
    reach TARGET-001's LEVEL 1 decision. Asserted against the real selector."""
    from app.services.rules.exit_004_target_object import TargetObject
    from app.services.rules.target_001_concerning_objective import (
        ConcerningLiquidityIsStructural, InstitutionalDestination, Objective,
    )

    destination = InstitutionalDestination(
        id="dest-1", label="weekly high", direction="BULLISH", tf="1W",
    )

    def objective(oid: str, supports: bool, distance: float) -> Objective:
        return Objective(
            target=TargetObject(
                object_id=oid, object_type="EQUAL_HIGHS_LOWS", price=100.0,
                source_class="EQUAL_HIGHS_LOWS", tf="1H",
            ),
            resolved=False, supports_destination=supports, distance=distance,
        )

    # The EQUALS-boosted candidate is closer AND does not support the destination.
    candidates = [objective("boosted", supports=False, distance=1.0),
                  objective("structural", supports=True, distance=50.0)]

    chosen = ConcerningLiquidityIsStructural.select(candidates, destination)

    assert chosen is not None and chosen.target.object_id == "structural", (
        "a quality booster that changed the selection would be TARGET-006 overriding "
        "TARGET-001, which the rule's own closing clause forbids"
    )


# ===========================================================================
# THE ONE-GREP PROMISE: read the primitive, never recompute it
# ===========================================================================
def test_the_clearance_values_are_read_from_the_primitive_not_recomputed():
    """A conformance rule that recomputes the states in order to assert them has
    re-implemented clearance with extra steps. Provenance is where that shows: a recomputed
    key could only carry DERIVED."""
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99.5, 100), (100, 100, 99, 99.5)])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars_, tf="1H")

    ev = ClearanceIsStructural.evaluate([pool], sweeps)

    for key in ("pools_untested", "pools_tested_not_consumed", "pools_consumed",
                "penetration_maxima"):
        assert ev.value_provenance[key]["source"] == "PRIMITIVE_FIELD", (
            f"{key} must be READ off PRIM-004's emitted output, not derived here"
        )


def test_the_equals_tiers_are_read_from_the_primitive_not_recomputed():
    swings = [swing(100.0, "HIGH", 2), swing(100.2, "HIGH", 6)]
    pools = LiquidityPools.equal_highs_lows(swings, tf="1H")
    measurements = LiquidityPools.equals_classification(swings, tf="1H")

    ev = EqualsRanking.evaluate(pools, measurements)

    for key in ("pools_by_tier", "measurements_by_tier", "boosted_pools",
                "diff_pct_range_by_tier"):
        assert ev.value_provenance[key]["source"] == "PRIMITIVE_FIELD"


def test_every_value_names_where_it_came_from():
    """The house invariant, applied to both new rules."""
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99.5, 100), (100, 100, 99, 99.5)])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars_, tf="1H")
    swings = [swing(100.0, "HIGH", 2), swing(100.2, "HIGH", 6)]

    for ev in (
        ClearanceIsStructural.evaluate([pool], sweeps),
        EqualsRanking.evaluate(
            LiquidityPools.equal_highs_lows(swings, tf="1H"),
            LiquidityPools.equals_classification(swings, tf="1H"),
        ),
    ):
        assert set(ev.values) - {"violations", "not_applicable_reason",
                                 "indeterminate_reason"} <= set(ev.value_provenance)


# ===========================================================================
# verdicts the machinery must be ABLE to return
# ===========================================================================
def test_a_scan_with_no_sweep_is_not_applicable_rather_than_a_pass():
    """Silence is not a pass (C-04). A scan with no excursions carries no evidence about
    clearance in either direction, and that is a different fact from conformance."""
    bars_ = candles([(100, 99.5, 99, 99.2), (99, 99.4, 98, 98.5)])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars_, tf="1H")

    ev = ClearanceIsStructural.evaluate([pool], sweeps)

    assert ev.verdict == "NOT_APPLICABLE"
    assert "no pool was swept" in ev.values["not_applicable_reason"]


def test_an_indeterminate_removal_probe_is_not_reported_as_conformance():
    """A probe over a corpus that straddles nothing passes a correct and an incorrect
    implementation alike. That is T-0018's `1c` and T-0023's criterion 4, and it must not
    surface as PASS."""
    bars_ = candles([(100, 100, 99, 100), (100, 100.5, 99.5, 100), (100, 100, 99, 99.5)])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars_, tf="1H")

    inert = penetration_removal_probe(lambda _v: ([pool], sweeps), values=(1.0, 2.0))
    assert inert.instrument_moved is False
    assert inert.outcome == "INDETERMINATE"

    ev = ClearanceIsStructural.evaluate([pool], sweeps, removal=inert)
    assert ev.verdict == "NOT_APPLICABLE"
    assert "INDETERMINATE" in ev.values["indeterminate_reason"]


def test_target_006_never_reports_pass_while_its_ranking_half_is_unreadable():
    """THE SHARED INVARIANT (`base.quorum_blocked`): no rule reaches a verdict while a
    condition is unreadable.

    The first draft of this rule returned PASS here, and `scripts/check_partial_rules.py`
    caught it: a rule that scores its READABLE conditions and stops has claimed conformance
    to a three-part rule on the one part it can read, with the denominator silently shrinking
    to the readable subset. The tier classification is genuinely conformant — and that is
    reported in `values`, not in the verdict.
    """
    swings = [swing(100.0, "HIGH", 2), swing(100.2, "HIGH", 6)]
    pools = LiquidityPools.equal_highs_lows(swings, tf="1H")
    measurements = LiquidityPools.equals_classification(swings, tf="1H")

    ev = EqualsRanking.evaluate(pools, measurements)

    assert ev.verdict == "NOT_APPLICABLE"
    assert ev.values["ranking_outcome"] == "CLASSIFY_ONLY"
    assert set(ev.values["unreadable_inputs"]) == {
        "quality_boost_applied_to_target", "equals_outrank_v_shaped_liquidity",
    }
    # The conformance findings survive into the record — a blocked verdict is not a blank one.
    assert ev.values["pools_by_tier"]["RELATIVE"] == 1
    assert ev.values["measurements_by_tier"]["RELATIVE"] == 1


def test_a_tier_violation_still_fails_rather_than_hiding_behind_the_block():
    """FAIL must outrank the block, or an unreadable condition would mask a real defect."""
    bad = LiquidityPool(
        id="lq-bad", tf="1H", pool_class="EQUAL_HIGHS_LOWS", price=100.0,
        equals_class="SEPARATE_POOLS", equals_diff_pct=0.9, boosters=["EQUALS"],
    )

    assert EqualsRanking.evaluate([bad]).verdict == "FAIL"


def test_target_006_declares_the_producer_it_cannot_fire_without():
    """And TARGET-005 declares NONE, in the same task, on purpose.

    The reaction producer TARGET-005 needs EXISTS (`SweepEvents._reaction`), so declaring one
    there would understate coverage — the opposite of the usual error. The V-shaped object
    TARGET-006 needs does not exist and cannot while TARGET-007 is OPEN.
    """
    assert EqualsRanking.CANNOT_FIRE_WITHOUT == ("v_shaped_liquidity",)
    assert ClearanceIsStructural.CANNOT_FIRE_WITHOUT == ()


def test_the_tier_list_is_the_rules_own_three():
    assert EQUALS_TIERS == ("PERFECT", "RELATIVE", "SEPARATE_POOLS")


def test_the_equals_tier_census_matches_the_corpus_measurement(corpus):
    """The TARGET-006 side of the pinned figures, with its unit named: swing PAIRS."""
    tiers = {t: 0 for t in EQUALS_TIERS}
    emitted_pools = 0
    for _, _, swings, _, _, _ in corpus:
        for m in LiquidityPools.equals_classification(swings, tf="5m"):
            tiers[m.equals_class] += 1
        emitted_pools += len(LiquidityPools.equal_highs_lows(swings, tf="5m"))

    assert tiers["PERFECT"] == MEASURED_STEP_12["equals_pairs_perfect"]
    assert tiers["RELATIVE"] == MEASURED_STEP_12["equals_pairs_relative"]
    assert tiers["SEPARATE_POOLS"] == MEASURED_STEP_12["equals_pairs_separate"]
    assert tiers["SEPARATE_POOLS"] > tiers["PERFECT"] + tiers["RELATIVE"], (
        "the tier that recorded nothing was the MAJORITY one"
    )

    # THE BEFORE/AFTER, AT CORPUS SCALE. The two pool-emitting counts were measured on the
    # UNCHANGED code at 5c7208d, before `equals_classification` existed, and they are these
    # two numbers. So this is a comparison across the edit and not a restatement of it.
    assert emitted_pools == tiers["PERFECT"] + tiers["RELATIVE"], (
        "the extension was supposed to change the RECORD and not the PAIRING — an emitted "
        "pool count that no longer equals the two non-separate tiers means it changed both"
    )
    assert emitted_pools == (
        MEASURED_STEP_12["equals_pairs_perfect"] + MEASURED_STEP_12["equals_pairs_relative"]
    )
