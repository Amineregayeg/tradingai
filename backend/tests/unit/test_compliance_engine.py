"""Tests for ComplianceEngine.evaluate — drawdown transitions + kill-switch trigger.

These exercise the spec's prop-firm state machine (M12) end-to-end with a real DB
session, mocking only the kill switch boundary to assert it fires on HALTED.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.db.enums import ComplianceState
from app.models.prop_firm_profile import PropFirmProfile
from app.models.prop_firm_snapshot import PropFirmSnapshot
from app.services.compliance.engine import compliance_engine
from sqlalchemy import select


async def _make_profile(db, account_id="365105", initial=5000.0, daily_pct=5.0, max_pct=10.0):
    profile = PropFirmProfile(
        user_id="system",
        firm_name="Crypto Fund Trader",
        challenge_type="Phase 1",
        rules_json={
            "daily_dd_pct": daily_pct,
            "max_dd_pct": max_pct,
            "initial_balance": initial,
        },
        account_id=account_id,
        active=True,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _evaluate(db, profile, *, equity, balance, daily_pnl, total_pnl=0.0):
    return await compliance_engine.evaluate(
        db=db,
        user_id="system",
        profile=profile,
        equity=equity,
        balance=balance,
        daily_pnl=daily_pnl,
        total_pnl=total_pnl,
        open_positions=[],
    )


async def _latest_snapshot(db, profile):
    stmt = (
        select(PropFirmSnapshot)
        .where(PropFirmSnapshot.profile_id == profile.id)
        .order_by(PropFirmSnapshot.timestamp.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_when_no_loss(db_session):
    profile = await _make_profile(db_session)
    state = await _evaluate(db_session, profile, equity=5000.0, balance=5000.0, daily_pnl=0.0)
    assert state == "ACTIVE"


@pytest.mark.asyncio
async def test_at_risk_at_80pct_of_daily_limit(db_session):
    # daily_limit = 5000 * 5% = 250; 80% of 250 = 200
    profile = await _make_profile(db_session)
    state = await _evaluate(db_session, profile, equity=4800.0, balance=5000.0, daily_pnl=-200.0)
    assert state == "AT_RISK"


@pytest.mark.asyncio
async def test_critical_at_95pct_of_daily_limit(db_session):
    profile = await _make_profile(db_session)
    state = await _evaluate(db_session, profile, equity=4760.0, balance=5000.0, daily_pnl=-240.0)
    assert state == "CRITICAL"


@pytest.mark.asyncio
async def test_halted_when_daily_limit_reached(db_session):
    profile = await _make_profile(db_session)
    with patch("app.services.compliance.kill_switch.kill_switch.trigger", new=AsyncMock(return_value={})):
        state = await _evaluate(db_session, profile, equity=4750.0, balance=5000.0, daily_pnl=-250.0)
    assert state == "HALTED"


@pytest.mark.asyncio
async def test_halted_when_max_drawdown_breached(db_session):
    # max_limit = 5000 * 10% = 500; total_loss = initial - equity = 500
    profile = await _make_profile(db_session)
    with patch("app.services.compliance.kill_switch.kill_switch.trigger", new=AsyncMock(return_value={})):
        state = await _evaluate(db_session, profile, equity=4500.0, balance=4500.0, daily_pnl=0.0)
    assert state == "HALTED"


@pytest.mark.asyncio
async def test_max_drawdown_overrides_daily_active(db_session):
    """Even if daily is fine, blowing max DD halts."""
    profile = await _make_profile(db_session)
    with patch("app.services.compliance.kill_switch.kill_switch.trigger", new=AsyncMock(return_value={})):
        # daily_pnl = 0 (no daily loss), but total_loss = 600 > max_limit 500
        state = await _evaluate(db_session, profile, equity=4400.0, balance=4400.0, daily_pnl=0.0)
    assert state == "HALTED"


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_persisted_with_correct_values(db_session):
    profile = await _make_profile(db_session)
    await _evaluate(db_session, profile, equity=4900.0, balance=5000.0, daily_pnl=-100.0)
    snap = await _latest_snapshot(db_session, profile)
    assert snap is not None
    assert float(snap.equity) == 4900.0
    assert float(snap.balance) == 5000.0
    assert float(snap.daily_loss) == 100.0
    assert float(snap.total_loss) == 100.0  # initial 5000 - equity 4900
    assert snap.state == ComplianceState.ACTIVE


@pytest.mark.asyncio
async def test_snapshot_records_halted_state(db_session):
    profile = await _make_profile(db_session)
    with patch("app.services.compliance.kill_switch.kill_switch.trigger", new=AsyncMock(return_value={})):
        await _evaluate(db_session, profile, equity=4750.0, balance=5000.0, daily_pnl=-250.0)
    snap = await _latest_snapshot(db_session, profile)
    assert snap.state == ComplianceState.HALTED


# ---------------------------------------------------------------------------
# Kill-switch wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_switch_armed_and_triggered_on_halted(db_session):
    profile = await _make_profile(db_session)
    with patch("app.services.compliance.kill_switch.kill_switch.arm") as mock_arm, \
         patch("app.services.compliance.kill_switch.kill_switch.trigger", new=AsyncMock(return_value={})) as mock_trigger:
        await _evaluate(db_session, profile, equity=4750.0, balance=5000.0, daily_pnl=-250.0)
    assert mock_arm.called, "kill_switch.arm should be called on HALTED"
    assert mock_trigger.called, "kill_switch.trigger should be called on HALTED"


@pytest.mark.asyncio
async def test_kill_switch_not_called_when_not_halted(db_session):
    profile = await _make_profile(db_session)
    with patch("app.services.compliance.kill_switch.kill_switch.arm") as mock_arm, \
         patch("app.services.compliance.kill_switch.kill_switch.trigger", new=AsyncMock()) as mock_trigger:
        # Below daily limit — should not fire
        await _evaluate(db_session, profile, equity=4900.0, balance=5000.0, daily_pnl=-100.0)
    assert not mock_arm.called
    assert not mock_trigger.called


# ---------------------------------------------------------------------------
# CFT real-world calibration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cft_5k_phase1_breach_at_5pct_daily(db_session):
    """Real CFT 5K Phase 1: 5% daily DD on $5,000 = $250/day max loss."""
    profile = await _make_profile(db_session, account_id="365105", initial=5000.0, daily_pct=5.0, max_pct=10.0)
    with patch("app.services.compliance.kill_switch.kill_switch.trigger", new=AsyncMock(return_value={})):
        state = await _evaluate(db_session, profile, equity=4748.0, balance=5000.0, daily_pnl=-252.0)
    assert state == "HALTED"


@pytest.mark.asyncio
async def test_cft_25k_instant_breach_at_4pct_daily(db_session):
    """Real CFT 2.5K Instant: 4% daily DD on $2,500 = $100/day max loss."""
    profile = await _make_profile(db_session, account_id="373010", initial=2500.0, daily_pct=4.0, max_pct=6.0)
    with patch("app.services.compliance.kill_switch.kill_switch.trigger", new=AsyncMock(return_value={})):
        state = await _evaluate(db_session, profile, equity=2398.0, balance=2500.0, daily_pnl=-102.0)
    assert state == "HALTED"
