"""T-0046 — PRIM-007, and the arms that separate Salim's definition from a plausible detector.

**The load-bearing test in this file is the one that expects DISAGREEMENT.** `detect_order_blocks()`
already existed at `ict/detector.py:192`, wrapping it would have produced a working rung 4 in an
afternoon, and the pack says *"the third-party detector's 94.5% hit rate is not evidence about this
definition."* So the corpus arm measures PRIM-007 against the ICT proxy and **fails if they agree
exactly** — the one outcome that cannot be read as success, because it is what reimplementing ICT
would look like.
"""
from __future__ import annotations

import csv
import pathlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.rules.gate_027_stop_ladder import (
    RUNG2_ELIGIBILITY, LadderInputs, StopCandidateLadder,
)
from app.services.rules.prim_001_swings import Bar
from app.services.rules.prim_002_imbalances import ImbalanceInventory
from app.services.rules.prim_005_breaks import BreakEvent
from app.services.rules.prim_007_order_blocks import (
    BOX_BOUNDS_DEFAULT, DECLARED_WALK_BACK_CAP, OrderBlock, OrderBlocks, _is_opposite_colour,
)

T0 = datetime(2024, 3, 1, 9, 30, tzinfo=ZoneInfo("America/New_York"))
FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "btcusdtp_5m_1500.csv"


def _bar(i: int, o: float, h: float, low: float, c: float) -> Bar:
    return Bar(time=T0 + timedelta(minutes=5 * i), high=h, low=low, open=o, close=c)


def _up_break(bar_index: int) -> BreakEvent:
    return BreakEvent(
        id="MSB-1", tf="5m", bar_time=T0 + timedelta(minutes=5 * bar_index), type="MSB",
        scale="MAIN", consumed_swing_id="SW-1", break_price=100.0, direction="UP",
        bar_index=bar_index,
    )


# ---------------------------------------------------------------------------
# The walk back — the definition itself
# ---------------------------------------------------------------------------
def test_the_block_is_the_LAST_opposite_colour_candle_before_the_impulse():
    """His words: the small red candle before the big green. LAST, not first, not all."""
    bars = [
        _bar(0, 100, 101, 99, 98),    # red, EARLIER — must NOT be chosen
        _bar(1, 98, 99, 97, 96),      # red, the LAST one before the impulse -> THE BLOCK
        _bar(2, 96, 104, 96, 103),    # green impulse
        _bar(3, 103, 110, 103, 109),  # green impulse, the break candle
    ]
    blocks = OrderBlocks.detect(bars, [_up_break(3)], tf="5m")
    assert len(blocks) == 1
    assert blocks[0].bar_index == 1, "picked the wrong red candle — LAST_CANDLE_ONLY"
    assert blocks[0].direction == "DEMAND"
    assert blocks[0].ob_at_origin is False


def test_a_DOJI_counts_as_same_colour_and_does_not_stop_the_walk():
    """Named in the ruling, so it is not a rounding decision.

    A doji is precisely where a body-less reading would pick a different candle, which is why he
    says which way it falls.
    """
    bars = [
        _bar(0, 100, 101, 99, 98),   # red -> the block
        _bar(1, 98, 99, 97, 98),     # DOJI: close == open. Same-colour by ruling: keep walking
        _bar(2, 98, 104, 98, 103),   # green impulse
        _bar(3, 103, 110, 103, 109),
    ]
    blocks = OrderBlocks.detect(bars, [_up_break(3)], tf="5m")
    assert blocks[0].bar_index == 0, "the doji stopped the walk — it counts as same-colour"
    assert _is_opposite_colour(bars[1], "UP") is False
    # MUST-HIT on the helper, or "False" above could be a body-less None coerced by luck.
    assert _is_opposite_colour(bars[0], "UP") is True
    assert _is_opposite_colour(Bar(time=T0, high=1.0, low=0.0), "UP") is None


def test_a_bearish_setup_mirrors_and_produces_SUPPLY():
    bars = [
        _bar(0, 100, 101, 99, 102),   # green -> the block for a DOWN impulse
        _bar(1, 102, 103, 96, 97),    # red impulse
        _bar(2, 97, 98, 90, 91),      # red impulse, break candle
    ]
    blocks = OrderBlocks.detect(bars, [BreakEvent(
        id="MSB-2", tf="5m", bar_time=T0, type="MSB", scale="MAIN", consumed_swing_id="SW",
        break_price=90.0, direction="DOWN", bar_index=2,
    )], tf="5m")
    assert blocks[0].direction == "SUPPLY"
    assert blocks[0].bar_index == 0


