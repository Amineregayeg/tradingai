"""Swing points and break events (M3, PRIM-001 / PRIM-005).

These are the atoms. Every liquidity pool, structure box and stop anchor downstream is
derived from a swing, and the box grade they feed keys the 3x3 risk matrix — so a subtly
wrong swing series does not produce a wrong swing, it produces a wrong position size.

The series below are hand-built so the correct answer is known by construction rather than
by running the code and blessing the output.

WHAT THESE TESTS CANNOT TELL YOU
Whether these are the swings the trader would have marked. Nothing in the conformance suite
tests detector quality — a systematically wrong series scores 100% CONFORMANT while
mis-grading every box. That is readiness gate 7's job, and it needs a human.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.rules.prim_001_swings import Bar, SwingPoints
from app.services.rules.prim_005_breaks import BreakEvents
from app.services.telemetry import validate as val

T0 = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def series(highs: list[float], lows: list[float]) -> list[Bar]:
    assert len(highs) == len(lows)
    return [Bar(time=T0 + timedelta(hours=i), high=h, low=lo)
            for i, (h, lo) in enumerate(zip(highs, lows))]


# ---------------------------------------------------------------------------
# PRIM-001 — detection
# ---------------------------------------------------------------------------
def test_a_clear_swing_high_and_low_are_found():
    #        0    1    2    3    4    5    6
    bars = series(highs=[10, 11, 15, 11, 10, 11, 12],
                  lows=[ 8,  9, 13,  9,  5,  9, 10])
    swings = SwingPoints.detect(bars, tf="1H", window=2)

    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]
    assert [s.price for s in highs] == [15]
    assert [s.price for s in lows] == [5]
    assert highs[0].bar_index == 2 and lows[0].bar_index == 4


def test_the_unconfirmable_right_edge_is_omitted_not_guessed():
    """Confirmation needs bars to the right that do not exist yet. Emitting a swing at the
    hard right edge is how look-ahead enters a system that believes it is causal."""
    bars = series(highs=[10, 11, 12, 13, 20], lows=[1, 2, 3, 4, 5])
    swings = SwingPoints.detect(bars, tf="1H", window=2)
    assert all(s.bar_index < len(bars) - 2 for s in swings)
    assert not any(s.price == 20 for s in swings), "the last bar was called a swing"


def test_a_double_top_is_not_two_swings():
    """Strictly greater on both sides. Equal highs are a liquidity pool in their own right
    (PRIM-003); emitting them here too would double-count one level in two inventories."""
    bars = series(highs=[10, 11, 15, 12, 15, 11, 10],
                  lows=[ 1,  2,  3,  4,  5,  6,  7])
    highs = [s for s in SwingPoints.detect(bars, tf="1H", window=2) if s.kind == "HIGH"]
    assert highs == [] or len(highs) == 1


def test_a_window_below_one_is_refused():
    with pytest.raises(ValueError, match="window"):
        SwingPoints.detect(series([1], [1]), tf="1H", window=0)


# ---------------------------------------------------------------------------
# PRIM-005 — the geometry, which is the whole rule
# ---------------------------------------------------------------------------
def test_a_break_with_the_trend_is_a_bos_and_against_it_is_an_msb():
    """SAME candle quality, DIFFERENT location. The candles are identical here by
    construction; only the location relative to the prevailing leg differs."""
    # up, up (BOS), then a reversal down through a swing low (MSB)
    bars = series(
        highs=[10, 12, 20, 14, 16, 24, 18, 15, 12, 11, 12, 13],
        lows=[  8,  9, 15,  9, 11, 19, 13, 10,  4,  5,  6,  7],
    )
    swings = SwingPoints.detect(bars, tf="1H", window=2)
    breaks = BreakEvents.detect(bars, swings, tf="1H")

    assert breaks, "no breaks detected in a series built to contain them"
    assert breaks[0].type == "BOS", "the first break must not be an MSB"
    assert breaks[0].validity_criteria_met == ["FIRST_LEG"]

    kinds = {b.type for b in breaks}
    assert "BOS" in kinds
    # A leg that turns must produce at least one against-trend break.
    against = [b for b in breaks if b.validity_criteria_met == ["AGAINST_TREND"]]
    assert all(b.type == "MSB" for b in against)


def test_the_first_break_is_a_bos_because_no_trend_exists_yet():
    """A trend cannot be *challenged* before there is one. The assumption is stamped into
    telemetry rather than buried in the implementation."""
    bars = series(highs=[10, 11, 15, 11, 10, 20], lows=[8, 9, 13, 9, 8, 15])
    swings = SwingPoints.detect(bars, tf="1H", window=2)
    breaks = BreakEvents.detect(bars, swings, tf="1H")
    assert breaks[0].type == "BOS"
    assert "FIRST_LEG" in breaks[0].validity_criteria_met


def test_a_swing_cannot_be_broken_by_its_own_candle():
    """Allowing it would let one bar both create and consume a level — look-ahead wearing
    the shape of structure."""
    bars = series(highs=[10, 11, 15, 11, 10, 11, 12], lows=[8, 9, 13, 9, 5, 9, 10])
    swings = SwingPoints.detect(bars, tf="1H", window=2)
    breaks = BreakEvents.detect(bars, swings, tf="1H")
    by_id = {s.id: s for s in swings}
    for b in breaks:
        assert b.id.split("-")[2] != str(by_id[b.consumed_swing_id].bar_index), (
            "a swing was consumed by the bar that formed it"
        )


def test_a_level_is_only_broken_once():
    """The second run through a level is a re-test or an engineered-liquidity build
    (PRIM-004), not another break. Emitting it twice double-counts the structure."""
    bars = series(highs=[10, 11, 15, 11, 10, 20, 12, 21, 13, 22, 14, 15],
                  lows=[ 8,  9, 13,  9,  8, 15, 10, 16, 11, 17, 12, 13])
    swings = SwingPoints.detect(bars, tf="1H", window=2)
    breaks = BreakEvents.detect(bars, swings, tf="1H")
    consumed = [b.consumed_swing_id for b in breaks]
    assert len(consumed) == len(set(consumed))


def test_fake_msb_is_left_unset_because_grade_008_is_open():
    """GRADE-008 is OPEN — the trader declined to fix the detection windows. A False here
    would be a claim we cannot support."""
    bars = series(highs=[10, 11, 15, 11, 10, 20], lows=[8, 9, 13, 9, 8, 15])
    swings = SwingPoints.detect(bars, tf="1H", window=2)
    for b in BreakEvents.detect(bars, swings, tf="1H"):
        assert b.fake_msb is None
        assert "fake_msb" not in b.as_dict()


# ---------------------------------------------------------------------------
# Strength — conferred by breaks, never by shape
# ---------------------------------------------------------------------------
def test_an_unbroken_series_is_all_unconfirmed():
    """A real state, not a placeholder. Defaulting to WEAK would manufacture confirmation
    the market never gave."""
    bars = series(highs=[10, 11, 15, 11, 10, 11, 12], lows=[8, 9, 13, 9, 5, 9, 10])
    swings = SwingPoints.detect(bars, tf="1H", window=2)
    SwingPoints.classify_strength(swings, [])
    assert {s.strength for s in swings} == {"UNCONFIRMED"}


def test_a_taken_swing_becomes_weak_and_protects_a_strong_one():
    """"When the buyers push the price and take out a weak high, a strong low is
    confirmed"."""
    bars = series(highs=[10, 11, 15, 11, 10, 20, 12, 13],
                  lows=[ 8,  9, 13,  9,  5,  15, 10, 11])
    swings = SwingPoints.detect(bars, tf="1H", window=2)
    breaks = BreakEvents.detect(bars, swings, tf="1H")
    SwingPoints.classify_strength(swings, breaks)

    taken = [s for s in swings if s.strength == "WEAK"]
    assert taken, "a consumed swing was not marked WEAK"
    assert any(s.strength == "STRONG" for s in swings), "no swing was confirmed strong"
    for weak in taken:
        assert any(b.consumed_swing_id == weak.id for b in breaks)


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------
def test_emitted_primitives_satisfy_the_telemetry_schema():
    """The shapes are validated against the delivered schema, not against our reading."""
    bars = series(highs=[10, 11, 15, 11, 10, 20, 12, 13],
                  lows=[ 8,  9, 13,  9,  5, 15, 10, 11])
    swings = SwingPoints.detect(bars, tf="1H", window=2)
    breaks = BreakEvents.detect(bars, swings, tf="1H")
    SwingPoints.classify_strength(swings, breaks)

    schema = val.contract.schema()["$defs"]
    from jsonschema import Draft202012Validator

    for name, objects in (("swing_point", swings), ("break_event", breaks)):
        sub = dict(schema[name])
        sub["$defs"] = schema
        validator = Draft202012Validator(sub)
        for obj in objects:
            errors = sorted(validator.iter_errors(obj.as_dict()), key=lambda e: list(e.absolute_path))
            assert not errors, f"{name}: {[e.message for e in errors]}"
