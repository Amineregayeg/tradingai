"""Live positions endpoints — proxied from connected broker(s)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import CurrentUser, DBSession
from app.core.exceptions import BrokerError
from app.core.logging import logger
from app.db.enums import DirectionType, OrderType
from app.schemas.broker import Position
from app.services.broker import broker_manager

router = APIRouter(prefix="/positions", tags=["positions"])


@router.post("/demo")
async def seed_demo_position(request: Request, user_id: CurrentUser) -> dict:
    """DEV: open one paper BTC trade via the live loop so the dashboard shows a
    position whose PnL marks-to-market against real Binance price."""
    from app.services.execution.service import Signal
    from app.services.live.crypto_loop import _ticker_price

    loop = getattr(request.app.state, "live_loop", None)
    if loop is None:
        raise HTTPException(status_code=503, detail="live loop not running")
    pair, bsym = "BTC/USD", "BTCUSDT"
    price = await asyncio.to_thread(_ticker_price, bsym)
    if not price:
        raise HTTPException(status_code=502, detail="no live price")
    loop._marks[pair] = price
    sig = Signal(pair, DirectionType.LONG, price, price * 0.99, price * 1.02,
                 0.02, OrderType.MARKET, approved=True)
    res = await loop.execution.execute(sig)
    await loop._push_state()
    return res


@router.get("", response_model=list[Position])
async def list_positions(
    db: DBSession,
    user_id: CurrentUser,
) -> list[Position]:
    """Return all currently open positions from all connected brokers.

    Returns an empty list when no brokers are connected — never an error.
    """
    try:
        positions = await broker_manager.get_all_positions()
    except BrokerError as exc:
        logger.warning("Error fetching positions", error=str(exc))
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    return positions


@router.get("/{position_id}", response_model=Position)
async def get_position(
    position_id: str,
    db: DBSession,
    user_id: CurrentUser,
) -> Position:
    """Return a single live position by broker position ID.

    Searches across all connected adapters.
    """
    try:
        positions = await broker_manager.get_all_positions()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=exc.detail) from exc

    for pos in positions:
        if pos.id == position_id:
            return pos

    raise HTTPException(status_code=404, detail=f"Position '{position_id}' not found")


@router.delete("/{position_id}", status_code=204)
async def close_position(
    position_id: str,
    db: DBSession,
    user_id: CurrentUser,
) -> None:
    """Close (market-exit) a live position by ID.

    Iterates all connected adapters and attempts to close the position.
    """
    # Find which adapter holds this position
    positions = await broker_manager.get_all_positions()
    target = next((p for p in positions if p.id == position_id), None)

    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"Position '{position_id}' not found in any connected broker",
        )

    # Try each adapter until one succeeds
    closed = False
    for adapter in broker_manager._adapters.values():
        try:
            await adapter.close_position(position_id)
            closed = True
            logger.info("Position closed via API", position_id=position_id)
            break
        except BrokerError as exc:
            logger.warning(
                "Adapter could not close position",
                position_id=position_id,
                broker=adapter.broker_name,
                error=str(exc),
            )
            continue

    if not closed:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to close position '{position_id}' on any connected broker",
        )
