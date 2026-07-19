"""Permanent lookahead guard for the v1 backtest engine.

Regression test for the FVG lookahead tautology fixed at
``app/services/backtest/engine.py:262``.

``smc.fvg`` stamps a fair-value gap at its MIDDLE bar (``born``); the engine's
near edge (``c["ph"]`` bullish / ``c["pl"]`` bearish) equals ``low[born+1]`` /
``high[born+1]``.  At ``born+1`` that edge is the bar's OWN extreme, so the
retrace test (``lo <= ph`` / ``hi >= pl``) is vacuously satisfied and the engine
would "fill" at the bar's exact low/high — information that did not yet exist.
The fix admits an entry only from ``born+2`` onward.

This test runs the real :func:`run_backtest` on a small, committed fixture that
opens a few dozen trades in BOTH directions and asserts:

1. no produced trade's entry price equals its OWN entry-bar high or low; and
2. every entry occurs at ``born+2`` or later (re-derived from the same FVGs the
   engine sees).

The fixture is intentionally bug-sensitive: at ``born+1`` the retrace condition
is already true, so a regression of the ``(i - born) < 2`` guard would fill at
the bar's extreme and trip assertion (1).
"""
from __future__ import annotations

import pytest

from app.services.backtest.engine import run_backtest
from app.services.ict.detector import ict_detector, _normalize_df
from tests.fixtures.make_fixtures import FIXTURE_PARAMS, load_daily, load_hourly

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def backtest_result():
    """Run the engine once on the committed fixture; reuse across assertions."""
    hourly = load_hourly()
    daily = load_daily()
    trades, _equity = run_backtest(hourly, daily, "BTCUSDT", FIXTURE_PARAMS)
    return hourly, daily, trades


def _rederive_fvgs(hourly):
    """Re-run FVG detection exactly as the engine does, keyed by direction."""
    ndf = _normalize_df(hourly.reset_index().copy())
    out = []
    for f in ict_detector.detect_fvg(ndf):
        direction = "LONG" if str(f["direction"]).endswith("BULL") else "SHORT"
        # near edge the engine enters at: Top for longs, Bottom for shorts
        edge = f["price_high"] if direction == "LONG" else f["price_low"]
        out.append((direction, float(edge), int(f["candle_index"])))
    return out


def test_fixture_opens_trades_both_directions(backtest_result):
    """Guard is meaningless unless the fixture actually trades — assert it does."""
    _hourly, _daily, trades = backtest_result
    longs = sum(1 for t in trades if t.direction == "LONG")
    shorts = sum(1 for t in trades if t.direction == "SHORT")
    assert len(trades) >= 6, f"fixture opened too few trades: {len(trades)}"
    assert longs >= 1 and shorts >= 1, f"want both dirs, got LONG={longs} SHORT={shorts}"


def test_no_entry_fills_at_its_own_bar_extreme(backtest_result):
    """Core lookahead guard: an entry must never equal its own bar's high/low.

    Exact equality is the right test — the tautology fills at *exactly* the bar's
    extreme, and every price here originates from the same fixture floats.
    """
    hourly, _daily, trades = backtest_result
    offenders = []
    for t in trades:
        ei = hourly.index.get_loc(t.entry_time)
        bar_high = float(hourly["high"].iloc[ei])
        bar_low = float(hourly["low"].iloc[ei])
        if t.entry == bar_high or t.entry == bar_low:
            offenders.append(
                f"{t.direction} @ {t.entry_time}: entry {t.entry} == "
                f"{'high' if t.entry == bar_high else 'low'} of its own bar"
            )
    assert not offenders, "lookahead fill(s) at own-bar extreme:\n" + "\n".join(offenders)


def test_every_entry_is_born_plus_two_or_later(backtest_result):
    """Each entry must trace to an FVG that formed >= 2 bars earlier (and still fresh).

    Re-derives the FVGs the engine saw and matches each trade to the gap whose
    near edge equals the fill price. A born+1 fill (the bug) has no such gap in
    the admissible ``[born+2, born+fvg_lookback]`` window.
    """
    hourly, _daily, trades = backtest_result
    fvgs = _rederive_fvgs(hourly)
    lookback = FIXTURE_PARAMS.fvg_lookback
    unmatched = []
    for t in trades:
        ei = hourly.index.get_loc(t.entry_time)
        matched = any(
            direction == t.direction
            and abs(edge - t.entry) < 1e-6
            and 2 <= (ei - born) <= lookback
            for (direction, edge, born) in fvgs
        )
        if not matched:
            unmatched.append(f"{t.direction} @ {t.entry_time} (bar {ei}) entry={t.entry}")
    assert not unmatched, (
        "entries not attributable to a born+2..born+lookback FVG:\n"
        + "\n".join(unmatched)
    )
