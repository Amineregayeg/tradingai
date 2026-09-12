"""T-0138 — the safety flag must agree with where the client POINTS, and a run that cannot place
an order must refuse to START.

**`B389`, settled by CONSTRUCTION rather than by reading the constructor.** The SDK resolves the
endpoint as

    base_url = url_override if url_override else (TRADING_PAPER if paper else TRADING_LIVE)

so `url_override` outranks `paper` entirely. `TradingClient(k, s, paper=True, url_override=<live>)`
points at real money while `is_simulation` returns `True` — **the assertion gating all execution
passing on a real-money client.** We pass `url_override` nowhere today, so it was latent: one
keyword argument, and the flag would not have noticed.

**A flag we passed is a record of our intent. The base URL is where the money is.**

---

**THE OTHER HALF IS ABOUT WHERE A FAILURE IS ALLOWED TO APPEAR.** `place_order`'s body was scoped
to part D, which measured the minimum order size it must round to (`T-0139`/`T-0140` — landed, so
the gate is now removed and `test_t0138_order_path_gate` guards the crossing from the far side).
Before that, a run pointed at Alpaca
would fail *every entry, one at a time* — and an operator reading a wall of venue errors concludes
the VENUE is down and goes to debug Alpaca. That is `B380`'s shape with the diagnosis relocated.
**One refusal at startup cannot be mistaken for a market condition.**
"""
from __future__ import annotations

import pytest

from app.core.exceptions import BrokerError
from app.services.broker.alpaca import (
    LIVE_ENDPOINT,
    PAPER_ENDPOINT,
    AlpacaAdapter,
    AlpacaEndpointMismatch,
    _endpoint_of,
)
from app.services.broker.base import BrokerAdapter
from app.services.broker.paper import PaperBroker

pytestmark = pytest.mark.asyncio


def _client(**kw):
    """A REAL `TradingClient`. Imported inside because the SDK must not be needed to import the
    adapter (`B328`) — but this arm's whole subject is the SDK's own resolution, so a mock here
    would be the mock encoding my reading of the thing under test (`B356`)."""
    from alpaca.trading.client import TradingClient

    return TradingClient("key", "secret", **kw)


# =====================================================================================
# THE VENUE CONSTANTS — pinned against the INSTALLED enum, not against my memory of it
# =====================================================================================

async def test_t0138_endpoint_agreement():
    """`alpaca.py` hardcodes the two endpoints because it may not import the SDK at module scope
    (`B328`). **A hardcoded venue fact that nothing checks is a venue fact that rots**, so this
    pins them against `BaseURL` itself: if Alpaca moves a host, this goes red rather than the
    safety flag quietly becoming a lie.
    """
    from alpaca.common.enums import BaseURL

    assert PAPER_ENDPOINT == BaseURL.TRADING_PAPER.value
    assert LIVE_ENDPOINT == BaseURL.TRADING_LIVE.value
    assert PAPER_ENDPOINT != LIVE_ENDPOINT


async def test_the_enum_is_a_str_enum_and_only_str_OF_it_misleads():
    """**THE TRAP THAT WOULD HAVE INVERTED THE FIX, PINNED SO THE NEXT READER INHERITS IT MEASURED.**

    My first explanation of this said *"`BaseURL` is a plain `Enum`, not a `str, Enum`"*. **False**
    — corrected by the manager, who drove it. The member IS a string and compares equal to the URL;
    what breaks is `str()` of it, because `Enum.__str__` takes precedence over `str.__str__` for a
    mixin enum.

    The conclusion and the code were right for a reason that was not the real one, and **the reason
    is the load-bearing half for whoever reads it next** — someone trusting the old sentence would
    reach for `.value` in places where plain comparison is fine.
    """
    from alpaca.common.enums import BaseURL

    assert issubclass(BaseURL, str), "the member is a string; that is why containment works on it"
    assert BaseURL.TRADING_PAPER == PAPER_ENDPOINT
    assert "paper-api" in BaseURL.TRADING_PAPER
    assert "paper-api" not in str(BaseURL.TRADING_PAPER), (
        "if this ever becomes true, `str()` is safe and the _endpoint_of dance can be simplified"
    )


