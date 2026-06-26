"""Audit log endpoints — read-only view of the append-only audit_log table."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.models.audit_log import AuditLog
from app.schemas.audit import AuditEventRead

router = APIRouter(prefix="/audit-log", tags=["audit-log"])


@router.get("", response_model=list[AuditEventRead])
async def list_audit_events(
    db: DBSession,
    user_id: CurrentUser,
    event_type: str | None = Query(default=None, description="Filter by event_type"),
    entity_type: str | None = Query(default=None, description="Filter by entity_type"),
    from_dt: datetime | None = Query(default=None, description="Include events at or after this timestamp (ISO 8601)"),
    to_dt: datetime | None = Query(default=None, description="Include events at or before this timestamp (ISO 8601)"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=100, ge=1, le=500),
) -> list[AuditEventRead]:
    """Return audit log entries for the current user.

    Results are ordered by ``created_at`` descending (newest first).

    Args:
        event_type: Optional filter on ``event_type`` (exact match).
        entity_type: Optional filter on ``entity_type`` (exact match).
        from_dt: Optional lower bound on ``created_at``.
        to_dt: Optional upper bound on ``created_at``.
        page: 1-based page number.
        per_page: Page size (max 500).
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
    )

    if event_type is not None:
        stmt = stmt.where(AuditLog.event_type == event_type)

    if entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == entity_type)

    if from_dt is not None:
        stmt = stmt.where(AuditLog.created_at >= from_dt)

    if to_dt is not None:
        stmt = stmt.where(AuditLog.created_at <= to_dt)

    offset = (page - 1) * per_page
    stmt = stmt.offset(offset).limit(per_page)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [AuditEventRead.model_validate(row) for row in rows]
