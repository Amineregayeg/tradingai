"""Live engine monitoring + control — status, metrics, pause/resume,
plus the decision log and the feedback-loop (expected-vs-actual → corrections)."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession

router = APIRouter(prefix="/engine", tags=["engine"])


def _loop(request: Request):
    loop = getattr(request.app.state, "live_loop", None)
    if loop is None:
        raise HTTPException(status_code=503, detail="live engine not running")
    return loop


def _num(x):
    """JSON-safe number (Decimal -> float), preserving None."""
    return float(x) if x is not None else None


def _serialize_decision(r) -> dict:
    """DecisionRecord -> JSON-safe dict. The keys match what feedback.analyze
    reads, so the same dict feeds both the decision log and the feedback loop."""
    return {
        "id": str(r.id),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "symbol": r.symbol,
        "timeframe": r.timeframe,
        "inputs_hash": r.inputs_hash,
        "code_path_hash": r.code_path_hash,
        "score": _num(r.score),
        "abstained": bool(r.abstained),
        "reasons": r.reasons,
        "signal_dir": r.signal_dir,
        "signal_entry": _num(r.signal_entry),
        "signal_sl": _num(r.signal_sl),
        "signal_tp": _num(r.signal_tp),
        "sized_units": _num(r.sized_units),
        "expected_r": _num(r.expected_r),
        "realized_r": _num(r.realized_r),
        "gap_r": _num(r.gap_r),
        "outcome": r.outcome,
        "cohort": r.cohort,
    }


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


@router.get("/sim")
async def engine_sim(request: Request, user_id: CurrentUser) -> dict:
    """Prop-firm challenge state (balance, day P&L, drawdown, profit target,
    halted/passed/failed) when the engine runs the SimPropFirmBroker. Returns
    {"enabled": False} in plain paper mode."""
    loop = _loop(request)
    state = loop.sim_state()
    if state is None:
        return {"enabled": False, "mode": loop.mode}
    return {"enabled": True, "mode": loop.mode, **state}


@router.get("/decisions")
async def engine_decisions(
    request: Request, user_id: CurrentUser, db: DBSession, limit: int = 50
) -> list[dict]:
    """The decision log — one row per taken signal, with its expected vs realized
    R and outcome once closed. This is what makes the engine's reasoning visible."""
    from app.models.decision_record import DecisionRecord

    limit = max(1, min(limit, 500))
    rows = (
        await db.execute(
            select(DecisionRecord).order_by(DecisionRecord.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [_serialize_decision(r) for r in rows]


@router.get("/feedback")
async def engine_feedback(
    request: Request, user_id: CurrentUser, db: DBSession, min_evidence: int = 30
) -> dict:
    """Run the feedback loop: expected-vs-actual across closed decisions, the
    structured gaps, and bounded correction proposals (never touching risk_pct).
    Abstains when there is too little evidence to correct confidently."""
    from app.models.decision_record import DecisionRecord
    from app.services.evaluation.feedback import analyze

    rows = (
        await db.execute(
            select(DecisionRecord).order_by(DecisionRecord.created_at.desc()).limit(2000)
        )
    ).scalars().all()
    records = [_serialize_decision(r) for r in rows]

    loop = getattr(request.app.state, "live_loop", None)
    params = {"risk_pct": getattr(loop, "risk_pct", 0.01)}
    result = analyze(records, params, min_evidence=min_evidence)
    result["corrections"] = [
        asdict(c) if is_dataclass(c) else c for c in result.get("corrections", [])
    ]
    return result
