"""Unit tests for the pure compute_score() scoring function.

No I/O, no mocking — scoring.py is a pure function and these tests
exercise its spec invariants directly.
"""
import pytest
from app.services.decision.scoring import compute_score, score_to_priority


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def make_detection(confidence: float = 0.8, strength: float = 0.7, direction: str = "BULL") -> dict:
    return {
        "confidence": confidence,
        "strength": strength,
        "direction": direction,
        "detection_type": "OB",
    }


def balanced_profile() -> dict:
    """Scoring profile with equal-ish weights that sum to 1.0 (plus 0.1 MTF bonus)."""
    return {
        "ict_weight": 0.40,
        "ta_weight": 0.30,
        "price_action_weight": 0.20,
        "mtf_bonus": 0.10,
        "min_score_entry": 65,
    }


def make_indicators(
    rsi: float = 55,
    ema_stack: str = "bullish",
    macd_histogram: float = 0.001,
) -> dict:
    return {
        "rsi_14": rsi,
        "ema_21": 1.10,
        "ema_50": 1.09,
        "ema_200": 1.08,
        "atr_14": 0.0010,
        "macd_histogram": macd_histogram,
        "macd_signal": 0.0,
        "stoch_k": 60,
        "stoch_d": 55,
        "ema_stack": ema_stack,
    }


# ---------------------------------------------------------------------------
# TestComputeScore
# ---------------------------------------------------------------------------


class TestComputeScore:
    def test_returns_float_in_range(self) -> None:
        score = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction="BULL",
            setup_direction="LONG",
        )
        assert isinstance(score, float)
        assert 0.0 <= score <= 100.0

    def test_no_detections_returns_low_score(self) -> None:
        # With no ICT detections the ict_signal_score is 0, so the composite
        # is driven only by TA and price-action stubs.  Should be well below 50.
        score = compute_score(
            ict_detections=[],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        assert score < 50

    def test_high_confidence_detection_increases_score(self) -> None:
        low = compute_score(
            ict_detections=[make_detection(confidence=0.3, strength=0.3)],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        high = compute_score(
            ict_detections=[make_detection(confidence=0.9, strength=0.9)],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        assert high > low

    def test_mtf_aligned_adds_bonus(self) -> None:
        """Score WITH aligned HTF direction must exceed score WITHOUT it."""
        without_mtf = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        with_mtf = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction="BULL",
            setup_direction="LONG",
        )
        assert with_mtf > without_mtf

    def test_mtf_misaligned_no_bonus(self) -> None:
        """BEAR HTF on a LONG setup must NOT award the bonus."""
        bull_long = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction="BULL",
            setup_direction="LONG",
        )
        bear_long = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction="BEAR",
            setup_direction="LONG",
        )
        assert bull_long > bear_long

    def test_score_clamped_max_100(self) -> None:
        """Perfect conditions must never exceed 100."""
        score = compute_score(
            ict_detections=[
                make_detection(confidence=1.0, strength=1.0),
                make_detection(confidence=1.0, strength=1.0),
            ],
            indicators=make_indicators(rsi=50, ema_stack="bullish", macd_histogram=0.01),
            scoring_profile=balanced_profile(),
            htf_direction="BULL",
            setup_direction="LONG",
        )
        assert score <= 100.0

    def test_score_clamped_min_0(self) -> None:
        """Worst conditions must never go below 0."""
        score = compute_score(
            ict_detections=[],
            indicators=make_indicators(rsi=80, ema_stack="bearish", macd_histogram=-0.01),
            scoring_profile=balanced_profile(),
            htf_direction="BEAR",
            setup_direction="LONG",
        )
        assert score >= 0.0

    def test_same_inputs_same_output(self) -> None:
        """Score must be deterministic — identical inputs produce identical output."""
        args = (
            [make_detection()],
            make_indicators(),
            balanced_profile(),
            "BULL",
            "LONG",
        )
        assert compute_score(*args) == compute_score(*args)

    def test_short_setup_inverts_macd_and_ema(self) -> None:
        """For a SHORT setup, bearish indicators should score better than bullish."""
        bearish = compute_score(
            ict_detections=[make_detection(direction="BEAR")],
            indicators=make_indicators(ema_stack="bearish", macd_histogram=-0.005),
            scoring_profile=balanced_profile(),
            htf_direction="BEAR",
            setup_direction="SHORT",
        )
        bullish = compute_score(
            ict_detections=[make_detection(direction="BEAR")],
            indicators=make_indicators(ema_stack="bullish", macd_histogram=0.005),
            scoring_profile=balanced_profile(),
            htf_direction="BULL",
            setup_direction="SHORT",
        )
        # bearish indicators + BEAR HTF alignment give a higher SHORT score
        assert bearish > bullish

    def test_bear_htf_with_short_gives_bonus(self) -> None:
        """BEAR HTF + SHORT setup should be aligned and grant the MTF bonus."""
        without = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(ema_stack="bearish", macd_histogram=-0.001),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="SHORT",
        )
        with_bear = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(ema_stack="bearish", macd_histogram=-0.001),
            scoring_profile=balanced_profile(),
            htf_direction="BEAR",
            setup_direction="SHORT",
        )
        assert with_bear > without

    def test_weights_respected(self) -> None:
        """Higher ict_weight should make ICT detection have greater impact on score."""
        ict_heavy = {
            "ict_weight": 0.80,
            "ta_weight": 0.10,
            "price_action_weight": 0.10,
            "mtf_bonus": 0.0,
        }
        ta_heavy = {
            "ict_weight": 0.10,
            "ta_weight": 0.80,
            "price_action_weight": 0.10,
            "mtf_bonus": 0.0,
        }
        # High-confidence detection + poor TA should score better with ict_heavy weights
        high_det_poor_ta = compute_score(
            ict_detections=[make_detection(0.9, 0.9)],
            indicators=make_indicators(rsi=50, ema_stack="mixed", macd_histogram=0.0),
            scoring_profile=ict_heavy,
            htf_direction=None,
            setup_direction="LONG",
        )
        high_det_poor_ta_ta_weight = compute_score(
            ict_detections=[make_detection(0.9, 0.9)],
            indicators=make_indicators(rsi=50, ema_stack="mixed", macd_histogram=0.0),
            scoring_profile=ta_heavy,
            htf_direction=None,
            setup_direction="LONG",
        )
        assert high_det_poor_ta > high_det_poor_ta_ta_weight


# ---------------------------------------------------------------------------
# TestScoreToPriority
# ---------------------------------------------------------------------------


class TestScoreToPriority:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (100.0, "CRITICAL"),
            (85.0, "CRITICAL"),
            (80.0, "CRITICAL"),
            (79.9, "WARNING"),
            (65.0, "WARNING"),
            (60.0, "WARNING"),
            (59.9, "SUGGESTION"),
            (45.0, "SUGGESTION"),
            (40.0, "SUGGESTION"),
            (39.9, "INFO"),
            (20.0, "INFO"),
            (0.0, "INFO"),
        ],
    )
    def test_thresholds(self, score: float, expected: str) -> None:
        assert score_to_priority(score) == expected

    def test_returns_string(self) -> None:
        assert isinstance(score_to_priority(75.0), str)
