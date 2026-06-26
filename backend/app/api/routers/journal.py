"""Trading journal endpoints (notes, checklists, tagging, CSV export)."""
import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.logging import logger
from app.db.enums import TradeStatus
from app.models.trade import Trade
from app.schemas.trade import TradeRead, TradeUpdate

router = APIRouter(prefix="/journal", tags=["journal"])


@router.get("", response_model=list[TradeRead])
async def list_journal_entries(
    db: DBSession,
    user_id: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    setup_tag: str | None = Query(default=None),
) -> list[TradeRead]:
    """Return journal entries (closed trades with notes/tags)."""
    stmt = select(Trade).where(
        Trade.user_id == user_id,
        Trade.status == TradeStatus.CLOSED,
    )

    if setup_tag:
        stmt = stmt.where(Trade.setup_tag == setup_tag)

    stmt = (
        stmt.order_by(Trade.entry_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.patch("/{trade_id}/notes", response_model=TradeRead)
async def update_trade_notes(
    trade_id: uuid.UUID,
    payload: TradeUpdate,
    db: DBSession,
    user_id: CurrentUser,
) -> TradeRead:
    """Update the notes and setup_tag for a trade."""
    stmt = select(Trade).where(Trade.id == trade_id, Trade.user_id == user_id)
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()

    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Only update notes-related fields
    notes_fields = {"notes", "setup_tag"}
    update_data = {
        k: v
        for k, v in payload.model_dump(exclude_none=True).items()
        if k in notes_fields
    }
    for field, value in update_data.items():
        setattr(trade, field, value)

    db.add(trade)
    await db.flush()
    await db.refresh(trade)
    return TradeRead.model_validate(trade)


@router.get("/export")
async def export_trades_csv(
    db: DBSession,
    user_id: CurrentUser,
    from_dt: datetime | None = Query(default=None),
    to_dt: datetime | None = Query(default=None),
) -> StreamingResponse:
    """Export trades as CSV. Columns: id, pair, direction, entry_price, exit_price,
    sl, tp, lot_size, entry_time, exit_time, r_multiple, outcome, session,
    pnl_dollars, pnl_pips, notes, setup_tag.
    """
    stmt = select(Trade).where(Trade.user_id == user_id)

    if from_dt:
        stmt = stmt.where(Trade.entry_time >= from_dt)
    if to_dt:
        stmt = stmt.where(Trade.entry_time <= to_dt)

    stmt = stmt.order_by(Trade.entry_time.desc())

    result = await db.execute(stmt)
    trades = result.scalars().all()

    logger.info("Exporting trades to CSV", user_id=user_id, count=len(trades))

    output = io.StringIO()
    fieldnames = [
        "id",
        "pair",
        "direction",
        "entry_price",
        "exit_price",
        "sl",
        "tp",
        "lot_size",
        "entry_time",
        "exit_time",
        "r_multiple",
        "outcome",
        "session",
        "pnl_dollars",
        "pnl_pips",
        "notes",
        "setup_tag",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()

    for trade in trades:
        writer.writerow({
            "id": str(trade.id),
            "pair": trade.pair,
            "direction": trade.direction.value if trade.direction else "",
            "entry_price": str(trade.entry_price),
            "exit_price": str(trade.exit_price) if trade.exit_price is not None else "",
            "sl": str(trade.sl) if trade.sl is not None else "",
            "tp": str(trade.tp) if trade.tp is not None else "",
            "lot_size": str(trade.lot_size),
            "entry_time": trade.entry_time.isoformat() if trade.entry_time else "",
            "exit_time": trade.exit_time.isoformat() if trade.exit_time else "",
            "r_multiple": str(trade.r_multiple) if trade.r_multiple is not None else "",
            "outcome": trade.outcome.value if trade.outcome else "",
            "session": trade.session or "",
            "pnl_dollars": str(trade.pnl_dollars) if trade.pnl_dollars is not None else "",
            "pnl_pips": str(trade.pnl_pips) if trade.pnl_pips is not None else "",
            "notes": trade.notes or "",
            "setup_tag": trade.setup_tag or "",
        })

    csv_content = output.getvalue()
    output.close()

    filename = f"trades_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
