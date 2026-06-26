"""Economic calendar endpoint backed by Finnhub (cached in Redis)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import settings as app_settings

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/today")
async def get_today_calendar() -> list[dict]:
    """Return today's economic calendar events.

    Requires FINNHUB_API_KEY in the environment. Returns 503 if unconfigured.
    """
    if not app_settings.finnhub_api_key:
        raise HTTPException(
            status_code=503,
            detail="FINNHUB_API_KEY not configured — set it in .env to enable the economic calendar",
        )

    try:
        from app.services.calendar.finnhub import calendar_service  # noqa: PLC0415
        events = await calendar_service.get_today_events()
        return [e.to_dict() if hasattr(e, "to_dict") else e for e in events]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Calendar fetch failed: {exc}") from exc
