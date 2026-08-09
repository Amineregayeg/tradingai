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


@router.post("/start")
async def engine_start(request: Request, user_id: CurrentUser) -> dict:
    """Open a new run and begin scanning.

    There is nothing to configure. The engine's settings live in
    `services/live/fixed_config.py` and are the same for every run, which is what
    makes two runs comparable at all. Pressing this twice is harmless — the
    second press finds the engine already running and changes nothing, rather
    than quietly abandoning the first run for a second one.
    """
    return await _loop(request).start()


@router.post("/stop")
async def engine_stop(request: Request, user_id: CurrentUser) -> dict:
    """Stop scanning and end the run.

    Open positions are closed at the current price first, so the run has no
    trade left unresolved — a stopped engine marks no prices, and a position
    whose stop-loss will never be checked again is not "still open", it is
    abandoned. Nothing is deleted: the run keeps its trades and decisions and
    stays in the history.
    """
    return await _loop(request).stop()


@router.post("/pause")
async def engine_pause(request: Request, user_id: CurrentUser) -> dict:
    """Stop taking new setups. The run stays open and open positions are still
    managed — this is the control for stepping away, not for finishing."""
    loop = _loop(request)
    if not loop._running:  # noqa: SLF001
        raise HTTPException(
            status_code=409,
            detail="The engine is stopped. Pause suspends a running engine; "
                   "press Start to begin a run.",
        )
    loop.paused = True
    await loop._act("engine", "Engine PAUSED — no new entries (open positions still managed)")
    return await loop.status()


@router.post("/resume")
async def engine_resume(request: Request, user_id: CurrentUser) -> dict:
    loop = _loop(request)
    if not loop._running:  # noqa: SLF001
        raise HTTPException(
            status_code=409,
            detail="The engine is stopped. Press Start to begin a new run.",
        )
    loop.paused = False
    await loop._act("engine", "Engine RESUMED — taking new setups")
    return await loop.status()


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
        from app.db.enums import OutcomeType

        agg = (
            await db.execute(
                select(
                    func.count(Trade.id),
                    func.coalesce(func.sum(Trade.pnl_dollars), 0),
                    func.count(Trade.id).filter(Trade.outcome == OutcomeType.WIN),
                )
                .where(
                    Trade.run_id == r.id,
                    Trade.status == TradeStatus.CLOSED,
                    Trade.setup_tag.is_distinct_from(SETUP_TAG_REPLAY),
                )
            )
        ).one()

        # How many decisions the engine made in this run, and how many it
        # DECLINED. A run with 4 trades and 300 abstentions was evaluated 304
        # times; one with 4 trades and 4 abstentions barely ran at all. Trade
        # count alone cannot distinguish those, and they mean very different
        # things about a result.
        from app.models.decision_record import DecisionRecord

        decisions = (
            await db.execute(
                select(
                    func.count(DecisionRecord.id),
                    func.count(DecisionRecord.id).filter(DecisionRecord.abstained.is_(True)),
                ).where(DecisionRecord.run_id == r.id)
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
            "wins": int(agg[2] or 0),
            "decisions": int(decisions[0] or 0),
            "abstentions": int(decisions[1] or 0),
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


@router.get("/shadow")
async def engine_shadow(user_id: CurrentUser, db: DBSession, limit: int = 50) -> dict:
    """M9 Stage A — what the CONTRACT engine made of the same bars.

    This is the answer to "is the platform running Salim's strategy yet". It is
    not, and this endpoint is how you watch the distance close: every record here
    was produced by the rule layer on live data and acted on by nobody.

    `blocked` is the part worth reading first. It counts, per rule, how often a
    rule that IS implemented could not be evaluated — today that is the whole
    roster layer, because the correlate panels are not wired. A rule appearing
    there is not a bug in the rule; it is a dependency that has not been built,
    counted from production rather than estimated.
    """
    from collections import Counter

    from app.models.telemetry_record import TelemetryRecord

    rows = (
        await db.execute(
            select(TelemetryRecord)
            .where(TelemetryRecord.record_type == "setup_evaluation")
            .order_by(TelemetryRecord.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    decisions: Counter[str] = Counter()
    deciders: Counter[str] = Counter()
    blocked: Counter[str] = Counter()
    evaluated: Counter[str] = Counter()

    recent: list[dict] = []
    for row in rows:
        payload = row.payload or {}
        decisions[str(payload.get("decision", "?"))] += 1
        deciders[str(payload.get("deciding_rule_id", "?"))] += 1
        for ev in payload.get("rule_evaluations", []):
            rule_id = str(ev.get("rule_id"))
            if ev.get("verdict") == "NOT_APPLICABLE":
                blocked[rule_id] += 1
            else:
                evaluated[rule_id] += 1
        recent.append({
            "id": payload.get("evaluation_id"),
            "at": payload.get("timestamp_ny"),
            "symbol": (payload.get("instrument") or {}).get("symbol"),
            "signal_tf": (payload.get("timeframes") or {}).get("signal_tf"),
            "decision": payload.get("decision"),
            "deciding_rule_id": payload.get("deciding_rule_id"),
            "block_reason": payload.get("block_reason"),
            "why": payload.get("notes"),
            "flags": payload.get("flags", []),
            "decision_path": payload.get("decision_path", []),
            "primitive_counts": {
                k: len(v) for k, v in (payload.get("primitives") or {}).items()
            },
        })

    return {
        # Stated on the response so no caller can mistake this for live behaviour.
        "stage": "M9 Stage A — shadow. These decisions were recorded and acted on by nobody.",
        "n": len(rows),
        "decisions": dict(decisions),
        "deciding_rules": dict(deciders),
        "rules_evaluated": dict(evaluated),
        "rules_blocked": dict(blocked),
        "recent": recent,
    }
