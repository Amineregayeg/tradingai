"""Tests for the observe-only compliance state machine (no side effects)."""
from __future__ import annotations

from app.db.enums import ComplianceState
from app.services.broker.observe_sync import compute_compliance_state

RULES = {"daily_dd_pct": 5.0, "max_dd_pct": 10.0}
INITIAL = 5000.0  # daily_limit = 250, max_limit = 500


def test_active_when_loss_low():
    assert compute_compliance_state(RULES, INITIAL, daily_loss=0.0, total_loss=0.0) == ComplianceState.ACTIVE
    assert compute_compliance_state(RULES, INITIAL, daily_loss=100.0, total_loss=50.0) == ComplianceState.ACTIVE


def test_at_risk_at_80pct_daily():
    # 80% of 250 = 200
    assert compute_compliance_state(RULES, INITIAL, daily_loss=200.0, total_loss=0.0) == ComplianceState.AT_RISK


def test_critical_at_95pct_daily():
    assert compute_compliance_state(RULES, INITIAL, daily_loss=240.0, total_loss=0.0) == ComplianceState.CRITICAL


def test_halted_at_daily_limit():
    assert compute_compliance_state(RULES, INITIAL, daily_loss=250.0, total_loss=0.0) == ComplianceState.HALTED


def test_halted_on_max_drawdown_breach():
    # total_loss >= max_limit (500) -> HALTED regardless of daily
    assert compute_compliance_state(RULES, INITIAL, daily_loss=0.0, total_loss=500.0) == ComplianceState.HALTED


def test_real_cft_instant_account_is_active():
    # 2,500 Instant: initial 2500, equity 2425.68 -> total_loss 74.32, daily_dd 4% (limit 100)
    rules = {"daily_dd_pct": 4.0, "max_dd_pct": 12.0}
    state = compute_compliance_state(rules, 2500.0, daily_loss=0.0, total_loss=74.32)
    assert state == ComplianceState.ACTIVE
