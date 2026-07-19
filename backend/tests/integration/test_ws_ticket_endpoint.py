"""The ws-ticket endpoint mints a usable single-use ticket over HTTP."""
from __future__ import annotations

import pytest

from app.core import ws_tickets


@pytest.mark.asyncio
async def test_ws_ticket_endpoint_mints_consumable_ticket(client):
    resp = await client.post("/api/auth/ws-ticket")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ticket")
    assert body.get("expires_in") == 30
    # the ticket the endpoint minted is valid exactly once
    assert ws_tickets.consume(body["ticket"]) is True
    assert ws_tickets.consume(body["ticket"]) is False
