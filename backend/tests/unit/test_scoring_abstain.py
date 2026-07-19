"""Unit tests for the CONTRACT-1 ``ScoreResult`` scoring engine.

These tests pin the *refactored* :func:`compute_score`, which returns a
:class:`ScoreResult` instead of a bare float. Invariants under test:

* A required numeric input that is NaN -> ``abstained=True`` and ``score=None``
  (explicitly NOT ``0.0``); the offending input is named in ``reasons``.
* ``price_action`` is not implemented, so it is EXCLUDED from the weighted sum
  and the weights are renormalized over the present components — there is NO
  fabricated ``0.5`` price-action floor; a ``price_action:not_implemented``
  reason is recorded and ``price_action`` never appears in ``components``.
* A few golden numeric scores are pinned for known inputs (all with
  ``htf_direction=None`` so the assertions do not depend on any MTF bonus).
"""
from __future__ import annotations

import math

import pytest

from app.services.decision.scoring import ScoreResult, compute_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_detection(confidence: float = 0.8, strength: float = 0.7) -> dict:
    return {"confidence": confidence, "strength": strength, "direction": "BULL"}


def make_indicators(
    rsi: float = 60.0, macd_histogram: float = 0.001, ema_stack: str = "bullish"
) -> dict:
    return {"rsi_14": rsi, "macd_histogram": macd_histogram, "ema_stack": ema_stack}


def balanced_profile() -> dict:
    return {
        "ict_weight": 0.40,
        "ta_weight": 0.35,
        "price_action_weight": 0.25,
        "mtf_bonus": 0.10,
    }


# ---------------------------------------------------------------------------
# Abstention on NaN required input
# ---------------------------------------------------------------------------


class TestNaNAbstains:
    def test_nan_rsi_abstains_with_none_score(self) -> None:
        res = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(rsi=float("nan")),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        assert isinstance(res, ScoreResult)
        assert res.abstained is True
        # The whole point of the contract: abstain != a confident zero.
        assert res.score is None
        assert res.score != 0.0

    def test_nan_rsi_names_the_offending_input(self) -> None:
        res = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(rsi=float("nan")),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        assert any("rsi" in r.lower() for r in res.reasons), res.reasons

    def test_valid_inputs_do_not_abstain(self) -> None:
        res = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        assert res.abstained is False
        assert res.score is not None
        assert 0.0 <= res.score <= 100.0


# ---------------------------------------------------------------------------
# price_action is excluded, NOT floored at 0.5
# ---------------------------------------------------------------------------


class TestPriceActionExcluded:
    def test_price_action_reason_recorded(self) -> None:
        res = compute_score(
            ict_detections=[make_detection()],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        assert any("price_action" in r for r in res.reasons), res.reasons
        assert "price_action" not in res.components

    def test_empty_detections_reflect_only_ict_and_ta(self) -> None:
        """No detections + no price action -> pure (ict=0, ta) with weights
        renormalized over the present components. A leftover 0.5 PA floor would
        inflate this to ~38.17 instead of ~34.22."""
        res = compute_score(
            ict_detections=[],
            indicators=make_indicators(rsi=60.0, macd_histogram=0.001, ema_stack="bullish"),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        assert res.abstained is False
        assert res.score is not None
        # ta = (|60-50|/50 + 1[macd>0] + 1[ema bullish]) / 3 = 0.733333;
        # ict = 0 (empty); renormalized over {ict, ta}: 0.35/0.75 -> 34.2222.
        assert res.score == pytest.approx(34.2222, abs=0.05)
        # And explicitly NOT the value a 0.5 price-action floor would produce.
        assert abs(res.score - 38.1667) > 1.0
        assert "price_action" not in res.components


# ---------------------------------------------------------------------------
# Golden numeric scores (htf_direction=None -> no MTF bonus in play)
# ---------------------------------------------------------------------------


class TestGoldenScores:
    @pytest.mark.parametrize(
        "detections, indicators, direction, expected",
        [
            # ict = 0.8*0.7 = 0.56; ta = (0.2 + 1 + 1)/3 = 0.733333;
            # renorm {0.4, 0.35} -> (0.56*0.4 + 0.733333*0.35)/0.75 * 100 = 64.0889
            (
                [make_detection(0.8, 0.7)],
                make_indicators(rsi=60.0, macd_histogram=0.001, ema_stack="bullish"),
                "LONG",
                64.0889,
            ),
            # ict = 0 (empty); ta = 0.733333 -> 34.2222
            (
                [],
                make_indicators(rsi=60.0, macd_histogram=0.001, ema_stack="bullish"),
                "LONG",
                34.2222,
            ),
            # ict = 1.0*1.0 = 1.0; ta = (0 + 1[macd<0] + 1[ema bearish])/3 = 0.666667;
            # renorm {0.4, 0.35} -> (1.0*0.4 + 0.666667*0.35)/0.75 * 100 = 84.4444
            (
                [make_detection(1.0, 1.0)],
                make_indicators(rsi=50.0, macd_histogram=-0.01, ema_stack="bearish"),
                "SHORT",
                84.4444,
            ),
        ],
    )
    def test_pinned_scores(self, detections, indicators, direction, expected) -> None:
        res = compute_score(
            ict_detections=detections,
            indicators=indicators,
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction=direction,
        )
        assert res.abstained is False
        assert res.score is not None
        assert res.score == pytest.approx(expected, abs=0.05)

    def test_scores_are_deterministic(self) -> None:
        args = dict(
            ict_detections=[make_detection()],
            indicators=make_indicators(),
            scoring_profile=balanced_profile(),
            htf_direction=None,
            setup_direction="LONG",
        )
        first = compute_score(**args)
        second = compute_score(**args)
        assert first.score == second.score
        assert not math.isnan(first.score if first.score is not None else 0.0)