def test_no_opposite_colour_candle_is_recorded_as_ob_at_origin_and_NOT_as_a_find():
    """The ruling's fallback, and it must stay distinguishable.

    A block at the origin is not the object the definition describes. Recording it as an ordinary
    find would put a candle nobody selected into rung 4's anchor pool.
    """
    bars = [_bar(i, 100 + i, 105 + i, 99 + i, 104 + i) for i in range(5)]  # all green
    blocks = OrderBlocks.detect(bars, [_up_break(4)], tf="5m")
    assert blocks and blocks[0].ob_at_origin is True
    assert blocks[0].as_dict()["ob_at_origin"] is True
    # MUST-MISS: a real find does NOT carry the flag, so it is not simply always set.
    real = OrderBlocks.detect(
        [_bar(0, 100, 101, 99, 98), _bar(1, 98, 106, 98, 105), _bar(2, 105, 112, 105, 111)],
        [_up_break(2)], tf="5m",
    )
    assert real[0].ob_at_origin is False


def test_the_walk_stops_at_rung_1s_swing_bound_when_one_is_given():
    """The ruling bounds the walk; the declared cap applies ONLY when no bound is supplied."""
    bars = [
        _bar(0, 100, 101, 99, 98),    # red, but BEFORE the bound
        _bar(1, 98, 104, 98, 103),
        _bar(2, 103, 105, 102, 104),
        _bar(3, 104, 110, 104, 109),
    ]
    bounded = OrderBlocks.detect(bars, [_up_break(3)], tf="5m", swing_bound_index=1)
    assert bounded[0].ob_at_origin is True, "the walk crossed its bound and found the red candle"
    unbounded = OrderBlocks.detect(bars, [_up_break(3)], tf="5m")
    assert unbounded[0].bar_index == 0 and unbounded[0].ob_at_origin is False
    assert DECLARED_WALK_BACK_CAP.ratified is False
    assert DECLARED_WALK_BACK_CAP.competing, "the option not taken must be recorded"


# ---------------------------------------------------------------------------
# FAILED requires a BODY close — and the wick case is the must-miss
# ---------------------------------------------------------------------------
def test_a_WICK_through_the_box_is_NOT_a_flip():
    """The doctrine, and the same fact as the stop sitting beyond the wick.

    A definition that failed on wicks would flip the block on exactly the excursions the stop is
    placed to survive — so this must-miss is the arm that makes the FAILED test mean anything.
    """
    bars = [
        _bar(0, 100, 101, 99, 98),     # the block: wick_low 99, body_low 98
        _bar(1, 98, 106, 98, 105),
        _bar(2, 105, 106, 90, 104),    # WICK to 90, well through — but CLOSES at 104
    ]
    blocks = OrderBlocks.detect(bars, [_up_break(1)], tf="5m")
    assert blocks[0].state != "FAILED", "a wick through flipped the block"

    # MUST-HIT: the same excursion that CLOSES through does flip it.
    bars_closing = list(bars[:2]) + [_bar(2, 105, 106, 90, 91)]
    flipped = OrderBlocks.detect(bars_closing, [_up_break(1)], tf="5m")
    assert flipped[0].state == "FAILED", "a body close through did NOT flip the block"


def test_a_block_is_TESTED_only_once_price_has_LEFT_it_and_COME_BACK():
    """The impulse candle emerges FROM the block and necessarily overlaps it.

    Counting that contact would mark every block TESTED at birth — *tested by the move that
    created it* — and make `first_test` meaningless. Price must leave before it can return.
    """
    away = [
        _bar(0, 100, 101, 99, 98),      # the block: 99..101
        _bar(1, 98, 106, 98, 105),      # the impulse — starts INSIDE, so it is not a test
        _bar(2, 105, 110, 104, 109),    # fully clear of the box: price has LEFT
    ]
    assert OrderBlocks.detect(away, [_up_break(1)], tf="5m")[0].state == "UNTESTED"

    returned = away + [_bar(3, 109, 110, 100, 102)]  # back inside 99..101 -> a real test
    assert OrderBlocks.detect(returned, [_up_break(1)], tf="5m")[0].state == "TESTED"

    # MUST-MISS on the departure itself: the impulse alone never marks the block tested, even
    # though it overlaps — which is the whole point of the `left_the_box` gate.
    impulse_only = away[:2]
    assert OrderBlocks.detect(impulse_only, [_up_break(1)], tf="5m")[0].state == "UNTESTED"


