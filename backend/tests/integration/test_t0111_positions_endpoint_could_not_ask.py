"""T-0111 / B372 — the endpoint must not tell an operator a live position does not exist.

**THE WORST INSTANCE IS A CLOSE PATH.** `DELETE /positions/{id}` looked the position up in the
aggregate and raised `404 "not found in any connected broker"`. If the broker holding it could not
be reached, its positions were missing from that list — so the message was **affirmatively wrong
twice**: the broker IS connected and the position IS open. Its honest reading is *it is already
closed*, which is the one conclusion that stops an operator looking further.

**AND `positions.py:49` HAD A 502 HANDLER FOR EXACTLY THIS AND IT WAS UNREACHABLE**, because the
aggregate swallowed first and returned `[]`. That is why the collapse survived review: a reader
concludes a broker failure surfaces as a 502 — the handler is right there, well written — while the
layer below made it dead code. `B272`'s family. **These arms drive the endpoint**, so a handler that
cannot fire fails them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.exceptions import BrokerError
from app.db.enums import DirectionType
from app.schemas.broker import Position
from app.services.broker.manager import broker_manager

pytestmark = pytest.mark.asyncio


def _position(pid: str) -> Position:
    return Position(
        id=pid, pair="BTC/USD", direction=DirectionType.LONG,
        entry_price=Decimal("100"), current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"), lot_size=Decimal("0.5"),
        produced_by="paper", pnl_source="profit",
        duration_seconds=0, open_time=datetime.now(timezone.utc),
    )


class _Adapter:
    def __init__(self, name, positions=None, error=None):
        self.broker_name = name
        self._positions = positions or []
        self._error = error

    async def get_positions(self):
        if self._error is not None:
            raise self._error
        return list(self._positions)

    async def close_position(self, position_id, lot_size=None):
        return {"status": "closed", "id": position_id}


@pytest.fixture
def adapters():
    """Install adapters on the real singleton the router calls, then restore."""
    original = dict(broker_manager._adapters)

    def _install(**kw):
        broker_manager._adapters = dict(kw)

    yield _install
    broker_manager._adapters = original


async def test_DELETE_does_not_404_while_a_broker_could_not_be_asked(client: AsyncClient, adapters):
    """**M-3.** Assert the DETAIL, not only the code — a 404 whose detail says *not found in any
    connected broker* IS the defect, so a different code with a vague body would still be wrong.
    """
    adapters(
        c1=_Adapter("paper", [_position("a1")]),
        c2=_Adapter("cryptofundtrader", error=BrokerError("link down", broker="cft")),
    )
    resp = await client.delete("/api/positions/UNKNOWN-TO-US")

    assert resp.status_code != 404, (
        "the operator was told a position does not exist while a broker could not be asked"
    )
    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "cryptofundtrader" in detail, "the unreachable broker must be NAMED"
    assert "NOT a statement that the position does not exist" in detail


async def test_DELETE_STILL_404s_when_every_broker_ANSWERED(client: AsyncClient, adapters):
    """The must-miss. *Not found* is the right answer when we actually looked everywhere, and a
    fix that never 404s again has replaced one wrong answer with another."""
    adapters(c1=_Adapter("paper", [_position("a1")]))
    resp = await client.delete("/api/positions/UNKNOWN-TO-US")
    assert resp.status_code == 404
    assert "not found in any connected broker" in resp.json()["detail"]


async def test_GET_one_distinguishes_not_found_from_not_asked(client: AsyncClient, adapters):
    adapters(
        c1=_Adapter("paper", [_position("a1")]),
        c2=_Adapter("cft", error=BrokerError("link down", broker="cft")),
    )
    assert (await client.get("/api/positions/MISSING")).status_code == 502

    adapters(c1=_Adapter("paper", [_position("a1")]))
    assert (await client.get("/api/positions/MISSING")).status_code == 404


async def test_the_502_PATH_IS_REACHABLE_when_no_broker_could_be_asked(client: AsyncClient, adapters):
    """**M-4.** The handler existed and could not fire. An empty list with brokers connected and
    none reachable means *we could not look*, not *nothing is open*."""
    adapters(c1=_Adapter("cft", error=BrokerError("link down", broker="cft")))
    resp = await client.get("/api/positions")
    assert resp.status_code == 502
    assert "could not be asked" in resp.json()["detail"]


async def test_a_PARTIAL_failure_still_returns_200_because_three_consumers_rest_on_that(
    client: AsyncClient, adapters,
):
    """The contract control. A partial answer must NOT become a failure — the endpoint's contract
    is *never an error*. The unasked brokers ride on a header so the fact is available without
    changing the response model."""
    adapters(
        c1=_Adapter("paper", [_position("a1")]),
        c2=_Adapter("cft", error=BrokerError("link down", broker="cft")),
    )
    resp = await client.get("/api/positions")
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()] == ["a1"]
    assert resp.headers.get("X-Unasked-Brokers") == "cft"


async def test_NO_brokers_connected_is_still_an_empty_list_and_not_an_error(
    client: AsyncClient, adapters,
):
    """The other control: *no brokers connected* is a real, answerable state and always was."""
    adapters()
    resp = await client.get("/api/positions")
    assert resp.status_code == 200 and resp.json() == []
    assert "X-Unasked-Brokers" not in resp.headers
