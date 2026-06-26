"""In-process WebSocket connection manager with per-channel fanout and backpressure."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from app.core.logging import logger

CHANNELS = {"prices", "positions", "alerts", "ict", "propfirm", "system"}
PING_INTERVAL_SECONDS = 30
MAX_QUEUE_SIZE = 1000

# Price tick rate limiting: max 10 ticks per second per pair
PRICE_TICK_MIN_INTERVAL = 0.1  # seconds


class WSConnection:
    """Represents a single connected WebSocket client."""

    def __init__(self, websocket: WebSocket, user_id: str) -> None:
        self.websocket = websocket
        self.user_id = user_id
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self.connected = True
        self.subscribed_channels: set[str] = set(CHANNELS)


class WSManager:
    """
    In-process WebSocket connection manager.
    Single-tenant: all connections are user_id='system'.
    Multiplexes channels over a single WS connection per client.

    Price ticks: max 10/s per pair (drop oldest if faster).
    Alert/position/ict events: queued without drop (up to MAX_QUEUE_SIZE).
    """

    def __init__(self) -> None:
        self._connections: list[WSConnection] = []
        self._lock = asyncio.Lock()
        self._price_last_sent: dict[str, float] = {}  # pair → timestamp
        self._ping_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket, user_id: str) -> WSConnection:
        """Accept WS, add to list, send 'connected' event, start ping loop."""
        await websocket.accept()
        conn = WSConnection(websocket=websocket, user_id=user_id)

        async with self._lock:
            self._connections.append(conn)
            if self._ping_task is None or self._ping_task.done():
                self._ping_task = asyncio.create_task(self._ping_loop())

        connected_msg = self._make_message(
            channel="system",
            event="connected",
            data={
                "channels": list(CHANNELS),
                "user_id": user_id,
            },
            user_id=user_id,
        )
        await websocket.send_text(connected_msg)

        logger.info(
            "WebSocket client connected",
            user_id=user_id,
            total=len(self._connections),
        )
        return conn

    async def disconnect(self, conn: WSConnection) -> None:
        """Remove from list, clean up."""
        conn.connected = False
        async with self._lock:
            try:
                self._connections.remove(conn)
            except ValueError:
                pass
            # Stop ping task if no more connections
            if not self._connections and self._ping_task and not self._ping_task.done():
                self._ping_task.cancel()
                self._ping_task = None

        logger.info(
            "WebSocket client disconnected",
            user_id=conn.user_id,
            total=len(self._connections),
        )

    # ------------------------------------------------------------------
    # Client message handling
    # ------------------------------------------------------------------

    async def handle_client_message(self, conn: WSConnection, raw: str) -> None:
        """
        Parse JSON. Handle:
        - {channel: 'system', event: 'pong'} → ignore
        - {channel: X, event: 'subscribe'} → add to conn.subscribed_channels
        - {channel: X, event: 'unsubscribe'} → remove from subscribed_channels
        - unknown → send error
        """
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            error_msg = self._make_message(
                channel="system",
                event="error",
                data={"message": "Invalid JSON", "raw": raw[:200]},
            )
            try:
                await conn.websocket.send_text(error_msg)
            except Exception:
                pass
            return

        channel = msg.get("channel")
        event = msg.get("event")

        # Ignore pong heartbeats
        if channel == "system" and event == "pong":
            return

        if event == "subscribe":
            if channel in CHANNELS:
                conn.subscribed_channels.add(channel)
                ack = self._make_message(
                    channel="system",
                    event="subscribed",
                    data={"channel": channel},
                )
                try:
                    await conn.websocket.send_text(ack)
                except Exception:
                    pass
            else:
                error_msg = self._make_message(
                    channel="system",
                    event="error",
                    data={"message": f"Unknown channel: {channel!r}"},
                )
                try:
                    await conn.websocket.send_text(error_msg)
                except Exception:
                    pass
            return

        if event == "unsubscribe":
            conn.subscribed_channels.discard(channel)
            ack = self._make_message(
                channel="system",
                event="unsubscribed",
                data={"channel": channel},
            )
            try:
                await conn.websocket.send_text(ack)
            except Exception:
                pass
            return

        # Unknown message
        error_msg = self._make_message(
            channel="system",
            event="error",
            data={"message": f"Unknown event: {event!r} on channel: {channel!r}"},
        )
        try:
            await conn.websocket.send_text(error_msg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def broadcast(
        self,
        channel: str,
        event: str,
        data: Any,
        user_id: str = "system",
    ) -> None:
        """
        Enqueue message to all connections subscribed to channel.
        For 'prices' channel: apply 10/s rate limit per pair (data['pair']).
        Drop oldest tick if queue is full for prices.
        For other channels: if queue is full, disconnect slow client.
        """
        if channel not in CHANNELS:
            logger.warning("broadcast: unknown channel", channel=channel)
            return

        is_prices = channel == "prices"

        if is_prices:
            pair = data.get("pair", "") if isinstance(data, dict) else ""
            now = time.monotonic()
            last_sent = self._price_last_sent.get(pair, 0.0)
            if now - last_sent < PRICE_TICK_MIN_INTERVAL:
                # Rate limit exceeded — drop this tick
                return
            self._price_last_sent[pair] = now

        message = self._make_message(channel=channel, event=event, data=data, user_id=user_id)

        to_disconnect: list[WSConnection] = []

        async with self._lock:
            targets = [c for c in self._connections if channel in c.subscribed_channels]

        for conn in targets:
            if not conn.connected:
                continue
            if is_prices:
                # For prices: drop oldest if queue full
                if conn.queue.full():
                    try:
                        conn.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    conn.queue.put_nowait(message)
                except asyncio.QueueFull:
                    pass  # already drained above, ignore if still full
            else:
                # Non-price: disconnect slow clients with full queues
                if conn.queue.full():
                    logger.warning(
                        "Client queue full — disconnecting slow client",
                        user_id=conn.user_id,
                        channel=channel,
                    )
                    to_disconnect.append(conn)
                else:
                    try:
                        conn.queue.put_nowait(message)
                    except asyncio.QueueFull:
                        to_disconnect.append(conn)

        for conn in to_disconnect:
            try:
                await conn.websocket.close(code=1008, reason="Queue overflow")
            except Exception:
                pass
            await self.disconnect(conn)

    # ------------------------------------------------------------------
    # Send loop (runs as asyncio task per connection)
    # ------------------------------------------------------------------

    async def _send_loop(self, conn: WSConnection) -> None:
        """Drain conn.queue → send to WebSocket."""
        try:
            while conn.connected:
                try:
                    message = await asyncio.wait_for(conn.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                try:
                    await conn.websocket.send_text(message)
                except Exception as exc:
                    logger.warning(
                        "WebSocket send failed",
                        user_id=conn.user_id,
                        error=str(exc),
                    )
                    conn.connected = False
                    break
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Ping loop
    # ------------------------------------------------------------------

    async def _ping_loop(self) -> None:
        """Every 30s, broadcast {channel:'system', event:'ping'} to all connections."""
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL_SECONDS)
                async with self._lock:
                    if not self._connections:
                        break
                await self.broadcast(channel="system", event="ping", data={})
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Message factory
    # ------------------------------------------------------------------

    def _make_message(
        self,
        channel: str,
        event: str,
        data: Any,
        user_id: str = "system",
    ) -> str:
        return json.dumps({
            "channel": channel,
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
        })

    # ------------------------------------------------------------------
    # Convenience broadcast methods
    # ------------------------------------------------------------------

    async def push_tick(self, pair: str, bid: float, ask: float, spread: float) -> None:
        """Broadcast prices.tick event."""
        await self.broadcast(
            channel="prices",
            event="tick",
            data={"pair": pair, "bid": bid, "ask": ask, "spread": spread},
        )

    async def push_alert(self, alert: dict) -> None:
        """Broadcast alerts.new event."""
        await self.broadcast(channel="alerts", event="new", data=alert)

    async def push_alert_resolved(self, alert: dict) -> None:
        """Broadcast alerts.resolved event."""
        await self.broadcast(channel="alerts", event="resolved", data=alert)

    async def push_position_update(self, position: dict) -> None:
        """Broadcast positions.update event."""
        await self.broadcast(channel="positions", event="update", data=position)

    async def push_position_open(self, position: dict) -> None:
        """Broadcast positions.open event."""
        await self.broadcast(channel="positions", event="open", data=position)

    async def push_position_close(self, position: dict) -> None:
        """Broadcast positions.close event."""
        await self.broadcast(channel="positions", event="close", data=position)

    async def push_ict_detected(self, detection: dict) -> None:
        """Broadcast ict.detected event."""
        await self.broadcast(channel="ict", event="detected", data=detection)

    async def push_ict_mitigated(
        self,
        detection_id: str,
        mitigated_at: str,
        price: float,
    ) -> None:
        """Broadcast ict.mitigated event."""
        await self.broadcast(
            channel="ict",
            event="mitigated",
            data={"detection_id": detection_id, "mitigated_at": mitigated_at, "price": price},
        )

    async def push_kill_switch(
        self,
        profile_id: str,
        reason: str,
        positions_closed: int,
        positions_failed: int,
    ) -> None:
        """Broadcast propfirm.kill_switch_triggered event."""
        await self.broadcast(
            channel="propfirm",
            event="kill_switch_triggered",
            data={
                "profile_id": profile_id,
                "reason": reason,
                "positions_closed": positions_closed,
                "positions_failed": positions_failed,
            },
        )

    async def push_broker_status(self, broker: str, status: str) -> None:
        """Broadcast system.connection_status event."""
        await self.broadcast(
            channel="system",
            event="connection_status",
            data={"broker": broker, "status": status},
        )


ws_manager = WSManager()