# ---------------------------------------------------------------------------
# The box carries BOTH extremes, because his slides disagree
# ---------------------------------------------------------------------------
def test_both_box_extremes_are_stored_and_the_WICK_is_anchored():
    bars = [_bar(0, 100, 103, 96, 98), _bar(1, 98, 106, 98, 105), _bar(2, 105, 112, 105, 111)]
    block = OrderBlocks.detect(bars, [_up_break(1)], tf="5m")[0]
    assert (block.wick_high, block.wick_low) == (103, 96)
    assert (block.body_high, block.body_low) == (100, 98)
    assert block.stop_anchor == 96, "DEMAND must anchor on the wick LOW — trader ruling round 3"
    emitted = block.as_dict()
    for key in ("wick_high", "wick_low", "body_high", "body_low", "box_high", "box_low"):
        assert key in emitted, f"{key} missing — the alternative bounds become uncomputable"
    assert emitted["box_bounds"] == BOX_BOUNDS_DEFAULT == "WICK_TO_WICK"


def test_several_same_colour_candles_box_the_LAST_and_LOG_the_merged_alternative():
    """`LAST_CANDLE_ONLY` is the policy; merging is the option he did not take, so it is logged."""
    bars = [
        _bar(0, 100, 108, 92, 98),    # red, earlier, WIDE — the merged extreme comes from here
        _bar(1, 98, 99, 97, 99.5),    # green (same colour as the impulse)
        _bar(2, 99.5, 100, 98, 100),  # green
        _bar(3, 100, 107, 100, 106),  # impulse / break candle
    ]
    block = OrderBlocks.detect(bars, [_up_break(3)], tf="5m")[0]
    assert block.bar_index == 0
    assert block.merged_alternative is not None, "the merged extreme was discarded, not logged"
    merged_high, merged_low = block.merged_alternative
    assert merged_high >= block.wick_high and merged_low <= block.wick_low
    assert block.box_high == block.wick_high, "the MERGED extreme was selected — policy is LAST"


def test_ob_grade_is_OMITTED_when_unevaluable_and_never_a_dict_of_False():
    """`False` says "checked and it does not hold". Absence says "not checked".

    `B166` is this session's evidence for what collapsing those costs.
    """
    bars = [_bar(0, 100, 101, 99, 98), _bar(1, 98, 106, 98, 105), _bar(2, 105, 112, 105, 111)]
    emitted = OrderBlocks.detect(bars, [_up_break(1)], tf="5m")[0].as_dict()
    assert "ob_grade" not in emitted or emitted["ob_grade"], (
        "ob_grade emitted as an empty or all-False dict — that asserts six checks nobody ran"
    )


# ---------------------------------------------------------------------------
# GATE-027 — the unblocking, and the None/() distinction
# ---------------------------------------------------------------------------
def _inputs(**kw) -> LadderInputs:
    base = dict(entry=100.0, target=110.0, direction="LONG",
                search_window_from=T0, search_window_to=T0 + timedelta(hours=4))
    base.update(kw)
    return LadderInputs(**base)


def test_the_rule_level_blocker_is_GONE_because_the_producer_exists():
    assert not getattr(StopCandidateLadder, "CANNOT_FIRE_WITHOUT", ()), (
        "GATE-027 still declares it cannot fire without an order-block detector — PRIM-007 is one"
    )


def test_a_caller_that_did_NOT_run_the_detector_is_not_the_same_as_one_that_found_nothing():
    """`None` is a producer gap for THAT call; `()` is a real empty search.

    Collapsing them is B166 one layer down, and it is the difference between "we never looked" and
    "there are no order blocks here" appearing identically in the record.
    """
    not_run = StopCandidateLadder.build(_inputs(order_blocks=None))
    rung4_not_run = next(c for c in not_run if c.anchor == "ORDER_BLOCK")
    assert rung4_not_run.missing_producer, "a caller that never searched claims a search failure"

    searched = StopCandidateLadder.build(_inputs(order_blocks=()))
    rung4_searched = next(c for c in searched if c.anchor == "ORDER_BLOCK")
    assert not rung4_searched.missing_producer, (
        "a caller that ran the detector and found nothing is still reported as a producer gap"
    )
    assert rung4_searched.locatable is False


