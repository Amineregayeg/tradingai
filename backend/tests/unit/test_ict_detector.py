"""Unit tests for ICTDetector's pure detection methods.

Exercises detect_fvg(), detect_order_blocks(), detect_sd_zones(), and
detect_liquidity() on synthetic OHLCV data.

These tests do NOT touch the database — they only call the synchronous
detection methods (not detect_all(), which requires an AsyncSession).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.ict.detector import ICTDetector

# ---------------------------------------------------------------------------
# OHLCV fixture factory
# ---------------------------------------------------------------------------

REQUIRED_DETECTION_KEYS = {
    "detection_type",
    "direction",
    "price_high",
    "price_low",
    "confidence",
    "strength",
    "candle_index",
}


def make_ohlcv(n: int = 100, base_price: float = 1.1000, seed: int = 42) -> pd.DataFrame:
    """Generate reproducible synthetic OHLCV data without a time index."""
    rng = np.random.default_rng(seed)
    price = base_price
    rows = []
    for _ in range(n):
        open_ = price
        close = price + rng.uniform(-0.001, 0.001)
        high = max(open_, close) + rng.uniform(0, 0.0005)
        low = min(open_, close) - rng.uniform(0, 0.0005)
        rows.append(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000.0 + rng.uniform(0, 500),
            }
        )
        price = close
    return pd.DataFrame(rows)


def make_bullish_fvg_df() -> pd.DataFrame:
    """Craft a DataFrame that must contain at least one bullish FVG.

    Pattern: candle[0].high < candle[2].low  (3-candle imbalance).
    """
    # Build three candles guaranteeing a bullish FVG
    rows = [
        {"open": 1.1000, "high": 1.1010, "low": 1.0990, "close": 1.1005, "volume": 1000},  # c0
        {"open": 1.1020, "high": 1.1030, "low": 1.1015, "close": 1.1025, "volume": 1100},  # c1
        {"open": 1.1040, "high": 1.1050, "low": 1.1035, "close": 1.1045, "volume": 1200},  # c2
    ]
    # c0.high (1.1010) < c2.low (1.1035) → bullish FVG
    df = pd.DataFrame(rows)
    return df


# ---------------------------------------------------------------------------
# TestDetectFVG
# ---------------------------------------------------------------------------


class TestDetectFVG:
    def test_returns_list(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        result = detector.detect_fvg(df)
        assert isinstance(result, list)

    def test_each_detection_has_required_fields(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_fvg(df):
            for key in REQUIRED_DETECTION_KEYS:
                assert key in det, f"Detection missing key: {key}"

    def test_confidence_in_range(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_fvg(df):
            assert 0.0 <= det["confidence"] <= 1.0

    def test_strength_in_range(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_fvg(df):
            assert 0.0 <= det["strength"] <= 1.0

    def test_price_high_gte_price_low(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_fvg(df):
            assert det["price_high"] >= det["price_low"]

    def test_detects_bullish_fvg(self) -> None:
        """Manual FVG fallback should find the crafted bullish gap."""
        detector = ICTDetector()
        df = make_bullish_fvg_df()
        results = detector._detect_fvg_manual(df)
        assert len(results) >= 1
        # direction may be an ICTDir enum or its string value
        directions = {
            d["direction"].value if hasattr(d["direction"], "value") else str(d["direction"]).upper()
            for d in results
        }
        assert "BULL" in directions

    def test_direction_is_valid(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_fvg(df):
            direction_val = (
                det["direction"].value
                if hasattr(det["direction"], "value")
                else str(det["direction"])
            )
            assert direction_val.upper() in {"BULL", "BEAR"}

    def test_candle_index_within_bounds(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_fvg(df):
            assert 0 <= det["candle_index"] < len(df)


# ---------------------------------------------------------------------------
# TestDetectOrderBlocks
# ---------------------------------------------------------------------------


class TestDetectOrderBlocks:
    def test_returns_list(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        result = detector.detect_order_blocks(df)
        assert isinstance(result, list)

    def test_each_detection_has_required_fields(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_order_blocks(df):
            for key in REQUIRED_DETECTION_KEYS:
                assert key in det, f"OB detection missing key: {key}"

    def test_confidence_in_range(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_order_blocks(df):
            assert 0.0 <= det["confidence"] <= 1.0

    def test_price_high_gte_price_low(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_order_blocks(df):
            assert det["price_high"] >= det["price_low"]


# ---------------------------------------------------------------------------
# TestDetectSDZones
# ---------------------------------------------------------------------------


class TestDetectSDZones:
    def test_returns_list(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        result = detector.detect_sd_zones(df)
        assert isinstance(result, list)

    def test_each_detection_has_required_fields(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_sd_zones(df):
            for key in REQUIRED_DETECTION_KEYS:
                assert key in det, f"SD zone detection missing key: {key}"

    def test_confidence_in_range(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(200)
        for det in detector.detect_sd_zones(df):
            assert 0.0 <= det["confidence"] <= 1.0

    def test_too_few_candles_returns_empty(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(5)
        result = detector.detect_sd_zones(df)
        assert result == []


# ---------------------------------------------------------------------------
# TestDetectLiquidity
# ---------------------------------------------------------------------------


class TestDetectLiquidity:
    def test_returns_list(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        result = detector.detect_liquidity(df)
        assert isinstance(result, list)

    def test_manual_liquidity_has_required_fields(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(50)
        for det in detector._detect_liquidity_manual(df):
            for key in REQUIRED_DETECTION_KEYS:
                assert key in det, f"Liquidity detection missing key: {key}"

    def test_manual_liquidity_confidence_in_range(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(50)
        for det in detector._detect_liquidity_manual(df):
            assert 0.0 <= det["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# TestCombinedDetections
# ---------------------------------------------------------------------------


class TestCombinedDetections:
    def test_combined_detections_all_have_required_fields(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        all_detections = detector.detect_fvg(df) + detector.detect_order_blocks(df)
        for det in all_detections:
            for key in REQUIRED_DETECTION_KEYS:
                assert key in det

    def test_detection_type_is_string_or_enum(self) -> None:
        detector = ICTDetector()
        df = make_ohlcv(100)
        for det in detector.detect_fvg(df):
            # detection_type may be an ICTType enum or its string value
            assert det["detection_type"] is not None


# ---------------------------------------------------------------------------
# TestStructureDetectionRegression
#
# Guards against the smc-signature regression where detect_order_blocks /
# detect_bos_choch / detect_liquidity silently returned [] because the
# required swing_highs_lows argument was never passed. These detectors MUST
# emit structure on a swing-rich series. (See detector.py:_compute_swing.)
# ---------------------------------------------------------------------------


def make_zigzag(legs: int = 10, leg_len: int = 20, base: float = 100.0) -> pd.DataFrame:
    """Build a swing-rich OHLCV series of clean alternating impulse legs.

    Each leg trends decisively so smc.swing_highs_lows produces well-defined
    swing points, which OB / BOS / CHoCH detection depends on.
    """
    rng = np.random.default_rng(7)
    price = base
    rows = []
    direction = 1
    for leg in range(legs):
        step = (0.6 + 0.4 * (leg % 3)) * direction  # vary leg slope a little
        for _ in range(leg_len):
            open_ = price
            close = price + step + rng.uniform(-0.15, 0.15)
            high = max(open_, close) + rng.uniform(0.05, 0.3)
            low = min(open_, close) - rng.uniform(0.05, 0.3)
            rows.append(
                {
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 1000.0 + rng.uniform(0, 500),
                }
            )
            price = close
        direction *= -1
    return pd.DataFrame(rows)


class TestStructureDetectionRegression:
    def test_order_blocks_emit_on_swing_rich_series(self) -> None:
        detector = ICTDetector()
        df = make_zigzag()
        obs = detector.detect_order_blocks(df)
        assert len(obs) > 0, "OB detection returned [] — swing_highs_lows likely not passed (regression)"
        for det in obs:
            assert REQUIRED_DETECTION_KEYS <= set(det)
            assert det["price_high"] >= det["price_low"]

    def test_bos_choch_emit_on_swing_rich_series(self) -> None:
        detector = ICTDetector()
        df = make_zigzag()
        bos = detector.detect_bos_choch(df)
        assert len(bos) > 0, "BOS/CHoCH detection returned [] — swing_highs_lows likely not passed (regression)"

    def test_swing_is_computed(self) -> None:
        detector = ICTDetector()
        df = make_zigzag()
        swing = detector._compute_swing(df)
        assert swing is not None, "swing_highs_lows failed to compute"
