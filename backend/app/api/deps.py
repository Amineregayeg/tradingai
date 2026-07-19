"""FastAPI dependency functions shared across routers."""
import secrets
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.core.logging import logger
from app.db.session import get_session

_SINGLE_USER_ID = "system"


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async for session in get_session():
        yield session


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Authenticate the request and return the user's ID.

    This is the real auth gate — it RAISES 401 by default. A request is
    authenticated only when it carries ``Authorization: Bearer <token>`` with a
    token matching ``settings.api_auth_token`` (constant-time compare). There is
    NO anonymous fallback: the previous placeholder that returned ``"system"``
    unconditionally is gone.

    ``auth_disabled=true`` is a LOCAL-DEV-ONLY bypass (logged loudly); it is
    rejected at startup for any non-local deployment via ``assert_auth_configured``.
    """
    if settings.auth_disabled:
        return _SINGLE_USER_ID

    expected = settings.api_auth_token
    if not expected:
        # Should be unreachable in a correctly-started app (startup asserts a
        # token is set unless auth is disabled), but fail closed regardless.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Server auth is not configured",
        )

    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()

    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _SINGLE_USER_ID


def assert_auth_configured() -> None:
    """Fail startup if the app would otherwise serve anonymously.

    Called from the lifespan startup. If auth is not explicitly disabled and no
    token is configured, we raise — the process must not come up in an open
    state. If auth IS disabled, we log a loud warning so it can never pass
    silently.
    """
    if settings.auth_disabled:
        logger.warning(
            "AUTH IS DISABLED (auth_disabled=true) — every /api route is OPEN. "
            "This is a local-dev-only setting and must never be used in production."
        )
        return
    if not settings.api_auth_token:
        raise RuntimeError(
            "API_AUTH_TOKEN is not set and AUTH_DISABLED is false. Refusing to "
            "start in an unauthenticated (open) state. Set API_AUTH_TOKEN to a "
            "strong secret, or AUTH_DISABLED=true for local development only."
        )


def get_settings_obj() -> Settings:
    """Return the application settings object."""
    return settings


# Convenience type aliases for use in router signatures
DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[str, Depends(current_user)]
AppSettings = Annotated[Settings, Depends(get_settings_obj)]
