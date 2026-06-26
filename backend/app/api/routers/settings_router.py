"""User settings endpoints."""
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.logging import logger
from app.models.settings import UserSettings
from app.schemas.settings import SettingsRead, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsRead)
async def get_settings(
    db: DBSession,
    user_id: CurrentUser,
) -> SettingsRead:
    """Return current user settings, creating defaults if not yet persisted."""
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await db.execute(stmt)
    settings_obj = result.scalar_one_or_none()

    if settings_obj is None:
        # Create default settings row on first access
        settings_obj = UserSettings(user_id=user_id)
        db.add(settings_obj)
        await db.flush()
        await db.refresh(settings_obj)
        logger.info("Created default settings for user", user_id=user_id)

    return SettingsRead.model_validate(settings_obj)


@router.patch("", response_model=SettingsRead)
async def update_settings(
    payload: SettingsUpdate,
    db: DBSession,
    user_id: CurrentUser,
) -> SettingsRead:
    """Partially update user settings. Only provided (non-None) fields are changed."""
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await db.execute(stmt)
    settings_obj = result.scalar_one_or_none()

    if settings_obj is None:
        # Create default row if missing
        settings_obj = UserSettings(user_id=user_id)
        db.add(settings_obj)
        await db.flush()

    update_data = payload.model_dump(exclude_none=True)
    changed_fields: list[str] = []

    for field, new_value in update_data.items():
        old_value = getattr(settings_obj, field, None)
        if old_value != new_value:
            setattr(settings_obj, field, new_value)
            changed_fields.append(field)
            logger.info(
                "Setting changed",
                user_id=user_id,
                field=field,
                old_value=str(old_value),
                new_value=str(new_value),
            )

    if changed_fields:
        settings_obj.updated_at = datetime.now(timezone.utc)
        db.add(settings_obj)
        await db.flush()
        await db.refresh(settings_obj)

    return SettingsRead.model_validate(settings_obj)
