"""WebSocket endpoint for real-time streaming."""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import logger
from app.services.ws.manager import ws_manager

router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket endpoint.

    Clients connect and receive events on 5 channels:
    prices, positions, alerts, ict, propfirm, system.

    Subscribe/unsubscribe by sending JSON messages:
    ``{"channel": "prices", "event": "subscribe"}``
    ``{"channel": "prices", "event": "unsubscribe"}``

    The server pings every 30s; clients should respond with pong:
    ``{"channel": "system", "event": "pong"}``
    """
    conn = await ws_manager.connect(websocket, "system")
    send_task = asyncio.create_task(ws_manager._send_loop(conn))
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                await ws_manager.handle_client_message(conn, raw)
            except asyncio.TimeoutError:
                # No message is fine; ping loop handles heartbeat
                continue
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected normally")
    except Exception as exc:
        logger.warning("WebSocket error", error=str(exc))
    finally:
        send_task.cancel()
        try:
            await send_task
        except asyncio.CancelledError:
            pass
        await ws_manager.disconnect(conn)
