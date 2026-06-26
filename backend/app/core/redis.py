"""Shared Redis client singleton."""
from __future__ import annotations

import redis.asyncio as aioredis

from app.config import settings

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return the shared Redis client, creating it on first call."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    """Close and discard the shared Redis client."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
