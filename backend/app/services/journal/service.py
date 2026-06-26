"""Trade journal service — query, filter, update and export trade records."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import logger
from app.db.enums import OutcomeType, TradeStatus
from app.models.trade import Trade


async def get_trades(
    db: AsyncSession,
    user_id: str,
    *,
    pair: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    outcome: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[Trade], int]:
    """Return a paginated list of trades and the total matching count.

    Args:
        db: Async database session.
        user_id: Owning user ID.
        pair: Optional instrument filter (e.g. ``"EUR/USD"``).
        from_dt: Filter trades opened on or after this datetime.
        to_dt: Filter trades opened on or before this datetime.
        outcome: Filter by OutcomeType value (e.g. ``"WIN"``).
        page: 1-based page number.
        per_page: Results per page (capped at 200).

    Returns:
        Tuple of ``(trades, total_count)``.
    """
    per_page = min(per_page, 200)
    offset = (page - 1) * per_page

    base_stmt = select(Trade).where(Trade.user_id == user_id)

    if pair:
        base_stmt = base_stmt.where(Trade.pair == pair)
    if from_dt:
        base_stmt = base_stmt.where(Trade.entry_time >= from_dt)
    if to_dt:
        base_stmt = base_stmt.where(Trade.entry_time <= to_dt)
    if outcome:
        try:
            outcome_enum = OutcomeType(outcome.upper())
            base_stmt = base_stmt.where(Trade.outcome == outcome_enum)
        except ValueError:
            logger.warning("Invalid outcome filter value", value=outcome)

    # Total count
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    # Paginated results, newest first
    list_stmt = (
        base_stmt.order_by(Trade.entry_time.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(list_stmt)
    trades = list(result.scalars().all())

    return trades, total


async def get_trade_detail(
    db: AsyncSession,
    user_id: str,
    trade_id: uuid.UUID,
) -> Trade | None:
    """Load a single trade with all related entities eagerly loaded.

    Loads: screenshots → analyses, alerts (via trade's alert relationship
    resolved through orders), edit_diffs.
    """
    stmt = (
        select(Trade)
        .where(Trade.id == trade_id, Trade.user_id == user_id)
        .options(
            selectinload(Trade.screenshots),
            selectinload(Trade.orders),
            selectinload(Trade.checklists),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_trade_notes(
    db: AsyncSession,
    user_id: str,
    trade_id: uuid.UUID,
    notes: str | None,
    setup_tag: str | None,
) -> Trade | None:
    """Update notes and setup_tag on a trade.

    Returns the updated Trade, or None if not found.
    """
    stmt = select(Trade).where(Trade.id == trade_id, Trade.user_id == user_id)
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()

    if trade is None:
        return None

    if notes is not None:
        trade.notes = notes
    if setup_tag is not None:
        trade.setup_tag = setup_tag

    db.add(trade)
    await db.commit()
    await db.refresh(trade)
    logger.info("Trade notes updated", trade_id=str(trade_id))
    return trade


async def close_trade_from_broker(
    db: AsyncSession,
    user_id: str,
    broker_id: str,
    broker: str,
    exit_price: float,
    exit_time: datetime,
    pnl_dollars: float,
    pnl_pips: float,
) -> Trade | None:
    """Called when the broker reports a position has closed.

    Finds an open trade by ``broker_id`` + ``broker``, updates exit fields,
    and marks it CLOSED.  Returns the updated Trade or None if not found.
    """
    stmt = select(Trade).where(
        Trade.user_id == user_id,
        Trade.broker_id == broker_id,
        Trade.broker == broker,
        Trade.status == TradeStatus.OPEN,
    )
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()

    if trade is None:
        logger.warning(
            "close_trade_from_broker: open trade not found",
            broker_id=broker_id,
            broker=broker,
        )
        return None

    pnl = Decimal(str(pnl_dollars))
    trade.exit_price = Decimal(str(exit_price))
    trade.exit_time = exit_time if exit_time.tzinfo else exit_time.replace(tzinfo=timezone.utc)
    trade.pnl_dollars = pnl
    trade.pnl_pips = Decimal(str(pnl_pips))
    trade.status = TradeStatus.CLOSED

    if pnl > 0:
        trade.outcome = OutcomeType.WIN
    elif pnl < 0:
        trade.outcome = OutcomeType.LOSS
    else:
        trade.outcome = OutcomeType.BE

    db.add(trade)
    await db.commit()
    await db.refresh(trade)

    logger.info(
        "Trade closed from broker event",
        trade_id=str(trade.id),
        broker_id=broker_id,
        pnl_dollars=str(pnl),
        outcome=trade.outcome.value,
    )
    return trade


async def export_trades_csv(
    db: AsyncSession,
    user_id: str,
    from_dt: datetime | None,
    to_dt: datetime | None,
) -> str:
    """Export trades as a CSV string.

    Filters by ``entry_time`` within [from_dt, to_dt] if provided.

    Returns:
        A UTF-8 CSV string with a header row followed by one row per trade.
    """
    stmt = select(Trade).where(Trade.user_id == user_id)
    if from_dt:
        stmt = stmt.where(Trade.entry_time >= from_dt)
    if to_dt:
        stmt = stmt.where(Trade.entry_time <= to_dt)
    stmt = stmt.order_by(Trade.entry_time.asc())

    result = await db.execute(stmt)
    trades = list(result.scalars().all())

    fieldnames = [
        "id",
        "broker_id",
        "broker",
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
        "status",
        "pnl_dollars",
        "pnl_pips",
        "session",
        "setup_tag",
        "notes",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for trade in trades:
        writer.writerow(
            {
                "id": str(trade.id),
                "broker_id": trade.broker_id,
                "broker": trade.broker,
                "pair": trade.pair,
                "direction": trade.direction.value,
                "entry_price": str(trade.entry_price),
                "exit_price": str(trade.exit_price) if trade.exit_price is not None else "",
                "sl": str(trade.sl) if trade.sl is not None else "",
                "tp": str(trade.tp) if trade.tp is not None else "",
                "lot_size": str(trade.lot_size),
                "entry_time": trade.entry_time.isoformat() if trade.entry_time else "",
                "exit_time": trade.exit_time.isoformat() if trade.exit_time else "",
                "r_multiple": str(trade.r_multiple) if trade.r_multiple is not None else "",
                "outcome": trade.outcome.value,
                "status": trade.status.value,
                "pnl_dollars": str(trade.pnl_dollars) if trade.pnl_dollars is not None else "",
                "pnl_pips": str(trade.pnl_pips) if trade.pnl_pips is not None else "",
                "session": trade.session or "",
                "setup_tag": trade.setup_tag or "",
                "notes": trade.notes or "",
            }
        )

    return output.getvalue()
