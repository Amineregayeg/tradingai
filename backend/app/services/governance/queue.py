"""Governance queue — the sole path from alert to broker execution in MVP.

All approve / reject / edit actions on alerts are processed here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AlertNotFound, InvalidAlertAction, KillSwitchArmed
from app.core.logging import logger
from app.db.enums import AlertStatus
from app.models.alert import Alert
from app.models.edit_diff import EditDiff
from app.services.audit.logger import audit_logger


class GovernanceQueue:
    """Handles approve / reject / edit lifecycle transitions for alerts.

    The approval queue is the ONLY path to broker execution in MVP.  In test
    mode (which is the default for MVP), approved alerts stay at
    ``status=APPROVED`` and are never forwarded to the broker.
    """

    async def process_action(
        self,
        db: AsyncSession,
        user_id: str,
        alert_id: uuid.UUID,
        action: str,
        changes: dict | None,
        reason: str | None,
    ) -> Alert:
        """Apply an approve / reject / edit action to an alert.

        Args:
            db: SQLAlchemy async session.
            user_id: Acting user (safety-scoped).
            alert_id: UUID of the target alert.
            action: One of ``"approve"``, ``"reject"``, ``"edit"``.
            changes: Dict of ``{field_path: new_value}`` (required for edit).
            reason: Human-readable rationale (optional for approve/reject).

        Returns:
            The updated :class:`~app.models.alert.Alert` ORM object.

        Raises:
            AlertNotFound: Alert does not exist or belongs to another user.
            InvalidAlertAction: Alert is not PENDING, or ``action`` is unknown.
            KillSwitchArmed: Triggered on approve when compliance is HALTED.
        """
        # 1. Load alert (with edit_diffs for completeness) -------------------
        stmt = (
            select(Alert)
            .options(selectinload(Alert.edit_diffs))
            .where(
                Alert.id == alert_id,
                Alert.user_id == user_id,
            )
        )
        result = await db.execute(stmt)
        alert = result.scalar_one_or_none()

        if alert is None:
            raise AlertNotFound(str(alert_id))

        # 2. Validate status -------------------------------------------------
        if alert.status != AlertStatus.PENDING:
            raise InvalidAlertAction(
                f"Alert {alert_id} is not PENDING (current status: {alert.status.value})",
                action=action,
                current_status=alert.status.value,
            )

        action_lower = action.lower()

        # 3–5. Dispatch by action -------------------------------------------
        if action_lower == "approve":
            alert = await self._approve(db, user_id, alert)

        elif action_lower == "reject":
            alert = await self._reject(db, user_id, alert, reason)

        elif action_lower == "edit":
            if not changes:
                raise InvalidAlertAction(
                    "Edit action requires a non-empty 'changes' dict",
                    action=action,
                    current_status=alert.status.value,
                )
            alert = await self._edit(db, user_id, alert, changes, reason)

        else:
            raise InvalidAlertAction(
                f"Unknown action: {action!r}. Must be one of: approve, reject, edit",
                action=action,
                current_status=alert.status.value,
            )

        return alert

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _approve(
        self, db: AsyncSession, user_id: str, alert: Alert
    ) -> Alert:
        """Approve an alert.

        Compliance check: raises :exc:`KillSwitchArmed` if a HALTED prop-firm
        profile is detected.

        In MVP Test Mode the alert stays at ``APPROVED`` — no broker call.
        """
        # KillSwitch check (read compliance state from context_json if present)
        compliance_state = (alert.context_json or {}).get("compliance_state", "")
        if str(compliance_state).upper() == "HALTED":
            raise KillSwitchArmed(
                detail=f"Trading is halted — cannot approve alert {alert.id}",
            )

        now = datetime.now(tz=timezone.utc)
        alert.status = AlertStatus.APPROVED
        alert.resolved_at = now
        alert.resolved_by = user_id

        db.add(alert)
        await db.commit()
        await db.refresh(alert)

        # Audit
        await audit_logger.alert_approved(db, user_id, alert, actor="TRADER")

        logger.info(
            "Alert approved",
            user_id=user_id,
            alert_id=str(alert.id),
            pair=alert.pair,
        )
        return alert

    async def _reject(
        self, db: AsyncSession, user_id: str, alert: Alert, reason: str | None
    ) -> Alert:
        """Reject an alert."""
        now = datetime.now(tz=timezone.utc)
        alert.status = AlertStatus.REJECTED
        alert.resolved_at = now
        alert.resolved_by = user_id

        db.add(alert)
        await db.commit()
        await db.refresh(alert)

        # Audit
        await audit_logger.alert_rejected(db, user_id, alert, reason=reason or "")

        logger.info(
            "Alert rejected",
            user_id=user_id,
            alert_id=str(alert.id),
            pair=alert.pair,
            reason=reason,
        )
        return alert

    async def _edit(
        self,
        db: AsyncSession,
        user_id: str,
        alert: Alert,
        changes: dict,
        reason: str | None,
    ) -> Alert:
        """Apply field-level edits to an alert's suggested_action JSONB.

        For each ``(field_path, new_value)`` pair in *changes*:
        * Capture the current value from ``alert.suggested_action``.
        * Create an :class:`~app.models.edit_diff.EditDiff` record (APPEND-ONLY).
        * Apply the new value.

        The alert status transitions to ``EDITED``.
        """
        diffs: list[dict] = []

        # Work on a mutable copy of the suggested_action dict
        suggested = dict(alert.suggested_action or {})

        for field_path, new_value in changes.items():
            # Capture old value (support simple dot-notation in the future;
            # for MVP treat field_path as a top-level key)
            old_raw = suggested.get(field_path)
            old_str = str(old_raw) if old_raw is not None else None
            new_str = str(new_value) if new_value is not None else None

            # Persist EditDiff (APPEND-ONLY)
            diff = EditDiff(
                user_id=user_id,
                alert_id=alert.id,
                field_path=field_path,
                old_value=old_str,
                new_value=new_str,
                reason=reason,
            )
            db.add(diff)

            # Apply change
            suggested[field_path] = new_value

            diffs.append(
                {
                    "field_path": field_path,
                    "old_value": old_str,
                    "new_value": new_str,
                }
            )

        # Update alert
        alert.suggested_action = suggested
        alert.status = AlertStatus.EDITED

        db.add(alert)
        await db.commit()
        await db.refresh(alert)

        # Audit
        await audit_logger.alert_edited(db, user_id, alert, diffs=diffs)

        logger.info(
            "Alert edited",
            user_id=user_id,
            alert_id=str(alert.id),
            pair=alert.pair,
            fields_changed=list(changes.keys()),
        )
        return alert


# Module-level singleton
governance_queue = GovernanceQueue()
