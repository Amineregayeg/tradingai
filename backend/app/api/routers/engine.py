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
        # feedback._slippage_r() reads "fill_price" and, until this column
        # existed, found nothing on every row — which is why Rule B (adverse
        # fill slippage -> min_fvg_atr) has never once fired.
        "fill_price": _num(r.fill_price),
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


@router.post("/reset")
async def engine_reset(
    request: Request, user_id: CurrentUser,
    note: str | None = None, label: str | None = None,
) -> dict:
    """End the current run and start a clean one.

    NOTHING IS DELETED. The previous run's trades and decision records remain,
    still queryable by their run_id — they are the evidence of what the strategy
    did, and a reset that destroyed them would undo the reason backups exist.
    The slate is clean because metrics are scoped to the new run.

    Until this existed, starting a clean run meant an SSH session and a
    container restart, which meant in practice that runs were never restarted
    and results accumulated across configuration changes.
    """
    loop = _loop(request)
    return await loop.reset_run(note=note, label=label)


@router.get("/runs")
async def engine_runs(request: Request, user_id: CurrentUser, db: DBSession) -> list[dict]:
    """Past and present runs, newest first, with each one's result.

    Results are computed from the trades actually stamped with each run_id
    rather than stored at reset time, so they cannot drift from the underlying
    rows.
    """
    from sqlalchemy import func, select

    from app.db.enums import TradeStatus
    from app.models.engine_run import EngineRun
    from app.models.trade import SETUP_TAG_REPLAY, Trade

    runs = (
        await db.execute(select(EngineRun).order_by(EngineRun.started_at.desc()).limit(50))
    ).scalars().all()

    out: list[dict] = []
    active_id = getattr(_loop(request), "run_id", None)
    for r in runs:
        agg = (
            await db.execute(
                select(func.count(Trade.id), func.coalesce(func.sum(Trade.pnl_dollars), 0))
                .where(
                    Trade.run_id == r.id,
                    Trade.status == TradeStatus.CLOSED,
                    Trade.setup_tag.is_distinct_from(SETUP_TAG_REPLAY),
                )
            )
        ).one()
        out.append({
            "id": str(r.id),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "active": r.ended_at is None and str(r.id) == str(active_id),
            "label": r.label,
            "note": r.note,
            "config": r.config,
            "closed_trades": int(agg[0] or 0),
            "realized_pnl": float(agg[1] or 0),
        })
    return out


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
