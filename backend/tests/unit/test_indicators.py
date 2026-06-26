"""Unit tests for the Indicators.compute_all() method.

Uses synthetic OHLCV data — no external services required.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.services.ict.indicators import Indicators

# ---------------------------------------------------------------------------
# OHLCV fixture factory
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {
    "rsi_14",
    "ema_21",
    "ema_50",
    "ema_200",
    "atr_14",
    "macd_histogram",
    "macd_signal",
    "stoch_k",
    "stoch_d",
    "ema_stack",
}

VALID_EMA_STACKS = {"bullish", "bearish", "mixed"}


def make_candles(n: int = 250, trend: str = "up", seed: int = 42) -> pd.DataFrame:
    """Generate reproducible synthetic OHLCV data."""
    rng = np.random.default_rng(seed)
    price = 1.1000
    rows = []
    for i in range(n):
        if trend == "up":
            price += rng.uniform(0.0001, 0.0003)
        elif trend == "down":
            price -= rng.uniform(0.0001, 0.0003)
        else:
            price += rng.uniform(-0.0002, 0.0002)

        open_ = price
        close = price + rng.uniform(-0.0005, 0.0005)
        high = max(open_, close) + rng.uniform(0, 0.0002)
        low = min(open_, close) - rng.uniform(0, 0.0002)
        rows.append(
            {
                "time": pd.Timestamp("2024-01-01") + pd.Timedelta(minutes=i),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000.0 + rng.uniform(0, 500),
            }
        )

    df = pd.DataFrame(rows).set_index("time")
    return df


# ---------------------------------------------------------------------------
# TestComputeAll
# ---------------------------------------------------------------------------


class TestComputeAll:
    def test_returns_dict(self) -> None:
        ind = Indicators()
        result = ind.compute_all(make_candles(250))
        assert isinstance(result, dict)

    def test_returns_all_required_keys(self) -> None:
        ind = Indicators()
        result = ind.compute_all(make_candles(250))
        for key in REQUIRED_KEYS:
            assert key in result, f"Missing key: {key}"

    def test_rsi_in_valid_range(self) -> None:
        ind = Indicators()
        result = ind.compute_all(make_candles(250))
        rsi = result["rsi_14"]
        if not math.isnan(rsi):
            assert 0 <= rsi <= 100, f"RSI {rsi} out of range [0, 100]"

    def test_ema_stack_is_valid_string(self) -> None:
        ind = Indicators()
        result = ind.compute_all(make_candles(250))
        assert result["ema_stack"] in VALID_EMA_STACKS

    def test_atr_is_positive(self) -> None:
        ind = Indicators()
        result = ind.compute_all(make_candles(250))
        atr = result["atr_14"]
        if not math.isnan(atr):
            assert atr > 0, "ATR should be positive"

    def test_ema_values_are_numeric(self) -> None:
        ind = Indicators()
        result = ind.compute_all(make_candles(250))
        for key in ("ema_21", "ema_50", "ema_200"):
            assert isinstance(result[key], float), f"{key} should be float"

    def test_ema_stack_bullish_on_uptrend(self) -> None:
        """Strong uptrend with enough bars should produce a bullish EMA stack."""
        ind = Indicators()
        # 500 bars of strong uptrend to guarantee EMA 21 > 50 > 200
        df = make_candles(500, trend="up", seed=0)
        result = ind.compute_all(df)
        # The stack label should be bullish for a sustained uptrend
        assert result["ema_stack"] == "bullish"

    def test_ema_stack_bearish_on_downtrend(self) -> None:
        """Strong downtrend with enough bars should produce a bearish EMA stack."""
        ind = Indicators()
        df = make_candles(500, trend="down", seed=0)
        result = ind.compute_all(df)
        assert result["ema_stack"] == "bearish"

    def test_macd_histogram_is_numeric(self) -> None:
        ind = Indicators()
        result = ind.compute_all(make_candles(250))
        hist = result["macd_histogram"]
        if not math.isnan(hist):
            assert isinstance(hist, float)

    def test_stoch_in_range(self) -> None:
        ind = Indicators()
        result = ind.compute_all(make_candles(250))
        for key in ("stoch_k", "stoch_d"):
            val = result[key]
            if not math.isnan(val):
                assert 0 <= val <= 100, f"{key}={val} out of [0, 100]"

    def test_short_candle_series_does_not_crash(self) -> None:
        """compute_all must not raise even for a very short series."""
        ind = Indicators()
        df = make_candles(30)
        result = ind.compute_all(df)
        assert "rsi_14" in result  # key present, value may be NaN

    def test_ema_ordering_on_uptrend(self) -> None:
        """For 500-bar uptrend: EMA21 should be greater than EMA200."""
        ind = Indicators()
        df = make_candles(500, trend="up", seed=1)
        result = ind.compute_all(df)
        e21 = result["ema_21"]
        e200 = result["ema_200"]
        if not (math.isnan(e21) or math.isnan(e200)):
            assert e21 > e200


# ---------------------------------------------------------------------------
# TestEmaStackHelper (internal method tested directly)
# ---------------------------------------------------------------------------


class TestEmaStackHelper:
    def test_bullish_when_21_gt_50_gt_200(self) -> None:
        ind = Indicators()
        assert ind._ema_stack(1.12, 1.10, 1.08) == "bullish"

    def test_bearish_when_21_lt_50_lt_200(self) -> None:
        ind = Indicators()
        assert ind._ema_stack(1.08, 1.10, 1.12) == "bearish"

    def test_mixed_when_ordering_is_unclear(self) -> None:
        ind = Indicators()
        assert ind._ema_stack(1.10, 1.12, 1.08) == "mixed"

    def test_mixed_when_nan_present(self) -> None:
        ind = Indicators()
        assert ind._ema_stack(float("nan"), 1.10, 1.08) == "mixed"
