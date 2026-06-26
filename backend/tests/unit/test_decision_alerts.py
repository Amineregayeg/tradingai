"""Tests for decision/alerts.py — alert generation, supersede, expiration.

Covers spec §M6:
    - ENTRY_SIGNAL emitted only above ``min_score_entry`` threshold.
    - Same-pair PENDING ENTRY_SIGNAL gets SUPERSEDED by a newer one (dedup).
    - RISK_WARNING + EXIT_MGMT generation.
    - Score → Priority band mapping (CRITICAL ≥ 80, WARNING ≥ 60, SUGGESTION ≥ 40, INFO).
    - Stale PENDING alerts auto-expire.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.enums import AlertPriority, AlertStatus, AlertType
from app.models.alert import Alert
from app.services.decision.alerts import (
    expire_old_alerts,
    generate_entry_signal_alert,
    generate_exit_mgmt_alert,
    generate_risk_warning,
    supersede_alert,
)
from app.services.decision.scoring import score_to_priority


def _ict():
    return [{"id": "d1", "confidence": 0.8, "strength": 0.9, "direction": "BULL"}]


# ---------------------------------------------------------------------------
# Priority band mapping (the formula's tail)
# ---------------------------------------------------------------------------


def test_score_to_priority_critical():
    assert score_to_priority(80.0) == "CRITICAL"
    assert score_to_priority(99.9) == "CRITICAL"


def test_score_to_priority_warning():
    assert score_to_priority(60.0) == "WARNING"
    assert score_to_priority(79.9) == "WARNING"


def test_score_to_priority_suggestion():
    assert score_to_priority(40.0) == "SUGGESTION"
    assert score_to_priority(59.9) == "SUGGESTION"


def test_score_to_priority_info():
    assert score_to_priority(0.0) == "INFO"
    assert score_to_priority(39.9) == "INFO"


# ---------------------------------------------------------------------------
# generate_entry_signal_alert — threshold + supersede
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_signal_below_threshold_returns_none(db_session):
    with patch("app.services.audit.logger.audit_logger.alert_generated", new=AsyncMock()):
        result = await generate_entry_signal_alert(
            db=db_session, user_id="system", pair="EUR/USD",
            score=50.0,  # below default 65
            ict_detections=_ict(), indicators={},
            ai_confidence=None, context={"pair": "EUR/USD"},
        )
    assert result is None
    # No alert persisted
    stmt = select(Alert).where(Alert.user_id == "system")
    rows = (await db_session.execute(stmt)).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_entry_signal_above_threshold_creates_alert(db_session):
    with patch("app.services.audit.logger.audit_logger.alert_generated", new=AsyncMock()):
        result = await generate_entry_signal_alert(
            db=db_session, user_id="system", pair="EUR/USD",
            score=72.0, ict_detections=_ict(), indicators={},
            ai_confidence=0.85, context={"pair": "EUR/USD"},
        )
    assert result is not None
    assert result["type"] == "ENTRY_SIGNAL"
    assert result["pair"] == "EUR/USD"
    assert result["status"] == "PENDING"
    assert float(result["score"]) == 72.0


@pytest.mark.asyncio
async def test_entry_signal_assigns_warning_priority_at_60_to_80(db_session):
    with patch("app.services.audit.logger.audit_logger.alert_generated", new=AsyncMock()):
        result = await generate_entry_signal_alert(
            db=db_session, user_id="system", pair="EUR/USD",
            score=72.0, ict_detections=_ict(), indicators={},
            ai_confidence=None, context={"pair": "EUR/USD"},
        )
    assert result["priority"] == "WARNING"


@pytest.mark.asyncio
async def test_entry_signal_assigns_critical_priority_above_80(db_session):
    with patch("app.services.audit.logger.audit_logger.alert_generated", new=AsyncMock()):
        result = await generate_entry_signal_alert(
            db=db_session, user_id="system", pair="EUR/USD",
            score=85.0, ict_detections=_ict(), indicators={},
            ai_confidence=None, context={"pair": "EUR/USD"},
        )
    assert result["priority"] == "CRITICAL"


@pytest.mark.asyncio
async def test_entry_signal_supersedes_existing_pending_for_same_pair(db_session):
    """Newer ENTRY_SIGNAL on the same pair must supersede the older PENDING one."""
    with patch("app.services.audit.logger.audit_logger.alert_generated", new=AsyncMock()):
        first = await generate_entry_signal_alert(
            db=db_session, user_id="system", pair="EUR/USD",
            score=70.0, ict_detections=_ict(), indicators={},
            ai_confidence=None, context={"pair": "EUR/USD"},
        )
        await generate_entry_signal_alert(
            db=db_session, user_id="system", pair="EUR/USD",
            score=85.0, ict_detections=_ict(), indicators={},
            ai_confidence=None, context={"pair": "EUR/USD"},
        )

    # Reload the first alert from DB
    import uuid
    first_id = uuid.UUID(first["id"])
    stmt = select(Alert).where(Alert.id == first_id)
    refreshed = (await db_session.execute(stmt)).scalar_one()
    assert refreshed.status == AlertStatus.SUPERSEDED


@pytest.mark.asyncio
async def test_entry_signal_different_pairs_do_not_supersede_each_other(db_session):
    with patch("app.services.audit.logger.audit_logger.alert_generated", new=AsyncMock()):
        await generate_entry_signal_alert(
            db=db_session, user_id="system", pair="EUR/USD",
            score=70.0, ict_detections=_ict(), indicators={},
            ai_confidence=None, context={"pair": "EUR/USD"},
        )
        await generate_entry_signal_alert(
            db=db_session, user_id="system", pair="GBP/USD",
            score=70.0, ict_detections=_ict(), indicators={},
            ai_confidence=None, context={"pair": "GBP/USD"},
        )

    stmt = select(Alert).where(
        Alert.user_id == "system",
        Alert.status == AlertStatus.PENDING,
    )
    pending = (await db_session.execute(stmt)).scalars().all()
    assert len(pending) == 2  # both still pending


# ---------------------------------------------------------------------------
# generate_risk_warning + generate_exit_mgmt_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_risk_warning_persists_with_warning_priority(db_session):
    with patch("app.services.audit.logger.audit_logger.alert_generated", new=AsyncMock()):
        result = await generate_risk_warning(
            db=db_session, user_id="system", pair="EUR/USD",
            reason="NFP in 10 minutes", context={"pair": "EUR/USD"},
        )
    assert result["type"] == "RISK_WARNING"
    assert result["priority"] == "WARNING"
    assert "NFP" in result["message"]


@pytest.mark.asyncio
async def test_exit_mgmt_alert_persists_with_suggestion_priority(db_session):
    with patch("app.services.audit.logger.audit_logger.alert_generated", new=AsyncMock()):
        result = await generate_exit_mgmt_alert(
            db=db_session, user_id="system", pair="EUR/USD",
            r_multiple=2.0,
            suggested_action={"action": "partial_close", "r_multiple": 2.0,
                              "position_id": "p1", "pair": "EUR/USD"},
            context={"pair": "EUR/USD", "timeframe": "1H"},
        )
    assert result["type"] == "EXIT_MGMT"
    assert result["priority"] == "SUGGESTION"
    assert "2.0R" in result["message"] or "2R" in result["message"]


# ---------------------------------------------------------------------------
# expire_old_alerts
# ---------------------------------------------------------------------------


async def _make_alert(db, *, status=AlertStatus.PENDING, expires_at=None) -> Alert:
    """Build a PENDING-by-default alert. Explicit created_at because SQLite
    can't evaluate the model's PG-flavoured ``server_default='NOW()'``."""
    expires_at = expires_at or datetime.now(tz=timezone.utc) + timedelta(hours=1)
    alert = Alert(
        user_id="system",
        type=AlertType.ENTRY_SIGNAL,
        priority=AlertPriority.WARNING,
        pair="EUR/USD",
        message="x",
        context_json={},
        status=status,
        expires_at=expires_at,
        created_at=datetime.now(tz=timezone.utc),
    )
    db.add(alert)
    await db.flush()
    return alert


@pytest.mark.asyncio
async def test_expire_old_alerts_expires_past_pending(db_session):
    past = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    await _make_alert(db_session, expires_at=past)
    count = await expire_old_alerts(db_session, "system")
    assert count == 1


@pytest.mark.asyncio
async def test_expire_old_alerts_leaves_future_pending_alone(db_session):
    future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    await _make_alert(db_session, expires_at=future)
    count = await expire_old_alerts(db_session, "system")
    assert count == 0


@pytest.mark.asyncio
async def test_expire_old_alerts_skips_non_pending(db_session):
    past = datetime.now(tz=timezone.utc) - timedelta(hours=2)
    await _make_alert(db_session, status=AlertStatus.APPROVED, expires_at=past)
    count = await expire_old_alerts(db_session, "system")
    assert count == 0


# ---------------------------------------------------------------------------
# supersede_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supersede_alert_sets_status_and_resolution(db_session):
    import uuid
    alert = await _make_alert(db_session)
    new_id = uuid.uuid4()
    await supersede_alert(db_session, "system", alert.id, new_id)
    await db_session.flush()
    refreshed = (
        await db_session.execute(select(Alert).where(Alert.id == alert.id))
    ).scalar_one()
    assert refreshed.status == AlertStatus.SUPERSEDED
    assert refreshed.resolved_by == "system"
    assert refreshed.resolved_at is not None
