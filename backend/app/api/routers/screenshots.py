"""Screenshot capture and retrieval endpoints."""
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.config import settings
from app.core.logging import logger
from app.db.enums import ScreenshotTrigger
from app.models.screenshot import Screenshot
from app.schemas.screenshot import ScreenshotRead

router = APIRouter(prefix="/screenshots", tags=["screenshots"])

MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_MAGIC = b"\x89PNG"  # PNG magic bytes (first 4 bytes)


def _screenshot_dir(user_id: str) -> Path:
    return Path(settings.data_dir) / "screenshots" / user_id


@router.get("", response_model=list[ScreenshotRead])
async def list_screenshots(
    db: DBSession,
    user_id: CurrentUser,
    trade_id: uuid.UUID | None = Query(default=None),
    pair: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> list[ScreenshotRead]:
    """List screenshots with optional trade/pair filters."""
    stmt = select(Screenshot).where(Screenshot.user_id == user_id)

    if trade_id:
        stmt = stmt.where(Screenshot.trade_id == trade_id)
    if pair:
        stmt = stmt.where(Screenshot.pair == pair)

    stmt = (
        stmt.order_by(Screenshot.captured_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{screenshot_id}", response_model=ScreenshotRead)
async def get_screenshot(
    screenshot_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> ScreenshotRead:
    """Return metadata for a single screenshot."""
    stmt = select(Screenshot).where(
        Screenshot.id == screenshot_id,
        Screenshot.user_id == user_id,
    )
    result = await db.execute(stmt)
    screenshot = result.scalar_one_or_none()

    if screenshot is None:
        raise HTTPException(status_code=404, detail="Screenshot not found")

    return ScreenshotRead.model_validate(screenshot)


@router.post("", response_model=ScreenshotRead, status_code=201)
async def upload_screenshot(
    db: DBSession,
    user_id: CurrentUser,
    pair: str = Form(...),
    timeframe: str = Form(...),
    trigger_type: ScreenshotTrigger = Form(default=ScreenshotTrigger.MANUAL),
    trade_id: uuid.UUID | None = Form(default=None),
    image: UploadFile = File(...),
) -> ScreenshotRead:
    """Upload a chart screenshot for a given pair/timeframe.

    Validates:
    - File size < 5 MB
    - PNG magic bytes (first 4 bytes == 0x89504e47)
    - Deduplicates by SHA-256 hash
    """
    # Read file content
    content = await image.read()

    # 1. Validate size
    if len(content) > MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large. Maximum size is {MAX_SIZE_BYTES // (1024 * 1024)} MB",
        )

    # 2. Validate PNG magic bytes
    if len(content) < 4 or content[:4] != ALLOWED_MAGIC:
        raise HTTPException(
            status_code=422,
            detail="Invalid file type. Only PNG images are accepted",
        )

    # 3. Compute SHA-256 hash
    image_hash = hashlib.sha256(content).hexdigest()

    # 4. Check for duplicate in DB (cache hit)
    dedup_stmt = select(Screenshot).where(
        Screenshot.user_id == user_id,
        Screenshot.image_hash == image_hash,
    )
    dedup_result = await db.execute(dedup_stmt)
    existing = dedup_result.scalar_one_or_none()
    if existing is not None:
        logger.info(
            "Screenshot dedup cache hit",
            user_id=user_id,
            hash=image_hash,
            existing_id=str(existing.id),
        )
        return ScreenshotRead.model_validate(existing)

    # 5. Persist to disk
    screenshot_id = uuid.uuid4()
    save_dir = _screenshot_dir(user_id)
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / f"{screenshot_id}.png"
    file_path.write_bytes(content)

    # 6. Persist to DB
    screenshot = Screenshot(
        id=screenshot_id,
        user_id=user_id,
        trade_id=trade_id,
        pair=pair,
        timeframe=timeframe,
        trigger_type=trigger_type,
        image_path=str(file_path),
        image_hash=image_hash,
        captured_at=datetime.now(timezone.utc),
    )
    db.add(screenshot)
    await db.flush()
    await db.refresh(screenshot)

    logger.info(
        "Screenshot uploaded",
        user_id=user_id,
        screenshot_id=str(screenshot_id),
        pair=pair,
        timeframe=timeframe,
    )

    return ScreenshotRead.model_validate(screenshot)


@router.get("/{screenshot_id}/image")
async def get_screenshot_image(
    screenshot_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> FileResponse:
    """Serve the raw image file for a screenshot."""
    stmt = select(Screenshot).where(
        Screenshot.id == screenshot_id,
        Screenshot.user_id == user_id,
    )
    result = await db.execute(stmt)
    screenshot = result.scalar_one_or_none()

    if screenshot is None:
        raise HTTPException(status_code=404, detail="Screenshot not found")

    image_path = Path(screenshot.image_path)
    if not image_path.exists():
        logger.error(
            "Screenshot file missing from disk",
            screenshot_id=str(screenshot_id),
            path=str(image_path),
        )
        raise HTTPException(status_code=404, detail="Image file not found on disk")

    return FileResponse(
        path=str(image_path),
        media_type="image/png",
        filename=f"{screenshot_id}.png",
    )


@router.delete("/{screenshot_id}", status_code=204)
async def delete_screenshot(
    screenshot_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> None:
    """Delete a screenshot and its stored image file."""
    stmt = select(Screenshot).where(
        Screenshot.id == screenshot_id,
        Screenshot.user_id == user_id,
    )
    result = await db.execute(stmt)
    screenshot = result.scalar_one_or_none()

    if screenshot is None:
        raise HTTPException(status_code=404, detail="Screenshot not found")

    # Remove file from disk
    image_path = Path(screenshot.image_path)
    if image_path.exists():
        try:
            image_path.unlink()
        except OSError as exc:
            logger.warning(
                "Failed to delete screenshot file",
                path=str(image_path),
                error=str(exc),
            )

    await db.delete(screenshot)
    await db.flush()
    logger.info("Screenshot deleted", screenshot_id=str(screenshot_id), user_id=user_id)
