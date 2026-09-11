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

**THE OTHER HALF IS ABOUT WHERE A FAILURE IS ALLOWED TO APPEAR.** `place_order`'s body is scoped to
part D, which measures the minimum order size it must round to. Until then a run pointed at Alpaca
would fail *every entry, one at a time* — and an operator reading a wall of venue errors concludes
the VENUE is down and goes to debug Alpaca. That is `B380`'s shape with the diagnosis relocated.
**One refusal at startup cannot be mistaken for a market condition.**
"""
from __future__ import annotations

import pytest

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
    """**THE BICONDITIONAL, AND IT IS WHAT STOPS THIS GOING STALE.**

    `AlpacaAdapter.order_path_status()` declares that orders cannot be placed. That declaration and
    `place_order`'s actual refusal are two representations of one fact (`B184`), so they are pinned
    TOGETHER: implementing the body without deleting the override turns this red, and deleting the
    override without implementing the body turns this red.

    **This arm is meant to expire.** When part D writes the body, it fails — and that failure is
    the instruction to remove the override. An arm pinning a phase boundary expires when the phase
    ends, and the expiry is the point; `T-0136`'s direction-parametrized arm did exactly this and
    the ordering it protected is the reason `T-0137` landed in the right order.
    """
    from app.db.enums import DirectionType, OrderType
    from app.services.broker.base import OrderRequest

    adapter = AlpacaAdapter(object(), paper=True)
    declared = adapter.order_path_status()

    assert declared is not None, "the override was removed; was the body actually written?"
    assert "part D" in declared, "the refusal must point at the task that owns the body"

    with pytest.raises(NotImplementedError):
        await adapter.place_order(OrderRequest(
            pair="BTC/USD", direction=DirectionType.LONG, order_type=OrderType.MARKET,
            lot_size=0.001, sl=69_900.0,
        ))


async def test_an_adapter_that_CAN_place_orders_declares_nothing():
    """The control. A gate that blocks everything blocks nothing usefully — and the simulators are
    what the engine actually runs on today, so a false positive here stops the platform."""
    assert PaperBroker(starting_balance=1000.0).order_path_status() is None
    assert BrokerAdapter.order_path_status(object()) is None, (
        "the base default must be permissive, or every existing adapter becomes un-startable"
    )
