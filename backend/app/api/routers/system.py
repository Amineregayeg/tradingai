"""System health and status endpoints."""
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AppSettings, CurrentUser, DBSession
from app.config import settings as app_settings
from app.core.logging import logger

router = APIRouter(prefix="/system", tags=["system"])


async def _check_db(db: AsyncSession) -> str:
    """Return 'ok' or 'error' based on a simple SELECT 1."""
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        logger.warning("DB health check failed", error=str(exc))
        return "error"


async def _check_redis() -> str:
    """Return 'ok' or 'error' based on a PING to Redis."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(app_settings.redis_url, socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        return "ok"
    except Exception as exc:
        logger.warning("Redis health check failed", error=str(exc))
        return "error"


@router.get("/health")
async def health_check(db: DBSession) -> dict[str, Any]:
    """Full health check — verifies DB and Redis connectivity.

    This endpoint does not require authentication.
    Returns 200 even when downstream checks fail (callers inspect per-component status).
    """
    db_status = await _check_db(db)
    redis_status = await _check_redis()

    # Broker status: collect from broker_manager adapters
    from app.services.broker.manager import broker_manager

    broker_statuses: dict[str, str] = {}
    for conn_id, adapter in broker_manager._adapters.items():
        broker_statuses[adapter.broker_name] = "connected"

    # AI status: enabled if anthropic key configured
    ai_status = "ok" if app_settings.anthropic_api_key else "disabled"

    return {
        "status": "ok",
        "db": db_status,
        "redis": redis_status,
        "brokers": broker_statuses,
        "ai": ai_status,
        "version": "0.1.0",
    }


@router.get("/readiness")
async def readiness_check(db: DBSession) -> dict[str, Any]:
    """Readiness probe — checks DB connectivity."""
    db_status = await _check_db(db)
    ready = db_status == "ok"
    return {
        "ready": ready,
        "db": db_status,
    }


@router.get("/info")
async def system_info(
    settings: AppSettings,
    user_id: CurrentUser,
) -> dict[str, Any]:
    """Return non-sensitive system configuration info."""
    return {
        "version": "0.1.0",
        "mode": "single-tenant",
        "ai_primary_model": settings.ai_primary_model,
        "ai_screening_model": settings.ai_screening_model,
        "ai_monthly_budget_usd": settings.ai_monthly_budget_usd,
        "oanda_environment": settings.oanda_environment,
        "log_level": settings.log_level,
    }
