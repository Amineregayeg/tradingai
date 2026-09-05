"""Live positions endpoints — proxied from connected broker(s)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Response

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


def _unasked_detail(report: dict, position_id: str | None = None) -> str:
    """The sentence an operator reads when a broker could not be asked (`B372`).

    **The 404 it replaces was affirmatively wrong twice**: the broker IS connected and the position
    IS open. And *"not found in any connected broker"* has an honest reading — *it is already
    closed* — which is the one conclusion that stops someone looking further.
    """
    names = ", ".join(
        f"{u['broker']} ({u['connection_id']}): {u['reason']}" for u in report["unasked"]
    )
    subject = f"Position '{position_id}'" if position_id else "The position list"
    return (
        f"{subject} cannot be resolved: {len(report['unasked'])} of {report['connected']} "
        f"connected broker(s) could not be asked — {names}. This is NOT a statement that the "
        f"position does not exist; it may be open at a broker we could not reach."
    )

@router.get("", response_model=list[Position])
async def list_positions(
    response: Response,
    db: DBSession,
    user_id: CurrentUser,
) -> list[Position]:
    """Return all currently open positions from all connected brokers.

    Returns an empty list when no brokers are connected — never an error.
    """
    try:
        report = await broker_manager.get_all_positions_report()
    except BrokerError as exc:
        logger.warning("Error fetching positions", error=str(exc))
        raise HTTPException(status_code=502, detail=exc.detail) from exc

    # `B372`. THIS 502 HANDLER WAS UNREACHABLE and that is why the collapse survived review: a
    # reader of this file concludes a broker failure surfaces as a 502 — the handler is right
    # there and it is well written — while the layer below swallowed the error and returned `[]`.
    # `B272`'s family: a branch that cannot execute, whose presence is what hides the defect.
    #
    # IT IS NOW REACHABLE, and only in the state where the list would otherwise LIE OUTRIGHT:
    # brokers are connected and NOT ONE could be asked. An empty list then means *we could not
    # look*, not *nothing is open*. A PARTIAL failure still returns 200 with the positions we do
    # have — the contract here is "never an error" and three consumers rest on it, so a partial
    # answer must not become a failure — and the unasked brokers ride on a response header so the
    # fact is available without changing the response model.
    if report["unasked"] and report["asked"] == 0:
        raise HTTPException(status_code=502, detail=_unasked_detail(report))
    if report["unasked"]:
        response.headers["X-Unasked-Brokers"] = ",".join(
            u["broker"] for u in report["unasked"]
        )
    return report["positions"]


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
        report = await broker_manager.get_all_positions_report()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=exc.detail) from exc

    for pos in report["positions"]:
        if pos.id == position_id:
            return pos

    # `B372`. NOT FINDING IT AND NOT HAVING LOOKED ARE DIFFERENT ANSWERS. A 404 asserts the
    # position does not exist; if a broker could not be asked, we do not know that.
    if report["unasked"]:
        raise HTTPException(status_code=502, detail=_unasked_detail(report, position_id))
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
    report = await broker_manager.get_all_positions_report()
    target = next((p for p in report["positions"] if p.id == position_id), None)

    if target is None:
        # `B372`, AND THIS IS THE INSTANCE THAT MATTERS. An operator closing a position by hand
        # was told it does not exist while the broker was connected and the position open — the
        # message was affirmatively wrong twice, and its honest reading is *it is already closed*,
        # which is the one conclusion that stops him looking further. A broker we could not ask
        # cannot support that claim, so this is a different HTTP answer from "no such position".
        if report["unasked"]:
            raise HTTPException(status_code=502, detail=_unasked_detail(report, position_id))
        raise HTTPException(
            status_code=404,
            detail=f"Position '{position_id}' not found in any connected broker",
        )

    # Try each adapter, but treat the RESULT as authoritative — a broker that
    # returns {"status": "not_found"} WITHOUT raising (e.g. PaperBroker) did NOT
    # close the position, so we must not report success. Only a genuine close
    # counts; otherwise we keep trying and finally 502.
    _FAIL_STATUSES = {"not_found", "error", "rejected", "failed"}
    closed = False
    for adapter in broker_manager._adapters.values():
        try:
            result = await adapter.close_position(position_id)
        except BrokerError as exc:
            logger.warning(
                "Adapter raised closing position",
                position_id=position_id,
                broker=adapter.broker_name,
                error=str(exc),
            )
            continue
        status = str((result or {}).get("status", "")).lower()
        if status in _FAIL_STATUSES:
            logger.info(
                "Adapter did not hold position",
                position_id=position_id,
                broker=adapter.broker_name,
                status=status,
            )
            continue
        closed = True
        logger.info("Position closed via API", position_id=position_id,
                    broker=adapter.broker_name, status=status or "closed")
        break

    if not closed:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to close position '{position_id}' on any connected broker",
        )