async def test_endpoint_of_reads_BOTH_shapes_the_sdk_returns():
    """`_base_url` is a `BaseURL` normally and a plain `str` when overridden — two types for one
    concept, which is `Order.qty`'s `Union[str, float, None]` trap with a second surface."""
    assert _endpoint_of(_client(paper=True)) == PAPER_ENDPOINT
    assert _endpoint_of(_client(paper=False)) == LIVE_ENDPOINT
    assert _endpoint_of(_client(paper=True, url_override=LIVE_ENDPOINT)) == LIVE_ENDPOINT
    assert _endpoint_of(object()) is None, (
        "a client that cannot say is a QUESTION, not an answer — it must not read as paper"
    )


# =====================================================================================
# M-4 — `is_simulation` must agree with the client's ACTUAL base url
# =====================================================================================

async def test_a_paper_flag_over_a_LIVE_override_REFUSES_TO_CONSTRUCT():
    """**THE ROW THE KILL-SET ASKED FOR.** Reading our own flag cannot catch this: the client knows
    where it is pointed and the adapter never asked.

    Refused at CONSTRUCTION rather than reported by `is_simulation`, because a flag that quietly
    starts returning something else moves the failure away from the mistake that made it.
    """
    with pytest.raises(AlpacaEndpointMismatch) as exc:
        AlpacaAdapter(_client(paper=True, url_override=LIVE_ENDPOINT), paper=True)

    assert exc.value.endpoint == LIVE_ENDPOINT
    assert exc.value.paper is True
    message = str(exc.value).lower()
    assert "url_override" in message and "paper" in message, (
        "the refusal must name the MECHANISM, or the next reader cannot tell it from a typo"
    )


async def test_the_agreement_holds_in_the_OTHER_direction_too():
    """A live-pointed client claimed as live is not a mismatch — it is honest, and `is_simulation`
    reports `False` so `ExecutionService` refuses it. **A check that only fires one way would let
    `paper=False` over a PAPER endpoint through**, which misreports the opposite fact."""
    live = AlpacaAdapter(_client(paper=False), paper=False)
    assert live.is_simulation is False
    assert live.endpoint == LIVE_ENDPOINT

    with pytest.raises(AlpacaEndpointMismatch):
        AlpacaAdapter(_client(paper=False, url_override=PAPER_ENDPOINT), paper=False)


async def test_a_genuine_paper_client_still_constructs_and_says_WHERE_the_answer_came_from():
    """The control for the two above — **a refusal that never accepts anything is not a fix.**

    `simulation_source` is `Position.pnl_source`'s shape: *derived from the endpoint* and *taken
    from the flag because the endpoint was unreadable* are different claims and must not look alike.
    """
    adapter = AlpacaAdapter(_client(paper=True), paper=True)
    assert adapter.is_simulation is True
    assert adapter.endpoint == PAPER_ENDPOINT
    assert adapter.simulation_source == "endpoint"


async def test_a_client_that_cannot_be_ASKED_is_recorded_as_such_rather_than_refused():
    """**Deliberate, and the reason is an outage risk rather than a preference.** `_base_url` is
    private; raising when it cannot be read would take the platform down the day the SDK renames
    it — trading a latent risk for a certain one. Test doubles land here too.

    What must NOT happen is the unreadable case looking like the derived one.
    """
    adapter = AlpacaAdapter(object(), paper=True)
    assert adapter.is_simulation is True
    assert adapter.endpoint is None
    assert adapter.simulation_source != "endpoint"
    assert "unreadable" in adapter.simulation_source


# =====================================================================================
# M-5 — THE MUST-MISS: `is_simulation` must not be satisfiable by always-True
# =====================================================================================

