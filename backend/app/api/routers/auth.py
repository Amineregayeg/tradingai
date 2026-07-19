"""Auth helper endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core import ws_tickets

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/ws-ticket")
async def create_ws_ticket(user_id: CurrentUser) -> dict:
    """Mint a short-lived, single-use ticket for the WebSocket handshake.

    Requires the bearer token (like every /api route). The returned ticket — NOT
    the master token — goes in the `?ticket=` query param of the /ws URL, so the
    long-lived credential never lands in a URL, access log, or browser history.
    """
    return {"ticket": ws_tickets.mint(), "expires_in": 30}
