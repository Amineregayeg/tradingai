"""B438 / B427 — `DELETE /positions/{id}` must not answer success for a close that was only SUBMITTED.

Alpaca's `close_position` returned `str(Order)` and no status, and this route treated any status outside its
failure set — including none — as closed: an ACCEPTED close answered 204. The close order is now resolved,
and a result carrying `close_confirmed: False` is answered as what it is. **Driven through the endpoint**, so
a check that cannot fire fails these arms.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.db.enums import DirectionType
from app.schemas.broker import Position
from app.services.broker.manager import broker_manager

pytestmark = pytest.mark.asyncio


def _position(pid: str) -> Position:
    return Position(
        id=pid, pair="BTC/USD", direction=DirectionType.LONG,
        entry_price=Decimal("100"), current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"), lot_size=Decimal("0.5"),
        produced_by="alpaca", pnl_source="unrealized_pl",
        duration_seconds=0, open_time=datetime.now(timezone.utc),
    )


class _Adapter:
    def __init__(self, name, positions, close_result):
        self.broker_name = name
        self._positions = positions
        self._close_result = close_result
        self.closes: list[str] = []

    async def get_positions(self):
        return list(self._positions)

    async def close_position(self, position_id, lot_size=None):
        self.closes.append(position_id)
        return dict(self._close_result)


@pytest.fixture
def adapters():
    original = dict(broker_manager._adapters)

    def _install(**kw):
        broker_manager._adapters = dict(kw)

    yield _install
    broker_manager._adapters = original


UNCONFIRMED = {"position_id": "BTCUSD", "partial": False, "status": "ACCEPTED", "venue_status": "accepted",
               "terminal": False, "filled_units": 0.0, "close_confirmed": False,
               "resolution": {"resolved": False, "reads": 6}}


async def test_an_ACCEPTED_close_that_was_never_CONFIRMED_is_NOT_answered_as_success(client: AsyncClient, adapters):
    """**M-3: the DETAIL, not only the code.** And no second adapter is tried — the close was already SENT."""
    holder = _Adapter("alpaca", [_position("BTCUSD")], UNCONFIRMED)
    other = _Adapter("paper", [], {"status": "closed"})
    adapters(c1=holder, c2=other)

    resp = await client.delete("/api/positions/BTCUSD")
    assert holder.closes == ["BTCUSD"], "the route never asked the holding adapter to close"

    assert resp.status_code != 204, "a close that was only submitted was answered as a closed position"
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "SUBMITTED" in detail and "NOT CONFIRMED" in detail and "may still be open" in detail, detail
    assert "'accepted'" in detail, "the venue's own status is not in the operator's message"
    assert not other.closes, "a second adapter was asked to close a position whose close was already sent"


async def test_a_CONFIRMED_close_and_an_adapter_that_does_not_report_confirmation_still_answer_204(
        client: AsyncClient, adapters):
    """The must-miss, both halves: the fix must not turn a confirmed close, or a simulator's close that never
    carried the key, into a failure."""
    for result in ({**UNCONFIRMED, "status": "FILLED", "venue_status": "filled", "terminal": True,
                    "filled_units": 0.5, "close_confirmed": True},
                   {"status": "closed", "id": "BTCUSD"}):
        adapters(c1=_Adapter("alpaca", [_position("BTCUSD")], result))
        resp = await client.delete("/api/positions/BTCUSD")
        assert resp.status_code == 204, (result, resp.status_code, resp.text)