async def test_is_simulation_is_not_satisfied_by_returning_True_unconditionally():
    """**Without this, "the flag agrees with the endpoint" is satisfied by never disagreeing.**

    `B376-B`'s shape again: a raise-on-anything satisfies raise-on-unrecognised. The mutation this
    exists for makes `is_simulation` return `True` always — every other arm in this file survives
    it, and this one dies.
    """
    live = AlpacaAdapter(_client(paper=False), paper=False)
    paper = AlpacaAdapter(_client(paper=True), paper=True)

    assert live.is_simulation is False, "a LIVE-constructed adapter must report False"
    assert paper.is_simulation is True
    assert live.is_simulation != paper.is_simulation, (
        "the flag must DISCRIMINATE; one that answers the same either way answers nothing"
    )


# =====================================================================================
# THE START GATE — and the arm that forces its own removal when part D lands
# =====================================================================================

async def test_t0138_order_path_gate():
    """**THE BICONDITIONAL EXPIRED EXACTLY AS DESIGNED, AND THIS IS THE OTHER HALF OF IT.**

    It pinned two representations of one fact together (`B184`): `order_path_status()` declaring
    orders unplaceable, and `place_order` actually refusing. Either one changing alone turned it
    red. **Part D (`T-0140`) wrote the body, this arm went red, and that red was the instruction
    to remove the override** — which is the only reason the gate could not be left behind to
    refuse startup against a working order path.

    **The biconditional is kept, inverted.** The override is gone AND the body exists, and those
    are still two representations of one fact, so they are still pinned together: re-adding the
    override without removing the body turns this red, and gutting the body without restoring the
    override turns this red. An arm pinning a phase boundary does not stop being useful when the
    phase ends — it starts guarding the crossing from the other side.
    """
    import inspect

    from app.db.enums import DirectionType, OrderType
    from app.services.broker.base import BrokerAdapter, OrderRequest

    adapter = AlpacaAdapter(object(), paper=True)

    assert adapter.order_path_status() is None, (
        "the gate is declaring orders unplaceable while the body is written — a working adapter "
        "that refuses to start"
    )
    assert "order_path_status" not in AlpacaAdapter.__dict__, (
        "the override is back; it must be ABSENT, not overridden to return None, or the next "
        "reader cannot tell a deliberate permission from a forgotten stub"
    )
    assert AlpacaAdapter.order_path_status is BrokerAdapter.order_path_status

    # THE OTHER HALF: the body must actually be there. A `place_order` that still refuses
    # everything, with the gate removed, is the worst of both — startup permitted, every entry
    # failing one at a time, and an operator reading a wall of venue errors going to debug Alpaca
    # (`B380`'s shape with the diagnosis relocated, which is what the gate existed to prevent).
    source = inspect.getsource(AlpacaAdapter.place_order)
    assert "NotImplementedError" not in source, "the body is a stub with the gate removed"
    assert "submit_order" in source, "the body does not submit anything"

    # And driven, not just read: the refusal for a LONG is now about the CLIENT, never a blanket
    # unimplemented.
    with pytest.raises(BrokerError) as exc:
        await adapter.place_order(OrderRequest(
            pair="BTC/USD", direction=DirectionType.LONG, order_type=OrderType.MARKET,
            lot_size=0.001, sl=69_900.0,
        ))
    assert not isinstance(exc.value, NotImplementedError)
    assert "get_asset" in str(exc.value)


async def test_an_adapter_that_CAN_place_orders_declares_nothing():
    """The control. A gate that blocks everything blocks nothing usefully — and the simulators are
    what the engine actually runs on today, so a false positive here stops the platform."""
    assert PaperBroker(starting_balance=1000.0).order_path_status() is None
    assert BrokerAdapter.order_path_status(object()) is None, (
        "the base default must be permissive, or every existing adapter becomes un-startable"
    )
