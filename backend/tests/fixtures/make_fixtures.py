"""Deterministic fixture generator for the backtest lookahead regression test.

Running this module (``python -m tests.fixtures.make_fixtures`` from ``backend/``)
regenerates two small, commit-safe CSVs next to this file:

* ``btc_1h.csv``     — ~200 BTC-ish 1H OHLCV bars containing a run of clean
  BULLISH fair-value-gap + retrace motifs (while the daily bias is LONG) followed
  by a run of clean BEARISH ones (after the daily bias flips SHORT).
* ``btc_daily.csv``  — a daily series whose BOS/CHoCH structure yields a LONG
  bias for the first part of the 1H window and a SHORT bias for the remainder.

The motifs are hand-shaped so that, under :data:`FIXTURE_PARAMS`, the fixed
event-driven engine opens a few dozen trades in BOTH directions — enough to make
:mod:`tests.integration.test_lookahead_regression` a real guard.

Why this is a lookahead guard
-----------------------------
``smc.fvg`` stamps a 3-candle FVG at its MIDDLE bar (``born``) with the near
edge equal to ``low[born+1]`` (bullish) / ``high[born+1]`` (bearish).  At bar
``born+1`` that edge *is* the bar's own extreme, so the engine's retrace test
(``lo <= ph`` / ``hi >= pl``) is vacuously true and would fill at the bar's exact
low/high — the lookahead tautology fixed at ``engine.py:262``.  These motifs are
built so the retrace only truly completes at ``born+2``; if the ``(i-born) < 2``
guard ever regresses, entries would land on ``born+1`` at the bar's own extreme
and the regression test fails.

This generator is the single source of truth for both the CSV data AND the
:data:`FIXTURE_PARAMS` the test replays them under; the test imports both from
here so they can never drift apart.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.services.backtest.engine import Params

FIXTURE_DIR = Path(__file__).resolve().parent
HOURLY_CSV = FIXTURE_DIR / "btc_1h.csv"
DAILY_CSV = FIXTURE_DIR / "btc_daily.csv"

# The exact params the regression test replays the fixture under. Filters that
# are orthogonal to the lookahead guard are relaxed so the guard itself (the
# born+2 admission rule) is what the test exercises; max-hold caps keep trades
# short so the single open slot frees up and many discrete motifs can fire.
FIXTURE_PARAMS = Params(
    swing_length=3,
    fvg_lookback=20,
    min_fvg_atr=0.0,
    require_ltf_bos=False,
    use_premium_discount=False,
    one_per_day=False,
    max_hold_bars=6,
    runner_max_hold=6,
    atr_period=14,
)

# Minimum trades the fixture is expected to produce (sanity floor for the test).
MIN_EXPECTED_TRADES = 6

# 1H window starts inside the LONG-bias regime; bias flips SHORT at 2024-02-22.
HOURLY_START = "2024-02-18 00:00"
DAILY_START = "2024-01-01"

# --- one 6-bar motif, as (open, high, low, close) offsets from a moving base ---
# BULLISH: bars a,b,c form a gap (high[a] < low[c]); the FVG is stamped at b
# (born) with Top = low[c] = low[born+1]. Bar d (born+2) wicks back down THROUGH
# that Top and closes above the gap bottom -> a genuine LONG retrace fill at Top.
_BULL_MOTIF = [
    (0.0, 40.0, -10.0, 25.0),      # a  -> high[a] = base + 40  (gap bottom)
    (45.0, 92.0, 42.0, 88.0),      # b  -> born
    (90.0, 125.0, 84.0, 118.0),    # c  -> low[c] = base + 84   (gap top / entry)
    (112.0, 120.0, 55.0, 96.0),    # d  -> born+2 retrace: low 55 < 84 < high 120
    (96.0, 150.0, 90.0, 145.0),    # e  -> continuation up
    (145.0, 175.0, 138.0, 170.0),  # f  -> continuation up
]
# BEARISH: mirror image. high[c] < low[a]; FVG stamped at b (born) with
# Bottom = high[c] = high[born+1]. Bar d (born+2) rallies UP through that Bottom
# and closes below the gap top -> a genuine SHORT retrace fill at Bottom.
_BEAR_MOTIF = [
    (0.0, 10.0, -40.0, -25.0),        # a  -> low[a] = base - 40  (gap top)
    (-45.0, -42.0, -92.0, -88.0),     # b  -> born
    (-90.0, -84.0, -125.0, -118.0),   # c  -> high[c] = base - 84 (gap bottom / entry)
    (-112.0, -55.0, -120.0, -96.0),   # d  -> born+2 retrace: high -55 > -84 > low -120
    (-96.0, -90.0, -150.0, -145.0),   # e  -> continuation down
    (-145.0, -138.0, -175.0, -170.0),  # f  -> continuation down
]

_N_BULL = 16  # 16 * 6 = 96 bars -> exactly the LONG-bias window (indices 0..95)
_N_BEAR = 16  # then 96 bars in the SHORT-bias window (indices 96..191)
_STEP = 170.0


def build_hourly() -> pd.DataFrame:
    """Return the deterministic 1H OHLCV fixture as a UTC-indexed DataFrame."""
    rows: list[tuple[float, float, float, float, float]] = []
    base = 42000.0
    for _ in range(_N_BULL):
        for o, h, l, c in _BULL_MOTIF:
            rows.append((base + o, base + h, base + l, base + c, 1000.0))
        base += _STEP
    for _ in range(_N_BEAR):
        for o, h, l, c in _BEAR_MOTIF:
            rows.append((base + o, base + h, base + l, base + c, 1000.0))
        base -= _STEP
    idx = pd.date_range(HOURLY_START, periods=len(rows), freq="1h", tz="UTC")
    df = pd.DataFrame(
        rows, columns=["open", "high", "low", "close", "volume"], index=idx
    ).round(2)
    df.index.name = "time"
    return df


def build_daily() -> pd.DataFrame:
    """Return the deterministic daily bias fixture (LONG then SHORT)."""
    n, period, amp = 90, 8, 1200.0

    def drift(k: int) -> float:
        # rising for the first 45 days, falling afterwards -> bias flips once
        return 250.0 * k if k < 45 else 250.0 * 45 - 300.0 * (k - 45)

    rows: list[tuple[float, float, float, float, float]] = []
    for k in range(n):
        o = 30000.0 + drift(k) + amp * np.sin(2 * np.pi * k / period)
        c = 30000.0 + drift(k + 1) + amp * np.sin(2 * np.pi * (k + 1) / period)
        rows.append((o, max(o, c) + 150.0, min(o, c) - 150.0, c, 5000.0))
    idx = pd.date_range(DAILY_START, periods=n, freq="1D", tz="UTC")
    df = pd.DataFrame(
        rows, columns=["open", "high", "low", "close", "volume"], index=idx
    ).round(2)
    df.index.name = "time"
    return df


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["time"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time")


def load_hourly() -> pd.DataFrame:
    """Load the committed 1H fixture as a UTC-indexed DataFrame."""
    return _load(HOURLY_CSV)


def load_daily() -> pd.DataFrame:
    """Load the committed daily-bias fixture as a UTC-indexed DataFrame."""
    return _load(DAILY_CSV)


def write_fixtures() -> None:
    """(Re)generate and write both CSVs next to this file."""
    build_hourly().to_csv(HOURLY_CSV)
    build_daily().to_csv(DAILY_CSV)


def _self_check() -> None:
    """Fail loudly if the committed fixture no longer trades / stays no-lookahead."""
    from app.services.backtest.engine import run_backtest

    hourly, daily = load_hourly(), load_daily()
    trades, _ = run_backtest(hourly, daily, "BTCUSDT", FIXTURE_PARAMS)
    longs = sum(1 for t in trades if t.direction == "LONG")
    shorts = sum(1 for t in trades if t.direction == "SHORT")
    assert len(trades) >= MIN_EXPECTED_TRADES, f"only {len(trades)} trades"
    assert longs and shorts, f"want both dirs, got LONG={longs} SHORT={shorts}"
    for t in trades:
        ei = hourly.index.get_loc(t.entry_time)
        hi = float(hourly["high"].iloc[ei])
        lo = float(hourly["low"].iloc[ei])
        assert t.entry != hi and t.entry != lo, f"lookahead fill @ {t.entry_time}"
    print(f"OK: {len(trades)} trades (LONG={longs} SHORT={shorts}); no lookahead fills")


if __name__ == "__main__":
    write_fixtures()
    _self_check()
    print(f"wrote {HOURLY_CSV.name} and {DAILY_CSV.name}")
