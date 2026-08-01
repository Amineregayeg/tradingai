"""BrokerManager — singleton that owns all live broker adapter instances."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BrokerConnectionError, BrokerError
from app.core.logging import logger
from app.core.security import decrypt_credentials, encrypt_credentials
from app.models.broker_connection import BrokerConnection
from app.schemas.broker import BrokerConnectRequest, BrokerConnectionRead, Position
from app.services.broker.base import BrokerAdapter
from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter

_CFT_ALIASES = {"cryptofundtrader", "cft", "match-trader", "matchtrader"}


def _make_adapter(
    broker: str,
    creds: dict,
    account_id: str,
    environment: str,
) -> BrokerAdapter:
    """Factory: return the correct adapter for *broker*.

    The OANDA branch was removed: this app is crypto-only and OANDA was the only
    unguarded real-money path. Only CryptoFundTrader (crypto prop firm) is
    constructible here, and it is created observe-only unless live trading is
    explicitly enabled server-side.
    """
    key = broker.lower()
    if key in _CFT_ALIASES:
        # Centralised live-trading guard: a stored observe_only=False is honoured
        # ONLY when ALLOW_LIVE_TRADING is set server-side. This runs on EVERY
        # construction path (connect, load_from_db, reconnect), so a persisted
        # live-write connection cannot be silently reconstructed.
        allow_live = os.getenv("ALLOW_LIVE_TRADING", "false").strip().lower() == "true"
        observe_only = creds.get("observe_only", True)
        if observe_only is False and not allow_live:
            logger.warning(
                "Forcing observe_only=True for stored connection — live trading disabled",
                broker=broker,
            )
            observe_only = True
        common = dict(
            email=creds.get("email", ""),
            password=creds.get("password", ""),
            base_url=creds.get("base_url", creds.get("server", "")),
            account_id=account_id,
            environment=environment,
            observe_only=observe_only,
        )

        # CFT sits behind Cloudflare bot protection that fingerprints the TLS
        # handshake, so direct HTTP is refused (403) even with a valid token —
        # see cft_bridge_transport for the measurements. When a bridge is
        # configured, route through it; the two adapters are otherwise identical
        # (CFTBridgeAdapter subclasses this one and swaps only the transport).
        if os.getenv("CFT_BRIDGE_TOKEN"):
            from app.services.broker.cft_bridge_adapter import CFTBridgeAdapter

            logger.info("Using browser bridge for Crypto Fund Trader")
            return CFTBridgeAdapter(**common)

        # No bridge configured: the direct adapter. It will almost certainly be
        # blocked by Cloudflare, but it stays the default so behaviour does not
        # change silently for anyone who has not deployed the bridge, and so the
        # existing adapter tests keep exercising the path they were written for.
        return CryptoFundTraderAdapter(**common)
    raise ValueError(f"Unsupported broker: {broker!r}")


class BrokerManager:
    """Singleton manager that holds live broker adapter instances."""

    def __init__(self) -> None:
        # Maps connection_id (str UUID) → adapter instance
        self._adapters: dict[str, BrokerAdapter] = {}
        self._price_stream_tasks: list[asyncio.Task] = []
        self._price_callback: Callable | None = None

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def load_from_db(self, db: AsyncSession) -> None:
        """Called at startup — load all connected BrokerConnections and init adapters."""
        stmt = select(BrokerConnection).where(BrokerConnection.connected.is_(True))
        result = await db.execute(stmt)
        connections = result.scalars().all()

        logger.info("Loading broker connections from DB", count=len(connections))

        for conn in connections:
            try:
                creds_json = decrypt_credentials(conn.encrypted_creds)
                creds = json.loads(creds_json)
                adapter = _make_adapter(
                    broker=conn.broker,
                    creds=creds,
                    account_id=conn.account_id or "",
                    environment=conn.environment or "practice",
                )
                await adapter.connect()
                self._adapters[str(conn.id)] = adapter
                logger.info(
                    "Broker adapter loaded",
                    broker=conn.broker,
                    connection_id=str(conn.id),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to reconnect broker on startup",
                    connection_id=str(conn.id),
                    broker=conn.broker,
                    error=str(exc),
                )
                # Mark as disconnected in DB
                conn.connected = False
                db.add(conn)

        await db.commit()

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------

    async def connect_broker(
        self,
        db: AsyncSession,
        user_id: str,
        request: BrokerConnectRequest,
    ) -> BrokerConnection:
        """Create or update a BrokerConnection, connect, and return the model.

        Steps:
        1. Encrypt raw credentials and persist to DB (connected=False).
        2. Build and connect the adapter (raises BrokerConnectionError on failure).
        3. On success: mark connected=True and store adapter.
        """
        creds_dict: dict = {
            "api_key": request.api_key,
            "api_secret": request.api_secret or "",
        }
        # Match-Trader / Crypto Fund Trader style credentials (email + password + base URL).
        if request.email:
            creds_dict["email"] = request.email
        if request.password:
            creds_dict["password"] = request.password
        if request.server:
            creds_dict["base_url"] = request.server
        # SAFETY: an explicit observe_only=False from the API would enable
        # real-money trading. Honour it ONLY when live trading is explicitly
        # enabled server-side (env ALLOW_LIVE_TRADING=true, default OFF), which
        # the public API cannot set. Otherwise force observe-only.
        requested_observe = request.observe_only
        allow_live = os.getenv("ALLOW_LIVE_TRADING", "false").strip().lower() == "true"
        if requested_observe is False and not allow_live:
            logger.warning(
                "Ignoring observe_only=False — live trading is disabled server-side "
                "(set ALLOW_LIVE_TRADING=true to enable). Forcing observe-only.",
                broker=request.broker,
            )
            creds_dict["observe_only"] = True
        elif requested_observe is not None:
            creds_dict["observe_only"] = requested_observe
        creds_json = json.dumps(creds_dict)
        encrypted = encrypt_credentials(creds_json)

        # Check for an existing connection for this user + broker + account_id
        stmt = select(BrokerConnection).where(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker == request.broker,
            BrokerConnection.account_id == request.account_id,
        )
        result = await db.execute(stmt)
        conn: BrokerConnection | None = result.scalar_one_or_none()

        if conn is None:
            conn = BrokerConnection(
                user_id=user_id,
                broker=request.broker,
                label=request.label,
                encrypted_creds=encrypted,
                account_id=request.account_id,
                environment=request.environment,
                connected=False,
            )
            db.add(conn)
            await db.flush()  # get the generated ID
        else:
            conn.encrypted_creds = encrypted
            conn.label = request.label or conn.label
            conn.environment = request.environment
            conn.connected = False
            db.add(conn)
            await db.flush()

        # Disconnect existing adapter for this connection if any
        existing = self._adapters.pop(str(conn.id), None)
        if existing:
            try:
                await existing.disconnect()
            except Exception:
                pass

        # Build and connect adapter
        adapter = _make_adapter(
            broker=request.broker,
            creds=creds_dict,
            account_id=request.account_id,
            environment=request.environment,
        )

        try:
            await adapter.connect()
        except BrokerConnectionError:
            await db.commit()
            raise
        except Exception as exc:
            await db.commit()
            raise BrokerConnectionError(
                f"Unexpected error connecting to {request.broker}",
                broker=request.broker,
                detail=str(exc),
            ) from exc

        # Success — update DB
        conn.connected = True
        conn.last_connected_at = datetime.now(tz=timezone.utc)
        db.add(conn)
        await db.commit()

        self._adapters[str(conn.id)] = adapter
        logger.info(
            "Broker connected",
            broker=request.broker,
            connection_id=str(conn.id),
            account_id=request.account_id,
        )
        return conn

    async def disconnect_broker(self, db: AsyncSession, connection_id: str) -> None:
        """Disconnect an adapter and mark the DB row as disconnected."""
        adapter = self._adapters.pop(connection_id, None)
        if adapter:
            try:
                await adapter.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting adapter", connection_id=connection_id, error=str(exc))

        stmt = select(BrokerConnection).where(
            BrokerConnection.id == uuid.UUID(connection_id)
        )
        result = await db.execute(stmt)
        conn = result.scalar_one_or_none()
        if conn:
            conn.connected = False
            db.add(conn)
            await db.commit()

        logger.info("Broker disconnected", connection_id=connection_id)

    async def reconnect_broker(
        self,
        db: AsyncSession,
        connection_id: str,
        user_id: str,
    ) -> BrokerConnection:
        """Re-connect an existing BrokerConnection by its ID."""
        stmt = select(BrokerConnection).where(
            BrokerConnection.id == uuid.UUID(connection_id),
            BrokerConnection.user_id == user_id,
        )
        result = await db.execute(stmt)
        conn = result.scalar_one_or_none()

        if conn is None:
            raise BrokerError(
                f"BrokerConnection {connection_id} not found",
                broker="unknown",
            )

        # Disconnect existing adapter
        existing = self._adapters.pop(connection_id, None)
        if existing:
            try:
                await existing.disconnect()
            except Exception:
                pass

        creds_json = decrypt_credentials(conn.encrypted_creds)
        creds = json.loads(creds_json)

        adapter = _make_adapter(
            broker=conn.broker,
            creds=creds,
            account_id=conn.account_id or "",
            environment=conn.environment or "practice",
        )

        try:
            await adapter.connect()
        except BrokerConnectionError:
            conn.connected = False
            db.add(conn)
            await db.commit()
            raise

        conn.connected = True
        conn.last_connected_at = datetime.now(tz=timezone.utc)
        db.add(conn)
        await db.commit()

        self._adapters[connection_id] = adapter
        logger.info("Broker reconnected", connection_id=connection_id, broker=conn.broker)
        return conn

    # ------------------------------------------------------------------
    # Aggregate operations
    # ------------------------------------------------------------------

    async def get_all_positions(self) -> list[Position]:
        """Aggregate open positions across all connected adapters."""
        all_positions: list[Position] = []
        for connection_id, adapter in self._adapters.items():
            try:
                positions = await adapter.get_positions()
                all_positions.extend(positions)
            except Exception as exc:
                logger.warning(
                    "Failed to fetch positions",
                    connection_id=connection_id,
                    broker=adapter.broker_name,
                    error=str(exc),
                )
        return all_positions

    async def close_all_positions(self) -> list[dict]:
        """Kill switch: close ALL positions across ALL adapters."""
        results: list[dict] = []
        for connection_id, adapter in self._adapters.items():
            try:
                adapter_results = await adapter.close_all_positions()
                results.extend(adapter_results)
            except Exception as exc:
                logger.error(
                    "Kill switch: error closing positions",
                    connection_id=connection_id,
                    broker=adapter.broker_name,
                    error=str(exc),
                )
                results.append(
                    {
                        "broker": adapter.broker_name,
                        "connection_id": connection_id,
                        "status": "error",
                        "error": str(exc),
                    }
                )
        return results

    # ------------------------------------------------------------------
    # Adapter lookup
    # ------------------------------------------------------------------

    def get_adapter(self, broker: str) -> BrokerAdapter | None:
        """Return the first adapter matching *broker* name (e.g. ``'oanda'``)."""
        for adapter in self._adapters.values():
            if adapter.broker_name.lower() == broker.lower():
                return adapter
        return None

    def get_adapter_by_connection_id(self, connection_id: str) -> BrokerAdapter | None:
        """Return adapter by connection_id string."""
        return self._adapters.get(connection_id)

    def register_adapter(self, key: str, adapter: BrokerAdapter) -> None:
        """Register an externally-owned adapter (e.g. the live loop's in-process
        simulation broker) under a stable string key.

        This replaces the previous private-dict reach-in (``_adapters['paper'] =
        ...``). It is idempotent: registering the same key rebinds it. Used so the
        aggregate position view, the close-routing, and the kill switch all see
        the simulation broker without constructing a second instance.
        """
        self._adapters[key] = adapter
        logger.info("Adapter registered", key=key, broker=adapter.broker_name,
                    is_simulation=adapter.is_simulation)

    # ------------------------------------------------------------------
    # Price streaming
    # ------------------------------------------------------------------

    def set_price_callback(self, callback: Callable) -> None:
        """Register a callback to receive all price ticks."""
        self._price_callback = callback

    async def start_price_streaming(self, pairs: list[str]) -> None:
        """Start streaming prices for *pairs* across all adapters."""
        await self.stop_price_streaming()

        if not self._price_callback:
            logger.warning("No price callback registered — streaming will not forward ticks")

        for connection_id, adapter in self._adapters.items():
            cb = self._price_callback
            # Each adapter streams its own instrument set when it declares one
            # (e.g. a crypto broker streams crypto, not the forex defaults).
            adapter_pairs = adapter.default_pairs or pairs

            async def _stream(adp=adapter, conn_id=connection_id, strm_pairs=adapter_pairs):
                try:
                    await adp.stream_prices(strm_pairs, cb or (lambda _: None))
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.error(
                        "Price stream task error",
                        connection_id=conn_id,
                        broker=adp.broker_name,
                        error=str(exc),
                    )

            task = asyncio.create_task(_stream(), name=f"price_stream_{connection_id}")
            self._price_stream_tasks.append(task)

        logger.info("Price streaming started", adapter_count=len(self._adapters), pairs=pairs)

    async def stop_price_streaming(self) -> None:
        """Cancel all running price stream tasks."""
        for task in self._price_stream_tasks:
            if not task.done():
                task.cancel()
        if self._price_stream_tasks:
            await asyncio.gather(*self._price_stream_tasks, return_exceptions=True)
        self._price_stream_tasks.clear()
        logger.info("Price streaming stopped")

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<BrokerManager adapters={list(self._adapters.keys())}>"


# Module-level singleton
broker_manager = BrokerManager()
