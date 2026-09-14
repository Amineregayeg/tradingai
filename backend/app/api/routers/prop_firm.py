"""Prop firm compliance endpoints."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.core.logging import logger
from app.db.enums import ComplianceState
from app.models.prop_firm_profile import PropFirmProfile
from app.models.prop_firm_snapshot import PropFirmSnapshot
from app.schemas.propfirm import (
    KillSwitchRequest,
    KillSwitchTriggerResponse,
    PropFirmProfileCreate,
    PropFirmProfileRead,
    PropFirmStatusRead,
)

router = APIRouter(prefix="/prop-firm", tags=["prop-firm"])


@router.get("/profiles", response_model=list[PropFirmProfileRead])
async def list_profiles(
    db: DBSession,
    user_id: CurrentUser,
) -> list[PropFirmProfileRead]:
    """List all prop firm profiles."""
    stmt = select(PropFirmProfile).where(PropFirmProfile.user_id == user_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/profiles", response_model=PropFirmProfileRead, status_code=201)
async def create_profile(
    payload: PropFirmProfileCreate,
    db: DBSession,
    user_id: CurrentUser,
) -> PropFirmProfileRead:
    """Create a new prop firm profile."""
    profile = PropFirmProfile(
        user_id=user_id,
        firm_name=payload.firm_name,
        challenge_type=payload.challenge_type,
        rules_json=payload.rules_json,
        account_id=payload.account_id,
        active=True,
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)

    logger.info(
        "PropFirmProfile created",
        profile_id=str(profile.id),
        firm_name=payload.firm_name,
        user_id=user_id,
    )

    return PropFirmProfileRead.model_validate(profile)


@router.get("/profiles/{profile_id}", response_model=PropFirmProfileRead)
async def get_profile(
    profile_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> PropFirmProfileRead:
    """Return a single prop firm profile."""
    stmt = select(PropFirmProfile).where(
        PropFirmProfile.id == profile_id,
        PropFirmProfile.user_id == user_id,
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(status_code=404, detail="PropFirmProfile not found")

    return PropFirmProfileRead.model_validate(profile)


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> None:
    """Delete a prop firm profile."""
    stmt = select(PropFirmProfile).where(
        PropFirmProfile.id == profile_id,
        PropFirmProfile.user_id == user_id,
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(status_code=404, detail="PropFirmProfile not found")

    await db.delete(profile)
    await db.flush()
    logger.info("PropFirmProfile deleted", profile_id=str(profile_id), user_id=user_id)


@router.get("/status", response_model=list[PropFirmStatusRead])
async def list_compliance_status(
    db: DBSession,
    user_id: CurrentUser,
) -> list[PropFirmStatusRead]:
    """Return current compliance status for all active profiles."""
    stmt = (
        select(PropFirmProfile)
        .where(PropFirmProfile.user_id == user_id, PropFirmProfile.active.is_(True))
        .options(selectinload(PropFirmProfile.snapshots))
    )
    result = await db.execute(stmt)
    profiles = result.scalars().all()

    statuses: list[PropFirmStatusRead] = []
    for profile in profiles:
        # Use most recent snapshot if available, otherwise return zeros
        latest_snapshot = (
            max(profile.snapshots, key=lambda s: s.timestamp)
            if profile.snapshots
            else None
        )
        rules = profile.rules_json or {}
        statuses.append(
            PropFirmStatusRead(
                profile_id=profile.id,
                firm_name=profile.firm_name,
                state=latest_snapshot.state if latest_snapshot else ComplianceState.ACTIVE,
                equity=latest_snapshot.equity if latest_snapshot else Decimal("0"),
                balance=latest_snapshot.balance if latest_snapshot else Decimal("0"),
                daily_loss=latest_snapshot.daily_loss if latest_snapshot else Decimal("0"),
                total_loss=latest_snapshot.total_loss if latest_snapshot else Decimal("0"),
                daily_loss_limit_pct=Decimal(str(rules.get("daily_dd_pct", 0))) if "daily_dd_pct" in rules else None,
                total_loss_limit_pct=Decimal(str(rules.get("max_dd_pct", 0))) if "max_dd_pct" in rules else None,
                timestamp=latest_snapshot.timestamp if latest_snapshot else datetime.now(timezone.utc),
            )
        )

    return statuses


@router.get("/status/{profile_id}", response_model=PropFirmStatusRead)
async def get_compliance_status(
    profile_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> PropFirmStatusRead:
    """Return current compliance status for a single profile."""
    stmt = (
        select(PropFirmProfile)
        .where(
            PropFirmProfile.id == profile_id,
            PropFirmProfile.user_id == user_id,
        )
        .options(selectinload(PropFirmProfile.snapshots))
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(status_code=404, detail="PropFirmProfile not found")

    latest_snapshot = (
        max(profile.snapshots, key=lambda s: s.timestamp)
        if profile.snapshots
        else None
    )
    rules = profile.rules_json or {}

    return PropFirmStatusRead(
        profile_id=profile.id,
        firm_name=profile.firm_name,
        state=latest_snapshot.state if latest_snapshot else ComplianceState.ACTIVE,
        equity=latest_snapshot.equity if latest_snapshot else Decimal("0"),
        balance=latest_snapshot.balance if latest_snapshot else Decimal("0"),
        daily_loss=latest_snapshot.daily_loss if latest_snapshot else Decimal("0"),
        total_loss=latest_snapshot.total_loss if latest_snapshot else Decimal("0"),
        daily_loss_limit_pct=Decimal(str(rules.get("daily_dd_pct", 0))) if "daily_dd_pct" in rules else None,
        total_loss_limit_pct=Decimal(str(rules.get("max_dd_pct", 0))) if "max_dd_pct" in rules else None,
        timestamp=latest_snapshot.timestamp if latest_snapshot else datetime.now(timezone.utc),
    )


@router.post("/kill-switch", response_model=KillSwitchTriggerResponse)
async def trigger_kill_switch(
    payload: KillSwitchRequest,
    db: DBSession,
    user_id: CurrentUser,
) -> KillSwitchTriggerResponse:
    """Trigger the kill switch for a prop firm profile: close all positions immediately."""
    from app.services.compliance.kill_switch import kill_switch

    # Verify the profile exists and belongs to this user
    stmt = select(PropFirmProfile).where(
        PropFirmProfile.id == payload.profile_id,
        PropFirmProfile.user_id == user_id,
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(status_code=404, detail="PropFirmProfile not found")

    # `B442` (g), manager's ruling: NO separate arm() here. `trigger()` arms itself and KEEPS an existing reason
    # (K2-11), so a second request while a trigger runs no longer replaces the reason the switch was pulled for.
    result_data = await kill_switch.trigger(
        db=db,
        user_id=user_id,
        reason=payload.reason,
    )

    if result_data.get("already_in_progress"):
        # `B443` item 6, as corrected by the manager: a second trigger closed NOTHING, and a trigger response would
        # say `positions_closed: 0` — `B366`'s "0 closed" at the moment an operator is most likely to misread it.
        # 409, with what the running trigger has reported so far and no counters.
        #
        # RETURNED, not raised: the app's HTTPException handler renders `str(detail)`, so a dict of rows would reach
        # the operator as a Python repr. The body is the same problem+json the handler builds, with the rows as JSON
        # and every string in them passed through the response redactor (`B404`) — a row's reason carries venue text.
        from fastapi.encoders import jsonable_encoder
        from fastapi.responses import JSONResponse

        from app.core.exceptions import problem_response
        from app.core.logging import redact_for_response

        rows = [
            {k: (redact_for_response(v) if isinstance(v, str) else v) for k, v in row.items()}
            for row in result_data.get("details", [])
        ]
        return JSONResponse(  # type: ignore[return-value]
            status_code=409,
            media_type="application/problem+json",
            content=jsonable_encoder(problem_response(
                title="Kill switch already in progress",
                status=409,
                detail=result_data.get("message"),
                extensions={"in_progress_for_s": result_data.get("in_progress_for_s"), "rows_so_far": rows},
            )),
        )

    positions_closed = result_data.get("positions_closed", 0)

    return KillSwitchTriggerResponse(
        profile_id=payload.profile_id,
        armed=True,
        positions_closed=positions_closed,
        state=ComplianceState.HALTED,
        message=result_data.get("message", "Kill switch triggered"),
    )
