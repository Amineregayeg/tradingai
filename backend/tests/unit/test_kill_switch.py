"""Tests for the kill switch — the safety boundary that must always work.

Per the functional spec (M12):
    "The kill switch must work even when other services are degraded.
     It must not depend on Claude, Finnhub, or any service outside the broker
     adapter and the database."

These tests verify it stays functional when AI / calendar / Redis / WebSocket / SMTP
are all unreachable, isolating the broker-close path as the only hard dependency.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.compliance.kill_switch import KillSwitch, kill_switch


# ---------------------------------------------------------------------------
# Arm / disarm
# ---------------------------------------------------------------------------


def test_starts_disarmed():
    ks = KillSwitch()
    assert ks.is_armed is False


def test_arm_sets_state():
    ks = KillSwitch()
    ks.arm(reason="Daily DD 4.9%")
    assert ks.is_armed is True
    assert ks._reason == "Daily DD 4.9%"


def test_disarm_clears_state():
    ks = KillSwitch()
    ks.arm(reason="test")
    ks.disarm()
    assert ks.is_armed is False
    assert ks._reason is None


# ---------------------------------------------------------------------------
# Trigger — close-all + counters
# ---------------------------------------------------------------------------


def _db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_trigger_closes_all_positions():
    db = _db()
    close_results = [
        {"pair": "EUR/USD", "status": "closed"},
        {"pair": "GBP/USD", "status": "closed"},
        {"pair": "USD/JPY", "status": "error", "error": "timeout"},
    ]
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(return_value=close_results)):
        result = await kill_switch.trigger(db=db, user_id="system", reason="Test")
    assert result["positions_closed"] == 2
    assert result["positions_failed_to_close"] == 1
    assert "Test" in result["message"]


@pytest.mark.asyncio
async def test_trigger_writes_audit_log():
    db = _db()
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(return_value=[])):
        await kill_switch.trigger(db=db, user_id="system", reason="DD breached")
    # Audit row added to the DB session
    assert db.add.called
    audit_entry = db.add.call_args[0][0]
    assert audit_entry.event_type == "KILL_SWITCH_TRIGGERED"
    assert audit_entry.new_value["reason"] == "DD breached"


@pytest.mark.asyncio
async def test_trigger_uses_armed_reason_when_no_explicit_reason():
    db = _db()
    kill_switch.arm(reason="Auto-armed by compliance")
    try:
        with patch("app.services.broker.manager.broker_manager.close_all_positions",
                   new=AsyncMock(return_value=[])):
            result = await kill_switch.trigger(db=db, user_id="system")
        assert "Auto-armed by compliance" in result["message"]
    finally:
        kill_switch.disarm()


# ---------------------------------------------------------------------------
# Degraded mode — the spec requirement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_works_when_websocket_unreachable():
    """WS manager down (e.g. Redis dead) — kill switch must still close positions."""
    db = _db()
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(return_value=[{"pair": "EUR/USD", "status": "closed"}])), \
         patch("app.services.ws.manager.ws_manager.push_kill_switch",
               new=AsyncMock(side_effect=ConnectionError("redis down"))):
        result = await kill_switch.trigger(db=db, user_id="system", reason="DD")
    assert result["positions_closed"] == 1


@pytest.mark.asyncio
async def test_works_when_smtp_unreachable():
    """SMTP server unreachable — kill switch must still close positions and audit."""
    db = _db()
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(return_value=[{"pair": "EUR/USD", "status": "closed"}])), \
         patch("app.services.compliance.kill_switch._send_smtp_alert",
               new=AsyncMock(side_effect=ConnectionError("smtp dead"))):
        result = await kill_switch.trigger(db=db, user_id="system", reason="DD")
    assert result["positions_closed"] == 1
    assert db.add.called  # audit still wrote


@pytest.mark.asyncio
async def test_works_when_audit_log_fails():
    """Audit write fails — kill switch must STILL close positions (safety > logging)."""
    db = AsyncMock()
    db.flush = AsyncMock(side_effect=RuntimeError("db flush failed"))
    db.add = MagicMock()
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(return_value=[{"pair": "EUR/USD", "status": "closed"}])):
        result = await kill_switch.trigger(db=db, user_id="system", reason="DD")
    assert result["positions_closed"] == 1


@pytest.mark.asyncio
async def test_works_when_broker_close_raises():
    """Broker layer crash — trigger must report 0 closed but not blow up."""
    db = _db()
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(side_effect=RuntimeError("oanda dead"))):
        result = await kill_switch.trigger(db=db, user_id="system", reason="DD")
    assert result["positions_closed"] == 0
    assert "DD" in result["message"]


@pytest.mark.asyncio
async def test_does_not_import_or_call_ai_service():
    """Trigger must not touch Claude/AI service — verified by tracking imports."""
    db = _db()
    import sys
    ai_modules_before = {k for k in sys.modules if "ai" in k.lower() and "anthropic" in k.lower()}
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(return_value=[])):
        await kill_switch.trigger(db=db, user_id="system", reason="DD")
    ai_modules_after = {k for k in sys.modules if "ai" in k.lower() and "anthropic" in k.lower()}
    # No new anthropic imports caused by trigger path
    assert ai_modules_after == ai_modules_before


@pytest.mark.asyncio
async def test_does_not_import_or_call_finnhub():
    """Trigger must not touch Finnhub calendar."""
    db = _db()
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(return_value=[])), \
         patch("app.services.calendar.finnhub.calendar_service") as mock_cal:
        await kill_switch.trigger(db=db, user_id="system", reason="DD")
    # No method on calendar_service was called
    assert not mock_cal.method_calls
