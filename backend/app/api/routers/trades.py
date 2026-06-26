"""Trade history endpoints."""
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.db.enums import OutcomeType, TradeStatus
from app.models.alert import Alert
from app.models.edit_diff import EditDiff
from app.models.trade import Trade
from app.schemas.trade import TradeDetailRead, TradeRead, TradeUpdate

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=list[TradeRead])
async def list_trades(
    db: DBSession,
    user_id: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    pair: str | None = Query(default=None),
    status: TradeStatus | None = Query(default=None),
    outcome: OutcomeType | None = Query(default=None),
    from_dt: datetime | None = Query(default=None),
    to_dt: datetime | None = Query(default=None),
) -> list[TradeRead]:
    """Return paginated trade history with optional filters."""
    stmt = select(Trade).where(Trade.user_id == user_id)

    if pair:
        stmt = stmt.where(Trade.pair == pair)
    if status:
        stmt = stmt.where(Trade.status == status)
    if outcome:
        stmt = stmt.where(Trade.outcome == outcome)
    if from_dt:
        stmt = stmt.where(Trade.entry_time >= from_dt)
    if to_dt:
        stmt = stmt.where(Trade.entry_time <= to_dt)

    stmt = (
        stmt.order_by(Trade.entry_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{trade_id}", response_model=TradeDetailRead)
async def get_trade(
    trade_id: uuid.UUID,
    db: DBSession,
    user_id: CurrentUser,
) -> TradeDetailRead:
    """Return a single trade with full detail (screenshots, orders, alerts, edit_diffs)."""
    stmt = (
        select(Trade)
        .where(Trade.id == trade_id, Trade.user_id == user_id)
        .options(
            selectinload(Trade.screenshots),
            selectinload(Trade.orders),
        )
    )
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()

    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    # Load related alerts via orders (orders link to alerts via alert_id)
    from app.models.order import Order

    order_ids = [o.id for o in trade.orders]
    alerts: list[Alert] = []
    edit_diffs: list[EditDiff] = []

    if order_ids:
        # Fetch alerts referenced by this trade's orders
        alert_ids_stmt = select(Order.alert_id).where(
            Order.trade_id == trade_id,
            Order.alert_id.is_not(None),
        )
        alert_ids_result = await db.execute(alert_ids_stmt)
        alert_ids = [row[0] for row in alert_ids_result.fetchall() if row[0] is not None]

        if alert_ids:
            alerts_stmt = (
                select(Alert)
                .where(Alert.id.in_(alert_ids), Alert.user_id == user_id)
                .options(selectinload(Alert.edit_diffs))
            )
            alerts_result = await db.execute(alerts_stmt)
            alerts = list(alerts_result.scalars().all())

            for alert in alerts:
                edit_diffs.extend(alert.edit_diffs)

    # Build response — combine ORM object with extra related data
    trade_dict = TradeRead.model_validate(trade).model_dump()
    from app.schemas.alert import AlertRead, EditDiffRead
    from app.schemas.screenshot import ScreenshotRead

    return TradeDetailRead(
        **trade_dict,
        screenshots=[ScreenshotRead.model_validate(s) for s in trade.screenshots],
        analyses=[],  # AI analyses loaded separately if needed
        alerts=[AlertRead.model_validate(a) for a in alerts],
        edit_diffs=[EditDiffRead.model_validate(d) for d in edit_diffs],
    )


@router.patch("/{trade_id}", response_model=TradeRead)
async def update_trade(
    trade_id: uuid.UUID,
    payload: TradeUpdate,
    db: DBSession,
    user_id: CurrentUser,
) -> TradeRead:
    """Update editable trade fields (notes, setup_tag, SL, TP, etc.)."""
    stmt = select(Trade).where(Trade.id == trade_id, Trade.user_id == user_id)
    result = await db.execute(stmt)
    trade = result.scalar_one_or_none()

    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    update_data = payload.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(trade, field, value)

    db.add(trade)
    await db.flush()
    await db.refresh(trade)
    return TradeRead.model_validate(trade)
