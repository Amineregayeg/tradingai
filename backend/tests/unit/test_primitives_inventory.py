"""Imbalances, liquidity pools, sweeps and S/R flips (M3, PRIM-002/003/004/006).

These four complete the primitive layer. They matter disproportionately because of what sits
directly on top of them: ENTRY-001 makes an imbalance the ONLY admissible entry object,
TARGET-001 picks the trade's destination out of the pool inventory, and GATE-025's 2R floor
is measured between the two. An engine without these cannot compute a reward-to-risk at all.

The series below are hand-built so the right answer is known by construction rather than by
running the code and blessing whatever came out.

WHAT THESE TESTS CANNOT TELL YOU
Whether these are the objects the trader would have drawn. Nothing in the conformance suite
tests detector quality — a systematically wrong inventory scores 100% CONFORMANT while
mis-grading every box and therefore mis-sizing every trade. That is readiness gate 7's job,
and it needs a human with the charts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.rules.prim_001_swings import Bar, Swing
from app.services.rules.prim_002_imbalances import Imbalance, ImbalanceInventory
from app.services.rules.prim_003_liquidity import (
    RELATIVE_EQUALS_MAX_DIFF_PCT,
    LiquidityPool,
    LiquidityPools,
)
from app.services.rules.prim_004_sweeps import WEAK_SWEEP_PENETRATION_PCT, SweepEvents
from app.services.rules.prim_005_breaks import BreakEvent
from app.services.rules.prim_006_sr_flips import SRFlip, SRFlipZones

T0 = datetime(2026, 8, 3, 4, 0, tzinfo=timezone.utc)  # 00:00 New York, DST in force


def bar(o: float, h: float, lo: float, c: float, i: int = 0) -> Bar:
    return Bar(time=T0 + timedelta(hours=i), high=h, low=lo, open=o, close=c)


def candles(rows: list[tuple[float, float, float, float]]) -> list[Bar]:
    return [bar(o, h, lo, c, i) for i, (o, h, lo, c) in enumerate(rows)]


# ===========================================================================
# PRIM-002 — the imbalance inventory
# ===========================================================================
def test_a_classic_three_bar_fvg_is_found_with_the_gap_as_its_band():
    """The band is the untraded space between bar i-1 and bar i+1, not the impulse bar."""
    bars = candles([
        (10, 11, 9, 10),     # 0
        (10, 16, 9, 15),     # 1 — impulse
        (15, 17, 13, 16),    # 2 — its low (13) is above bar 0's high (11)
        (16, 18, 14, 17),    # 3 — stays away, so the gap is untouched
    ])
    found = ImbalanceInventory.detect(bars, tf="1H")

    assert [i.type for i in found] == ["FVG"]
    gap = found[0]
    assert (gap.price_low, gap.price_high) == (11, 13)
    assert gap.direction == "BULLISH"
    assert gap.fill_state == "UNFILLED"


def test_a_gap_and_a_volume_imbalance_are_separated_only_by_the_wicks():
    """"gaps and volume imbalances are the same thing the only difference is the wicks".

    Both have bodies that do not overlap. Detecting off wicks alone would collapse two
    documented types into one and silently drop an entry object the strategy permits.
    """
    wicks_apart = candles([(10, 11, 9, 10), (12, 14, 12, 13)])
    wicks_touch = candles([(10, 13, 9, 10), (11, 14, 10, 13)])

    gap = ImbalanceInventory.detect(wicks_apart, tf="1H")
    vi = ImbalanceInventory.detect(wicks_touch, tf="1H")

    assert [i.type for i in gap] == ["GAP"]
    assert (gap[0].price_low, gap[0].price_high) == (11, 12), "gap spans wick to wick"
    assert [i.type for i in vi] == ["VOLUME_IMBALANCE"]
    assert (vi[0].price_low, vi[0].price_high) == (10, 11), "volume imbalance spans body to body"


@pytest.mark.parametrize(
    "follow_up, expected, fraction",
    [
        ((17, 18, 14, 17), "UNFILLED", 0.0),                    # never returns
        ((15, 16, 12, 15), "HALF_FILLED", 0.5),                 # halfway into an 11–13 band
        ((14, 15, 11, 14), "FULLY_FILLED", 1.0),                # reaches the far edge
        ((14, 15, 10, 10.5), "FULLY_FILLED_AND_VIOLATED", 1.0),  # and closes through it
    ],
)
def test_fill_state_is_measured_from_the_edge_the_imbalance_fills_from(
    follow_up, expected, fraction
):
    """A bullish gap fills top-down. Measuring both directions from one edge would report a
    bullish gap as filled the moment price traded anywhere near it."""
    bars = candles([
        (10, 11, 9, 10), (10, 16, 9, 15), (15, 17, 13, 16), follow_up,
    ])
    gap = ImbalanceInventory.detect(bars, tf="1H")[0]

    assert (gap.price_low, gap.price_high) == (11, 13)
    assert gap.fill_state == expected
    assert gap.fill_fraction == pytest.approx(fraction)


def test_the_four_state_enum_keeps_the_measured_fraction_alongside_it():
    """The contract's enum has no PARTIAL, so any penetration short of the far edge maps to
    HALF_FILLED. `fill_fraction` carries the real number so a later ruling can re-cut the
    boundary against stored history instead of invalidating it."""
    bars = candles([
        (10, 11, 9, 10), (10, 16, 9, 15), (15, 17, 13, 16),
        (16, 17, 12.8, 16),   # barely in: 0.1 of a 2-wide band
    ])
    gap = ImbalanceInventory.detect(bars, tf="1H")[0]
    assert gap.fill_state == "HALF_FILLED"
    assert gap.fill_fraction == pytest.approx(0.1)


def test_a_slow_grind_through_the_band_is_one_test_not_thirty():
    """"first-vs-second test" counts returns to the band, not bars spent inside it."""
    bars = candles([
        (10, 11, 9, 10), (10, 16, 9, 15), (15, 17, 13, 16),
        (16, 17, 12.5, 16),   # in
        (16, 17, 12.4, 16),   # still in — same visit
        (16, 18, 14, 17),     # out
        (17, 18, 12.6, 17),   # back in — second test
    ])
    gap = ImbalanceInventory.detect(bars, tf="1H")[0]
    assert gap.test_count == 2


def test_a_bpr_is_the_overlap_of_two_opposite_direction_imbalances():
    """Opposite direction is the whole point: a BPR is a band contested from both ends.
    Overlapping two same-direction gaps is just a wider gap."""
    bars = candles([
        (10, 11, 9, 10), (10, 16, 9, 15), (15, 17, 13, 16),   # bullish FVG 11–13
        (16, 17, 14, 15), (15, 15, 11, 12), (12, 12, 10, 11),  # bearish FVG 12–14
    ])
    found = ImbalanceInventory.detect(bars, tf="1H")
    bprs = [i for i in found if i.type in ("BPR", "SUPER_BPR")]

    assert len(bprs) == 1
    assert bprs[0].type == "BPR"
    assert (bprs[0].price_low, bprs[0].price_high) == (12, 13), "the intersection, not the union"


def test_three_overlapping_imbalances_promote_the_bpr_to_a_super_bpr():
    """"≥3 overlapping gaps = SUPER BPR". Built from hand-made components so the count is the
    only thing under test — the geometry that produces three overlapping imbalances on one
    band is incidental to the promotion rule.

    THE FORMATION ORDER IS NOT INCIDENTAL AND USED TO BE (T-0020). This fixture originally
    had `c` forming at index 2 while the `(a, b)` pair created the band at index 1, so the
    promotion counted a component that did not exist yet — the band's classification on bar
    1 depended on bar 2. The promotion scan now refuses that, correctly, and this fixture
    was the only thing in the suite asserting the old behaviour.

    So `b` is the LAST to form: all three components exist at the moment the band does, and
    the test still measures what it says it measures. `a` and `c` are BULLISH and `b` is
    BEARISH, which also satisfies the both-directions constraint the pair rule always had
    and the promotion never enforced.
    """
    parts = [
        Imbalance(id="a", tf="1H", bar_time=T0, price_high=13, price_low=11,
                  type="FVG", direction="BULLISH", formed_index=0),
        Imbalance(id="c", tf="1H", bar_time=T0, price_high=13.5, price_low=11.5,
                  type="GAP", direction="BULLISH", formed_index=1),
        Imbalance(id="b", tf="1H", bar_time=T0, price_high=14, price_low=12,
                  type="FVG", direction="BEARISH", formed_index=2),
    ]
    bars = candles([(10, 11, 9, 10)] * 3)
    bprs = ImbalanceInventory._bprs(parts, bars, tf="1H")

    assert any(b.type == "SUPER_BPR" for b in bprs)
    super_bpr = next(b for b in bprs if b.type == "SUPER_BPR")
    assert len(super_bpr.component_ids) >= 3


def test_momentum_is_left_unassessed_rather_than_guessed():
    """"the large gaps left behind by impulsive moves" — the doctrine fixes no size for
    large. Unset is the honest answer; False would be a claim (the PRIM-005 `fake_msb`
    precedent)."""
    bars = candles([(10, 11, 9, 10), (10, 16, 9, 15), (15, 17, 13, 16), (16, 18, 14, 17)])

    assert ImbalanceInventory.detect(bars, tf="1H")[0].is_momentum_imbalance is None

    declared = ImbalanceInventory.detect(bars, tf="1H", momentum_min_width=1.0)[0]
    assert declared.is_momentum_imbalance is True


def test_a_filled_gap_is_never_a_momentum_imbalance_however_wide_it_was():
    """"the large gaps… and NEVER FILLED" — both halves are required."""
    bars = candles([
        (10, 11, 9, 10), (10, 16, 9, 15), (15, 17, 13, 16), (14, 15, 11, 14),
    ])
    imb = ImbalanceInventory.detect(bars, tf="1H", momentum_min_width=1.0)[0]
    assert imb.fill_state == "FULLY_FILLED"
    assert imb.is_momentum_imbalance is False


def test_a_body_less_bar_is_refused_rather_than_treated_as_a_wick():
    """PRIM-001 and PRIM-005 are pure wick geometry and Bar's body is optional for them.
    PRIM-002 cannot separate a gap from a volume imbalance without one, so it must fail
    loudly instead of detecting a different object."""
    wickonly = [Bar(time=T0, high=11, low=9), Bar(time=T0 + timedelta(hours=1), high=14, low=12)]
    with pytest.raises(ValueError, match="no open/close"):
        ImbalanceInventory.detect(wickonly, tf="1H")


# ===========================================================================
# PRIM-003 — the liquidity-pool inventory
# ===========================================================================
def swing(price: float, kind: str, i: int) -> Swing:
    return Swing(id=f"sw-{i}-{kind[0]}", tf="1H", bar_time=T0 + timedelta(hours=i),
                 price=price, kind=kind, bar_index=i)  # type: ignore[arg-type]


def test_every_swing_becomes_a_pool_including_the_weak_ones():
    """A WEAK swing is one whose liquidity has already been taken — that is a state, and
    dropping it here would delete the evidence PRIM-004 needs to record it."""
    swings = [swing(100, "HIGH", 2), swing(90, "LOW", 4)]
    swings[0].strength = "WEAK"
    pools = LiquidityPools.from_swings(swings, tf="1H")

    assert [p.pool_class for p in pools] == ["SWING_LEVEL", "SWING_LEVEL"]
    assert [p.side for p in pools] == ["HIGH", "LOW"]
    assert all(p.state == "UNTESTED" for p in pools), "state is PRIM-004's to advance"


@pytest.mark.parametrize(
    "second, expected",
    [
        (100.0, "PERFECT"),
        (100.2, "RELATIVE"),   # 0.1998% — inside 0.30%
        (101.0, None),         # 0.995% — SEPARATE_POOLS, so no equals pool at all
    ],
)
def test_equals_are_ranked_by_target_006_and_separate_pools_emit_nothing(second, expected):
    """Above 0.30% the two levels are separate pools. They are already in the inventory as
    swing levels; a third object would double-count the same liquidity."""
    swings = [swing(100.0, "HIGH", 2), swing(second, "HIGH", 6)]
    pools = LiquidityPools.equal_highs_lows(swings, tf="1H")

    if expected is None:
        assert pools == []
    else:
        assert len(pools) == 1
        assert pools[0].equals_class == expected
        assert pools[0].boosters == ["EQUALS"], "a booster, never a destination selector"
        assert pools[0].equals_diff_pct <= RELATIVE_EQUALS_MAX_DIFF_PCT


def test_the_equals_pool_sits_at_the_level_a_sweep_has_to_clear():
    """The outer of the two — that is where the resting orders are."""
    highs = LiquidityPools.equal_highs_lows(
        [swing(100.0, "HIGH", 2), swing(100.2, "HIGH", 6)], tf="1H")
    lows = LiquidityPools.equal_highs_lows(
        [swing(100.0, "LOW", 2), swing(99.8, "LOW", 6)], tf="1H")

    assert highs[0].price == 100.2
    assert lows[0].price == 99.8


def _three_ny_days() -> list[Bar]:
    """72 hourly bars from 00:00 New York, with a distinct high on each day."""
    rows: list[tuple[float, float, float, float]] = []
    for day, peak in enumerate((110.0, 120.0, 130.0)):
        for hour in range(24):
            top = peak if hour == 12 else peak - 5
            rows.append((100, top, 90 + day, 100))
    return candles(rows)


def test_previous_day_levels_are_cut_on_new_york_days_and_only_when_complete():
    """"Previous day's high" means the previous NY session's high. Cutting on UTC midnight
    moves the boundary by four or five hours (GATE-023). And the day still running is not a
    previous day — emitting it would hand downstream rules a level that moves mid-decision."""
    pools = LiquidityPools.institutional_candlesticks(_three_ny_days(), tf="1H")
    pd_high = [p for p in pools if p.label == "PDH"]

    assert [p.price for p in pd_high] == [110.0, 120.0]
    assert 130.0 not in [p.price for p in pd_high], "the still-forming day was emitted"


def test_every_institutional_candlestick_carries_its_eq_midline():
    pools = LiquidityPools.institutional_candlesticks(_three_ny_days(), tf="1H")
    first_day = {p.label: p.price for p in pools if p.id.endswith("2026-08-03")}

    assert first_day["PDEQ"] == pytest.approx((first_day["PDH"] + first_day["PDL"]) / 2)


def test_the_asia_session_is_keyed_by_the_date_it_started_not_the_date_it_ended():
    """Asia runs 20:00–00:00 New York. Keyed by the end date, the four hours either side of
    midnight become two different sessions and neither range is the one that was traded."""
    bars = _three_ny_days()
    pools = LiquidityPools.session_levels(bars, tf="1H")
    asia = [p for p in pools if p.label == "ASIA_HIGH"]

    assert asia, "no Asia session found"
    assert all(p.pool_class == "SESSION_LEVEL" for p in pools)
    assert len({p.id for p in asia}) == len(asia), "a session was split across midnight"


def test_the_inventory_never_emits_a_class_that_needs_an_undeclared_number():
    """PARABOLIC_COMPRESSED, INSTITUTIONAL_LEVEL and DIAGONAL_POOL all rest on thresholds the
    trader declined to fix (TARGET-007 is OPEN for exactly this reason). Inventing them would
    give TARGET-001 destinations the trader never marked."""
    bars = _three_ny_days()
    swings = [swing(110.0, "HIGH", 12), swing(91.0, "LOW", 30)]
    pools = LiquidityPools.detect(bars, swings, tf="1H")

    emitted = {p.pool_class for p in pools}
    assert emitted.isdisjoint(set(LiquidityPools.UNBUILT_CLASSES))
    assert LiquidityPools.COVERAGE_NOTE and "PARTIAL" in LiquidityPools.COVERAGE_NOTE


# ===========================================================================
# PRIM-004 — sweeps, and TARGET-005 clearance
# ===========================================================================
def pool_at(price: float, side: str = "HIGH", formed: int = 0) -> LiquidityPool:
    return LiquidityPool(id=f"lq-{price}-{side}", tf="1H", pool_class="SWING_LEVEL",
                         price=price, side=side, formed_index=formed)  # type: ignore[arg-type]


def brk(index: int, direction: str, consumed: str = "sw-x") -> BreakEvent:
    return BreakEvent(id=f"brk-{index}", tf="1H", bar_time=T0 + timedelta(hours=index),
                      type="MSB", scale="MAIN", consumed_swing_id=consumed,
                      break_price=100.0, direction=direction,  # type: ignore[arg-type]
                      bar_index=index)


def test_a_body_close_beyond_a_level_does_not_clear_it():
    """TARGET-005, and it is the opposite of the break-validity rule: "a liquidity level is
    not considered cleared solely because price wicks through it or closes beyond it". With no
    structural reaction the pool stays a live objective."""
    bars = candles([
        (100, 100, 99, 100),      # 0 — pool forms here
        (100, 103, 99, 102),      # 1 — closes well beyond 100
        (102, 102, 101, 101),     # 2
    ])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars, tf="1H")

    assert len(sweeps) == 1
    assert sweeps[0].wick_or_close == "BODY_CLOSE_BEYOND"
    assert pool.state == "TESTED_NOT_CONSUMED", "a close beyond cleared the level"


def test_a_pool_is_consumed_only_when_structure_turns_against_the_run():
    bars = candles([
        (100, 100, 99, 100), (100, 103, 99, 102), (102, 102, 95, 96), (96, 97, 94, 95),
    ])
    pool = pool_at(100.0)
    SweepEvents.detect([pool], bars, [brk(2, "DOWN")], tf="1H")
    assert pool.state == "CONSUMED"


def test_structure_carrying_straight_on_means_the_level_was_passed_not_hunted():
    bars = candles([
        (100, 100, 99, 100),      # 0 — pool
        (100, 103, 99, 102),      # 1 — the sweep
        (100, 100, 97, 98),       # 2 — pulls back below, closing the excursion
        (99, 106, 99, 105),       # 3 — and carries straight on through
    ])
    pool = pool_at(100.0)
    sweeps = SweepEvents.detect([pool], bars, [brk(3, "UP")], tf="1H")

    assert pool.state == "TESTED_NOT_CONSUMED"
    assert "passed rather than hunted" in sweeps[0].structural_reaction


def test_penetration_is_measured_and_its_basis_is_always_declared():
    """TARGET-005's own `values` record that the source never says one percent OF WHAT. The
    schema makes the basis mandatory so stored history stays recomputable."""
    bars = candles([(100, 100, 99, 100), (100, 100.5, 99, 100.2), (100, 100, 99, 99)])
    sweep = SweepEvents.detect([pool_at(100.0)], bars, tf="1H")[0]

    assert sweep.penetration_abs == pytest.approx(0.5)
    assert sweep.penetration_pct == pytest.approx(0.5)
    assert sweep.penetration_pct_basis == "LEVEL_PRICE"
    assert sweep.weak_sweep is True, f"0.5% is inside the {WEAK_SWEEP_PENETRATION_PCT}% band"


def test_three_bars_spent_above_a_level_are_one_sweep_not_three():
    """One excursion is one hunt. Emitting per bar would triple-count it and make any later
    count of "how often is this level run" meaningless."""
    bars = candles([
        (100, 100, 99, 100), (100, 102, 100.5, 101), (101, 103, 101, 102),
        (102, 102.5, 101, 102), (102, 100, 98, 99),
    ])
    sweeps = SweepEvents.detect([pool_at(100.0)], bars, tf="1H")

    assert len(sweeps) == 1
    assert sweeps[0].penetration_abs == pytest.approx(3.0), "measured at the deepest bar"


def test_a_prior_close_beyond_the_level_degrades_every_later_poke():
    """"this is not the ideal sweep, it has BO and new highs over level before sweep"."""
    bars = candles([
        (100, 100, 99, 100),      # 0 — pool
        (100, 104, 99, 103),      # 1 — breaks out and closes beyond
        (100, 100, 97, 98),       # 2 — back below, closing the excursion
        (98, 101, 97, 99),        # 3 — the final poke
        (99, 99, 97, 98),         # 4
    ])
    sweeps = SweepEvents.detect([pool_at(100.0)], bars, tf="1H")

    assert len(sweeps) == 2
    assert sweeps[0].degraded_by_prior_breakout is False
    assert sweeps[1].degraded_by_prior_breakout is True


def test_a_failed_sweep_is_reported_only_against_a_declared_threshold():
    """"price comes extremely close to the LIQ1 point but it was never hunted". Extremely
    close is not a number anywhere in the corpus, so silence is the honest default."""
    bars = candles([
        (100, 100, 99, 100), (99, 99.95, 99, 99.5), (99, 99.9, 98, 98.5),
    ])
    pool = pool_at(100.0)

    assert SweepEvents.detect([pool], bars, tf="1H") == []

    declared = SweepEvents.detect([pool_at(100.0)], bars, tf="1H", near_miss_pct=0.1)
    assert len(declared) == 1
    assert declared[0].sweep_failed is True
    assert pool.state == "UNTESTED", "a level that was never crossed was not tested"


def test_eq_midlines_are_not_swept():
    """An EQ is a reference level, not resting liquidity on one side of the market, so
    "running through it" has no hunting direction to measure penetration against."""
    bars = candles([(100, 100, 99, 100), (100, 105, 95, 104)])
    mid = LiquidityPool(id="lq-eq", tf="1H", pool_class="INSTITUTIONAL_CANDLESTICK",
                        price=100.0, side="MID", label="PDEQ", formed_index=0)
    assert SweepEvents.detect([mid], bars, tf="1H") == []


# ===========================================================================
# PRIM-006 — S/R flip zones
# ===========================================================================
def test_a_flip_is_a_zone_bounded_by_the_level_and_the_retest_extreme():
    """Never a line. A flip zone is a stop anchor, and a zone collapsed to a price does not
    produce a slightly wrong stop — it produces a systematically oversized position."""
    bars = candles([
        (95, 96, 94, 95),         # 0
        (96, 103, 96, 102),       # 1 — breaks the 100 high
        (102, 103, 99, 101),      # 2 — retest: wicks to 99, closes back above
        (101, 104, 101, 103),     # 3 — and goes
    ])
    swings = [swing(100.0, "HIGH", 0)]
    flips = SRFlipZones.from_broken_levels(
        bars, swings, [brk(1, "UP", consumed=swings[0].id)], tf="1H")

    assert len(flips) == 1
    zone = flips[0]
    assert zone.origin == "BROKEN_LEVEL"
    assert (zone.price_low, zone.price_high) == (99.0, 100.0)
    assert zone.price_high > zone.price_low, "a flip zone collapsed to a line"
    assert zone.touch_count == 1


def test_a_close_back_through_the_level_means_the_flip_never_happened():
    """The level went back to being a level. Recording it as a flip would put a stop behind a
    wall that is no longer there."""
    bars = candles([
        (95, 96, 94, 95), (96, 103, 96, 102), (102, 103, 97, 98), (98, 99, 96, 97),
    ])
    swings = [swing(100.0, "HIGH", 0)]
    flips = SRFlipZones.from_broken_levels(
        bars, swings, [brk(1, "UP", consumed=swings[0].id)], tf="1H")
    assert flips == []


def test_a_failed_imbalance_mutates_into_a_flip_zone_and_says_so_on_both_objects():
    """GRADE-038: "FAILED IMBALANCES can turn into Support or Resistance areas!" An auditor
    reading the two inventories should not have to join them by price to see it is one
    object."""
    bars = candles([
        (10, 11, 9, 10), (10, 16, 9, 15), (15, 17, 13, 16), (16, 17, 12, 16),
    ])
    imb = ImbalanceInventory.detect(bars, tf="1H")[0]
    imb.purpose_verdict = "FAIL"   # GRADE-038's verdict, never set by PRIM-006

    flips = SRFlipZones.from_failed_imbalances([imb], bars, tf="1H")

    assert len(flips) == 1
    assert flips[0].origin == "FAILED_IMBALANCE"
    assert (flips[0].price_low, flips[0].price_high) == (imb.price_low, imb.price_high)
    assert imb.mutated_to_sr_flip is True


def test_an_imbalance_that_has_not_failed_the_purpose_test_is_left_alone():
    """The purpose test is GRADE-038's. Computing it here would put two behaviours behind one
    rule id, which is what base.py exists to prevent."""
    bars = candles([(10, 11, 9, 10), (10, 16, 9, 15), (15, 17, 13, 16), (16, 18, 14, 17)])
    imb = ImbalanceInventory.detect(bars, tf="1H")[0]
    assert imb.purpose_verdict is None
    assert SRFlipZones.from_failed_imbalances([imb], bars, tf="1H") == []


def test_an_inverted_zone_is_refused_at_construction():
    """An inverted interval would silently become an empty stop cushion."""
    with pytest.raises(ValueError, match="below price_low"):
        SRFlip(id="bad", tf="1H", price_high=99.0, price_low=100.0, origin="BROKEN_LEVEL")


# ===========================================================================
# Contract shape
# ===========================================================================
def test_emitted_inventories_satisfy_the_telemetry_schema():
    """Validated against the DELIVERED schema, not against our reading of it.

    Shape is not truth — a record can validate perfectly and still describe an imbalance that
    is not there. But a shape mismatch guarantees the conformance suite cannot read the record
    at all, and that is worth catching at the source.
    """
    from jsonschema import Draft202012Validator

    from app.services.telemetry import validate as val

    bars = _three_ny_days()
    imb_bars = candles([
        (10, 11, 9, 10), (10, 16, 9, 15), (15, 17, 13, 16), (16, 17, 12, 16),
    ])
    swings = [swing(110.0, "HIGH", 12), swing(91.0, "LOW", 30), swing(110.0, "HIGH", 40)]
    breaks = [brk(41, "UP", consumed=swings[0].id)]

    # The flip series is its own: a break → retest → hold needs price to stay above the
    # broken level, which the three-day fixture never does.
    flip_bars = candles([
        (95, 96, 94, 95), (96, 103, 96, 102), (102, 103, 99, 101), (101, 104, 101, 103),
    ])
    flip_swing = swing(100.0, "HIGH", 0)

    imbalances = ImbalanceInventory.detect(imb_bars, tf="1H", momentum_min_width=1.0)
    pools = LiquidityPools.detect(bars, swings, tf="1H")
    sweeps = SweepEvents.detect(pools, bars, breaks, tf="1H")
    flips = SRFlipZones.from_broken_levels(
        flip_bars, [flip_swing], [brk(1, "UP", consumed=flip_swing.id)], tf="1H")

    assert imbalances and pools and sweeps and flips, (
        "an inventory came back empty, so nothing in it was checked"
    )

    schema = val.contract.schema()["$defs"]
    for name, objects in (
        ("imbalance", imbalances),
        ("liquidity_pool", pools),
        ("sweep_event", sweeps),
        ("sr_flip", flips),
    ):
        sub = dict(schema[name])
        sub["$defs"] = schema
        validator = Draft202012Validator(sub)
        for obj in objects:
            errors = sorted(
                validator.iter_errors(obj.as_dict()), key=lambda e: list(e.absolute_path)
            )
            assert not errors, f"{name}: {[e.message for e in errors]}"
