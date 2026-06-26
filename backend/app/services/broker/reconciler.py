"""Position reconciler — keeps local trade state in sync with broker live state."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.enums import OutcomeType, TradeStatus
from app.models.trade import Trade
from app.services.broker.base import BrokerAdapter


async def reconcile_positions(
    adapter: BrokerAdapter,
    db: AsyncSession,
    user_id: str,
) -> None:
    """Compare open trades in DB with live positions from broker.

    - Positions present in the broker but absent from the DB: log a warning
      (trade was opened outside the app).
    - Trades marked OPEN in DB that no longer appear in broker positions:
      mark as CLOSED and compute PnL where possible.
    """
    logger.info(
        "Starting position reconciliation",
        broker=adapter.broker_name,
        user_id=user_id,
    )

    # Fetch live positions
    try:
        live_positions = await adapter.get_positions()
    except Exception as exc:
        logger.error(
            "Reconciliation aborted — could not fetch live positions",
            broker=adapter.broker_name,
            error=str(exc),
        )
        return

    # Fetch recent closed trades from broker (to get exit prices)
    try:
        recent_trades = await adapter.get_recent_trades()
    except Exception as exc:
        logger.warning("Could not fetch recent trades from broker", error=str(exc))
        recent_trades = []

    # Build lookup: broker_id → closed trade info
    broker_closed: dict[str, dict] = {}
    for bt in recent_trades:
        bid = bt.get("id")
        if bid:
            broker_closed[str(bid)] = bt

    # Build set of instrument / position IDs that are live
    live_pairs = {pos.pair for pos in live_positions}
    live_position_ids = {pos.id for pos in live_positions}

    # ------------------------------------------------------------------
    # 1. Load all OPEN trades from DB for this user + broker
    # ------------------------------------------------------------------
    stmt = select(Trade).where(
        Trade.user_id == user_id,
        Trade.broker == adapter.broker_name,
        Trade.status == TradeStatus.OPEN,
    )
    result = await db.execute(stmt)
    open_db_trades = result.scalars().all()

    # Build lookup: broker_id → Trade
    db_by_broker_id: dict[str, Trade] = {t.broker_id: t for t in open_db_trades}

    # ------------------------------------------------------------------
    # 2. Positions in broker but not in DB → external trades
    # ------------------------------------------------------------------
    for pos in live_positions:
        if pos.id not in db_by_broker_id and pos.pair not in {
            t.pair for t in open_db_trades
        }:
            logger.warning(
                "Live position not tracked in DB — opened outside app",
                broker=adapter.broker_name,
                pair=pos.pair,
                position_id=pos.id,
                direction=pos.direction.value,
                lot_size=str(pos.lot_size),
            )

    # ------------------------------------------------------------------
    # 3. DB trades OPEN but not in live positions → mark as CLOSED
    # ------------------------------------------------------------------
    for broker_id, trade in db_by_broker_id.items():
        # Check if the trade's pair / position_id still appears in live positions
        still_live = (
            broker_id in live_position_ids
            or trade.pair in live_pairs
        )

        if not still_live:
            # Try to get exit data from broker closed trades
            closed_info = broker_closed.get(broker_id, {})
            exit_price_str = closed_info.get("close_price")
            exit_time_str = closed_info.get("close_time")
            realized_pl_str = closed_info.get("realized_pl")

            exit_price: Decimal | None = None
            if exit_price_str:
                try:
                    exit_price = Decimal(str(exit_price_str))
                except Exception:
                    pass

            exit_time: datetime | None = None
            if exit_time_str:
                try:
                    exit_time = datetime.fromisoformat(
                        str(exit_time_str).replace("Z", "+00:00")
                    )
                except Exception:
                    pass

            pnl_dollars: Decimal | None = None
            if realized_pl_str is not None:
                try:
                    pnl_dollars = Decimal(str(realized_pl_str))
                except Exception:
                    pass

            # Determine outcome
            outcome = OutcomeType.BE
            if pnl_dollars is not None:
                if pnl_dollars > 0:
                    outcome = OutcomeType.WIN
                elif pnl_dollars < 0:
                    outcome = OutcomeType.LOSS

            trade.status = TradeStatus.CLOSED
            trade.outcome = outcome
            if exit_price is not None:
                trade.exit_price = exit_price
            if exit_time is not None:
                trade.exit_time = exit_time
            else:
                trade.exit_time = datetime.now(tz=timezone.utc)
            if pnl_dollars is not None:
                trade.pnl_dollars = pnl_dollars

            db.add(trade)
            logger.info(
                "Trade auto-closed by reconciler",
                trade_id=str(trade.id),
                broker_id=broker_id,
                pair=trade.pair,
                pnl_dollars=str(pnl_dollars) if pnl_dollars else "unknown",
                outcome=outcome.value,
            )

    await db.commit()
    logger.info(
        "Position reconciliation complete",
        broker=adapter.broker_name,
        live_count=len(live_positions),
        db_open_count=len(open_db_trades),
    )
