"""Economic calendar endpoint backed by Finnhub (cached in Redis)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser
from app.config import settings as app_settings

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/today")
async def get_today_calendar(user_id: CurrentUser) -> list[dict]:
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
        # `B404`. THE UPSTREAM MESSAGE IS NOT FORWARDED AT ALL.
        #
        # This was `detail=f"Calendar fetch failed: {exc}"`, and an `httpx.HTTPStatusError`
        # renders the request URL — which carries Finnhub's key as `?token=` (`finnhub.py:290`).
        # A failing upstream therefore returned the key in a 502 body, most often when the key
        # was already wrong or expired.
        #
        # `problem_response` now redacts every detail, and that stays the backstop. But a 502
        # does not NEED the upstream text: the exception type and the upstream status diagnose
        # it, and neither can carry a credential. **A redactor is a floor; not forwarding the
        # text is a ceiling**, and this is a site where the ceiling costs nothing.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        suffix = f" (upstream {status})" if status is not None else ""
        raise HTTPException(
            status_code=502,
            detail=f"Calendar fetch failed: {type(exc).__name__}{suffix}",
        ) from exc
