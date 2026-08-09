"""Tests for the output-understanding feedback loop (CONTRACT 7e).

``feedback.analyze`` is a pure, deterministic function that compares what the engine
*expected* (signal RR geometry) against what it *actually realized* (R multiples,
fills, win rate) and emits small, bounded corrections to the engine's INDEPENDENT
knobs.

These tests verify:
  * corrections are produced ONLY on independent knobs, NEVER on ``risk_pct``;
  * ``risk_pct`` is refused with a reason by the caller-facing builder;
  * thin evidence (``n < min_evidence``) abstains — no corrections;
  * every correction's delta is bounded to at most ±25% of the current value;
  * corrections carry evidence and a plain-English rationale.
"""
from __future__ import annotations

from app.services.evaluation.feedback import (
    FIXED_KNOBS,
    INDEPENDENT_KNOBS,
    MAX_DELTA_FRAC,
    RISK_PCT_REFUSAL,
    Correction,
    analyze,
    propose_correction,
)

_EPS = 1e-9


# ---------------------------------------------------------------------------
# Synthetic evidence
# ---------------------------------------------------------------------------


def _params(**overrides) -> dict:
    """Current knob values, including the FIXED risk_pct as read-only context."""
    base = {
        "risk_pct": 0.01,          # FIXED — must never be a correction target
        "sl_buffer_atr": 0.25,
        "rr_partial": 2.0,
        "require_ltf_bos": True,
        "min_fvg_atr": 0.05,
        "max_hold_bars": 10,
        "runner_trail_atr": 2.5,
    }
    base.update(overrides)
    return base


def _record(realized_r: float, outcome: str) -> dict:
    """A closed LONG decision row with a fixed RR geometry (expected_r = 3.0).

    ``fill_price`` sits 0.30 above the signal entry — an adverse 0.30R slippage on a
    long — so the slippage rule has evidence to act on.
    """
    return {
        "symbol": "BTCUSDT",
        "timeframe": "1H",
        "signal_dir": "LONG",
        "signal_entry": 100.0,
        "signal_sl": 99.0,      # risk leg = 1.0
        "signal_tp": 103.0,     # reward leg = 3.0 -> expected_r = 3.0
        "sized_units": 1000.0,
        "expected_r": 3.0,
        "realized_r": realized_r,
        "gap_r": realized_r - 3.0,
        "outcome": outcome,
        "fill_price": 100.30,   # adverse fill on a long -> +0.30R slippage
        "cohort": "replay",
        "abstained": False,
    }


def _dataset(n_win: int = 6, n_loss: int = 54) -> list[dict]:
    """Under-performing sample: low win rate, negative mean R, adverse slippage.

    6 winners at +3R, 54 losers at -1R -> mean realized R = -0.6 (vs +3.0 targeted),
    win rate 10% (vs 25% break-even) — a clear, unambiguous gap on every axis.
    """
    recs = [_record(3.0, "WIN") for _ in range(n_win)]
    recs += [_record(-1.0, "LOSS") for _ in range(n_loss)]
    return recs


# ---------------------------------------------------------------------------
# Thin-evidence abstain
# ---------------------------------------------------------------------------


def test_abstains_on_thin_evidence():
    records = _dataset()[:5]
    result = analyze(records, _params(), min_evidence=30)
    assert result["n"] == 5
    assert result["abstained"] is True
    assert result["corrections"] == []
    assert isinstance(result["abstain_reason"], str) and result["abstain_reason"]


def test_abstain_reason_none_when_sufficient_evidence():
    result = analyze(_dataset(), _params(), min_evidence=30)
    assert result["abstained"] is False
    assert result["abstain_reason"] is None
    assert result["n"] == 60


# ---------------------------------------------------------------------------
# Corrections only on independent knobs
# ---------------------------------------------------------------------------


def test_produces_corrections_only_on_independent_knobs():
    result = analyze(_dataset(), _params(), min_evidence=30)
    corrections = result["corrections"]
    # A strong, multi-axis gap with ample evidence must yield at least one nudge.
    assert len(corrections) >= 1
    for c in corrections:
        assert isinstance(c, Correction)
        assert c.target_param in INDEPENDENT_KNOBS
        assert c.target_param not in FIXED_KNOBS


def test_never_targets_risk_pct():
    params = _params()
    assert "risk_pct" in params            # present as read-only context ...
    assert "risk_pct" in FIXED_KNOBS       # ... and classified as FIXED ...
    assert "risk_pct" not in INDEPENDENT_KNOBS  # ... never independent.

    result = analyze(_dataset(), params, min_evidence=30)
    targets = {c.target_param for c in result["corrections"]}
    assert "risk_pct" not in targets
    assert all(c.target_param != "risk_pct" for c in result["corrections"])


def test_propose_correction_refuses_risk_pct():
    refused = propose_correction("risk_pct", 0.01, 0.5)
    assert refused["refused"] is True
    assert refused["reason"] == RISK_PCT_REFUSAL
    # No correction object is minted for a refused knob.
    assert "correction" not in refused or refused.get("correction") is None


def test_propose_correction_allows_independent_knob():
    ok = propose_correction(
        "sl_buffer_atr", 0.25, 0.10, rationale="widen stops", evidence_n=40, confidence=0.5
    )
    assert ok["refused"] is False
    corr = ok["correction"]
    assert isinstance(corr, Correction)
    assert corr.target_param == "sl_buffer_atr"


# ---------------------------------------------------------------------------
# Bounded deltas + correction metadata
# ---------------------------------------------------------------------------


