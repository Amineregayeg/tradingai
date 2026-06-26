"""Alert management endpoints.

Spec: PATCH /api/alerts/{id} for approve / reject / edit.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.core.exceptions import AlertNotFound, InvalidAlertAction, KillSwitchArmed
from app.db.enums import AlertPriority, AlertStatus, AlertType
from app.models.alert import Alert
from app.schemas.alert import AlertActionRequest, AlertRead
from app.services.governance.queue import governance_queue

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertRead])
async def list_alerts(
    db: DBSession,
    user_id: CurrentUser,
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    pair: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> list[AlertRead]:
    """Return alerts filtered by status, priority, and/or pair.

    Results are ordered by ``created_at`` descending (newest first).
    Pagination is offset-based via *page* and *page_size*.
    """
    stmt = (
        select(Alert)
        .options(selectinload(Alert.edit_diffs))
        .where(Alert.user_id == user_id)
        .order_by(Alert.created_at.desc())
    )

    if status is not None:
        try:
            status_enum = AlertStatus(status.upper())
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid status: {status!r}")
        stmt = stmt.where(Alert.status == status_enum)

    if priority is not None:
        try:
            priority_enum = AlertPriority(priority.upper())
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid priority: {priority!r}")
        stmt = stmt.where(Alert.priority == priority_enum)

    if pair is not None:
        stmt = stmt.where(Alert.pair == pair.upper())

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    alerts = result.scalars().all()
    return [AlertRead.model_validate(a) for a in alerts]


@router.get("/{alert_id}", response_model=AlertRead)
async def get_alert(
    alert_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> AlertRead:
    """Return a single alert including its edit diff history."""
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
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    return AlertRead.model_validate(alert)


@router.patch("/{alert_id}", response_model=AlertRead)
async def act_on_alert(
    alert_id: uuid.UUID,
    payload: AlertActionRequest,
    db: DBSession,
    user_id: CurrentUser,
) -> AlertRead:
    """Approve, reject, or edit an alert's suggested action.

    This is the governance endpoint — the only path to moving an alert out
    of PENDING status in MVP.

    * ``approve`` — validates compliance, sets status=APPROVED.
    * ``reject``  — sets status=REJECTED.
    * ``edit``    — applies field-level changes, creates EditDiff records,
                    sets status=EDITED.
    """
    try:
        updated_alert = await governance_queue.process_action(
            db=db,
            user_id=user_id,
            alert_id=alert_id,
            action=payload.action,
            changes=payload.changes,
            reason=payload.reason,
        )
    except AlertNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KillSwitchArmed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidAlertAction as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Reload with edit_diffs eagerly so the response schema is complete
    stmt = (
        select(Alert)
        .options(selectinload(Alert.edit_diffs))
        .where(
            Alert.id == updated_alert.id,
            Alert.user_id == user_id,
        )
    )
    result = await db.execute(stmt)
    alert = result.scalar_one()
    return AlertRead.model_validate(alert)
