"""FastAPI dependency functions shared across routers."""
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.db.session import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async for session in get_session():
        yield session


async def current_user() -> str:
    """Return the authenticated user's ID.

    SaaS-ready placeholder — returns 'system' for the self-hosted single-user
    deployment. In a multi-tenant deployment this would extract the user ID
    from the JWT / session token.
    """
    return "system"


def get_settings_obj() -> Settings:
    """Return the application settings object."""
    return settings


# Convenience type aliases for use in router signatures
DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[str, Depends(current_user)]
AppSettings = Annotated[Settings, Depends(get_settings_obj)]