def test_numeric_correction_deltas_are_bounded():
    params = _params()
    result = analyze(_dataset(), params, min_evidence=30)
    for c in result["corrections"]:
        if c.delta is None:
            continue  # boolean/categorical knob — no numeric delta
        current = float(c.current)
        bound = MAX_DELTA_FRAC * abs(current) + _EPS
        assert abs(c.delta) <= bound, f"{c.target_param} delta {c.delta} exceeds ±25%"
        assert abs(float(c.proposed) - current) <= bound


def test_corrections_carry_evidence_and_rationale():
    result = analyze(_dataset(), _params(), min_evidence=30)
    assert result["corrections"], "expected at least one correction to inspect"
    for c in result["corrections"]:
        assert c.evidence_n == result["n"]
        assert c.evidence_n >= 30
        assert 0.0 <= c.confidence <= 1.0
        assert isinstance(c.rationale, str) and c.rationale.strip()


# ---------------------------------------------------------------------------
# Boolean-knob correction path (delta is None, still never risk_pct)
# ---------------------------------------------------------------------------


def test_boolean_knob_correction_has_none_delta():
    # With the LTF-BOS confirmation OFF and a badly sub-break-even win rate, the
    # engine proposes flipping require_ltf_bos on — a non-numeric correction.
    result = analyze(_dataset(), _params(require_ltf_bos=False), min_evidence=30)
    flips = [c for c in result["corrections"] if c.target_param == "require_ltf_bos"]
    assert len(flips) == 1
    flip = flips[0]
    assert flip.delta is None
    assert flip.current is False
    assert flip.proposed is True
    # Even here, risk_pct never appears.
    assert all(c.target_param != "risk_pct" for c in result["corrections"])


# ---------------------------------------------------------------------------
# Rule A soundness — winner-conditional, NOT a one-directional ratchet
# ---------------------------------------------------------------------------


def _rec(realized_r: float, outcome: str, expected_r: float = 2.0) -> dict:
    return {
        "symbol": "BTCUSDT", "timeframe": "1H", "signal_dir": "LONG",
        "signal_entry": 100.0, "signal_sl": 99.0,
        "signal_tp": 100.0 + expected_r, "sized_units": 1000.0,
        "expected_r": expected_r, "realized_r": realized_r,
        "outcome": outcome, "fill_price": 100.0, "cohort": "paper", "abstained": False,
    }


def test_profitable_strategy_does_not_ratchet_rr_partial():
    """A PROFITABLE strategy whose winners hit exactly their target must NOT
    trigger an rr_partial cut. The old all-trades gap (mean_realized - mean_expected)
    was structurally negative here and would have lowered rr_partial every round;
    the winner-conditional gap is 0, so Rule A correctly stays silent."""
    recs = [_rec(2.0, "WIN") for _ in range(30)] + [_rec(-1.0, "LOSS") for _ in range(15)]
    # sanity: this strategy is profitable (mean R = (30*2 - 15)/45 = +1.0)
    result = analyze(recs, _params(rr_partial=2.0), min_evidence=30)
    ev = result["expected_vs_actual"]
    assert ev["mean_realized_r"] > 0            # genuinely profitable
    assert ev["mean_winner_realized_r"] == 2.0  # winners hit target
    assert result["gaps"]["winner_realized_minus_target_r"] == 0.0
    assert all(c.target_param != "rr_partial" for c in result["corrections"])


def test_winners_short_of_target_lowers_rr_partial():
    """When winners systematically fall SHORT of the RR they targeted (reverse
    before it), Rule A lowers rr_partial — and only downward here."""
    recs = [_rec(1.2, "WIN") for _ in range(20)] + [_rec(-1.0, "LOSS") for _ in range(20)]
    result = analyze(recs, _params(rr_partial=2.0), min_evidence=30)
    rr = [c for c in result["corrections"] if c.target_param == "rr_partial"]
    assert len(rr) == 1
    assert rr[0].proposed < rr[0].current          # lowered
    assert rr[0].current - rr[0].proposed <= 2.0 * MAX_DELTA_FRAC + _EPS  # bounded


def test_profitable_runner_not_flagged_below_breakeven():
    """A PROFITABLE runner strategy (winners realize far more than the target RR)
    must NOT trip Rule C (widen sl_buffer) or Rule D (force require_ltf_bos). The
    old break-even used the TARGET RR and wrongly flagged such strategies; the fix
    uses the REALIZED win/loss geometry."""
    # winners realize +6R (runners) on a 3R target; losers -1R; WR 22% (18/81).
    # realized break-even = 1/(6+1) = 14.3%, so 22% is ABOVE break-even -> profitable.
    recs = [_rec(6.0, "WIN", expected_r=3.0) for _ in range(18)] \
         + [_rec(-1.0, "LOSS", expected_r=3.0) for _ in range(63)]
    result = analyze(recs, _params(rr_partial=3.0, sl_buffer_atr=0.25, require_ltf_bos=False), min_evidence=30)
    ev = result["expected_vs_actual"]
    assert ev["mean_winner_realized_r"] == 6.0
    assert abs(ev["expected_win_rate"] - 1.0 / 7.0) < 1e-6  # realized geometry, not 1/(1+3)
    assert ev["actual_win_rate"] > ev["expected_win_rate"]  # genuinely profitable
    targets = {c.target_param for c in result["corrections"]}
    assert "sl_buffer_atr" not in targets   # Rule C must not fire
    assert "require_ltf_bos" not in targets  # Rule D must not fire
