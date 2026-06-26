"""Append-only audit logger.

CRITICAL: this module ONLY performs INSERT operations on ``audit_log``.
No UPDATE or DELETE queries are ever issued.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger as app_logger
from app.db.enums import ActorType
from app.models.audit_log import AuditLog

if TYPE_CHECKING:
    from app.models.ai_analysis import AIAnalysis
    from app.models.alert import Alert


class AuditLogger:
    """Thin wrapper around the ``audit_log`` table.

    Every method is fire-and-forget: exceptions are caught and logged via
    loguru rather than propagated, so a logging failure never breaks the
    calling business flow.
    """

    async def log(
        self,
        db: AsyncSession,
        user_id: str,
        event_type: str,
        entity_type: str,
        actor: ActorType,
        *,
        entity_id: uuid.UUID | None = None,
        old_value: dict | None = None,
        new_value: dict | None = None,
        metadata: dict | None = None,
        result: str = "SUCCESS",
    ) -> None:
        """Insert a single audit log entry.

        This method never raises — errors are swallowed and emitted via loguru
        so that an audit-write failure cannot break a business-critical flow.

        Args:
            db: SQLAlchemy async session.
            user_id: Owning user.
            event_type: Free-text event identifier (e.g. ``"ALERT_GENERATED"``).
            entity_type: Type of the affected entity (e.g. ``"alert"``).
            actor: Who triggered the event (:class:`~app.db.enums.ActorType`).
            entity_id: Optional UUID of the affected entity row.
            old_value: Optional before-state snapshot (JSONB).
            new_value: Optional after-state snapshot (JSONB).
            metadata: Supplementary information (JSONB).
            result: Outcome string (default ``"SUCCESS"``).
        """
        try:
            entry = AuditLog(
                user_id=user_id,
                event_type=event_type,
                entity_type=entity_type,
                actor=actor,
                entity_id=entity_id,
                old_value=old_value,
                new_value=new_value,
                metadata_json=metadata,
                result=result,
            )
            db.add(entry)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            app_logger.error(
                "AuditLogger: failed to write audit entry",
                event_type=event_type,
                entity_type=entity_type,
                user_id=user_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Convenience methods for common event types
    # ------------------------------------------------------------------

    async def alert_generated(
        self, db: AsyncSession, user_id: str, alert: "Alert"
    ) -> None:
        """Log an ``ALERT_GENERATED`` event for a newly created alert."""
        await self.log(
            db,
            user_id,
            event_type="ALERT_GENERATED",
            entity_type="alert",
            actor=ActorType.SYSTEM,
            entity_id=alert.id,
            new_value={
                "type": alert.type.value if hasattr(alert.type, "value") else str(alert.type),
                "priority": alert.priority.value if hasattr(alert.priority, "value") else str(alert.priority),
                "pair": alert.pair,
                "score": float(alert.score) if alert.score is not None else None,
                "message": alert.message,
            },
        )

    async def alert_approved(
        self,
        db: AsyncSession,
        user_id: str,
        alert: "Alert",
        actor: str = "TRADER",
    ) -> None:
        """Log a ``SUGGESTION_APPROVED`` event."""
        actor_type = ActorType.TRADER if actor.upper() == "TRADER" else ActorType.SYSTEM
        await self.log(
            db,
            user_id,
            event_type="SUGGESTION_APPROVED",
            entity_type="alert",
            actor=actor_type,
            entity_id=alert.id,
            new_value={
                "status": "APPROVED",
                "pair": alert.pair,
            },
        )

    async def alert_rejected(
        self,
        db: AsyncSession,
        user_id: str,
        alert: "Alert",
        reason: str,
    ) -> None:
        """Log a ``SUGGESTION_REJECTED`` event."""
        await self.log(
            db,
            user_id,
            event_type="SUGGESTION_REJECTED",
            entity_type="alert",
            actor=ActorType.TRADER,
            entity_id=alert.id,
            new_value={
                "status": "REJECTED",
                "reason": reason,
                "pair": alert.pair,
            },
        )

    async def alert_edited(
        self,
        db: AsyncSession,
        user_id: str,
        alert: "Alert",
        diffs: list[dict],
    ) -> None:
        """Log a ``SUGGESTION_EDITED`` event with field-level diffs."""
        await self.log(
            db,
            user_id,
            event_type="SUGGESTION_EDITED",
            entity_type="alert",
            actor=ActorType.TRADER,
            entity_id=alert.id,
            new_value={
                "status": "EDITED",
                "diffs": diffs,
                "pair": alert.pair,
            },
        )

    async def ai_analysis_completed(
        self,
        db: AsyncSession,
        user_id: str,
        analysis: "AIAnalysis",
    ) -> None:
        """Log an ``AI_ANALYSIS_COMPLETED`` event."""
        await self.log(
            db,
            user_id,
            event_type="AI_ANALYSIS_COMPLETED",
            entity_type="ai_analysis",
            actor=ActorType.AI,
            entity_id=analysis.id,
            new_value={
                "model": analysis.model,
                "trade_bias": analysis.trade_bias,
                "confidence": float(analysis.confidence) if analysis.confidence is not None else None,
                "cost_usd": float(analysis.cost_usd),
                "downgraded": analysis.downgraded,
            },
        )

    async def ai_skipped(
        self,
        db: AsyncSession,
        user_id: str,
        reason: str,
    ) -> None:
        """Log an ``AI_SKIPPED`` event (budget cap, circuit open, disabled, etc.)."""
        await self.log(
            db,
            user_id,
            event_type="AI_SKIPPED",
            entity_type="ai_analysis",
            actor=ActorType.SYSTEM,
            metadata={"reason": reason},
            result="SKIPPED",
        )

    async def kill_switch_triggered(
        self,
        db: AsyncSession,
        user_id: str,
        profile_id: str,
        positions_closed: int,
    ) -> None:
        """Log a ``KILL_SWITCH_TRIGGERED`` event."""
        await self.log(
            db,
            user_id,
            event_type="KILL_SWITCH_TRIGGERED",
            entity_type="prop_firm_profile",
            actor=ActorType.SYSTEM,
            metadata={
                "profile_id": profile_id,
                "positions_closed": positions_closed,
            },
            result="SUCCESS",
        )

    async def broker_connected(
        self,
        db: AsyncSession,
        user_id: str,
        broker: str,
        account_id: str,
    ) -> None:
        """Log a ``BROKER_CONNECTED`` event."""
        await self.log(
            db,
            user_id,
            event_type="BROKER_CONNECTED",
            entity_type="broker_connection",
            actor=ActorType.TRADER,
            new_value={"broker": broker, "account_id": account_id},
        )

    async def setting_changed(
        self,
        db: AsyncSession,
        user_id: str,
        field: str,
        old_val: object,
        new_val: object,
    ) -> None:
        """Log a ``SETTING_CHANGED`` event for a UserSettings field mutation."""
        await self.log(
            db,
            user_id,
            event_type="SETTING_CHANGED",
            entity_type="settings",
            actor=ActorType.TRADER,
            old_value={field: str(old_val)},
            new_value={field: str(new_val)},
        )


# Module-level singleton
audit_logger = AuditLogger()
