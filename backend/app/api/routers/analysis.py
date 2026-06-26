"""AI analysis endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.exceptions import AIUnavailable
from app.models.ai_analysis import AIAnalysis
from app.models.screenshot import Screenshot
from app.schemas.analysis import AnalysisRead, AnalysisRunRequest
from app.services.ai.service import ai_service

router = APIRouter(prefix="/analysis", tags=["analysis"])


# ---------------------------------------------------------------------------
# Background task helper
# ---------------------------------------------------------------------------

async def _run_analysis_task(
    screenshot_id: str,
    image_path: str,
    trade_context: dict,
    user_id: str,
) -> None:
    """Background task wrapper that creates its own DB session."""
    from app.db.session import get_session  # noqa: PLC0415

    async for db in get_session():
        try:
            await ai_service.analyze_screenshot(
                db=db,
                user_id=user_id,
                screenshot_id=screenshot_id,
                image_path=image_path,
                trade_context=trade_context,
            )
        except Exception as exc:
            from app.core.logging import logger  # noqa: PLC0415
            logger.error(
                "Background AI analysis failed",
                user_id=user_id,
                screenshot_id=screenshot_id,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/run", status_code=202)
async def run_analysis(
    payload: AnalysisRunRequest,
    background_tasks: BackgroundTasks,
    db: DBSession,
    user_id: CurrentUser,
) -> dict:
    """Enqueue an AI analysis for *screenshot_id* as a background task.

    Returns a 202 Accepted response with the screenshot ID immediately.
    The analysis result can be retrieved via ``GET /api/analysis/{analysis_id}``
    once processing is complete.

    Raises:
        503 if the AI subsystem is currently unavailable.
        404 if the screenshot does not exist.
    """
    # Check AI availability
    available, reason = await ai_service.is_available(db, user_id)
    if not available:
        raise HTTPException(
            status_code=503,
            detail=f"AI unavailable: {reason}",
        )

    # Load screenshot to get image_path
    stmt = select(Screenshot).where(
        Screenshot.id == payload.screenshot_id,
        Screenshot.user_id == user_id,
    )
    result = await db.execute(stmt)
    screenshot = result.scalar_one_or_none()

    if screenshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"Screenshot {payload.screenshot_id} not found",
        )

    trade_context: dict = dict(payload.trade_context or {})
    trade_context.setdefault("pair", screenshot.pair)
    trade_context.setdefault("timeframe", screenshot.timeframe)

    background_tasks.add_task(
        _run_analysis_task,
        screenshot_id=str(payload.screenshot_id),
        image_path=screenshot.image_path,
        trade_context=trade_context,
        user_id=user_id,
    )

    return {
        "status": "accepted",
        "screenshot_id": str(payload.screenshot_id),
        "message": "AI analysis enqueued — poll GET /api/analysis/{analysis_id} for results.",
    }


@router.get("", response_model=list[AnalysisRead])
async def list_analyses(
    db: DBSession,
    user_id: CurrentUser,
    screenshot_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> list[AnalysisRead]:
    """List AI analyses, optionally filtered by *screenshot_id*."""
    stmt = (
        select(AIAnalysis)
        .where(AIAnalysis.user_id == user_id)
        .order_by(AIAnalysis.created_at.desc())
    )

    if screenshot_id is not None:
        stmt = stmt.where(AIAnalysis.screenshot_id == screenshot_id)

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)

    result = await db.execute(stmt)
    analyses = result.scalars().all()
    return [AnalysisRead.model_validate(a) for a in analyses]


@router.get("/{analysis_id}", response_model=AnalysisRead)
async def get_analysis(
    analysis_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> AnalysisRead:
    """Return a single AI analysis result by ID."""
    stmt = select(AIAnalysis).where(
        AIAnalysis.id == analysis_id,
        AIAnalysis.user_id == user_id,
    )
    result = await db.execute(stmt)
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail=f"Analysis {analysis_id} not found",
        )

    return AnalysisRead.model_validate(analysis)