def test_rung_4_locates_the_deepest_block_on_the_stop_side_at_its_WICK():
    near = OrderBlock(id="OB-near", tf="5m", origin_candle_ts=T0, direction="DEMAND",
                      wick_high=99.0, wick_low=98.0, body_high=98.8, body_low=98.2)
    deep = OrderBlock(id="OB-deep", tf="5m", origin_candle_ts=T0, direction="DEMAND",
                      wick_high=97.0, wick_low=94.0, body_high=96.5, body_low=95.0)
    wrong_side = OrderBlock(id="OB-above", tf="5m", origin_candle_ts=T0, direction="DEMAND",
                            wick_high=106.0, wick_low=105.0, body_high=105.8, body_low=105.2)
    ladder = StopCandidateLadder.build(_inputs(order_blocks=(near, deep, wrong_side)))
    rung4 = next(c for c in ladder if c.anchor == "ORDER_BLOCK")
    assert rung4.locatable is True
    assert rung4.anchor_object_id == "OB-deep", "rung 4 did not take the deepest block"
    assert rung4.stop_price == 94.0, "rung 4 anchored on something other than the WICK extreme"


# ---------------------------------------------------------------------------
# Rung 2 — B167, and the arm the forbidden fix must NOT satisfy
# ---------------------------------------------------------------------------
def test_the_rung_2_pool_selects_on_OPENNESS_and_not_on_the_momentum_flag():
    """The ruling: *"Split the flag from the anchor."* Read from the registry, not retyped."""
    assert RUNG2_ELIGIBILITY["gated_on_momentum_flag"] is False
    assert RUNG2_ELIGIBILITY["fill_state_in"] == ["UNFILLED", "HALF_FILLED"]
    assert RUNG2_ELIGIBILITY["min_width"] == 0


@pytest.mark.parametrize("state,eligible", [
    ("UNFILLED", True), ("HALF_FILLED", True),
    ("FULLY_FILLED", False), ("FULLY_FILLED_AND_VIOLATED", False),
])
def test_B167_the_closed_states_are_EXCLUDED_and_the_flag_is_irrelevant(state, eligible):
    """The regression arm for the dead comparison.

        was:  i.is_momentum_imbalance is True and i.fill_state != "FILLED"

    `"FILLED"` is `OrderStatus.FILLED`, not a `FillState` — always true, excluded nothing. It was
    invisible because the flag conjunct was always false. **Every imbalance below carries
    `is_momentum_imbalance = None`, which is its production value, so this arm cannot be satisfied
    by populating the flag** — the forbidden fix (`momentum_min_width`, the fixed-width test
    GATE-035 bans and Salim ruled has no threshold).
    """
    from app.services.rules.prim_002_imbalances import Imbalance

    imb = Imbalance(id="IMB-1", tf="5m", bar_time=T0, price_high=97.0, price_low=95.0,
                    type="FVG", direction="BULLISH", fill_state=state)
    assert imb.is_momentum_imbalance is None, "production value is None; this arm assumes it"
    report = StopCandidateLadder.rung2_pool_report(_inputs(imbalances=(imb,)))
    assert report["imbalances_considered"] == 1, "the denominator must be published either way"
    assert (report["open_pool"] == 1) is eligible, (
        f"{state} eligibility is wrong — a closed imbalance was admitted as a stop anchor"
    )


def test_the_entry_POI_exclusion_is_TRI_STATE_because_not_told_is_not_no():
    from app.services.rules.prim_002_imbalances import Imbalance

    poi = Imbalance(id="IMB-POI", tf="5m", bar_time=T0, price_high=97.0, price_low=95.0,
                    type="FVG", direction="BULLISH", fill_state="UNFILLED")
    other = Imbalance(id="IMB-2", tf="5m", bar_time=T0, price_high=94.0, price_low=92.0,
                      type="FVG", direction="BULLISH", fill_state="UNFILLED")
    assert RUNG2_ELIGIBILITY["entry_poi_imbalance_eligible"] is False

    not_told = StopCandidateLadder.rung2_pool_report(_inputs(imbalances=(poi, other)))
    assert not_told["entry_poi_excluded"] is None, "NOT TOLD was reported as a decision"
    assert not_told["pool_after_entry_poi_exclusion"] == 2

    told = StopCandidateLadder.rung2_pool_report(
        _inputs(imbalances=(poi, other), entry_poi_imbalance_id="IMB-POI"))
    assert told["entry_poi_excluded"] is True
    assert told["pool_after_entry_poi_exclusion"] == 1


