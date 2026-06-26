"""ICT structure detection endpoints."""
import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.db.enums import ICTStatus
from app.models.ict_detection import ICTDetection
from app.schemas.ict import ICTDetectionRead

router = APIRouter(prefix="/ict", tags=["ict"])


@router.get("", response_model=list[ICTDetectionRead])
async def list_ict_detections(
    db: DBSession,
    user_id: CurrentUser,
    pair: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    detection_type: str | None = Query(default=None),
    status: ICTStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> list[ICTDetectionRead]:
    """List ICT detections with optional filters. Defaults to ACTIVE status."""
    stmt = select(ICTDetection).where(ICTDetection.user_id == user_id)

    if pair:
        stmt = stmt.where(ICTDetection.pair == pair)
    if timeframe:
        stmt = stmt.where(ICTDetection.timeframe == timeframe)
    if detection_type:
        stmt = stmt.where(ICTDetection.detection_type == detection_type)

    # Default to ACTIVE only when no status filter provided
    if status is not None:
        stmt = stmt.where(ICTDetection.status == status)
    else:
        stmt = stmt.where(ICTDetection.status == ICTStatus.ACTIVE)

    stmt = (
        stmt.order_by(ICTDetection.detected_at.desc())
        .offset((page - 1) * page_size)
        .limit(min(page_size, 200))
    )

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{detection_id}", response_model=ICTDetectionRead)
async def get_ict_detection(
    detection_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> ICTDetectionRead:
    """Return a single ICT detection."""
    stmt = select(ICTDetection).where(
        ICTDetection.id == detection_id,
        ICTDetection.user_id == user_id,
    )
    result = await db.execute(stmt)
    detection = result.scalar_one_or_none()

    if detection is None:
        raise HTTPException(status_code=404, detail="ICT detection not found")

    return ICTDetectionRead.model_validate(detection)
