"""Broker connection management endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession
from app.core.exceptions import BrokerConnectionError, BrokerError
from app.core.logging import logger
from app.models.broker_connection import BrokerConnection
from app.schemas.broker import BrokerConnectRequest, BrokerConnectionRead
from app.services.broker import broker_manager
from app.services.broker.reconciler import reconcile_positions

router = APIRouter(prefix="/brokers", tags=["brokers"])


@router.get("/accounts")
async def list_broker_accounts(user_id: CurrentUser) -> list[dict]:
    """Live balance / equity / positions for every connected broker.

    This is what makes a connected account *visible*: until now the platform
    could reach CFT but nothing displayed it, so "connected" was a claim with
    nothing behind it.

    Two deliberate properties:

    * An unreachable broker still appears, with ``reachable: false`` and the
      reason. Dropping it would read as "no such account"; showing a cached
      number would be worse still — a stale balance presented as current is the
      class of dishonesty this project exists to have stopped.
    * It never 500s. One broker being down must not blank the panel for the
      others, and a status endpoint that fails when things are failing is
      useless exactly when it is needed.
    """
    return await broker_manager.get_all_accounts()


@router.get("/reconciliation")
async def broker_reconciliation(db: DBSession, user_id: CurrentUser) -> list[dict]:
    """Disagreements between our records and each broker's live state.

    Read-only, and deliberately so: it reports, it does not correct. Making the
    two sides agree by overwriting one of them destroys the evidence that they
    disagreed — the same mistake as an equity curve that looked right because
    nobody checked what it was drawn from.

    An empty `findings` list with `ok: true` means the checks ran and agreed.
    `checks_run` says which actually executed, so "no findings" is never confused
    with "nothing was checked".
    """
    return await broker_manager.reconcile_all(db, user_id)


@router.get("", response_model=list[BrokerConnectionRead])
async def list_broker_connections(
    db: DBSession,
    user_id: CurrentUser,
) -> list[BrokerConnectionRead]:
    """List all broker connections for the current user."""
    stmt = select(BrokerConnection).where(BrokerConnection.user_id == user_id)
    result = await db.execute(stmt)
    connections = result.scalars().all()
    return [BrokerConnectionRead.model_validate(conn) for conn in connections]


@router.post("", response_model=BrokerConnectionRead, status_code=201)
async def create_broker_connection(
    payload: BrokerConnectRequest,
    db: DBSession,
    user_id: CurrentUser,
) -> BrokerConnectionRead:
    """Register and test a new broker connection."""
    try:
        conn = await broker_manager.connect_broker(
            db=db,
            user_id=user_id,
            request=payload,
        )
    except BrokerConnectionError as exc:
        logger.warning(
            "Broker connection failed",
            broker=payload.broker,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Could not connect to broker: {exc.detail}",
        ) from exc
    except BrokerError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except ValueError as exc:
        # Configuration the adapter refuses: an unsupported broker, or an
        # environment a broker does not have (CFT is live-only). These carry a
        # precise, actionable message — "CryptoFundTrader has no 'practice'
        # environment" — but ValueError was uncaught, so it fell through to the
        # generic 500 handler and the user saw "An unexpected error occurred.
        # Please try again later." That is worse than unhelpful: it hides a
        # perfect explanation AND advises retrying, which can never work.
        # 400, because the request is invalid, not the server broken.
        logger.warning("Broker connection rejected", broker=payload.broker, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Run initial reconciliation in background (best-effort)
    adapter = broker_manager.get_adapter_by_connection_id(str(conn.id))
    if adapter:
        try:
            await reconcile_positions(adapter=adapter, db=db, user_id=user_id)
        except Exception as exc:
            logger.warning("Initial reconciliation failed", error=str(exc))

    return BrokerConnectionRead.model_validate(conn)


@router.delete("/{connection_id}", status_code=204)
async def delete_broker_connection(
    connection_id: str,
    db: DBSession,
    user_id: CurrentUser,
) -> None:
    """Disconnect and remove a broker connection."""
    # Verify ownership
    try:
        conn_uuid = uuid.UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid connection_id format")

    stmt = select(BrokerConnection).where(
        BrokerConnection.id == conn_uuid,
        BrokerConnection.user_id == user_id,
    )
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()

    if conn is None:
        raise HTTPException(status_code=404, detail="Broker connection not found")

    await broker_manager.disconnect_broker(db=db, connection_id=connection_id)


@router.post("/{connection_id}/reconnect", response_model=BrokerConnectionRead)
async def reconnect_broker(
    connection_id: str,
    db: DBSession,
    user_id: CurrentUser,
) -> BrokerConnectionRead:
    """Re-establish a disconnected broker connection."""
    try:
        conn_uuid = uuid.UUID(connection_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid connection_id format")

    # Ownership check
    stmt = select(BrokerConnection).where(
        BrokerConnection.id == conn_uuid,
        BrokerConnection.user_id == user_id,
    )
    result = await db.execute(stmt)
    conn = result.scalar_one_or_none()

    if conn is None:
        raise HTTPException(status_code=404, detail="Broker connection not found")

    try:
        updated_conn = await broker_manager.reconnect_broker(
            db=db,
            connection_id=connection_id,
            user_id=user_id,
        )
    except BrokerConnectionError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reconnect to broker: {exc.detail}",
        ) from exc
    except BrokerError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except ValueError as exc:
        # Same reasoning as create_broker_connection. This path matters more than
        # it looks: a connection stored with an environment the adapter no longer
        # accepts can only be rebuilt here, and a bare 500 would give no clue why.
        logger.warning("Broker reconnect rejected", connection_id=connection_id, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Reconcile after reconnect
    adapter = broker_manager.get_adapter_by_connection_id(connection_id)
    if adapter:
        try:
            await reconcile_positions(adapter=adapter, db=db, user_id=user_id)
        except Exception as exc:
            logger.warning("Reconciliation after reconnect failed", error=str(exc))

    return BrokerConnectionRead.model_validate(updated_conn)