def test_momentum_min_width_is_STILL_supplied_by_no_production_path():
    """THE MUST-MISS THE WHOLE RUNG-2 FIX DEPENDS ON.

    If this task had made rung 2 work by populating `is_momentum_imbalance`, it would have done so
    by passing `momentum_min_width` — a fixed-width test on an imbalance, which `GATE-035` bans and
    which Salim has now separately ruled has NO threshold (`min_imbalance_width: 0`). **The arm
    above would pass either way; this is what distinguishes the two fixes.**
    """
    import ast

    app_dir = pathlib.Path(__file__).resolve().parents[2] / "app"
    suppliers: list[str] = []
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "momentum_min_width" and not (
                        isinstance(kw.value, ast.Name) and kw.value.id == "momentum_min_width"
                    ):
                        suppliers.append(f"{path.name}:{node.lineno}")
    assert not suppliers, (
        f"momentum_min_width is now supplied at {suppliers} — the rung-2 pool was fixed with the "
        "banned fixed-width test rather than with the ruling's open-ness predicate"
    )


# ---------------------------------------------------------------------------
# THE ARM THAT EXPECTS DISAGREEMENT
# ---------------------------------------------------------------------------
def test_PRIM_007_DISAGREES_with_the_pre_contract_ICT_detector_on_the_pinned_corpus():
    """**Exact agreement is the failure.**

    `detect_order_blocks()` at `ict/detector.py:192` is the pre-contract strategy, allowed as a
    measurement PROXY and forbidden for selection. Wrapping it would have produced a working rung
    4 immediately — so the question this arm answers is not *"does PRIM-007 work?"* but *"is
    PRIM-007 a different object from the one that was already here?"*

    > If the two agreed exactly, the most likely explanation is that this module reimplemented ICT
    > rather than the ruling — and no amount of green elsewhere would distinguish those.

    The arm is deliberately weak in one direction and strong in the other: it does NOT claim
    PRIM-007 is right, only that it is NOT the proxy. *Correctness against his definition is not
    something a corpus can settle; distinctness is.*
    """
    pd = pytest.importorskip("pandas")
    from app.services.ict.detector import ICTDetector
    from app.services.rules.prim_001_swings import SwingPoints
    from app.services.rules.prim_005_breaks import BreakEvents

    rows = list(csv.DictReader(FIXTURE.open()))[:863]
    bars = [Bar(time=datetime.fromisoformat(r["time"]), high=float(r["high"]),
                low=float(r["low"]), open=float(r["open"]), close=float(r["close"]))
            for r in rows]

    swings = SwingPoints.detect(bars, tf="5m")
    breaks = BreakEvents.detect(bars, swings, tf="5m")
    ours = OrderBlocks.detect(bars, breaks, tf="5m")

    frame = pd.DataFrame({
        "open": [b.open for b in bars], "high": [b.high for b in bars],
        "low": [b.low for b in bars], "close": [b.close for b in bars],
        "volume": [1.0] * len(bars),
    })
    theirs = ICTDetector().detect_order_blocks(frame)

    # MUST-HIT on both instruments: an empty side would make "they differ" vacuous.
    assert ours, "PRIM-007 found no order blocks on the pinned corpus — the comparison is vacuous"
    assert theirs, "the ICT proxy found none — the comparison is vacuous"

    our_origins = {b.bar_index for b in ours}
    their_origins = {int(b.get("candle_index", -1)) for b in theirs}
    assert our_origins != their_origins, (
        f"PRIM-007 selected EXACTLY the ICT proxy's candles ({len(our_origins)} of them). The most "
        "likely explanation is that this module reimplemented the pre-contract detector rather "
        "than Salim's definition, which is the move TARGET-001 refuses."
    )
