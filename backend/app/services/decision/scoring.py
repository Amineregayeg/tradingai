"""Pure, deterministic scoring engine.

No I/O — fully testable in isolation.  All inputs are plain Python dicts /
lists / scalars; no SQLAlchemy models are imported here.
"""
from __future__ import annotations

from decimal import Decimal


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------


def compute_score(
    ict_detections: list[dict],
    indicators: dict,
    scoring_profile: dict,
    htf_direction: str | None,
    setup_direction: str,
) -> float:
    """Compute a composite trade-quality score in the range [0, 100].

    Formula::

        score = (
            ict_signal_score  * ict_weight  +
            ta_signal_score   * ta_weight   +
            price_action_score * price_action_weight
        ) * 100

        if mtf_aligned:
            score += mtf_bonus * 100

        score = clamp(score, 0, 100)

    Component definitions:

    ``ict_signal_score``
        ``max(confidence * strength)`` across ACTIVE detections in the list.
        Defaults to 0 when *ict_detections* is empty.

    ``ta_signal_score``
        Weighted average of three sub-scores:

        * **RSI deviation** — ``abs(rsi_14 - 50) / 50``, clamped to [0, 1].
        * **MACD histogram sign** — 1 when > 0, else 0 (buy-biased).
          Inverted for SHORT setups.
        * **EMA stack alignment** — 1 when ``ema_stack`` value implies
          direction matches *setup_direction*, else 0.

        Sub-scores receive equal weight (1/3 each).

    ``price_action_score``
        Stub value of 0.5 (full implementation deferred to Phase 2).

    ``mtf_aligned``
        ``True`` when *htf_direction* is ``"BULL"`` and *setup_direction* is
        ``"LONG"``, or *htf_direction* is ``"BEAR"`` and *setup_direction* is
        ``"SHORT"``.

    Args:
        ict_detections: List of ICT detection dicts.  Expected keys per item:
            ``confidence`` (float 0–1), ``strength`` (float 0–1).
        indicators: Dict of technical indicator values.  Expected keys:
            ``rsi_14`` (float), ``macd_histogram`` (float),
            ``ema_stack`` (str: ``"bullish"`` | ``"bearish"`` | other).
        scoring_profile: Dict with weighting params.  Expected keys:
            ``ict_weight``, ``ta_weight``, ``price_action_weight``,
            ``mtf_bonus`` — all numeric (``float`` or :class:`Decimal`).
        htf_direction: Higher-timeframe direction: ``"BULL"`` | ``"BEAR"``
            | ``None`` (unknown).
        setup_direction: The direction of the setup: ``"LONG"`` | ``"SHORT"``.

    Returns:
        Float score in the range [0.0, 100.0].
    """
    # ---- Weights -----------------------------------------------------------
    ict_weight = float(scoring_profile.get("ict_weight", 0.4))
    ta_weight = float(scoring_profile.get("ta_weight", 0.35))
    pa_weight = float(scoring_profile.get("price_action_weight", 0.25))
    mtf_bonus = float(scoring_profile.get("mtf_bonus", 0.1))

    # ---- ICT signal score --------------------------------------------------
    ict_signal_score = 0.0
    if ict_detections:
        best = max(
            float(d.get("confidence", 0.0)) * float(d.get("strength", 0.0))
            for d in ict_detections
        )
        ict_signal_score = min(max(best, 0.0), 1.0)

    # ---- TA signal score ---------------------------------------------------
    rsi = float(indicators.get("rsi_14", 50.0))
    macd_hist = float(indicators.get("macd_histogram", 0.0))
    ema_stack = str(indicators.get("ema_stack", "")).lower()

    # RSI deviation — how far from neutral 50
    rsi_score = min(abs(rsi - 50.0) / 50.0, 1.0)

    # MACD histogram directional alignment
    if setup_direction.upper() == "LONG":
        macd_score = 1.0 if macd_hist > 0 else 0.0
    else:  # SHORT
        macd_score = 1.0 if macd_hist < 0 else 0.0

    # EMA stack alignment
    if setup_direction.upper() == "LONG":
        ema_score = 1.0 if ema_stack == "bullish" else 0.0
    else:  # SHORT
        ema_score = 1.0 if ema_stack == "bearish" else 0.0

    ta_signal_score = (rsi_score + macd_score + ema_score) / 3.0

    # ---- Price action score ------------------------------------------------
    # Phase 2 stub
    price_action_score = 0.5

    # ---- Composite ---------------------------------------------------------
    raw = (
        ict_signal_score * ict_weight
        + ta_signal_score * ta_weight
        + price_action_score * pa_weight
    ) * 100.0

    # ---- Multi-timeframe bonus ---------------------------------------------
    htf_up = (htf_direction or "").upper()
    setup_up = setup_direction.upper()
    mtf_aligned = (htf_up == "BULL" and setup_up == "LONG") or (
        htf_up == "BEAR" and setup_up == "SHORT"
    )
    if mtf_aligned:
        raw += mtf_bonus * 100.0

    return max(0.0, min(raw, 100.0))


# ---------------------------------------------------------------------------
# Priority mapping
# ---------------------------------------------------------------------------


def score_to_priority(score: float) -> str:
    """Map a numeric score to an :class:`~app.db.enums.AlertPriority` string.

    Returns:
        ``"CRITICAL"``   when score ≥ 80
        ``"WARNING"``    when score ≥ 60
        ``"SUGGESTION"`` when score ≥ 40
        ``"INFO"``       otherwise
    """
    if score >= 80.0:
        return "CRITICAL"
    if score >= 60.0:
        return "WARNING"
    if score >= 40.0:
        return "SUGGESTION"
    return "INFO"
