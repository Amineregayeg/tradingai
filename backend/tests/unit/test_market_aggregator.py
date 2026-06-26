"""Tests for the market-data aggregator's boundary logic + OHLCV aggregation.

Covers the spec §M2 rules:
    5m closes when minute % 5 == 4
    15m when minute % 15 == 14
    1H when minute == 59
    4H when hour % 4 == 3 AND minute == 59
    D when hour == 23 AND minute == 59 (UTC)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from app.services.market_data.aggregator import (
    TIMEFRAMES,
    aggregate_candles,
    should_close,
)


def _t(h: int, m: int) -> datetime:
    return datetime(2026, 5, 29, h, m, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# should_close — the bar-boundary rules from the spec
# ---------------------------------------------------------------------------


def test_1m_always_closes():
    assert should_close("1m", _t(10, 0)) is True
    assert should_close("1m", _t(15, 33)) is True


def test_5m_closes_on_minute_4_9_14_etc():
    for m in [4, 9, 14, 19, 24, 29, 34, 39, 44, 49, 54, 59]:
        assert should_close("5m", _t(10, m)) is True, f"5m should close at :{m:02d}"
    for m in [0, 1, 2, 3, 5, 10, 13, 15, 30, 45, 58]:
        assert should_close("5m", _t(10, m)) is False, f"5m should NOT close at :{m:02d}"


def test_15m_closes_on_minute_14_29_44_59():
    for m in [14, 29, 44, 59]:
        assert should_close("15m", _t(10, m)) is True
    for m in [0, 13, 15, 28, 30, 43, 58]:
        assert should_close("15m", _t(10, m)) is False


def test_1h_closes_on_minute_59():
    assert should_close("1H", _t(10, 59)) is True
    for m in [0, 30, 45, 58]:
        assert should_close("1H", _t(10, m)) is False


def test_4h_closes_only_on_hour_3_7_11_15_19_23_at_minute_59():
    for h in [3, 7, 11, 15, 19, 23]:
        assert should_close("4H", _t(h, 59)) is True, f"4H should close at {h:02d}:59"
        assert should_close("4H", _t(h, 30)) is False, f"4H should NOT close at {h:02d}:30"
    for h in [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]:
        assert should_close("4H", _t(h, 59)) is False, f"4H should NOT close at {h:02d}:59"


def test_daily_closes_only_at_23_59_utc():
    assert should_close("D", _t(23, 59)) is True
    for h in range(0, 23):
        assert should_close("D", _t(h, 59)) is False, f"D should NOT close at {h:02d}:59"
    assert should_close("D", _t(23, 0)) is False
    assert should_close("D", _t(23, 30)) is False


def test_unknown_timeframe_returns_false():
    assert should_close("99m", _t(10, 30)) is False
    assert should_close("", _t(10, 30)) is False


# ---------------------------------------------------------------------------
# aggregate_candles — OHLCV correctness
# ---------------------------------------------------------------------------


def _df_1m(n: int = 5) -> pd.DataFrame:
    """5 consecutive 1m bars: prices 100..104, volume 1."""
    idx = pd.date_range("2026-05-29 10:00:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "open":   [100.0 + i for i in range(n)],
            "high":   [100.5 + i for i in range(n)],
            "low":    [99.5 + i for i in range(n)],
            "close":  [100.2 + i for i in range(n)],
            "volume": [1.0] * n,
        },
        index=idx,
    )


def test_aggregate_5m_ohlc_correctness():
    df = _df_1m(5)
    out = aggregate_candles(df, "5m")
    assert len(out) == 1
    row = out.iloc[0]
    assert row["open"] == 100.0      # first
    assert row["high"] == 104.5      # max
    assert row["low"] == 99.5        # min
    assert row["close"] == 104.2     # last
    assert row["volume"] == 5.0      # sum


def test_aggregate_unknown_timeframe_raises():
    with pytest.raises(ValueError):
        aggregate_candles(_df_1m(), "7m")


def test_aggregate_preserves_timeframes_constant():
    """The TIMEFRAMES constant defines the supported set."""
    assert "1m" in TIMEFRAMES
    assert "5m" in TIMEFRAMES
    assert "15m" in TIMEFRAMES
    assert "1H" in TIMEFRAMES
    assert "4H" in TIMEFRAMES
    assert "D" in TIMEFRAMES
