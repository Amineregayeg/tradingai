"""WebSocket endpoint for real-time streaming."""
import asyncio
import secrets

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.config import settings
from app.core.logging import logger
from app.services.ws.manager import ws_manager

router = APIRouter(tags=["websocket"])


def _ws_authorized(websocket: WebSocket) -> bool:
    """Authenticate a WebSocket handshake. Browsers can't set Authorization on a
    WS upgrade, so the bearer token is passed as ``?token=<token>`` (or an
    Authorization header for non-browser clients). Mirrors HTTP auth: open only
    when auth_disabled (local dev); otherwise a constant-time token match."""
    if settings.auth_disabled:
        return True
    expected = settings.api_auth_token
    if not expected:
        return False
    token = websocket.query_params.get("token", "")
    if not token:
        header = websocket.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    return bool(token) and secrets.compare_digest(token, expected)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket endpoint.

    Requires the bearer token (``?token=…``) — it streams live positions, alerts
    and kill-switch events, so it must not be open. Clients receive events on:
    prices, positions, alerts, ict, propfirm, system.

    Subscribe/unsubscribe by sending JSON messages:
    ``{"channel": "prices", "event": "subscribe"}``
    ``{"channel": "prices", "event": "unsubscribe"}``

    The server pings every 30s; clients should respond with pong:
    ``{"channel": "system", "event": "pong"}``
    """
    if not _ws_authorized(websocket):
        # Reject BEFORE accept: an unauthenticated client gets no stream.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("WebSocket rejected — missing/invalid token")
        return
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
