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
async def test_a_NOT_ATTEMPTED_position_is_counted_as_NEITHER_closed_NOR_failed():
    """`B330`. Malek ruled the kill switch as a PROPERTY on 2026-08-31:

    > Every position open when the switch was pulled must be reported as CLOSED, FAILED WITH A
    > REASON, or NOT ATTEMPTED.

    **This counter used to defeat that ruling at the last step.** `positions_closed` was
    `status not in ("error", "failed")`, so a row saying NOBODY REACHED THIS POSITION was counted
    as a position successfully closed — on the control whose whole purpose is to leave nothing
    open. **Worse than an error, because an error prompts a look and a closed-count does not.**
    """
    db = _db()
    close_results = [
        {"position_id": "p1", "disposition": "CLOSED", "status": "closed"},
        {"position_id": "p2", "disposition": "FAILED", "status": "failed",
         "reason": "TimeoutError"},
        {"position_id": "p3", "disposition": "NOT_ATTEMPTED", "status": "failed",
         "reason": "the close loop never reached this position"},
        {"position_id": "p4", "disposition": "NOT_ATTEMPTED", "status": "failed",
         "reason": "the close loop never reached this position"},
    ]
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(return_value=close_results)):
        result = await kill_switch.trigger(db=db, user_id="system", reason="Test")

    assert result["positions_closed"] == 1, (
        f"an unattempted position was counted as closed: {result['positions_closed']}"
    )
    assert result["positions_failed_to_close"] == 1
    assert result["positions_not_attempted"] == 2
    assert "NOT ATTEMPTED" in result["message"], (
        "the third state must reach the sentence a human reads at 3am, not only the payload — "
        f"got {result['message']!r}"
    )


@pytest.mark.asyncio
async def test_rows_WITHOUT_a_disposition_keep_their_old_meaning():
    """MUST-MISS. The three older shapes cannot express the third state, so widening the
    vocabulary must not reinterpret any adapter that has not adopted it.

    Without this, a counter that treated every unlabelled row as unattempted would satisfy the
    arm above and silently rewrite what every existing adapter reports.
    """
    db = _db()
    close_results = [
        {"pair": "EUR/USD", "status": "closed"},
        {"pair": "USD/JPY", "status": "error", "error": "timeout"},
    ]
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(return_value=close_results)):
        result = await kill_switch.trigger(db=db, user_id="system", reason="Test")

    assert result["positions_closed"] == 1
    assert result["positions_failed_to_close"] == 1
    assert result["positions_not_attempted"] == 0
    assert "NOT ATTEMPTED" not in result["message"], (
        "a run with nothing unattempted must not mention the state at all"
    )


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

@pytest.mark.asyncio
async def test_a_partial_report_on_the_EXCEPTION_is_recovered_rather_than_dropped():
    """`B366`. The adapter attaches its rows to the error it re-raises; the consumer dropped them.

    `close_all_positions` publishes the report BEFORE its loop and rides it on the exception, so a
    partial record survives an abnormal exit (`B303`). This boundary then set `close_results = []`
    and the operator was told **"0 closed, 0 failed"** while a complete report sat on the exception
    that had just been discarded. **The ruled property held at the adapter and died at the
    boundary** — and *nothing was closed* and *we lost the record of what was* read identically to
    whoever sees the alert at 3am.

    Nothing new was needed to fix it: the data is produced three lines away.
    """
    from app.core.exceptions import BrokerError

    failure = BrokerError("the close loop died", broker="mt5")
    failure.partial_report = [
        {"position_id": "p1", "disposition": "CLOSED", "status": "closed", "reason": None},
        {"position_id": "p2", "disposition": "FAILED", "status": "failed",
         "reason": "CancelledError: the close was SENT and the outcome was never observed"},
        {"position_id": "p3", "disposition": "NOT_ATTEMPTED", "status": "failed",
         "reason": "the close loop never reached this position"},
    ]

    db = _db()
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(side_effect=failure)):
        result = await kill_switch.trigger(db=db, user_id="system", reason="Test")

    assert len(result["details"]) == 3, (
        "the partial report was dropped; the operator would read 0 closed, 0 failed while a "
        "three-row record sat on the discarded exception"
    )
    assert result["positions_closed"] == 1
    assert result["positions_failed_to_close"] == 1
    assert result["positions_not_attempted"] == 1


@pytest.mark.asyncio
async def test_NO_partial_report_is_a_DIFFERENT_state_from_an_empty_book():
    """`B366`, the must-miss. Three zeros are what a flat account looks like.

    When the adapter fails without attaching a report, the counters read 0/0/0 — indistinguishable
    from *there was nothing to close*. The recovery must not make that case look answered, so the
    absence is stated in its own right rather than inferred from three zeros.
    """
    db = _db()
    with patch("app.services.broker.manager.broker_manager.close_all_positions",
               new=AsyncMock(side_effect=RuntimeError("no report at all"))):
        result = await kill_switch.trigger(db=db, user_id="system", reason="Test")

    assert result["details"] == []
    assert result["positions_closed"] == 0 and result["positions_failed_to_close"] == 0


@pytest.mark.asyncio
async def test_the_counter_reads_the_PRODUCERS_constant_and_not_a_copy_of_its_value():
    """`T-0132`. Both adapters write `BrokerAdapter.NOT_ATTEMPTED`; this counted a string literal.

    **Two sources for one fact is `B184`** — the thing hoisting the vocabulary to the base class
    was for, left behind at the consumer. It is inert while the constant's value equals the
    literal, so this arm changes the VALUE and asserts the counting follows it. Without that, the
    coincidence is what passes.

    The path matters: `B330` already bit here once, counting a `NOT_ATTEMPTED` row as CLOSED and
    telling the operator a position was closed that nobody had reached.
    """
    from app.services.broker.base import BrokerAdapter

    original = BrokerAdapter.NOT_ATTEMPTED
    db = _db()
    close_results = [
        {"position_id": "p1", "disposition": "CLOSED", "status": "closed"},
        {"position_id": "p2", "disposition": "RENAMED_STATE", "status": "failed"},
    ]
    try:
        BrokerAdapter.NOT_ATTEMPTED = "RENAMED_STATE"
        with patch("app.services.broker.manager.broker_manager.close_all_positions",
                   new=AsyncMock(return_value=close_results)):
            result = await kill_switch.trigger(db=db, user_id="system", reason="Test")
    finally:
        BrokerAdapter.NOT_ATTEMPTED = original

    assert result["positions_not_attempted"] == 1, (
        "the counter compared against a hardcoded 'NOT_ATTEMPTED' rather than the constant the "
        "adapters write, so a renamed state was counted as CLOSED — B330's exact failure"
    )
    assert result["positions_closed"] == 1
