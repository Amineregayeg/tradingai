"""Live engine monitoring + control — status, metrics, pause/resume."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import CurrentUser

router = APIRouter(prefix="/engine", tags=["engine"])


def _loop(request: Request):
    loop = getattr(request.app.state, "live_loop", None)
    if loop is None:
        raise HTTPException(status_code=503, detail="live engine not running")
    return loop


@router.get("/status")
async def engine_status(request: Request, user_id: CurrentUser) -> dict:
    """Engine status + metrics (balance, equity, win rate, trades, activity)."""
    return await _loop(request).status()


@router.post("/pause")
async def engine_pause(request: Request, user_id: CurrentUser) -> dict:
    loop = _loop(request)
    loop.paused = True
    await loop._act("engine", "Engine PAUSED — no new entries (open positions still managed)")
    return await loop.status()


@router.post("/resume")
async def engine_resume(request: Request, user_id: CurrentUser) -> dict:
    loop = _loop(request)
    loop.paused = False
    await loop._act("engine", "Engine RESUMED — taking new setups")
    return await loop.status()


@router.post("/warmup")
async def engine_warmup(request: Request, user_id: CurrentUser, days: int = 14) -> dict:
    """Backfill the paper account with the strategy's real recent trades."""
    return await _loop(request).warmup(days)
