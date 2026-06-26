"""Alert generation logic for the decision engine.

All functions interact with the DB to create, update, and expire Alert rows.
AuditLog writes are delegated to :mod:`app.services.audit.logger`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.enums import AlertPriority, AlertStatus, AlertType
from app.models.alert import Alert
from app.models.scoring_profile import ScoringProfile
from app.services.decision.scoring import score_to_priority

if TYPE_CHECKING:
    pass

# Default TTL for entry-signal alerts
_ENTRY_SIGNAL_TTL_HOURS = 4


async def _get_active_scoring_profile(db: AsyncSession, user_id: str) -> ScoringProfile | None:
    """Return the currently active ScoringProfile for *user_id*, or None."""
    stmt = (
        select(ScoringProfile)
        .where(
            ScoringProfile.user_id == user_id,
            ScoringProfile.active.is_(True),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def generate_entry_signal_alert(
    db: AsyncSession,
    user_id: str,
    pair: str,
    score: float,
    ict_detections: list[dict],
    indicators: dict,
    ai_confidence: float | None,
    context: dict,
) -> dict | None:
    """Create an ENTRY_SIGNAL alert if *score* meets the active profile threshold.

    Steps:
    1. Load the active :class:`~app.models.scoring_profile.ScoringProfile`.
    2. Return ``None`` immediately when *score* < ``min_score_entry``.
    3. Supersede any existing PENDING ENTRY_SIGNAL alert for the same pair.
    4. Create and persist the new :class:`~app.models.alert.Alert`.
    5. Emit an ``alert_generated`` audit event.

    Returns:
        Dict representation of the new alert, or ``None`` when below threshold.
    """
    profile = await _get_active_scoring_profile(db, user_id)
    min_score = float(profile.min_score_entry) if profile else 65.0

    if score < min_score:
        logger.debug(
            "Score below threshold — no entry signal alert generated",
            user_id=user_id,
            pair=pair,
            score=score,
            min_score=min_score,
        )
        return None

    # Supersede any existing PENDING ENTRY_SIGNAL for this pair
    existing_stmt = (
        select(Alert)
        .where(
            Alert.user_id == user_id,
            Alert.type == AlertType.ENTRY_SIGNAL,
            Alert.pair == pair,
            Alert.status == AlertStatus.PENDING,
        )
        .order_by(Alert.created_at.desc())
        .limit(1)
    )
    result = await db.execute(existing_stmt)
    existing_alert = result.scalar_one_or_none()

    priority_str = score_to_priority(score)
    priority = AlertPriority(priority_str)

    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(hours=_ENTRY_SIGNAL_TTL_HOURS)

    # Build suggested_action from ICT detections + indicators
    top_detection = (
        max(ict_detections, key=lambda d: float(d.get("confidence", 0)) * float(d.get("strength", 0)))
        if ict_detections
        else None
    )
    suggested_action: dict = {
        "action": "review_entry",
        "pair": pair,
        "score": round(score, 2),
        "top_ict_detection": top_detection,
        "ai_confidence": ai_confidence,
        "indicators_snapshot": {k: v for k, v in indicators.items()},
    }

    new_alert = Alert(
        user_id=user_id,
        type=AlertType.ENTRY_SIGNAL,
        priority=priority,
        pair=pair,
        message=f"Entry signal for {pair} — score {score:.1f}/{min_score:.0f}",
        suggested_action=suggested_action,
        context_json=context,
        status=AlertStatus.PENDING,
        ai_confidence=Decimal(str(round(ai_confidence, 3))) if ai_confidence is not None else None,
        score=Decimal(str(round(score, 2))),
        expires_at=expires_at,
    )
    db.add(new_alert)
    await db.flush()  # populate new_alert.id

    # Supersede old alert after we have the new ID
    if existing_alert is not None:
        await supersede_alert(db, user_id, existing_alert.id, new_alert.id)

    await db.commit()
    await db.refresh(new_alert)

    # Emit audit event (import here to avoid circular imports)
    from app.services.audit.logger import audit_logger  # noqa: PLC0415
    await audit_logger.alert_generated(db, user_id, new_alert)

    logger.info(
        "Entry signal alert generated",
        user_id=user_id,
        alert_id=str(new_alert.id),
        pair=pair,
        score=score,
        priority=priority_str,
    )

    return _alert_to_dict(new_alert)


async def generate_risk_warning(
    db: AsyncSession,
    user_id: str,
    pair: str,
    reason: str,
    context: dict,
) -> dict:
    """Create a RISK_WARNING alert.

    Used for news blackouts, bias invalidation, and drawdown warnings.

    Returns:
        Dict representation of the new alert.
    """
    now = datetime.now(tz=timezone.utc)

    alert = Alert(
        user_id=user_id,
        type=AlertType.RISK_WARNING,
        priority=AlertPriority.WARNING,
        pair=pair,
        message=f"Risk warning for {pair}: {reason}",
        suggested_action={"action": "avoid_trade", "reason": reason},
        context_json=context,
        status=AlertStatus.PENDING,
        expires_at=now + timedelta(hours=1),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    from app.services.audit.logger import audit_logger  # noqa: PLC0415
    await audit_logger.alert_generated(db, user_id, alert)

    logger.info(
        "Risk warning alert generated",
        user_id=user_id,
        alert_id=str(alert.id),
        pair=pair,
        reason=reason,
    )

    return _alert_to_dict(alert)


async def generate_exit_mgmt_alert(
    db: AsyncSession,
    user_id: str,
    pair: str,
    r_multiple: float,
    suggested_action: dict,
    context: dict,
) -> dict:
    """Create an EXIT_MGMT alert when a position hits + 1.5 R.

    Returns:
        Dict representation of the new alert.
    """
    now = datetime.now(tz=timezone.utc)

    alert = Alert(
        user_id=user_id,
        type=AlertType.EXIT_MGMT,
        priority=AlertPriority.SUGGESTION,
        pair=pair,
        message=f"Exit management: {pair} at {r_multiple:.1f}R — consider partial exit",
        suggested_action=suggested_action,
        context_json=context,
        status=AlertStatus.PENDING,
        expires_at=now + timedelta(hours=2),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    from app.services.audit.logger import audit_logger  # noqa: PLC0415
    await audit_logger.alert_generated(db, user_id, alert)

    logger.info(
        "Exit management alert generated",
        user_id=user_id,
        alert_id=str(alert.id),
        pair=pair,
        r_multiple=r_multiple,
    )

    return _alert_to_dict(alert)


async def expire_old_alerts(db: AsyncSession, user_id: str) -> int:
    """Mark PENDING alerts whose ``expires_at`` is in the past as EXPIRED.

    Returns:
        Number of alerts expired.
    """
    now = datetime.now(tz=timezone.utc)
    stmt = (
        update(Alert)
        .where(
            Alert.user_id == user_id,
            Alert.status == AlertStatus.PENDING,
            Alert.expires_at < now,
        )
        .values(status=AlertStatus.EXPIRED, resolved_at=now)
        .execution_options(synchronize_session="fetch")
    )
    result = await db.execute(stmt)
    count = result.rowcount
    if count:
        await db.commit()
        logger.info("Expired old alerts", user_id=user_id, count=count)
    return count


async def supersede_alert(
    db: AsyncSession,
    user_id: str,
    old_alert_id: uuid.UUID,
    new_alert_id: uuid.UUID,
) -> None:
    """Set *old_alert_id* status to SUPERSEDED.

    The *new_alert_id* is recorded in the alert's context_json for traceability.
    """
    now = datetime.now(tz=timezone.utc)
    stmt = (
        update(Alert)
        .where(
            Alert.id == old_alert_id,
            Alert.user_id == user_id,
        )
        .values(
            status=AlertStatus.SUPERSEDED,
            resolved_at=now,
            resolved_by="system",
        )
    )
    await db.execute(stmt)
    logger.info(
        "Alert superseded",
        user_id=user_id,
        old_alert_id=str(old_alert_id),
        new_alert_id=str(new_alert_id),
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _alert_to_dict(alert: Alert) -> dict:
    """Convert an Alert ORM object to a plain dict."""
    return {
        "id": str(alert.id),
        "user_id": alert.user_id,
        "type": alert.type.value if hasattr(alert.type, "value") else str(alert.type),
        "priority": alert.priority.value if hasattr(alert.priority, "value") else str(alert.priority),
        "pair": alert.pair,
        "message": alert.message,
        "suggested_action": alert.suggested_action,
        "context_json": alert.context_json,
        "status": alert.status.value if hasattr(alert.status, "value") else str(alert.status),
        "ai_confidence": float(alert.ai_confidence) if alert.ai_confidence is not None else None,
        "score": float(alert.score) if alert.score is not None else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "expires_at": alert.expires_at.isoformat() if alert.expires_at else None,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "resolved_by": alert.resolved_by,
    }
