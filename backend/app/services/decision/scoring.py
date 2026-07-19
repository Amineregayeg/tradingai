"""Pure, deterministic scoring engine.

No I/O — fully testable in isolation.  All inputs are plain Python dicts /
lists / scalars; no SQLAlchemy models are imported here.

Honesty contract (see ``ScoreResult``): the scorer NEVER fabricates a value it
does not have and NEVER launders a NaN into a confident number.  A corrupt
(NaN) required input makes it *abstain* (``score=None``) rather than silently
returning ``0.0``; the unimplemented price-action component is excluded and its
weight redistributed, not stubbed to ``0.5``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def _is_nan(x: object) -> bool:
    """True only for a genuine float NaN (never raises on non-floats)."""
    return isinstance(x, float) and math.isnan(x)


@dataclass(frozen=True)
class ScoreResult:
    """Outcome of scoring one setup.

    ``score``      composite quality in [0, 100], or ``None`` when abstained.
    ``abstained``  True when the scorer refused to produce a number (corrupt
                   input) — the caller MUST NOT treat this as a low score.
    ``reasons``    machine-readable notes, e.g. ``"nan:rsi_14"`` or
                   ``"price_action:not_implemented"`` — surfaced in the UI so a
                   human can see exactly why the engine did what it did.
    ``components`` the sub-scores actually computed (for transparency / the
                   feedback loop); only present components appear.
    """

    score: float | None
    abstained: bool
    reasons: tuple[str, ...] = ()
    components: dict[str, float] = field(default_factory=dict)


def compute_score(
    ict_detections: list[dict],
    indicators: dict,
    scoring_profile: dict,
    htf_direction: str | None,
    setup_direction: str,
) -> ScoreResult:
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
    reasons: list[str] = []

    # ---- Weights -----------------------------------------------------------
    ict_weight = float(scoring_profile.get("ict_weight", 0.4))
    ta_weight = float(scoring_profile.get("ta_weight", 0.35))
    mtf_bonus = float(scoring_profile.get("mtf_bonus", 0.1))
    # price_action is NOT implemented. We do NOT stub it to 0.5 (a fabricated
    # +12.5-point floor that made the engine unable to abstain). It is excluded
    # and its weight redistributed across the components we can actually compute.
    reasons.append("price_action:not_implemented")

    # ---- ICT signal score --------------------------------------------------
    # A NaN confidence/strength is a CORRUPT detection — drop it rather than let
    # it poison max(); a genuinely empty list yields 0.0 (no ICT confirmation,
    # an honest low score, not corruption).
    ict_signal_score = 0.0
    valid_products = [
        float(d.get("confidence", 0.0)) * float(d.get("strength", 0.0))
        for d in ict_detections
        if not (_is_nan(d.get("confidence")) or _is_nan(d.get("strength")))
    ]
    if len(valid_products) < len([d for d in ict_detections]):
        reasons.append("ict:dropped_nan_detections")
    if valid_products:
        ict_signal_score = min(max(max(valid_products), 0.0), 1.0)

    # ---- TA signal score ---------------------------------------------------
    # ABSENT keys fall back to a NEUTRAL value (no signal); a PRESENT-but-NaN
    # value is corrupt data → abstain (never launder it to a number).
    raw_rsi = indicators.get("rsi_14", 50.0)
    raw_macd = indicators.get("macd_histogram", 0.0)
    if _is_nan(raw_rsi):
        return ScoreResult(None, True, ("nan:rsi_14", *reasons), {})
    if _is_nan(raw_macd):
        return ScoreResult(None, True, ("nan:macd_histogram", *reasons), {})
    rsi = float(raw_rsi)
    macd_hist = float(raw_macd)
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

    # ---- Composite over PRESENT components (weights renormalized) -----------
    present_weight = ict_weight + ta_weight
    if present_weight <= 0:
        return ScoreResult(None, True, ("no_component_weight", *reasons), {})
    raw = (
        ict_signal_score * (ict_weight / present_weight)
        + ta_signal_score * (ta_weight / present_weight)
    ) * 100.0

    # ---- Multi-timeframe bonus ---------------------------------------------
    htf_up = (htf_direction or "").upper()
    setup_up = setup_direction.upper()
    mtf_aligned = (htf_up == "BULL" and setup_up == "LONG") or (
        htf_up == "BEAR" and setup_up == "SHORT"
    )
    if mtf_aligned:
        raw += mtf_bonus * 100.0

    # Defensive: if anything upstream still produced a NaN, ABSTAIN — never
    # collapse it to a confident 0.0 via bare min/max.
    if _is_nan(raw):
        return ScoreResult(None, True, ("nan:composite", *reasons), {})

    score = max(0.0, min(raw, 100.0))
    components = {"ict": ict_signal_score, "ta": ta_signal_score}
    if mtf_aligned:
        components["mtf_bonus"] = mtf_bonus
    return ScoreResult(score, False, tuple(reasons), components)


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
