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

    # Reconcile after reconnect
    adapter = broker_manager.get_adapter_by_connection_id(connection_id)
    if adapter:
        try:
            await reconcile_positions(adapter=adapter, db=db, user_id=user_id)
        except Exception as exc:
            logger.warning("Reconciliation after reconnect failed", error=str(exc))

    return BrokerConnectionRead.model_validate(updated_conn)
