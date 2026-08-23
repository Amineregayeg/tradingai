"""T-0062 — `B221`: the kill switch closes nothing and reports success.

**SAFETY PATH.** `main.py:236` registers `live_loop.paper` with `broker_manager` ONCE, and
every `POST /engine/start` runs `_reset_broker_state`, which REBINDS `self.paper` to a freshly
constructed broker and never re-registers. So `broker_manager._adapters` holds an orphan — and
because this deployment runs `PROP_FIRM_SIM` it is a different CLASS, not merely a stale
instance. `close_all_positions` iterates it, gets `[]`, and the caller reports success.

**THE REPORT IS THE THING THAT LIES.** `kill_switch.py:71-76` derives both counters from the
same list, so `[]` yields **0 closed and 0 failed** — and `:67-69` catches an exception into
`close_results = []`, so a raise renders identically. *Three causes, one rendering: closed
nothing, closed nothing while throwing, and genuinely had nothing to close.*

**So ARM 1 ASSERTS THE WORLD, NOT THE REPORT.** `assert positions_failed == 0` passes on the
broken code. The arm that fails is `loop.paper._positions == {}`.
"""
from __future__ import annotations

import pytest

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import BrokerAdapter, OrderRequest
from app.services.broker.manager import broker_manager
from app.services.compliance.kill_switch import kill_switch
from app.services.broker.live_loop_proxy import LiveLoopBrokerProxy
from app.services.live.crypto_loop import LiveCryptoLoop

pytestmark = pytest.mark.asyncio


@pytest.fixture
def clean_manager():
    """`broker_manager` is a module-level singleton; leaking a registration would make the
    next test's failure someone else's problem."""
    saved = dict(broker_manager._adapters)
    broker_manager._adapters.clear()
    try:
        yield broker_manager
    finally:
        broker_manager._adapters.clear()
        broker_manager._adapters.update(saved)


async def _open_a_position(broker, pair="BTC/USD", loop=None) -> None:
    """Open one position, at a REAL price.

    `SimPropFirmBroker` prices through the LOOP's `_marks` (`_reset_broker_state` builds its
    `_price_source` from `self._marks`), so setting only the broker's own marks fills at
    **0.0** — which then makes the stop distance the whole notional and trips
    `would_breach_daily_loss`. The first run of this fixture was REJECTED for exactly that,
    and the guard below is what caught it. *A setup that silently no-ops proves nothing about
    what the test asserts.*
    """
    if loop is not None:
        loop._marks[pair] = 70000.0
    broker._marks[pair] = 70000.0
    await broker.place_order(
        OrderRequest(
            pair=pair, direction=DirectionType.LONG, order_type=OrderType.MARKET,
            # Small enough that SimPropFirmBroker's daily-loss rule admits it. The fixture
            # guard below caught a REJECTED order the first time this ran — a test whose
            # setup silently no-ops proves nothing about what it asserts.
            lot_size=0.001, price=70000.0, sl=69900.0, tp=None,
        )
    )
    assert broker._positions, "the fixture must actually open a position"
    if loop is not None:
        entry = next(iter(broker._positions.values())).entry
        assert entry > 0, f"the position filled at {entry}; the price source is not wired"


async def test_arm1_the_kill_switch_ACTUALLY_closes_the_live_position(db_session, clean_manager):
    """**ARM 1. It must FAIL on today's code, and it must fail on the WORLD.**

    The report is what lies, so the assertion that matters is that the position is gone.
    """
    loop = LiveCryptoLoop()
    clean_manager.register_adapter("paper", LiveLoopBrokerProxy(loop))  # what main.py does

    await loop._reset_broker_state()                      # exactly what POST /engine/start does
    await _open_a_position(loop.paper, loop=loop)

    result = await kill_switch.trigger(db_session, "test-user", reason="arm 1")

    assert loop.paper._positions == {}, (
        "THE POSITION IS STILL OPEN after the kill switch reported success. The manager is "
        f"holding an orphan: {result}"
    )
    assert result["positions_closed"] == 1, (
        f"and the report must AGREE with the world, got {result}"
    )


async def test_arm1b_the_OLD_SHAPE_still_fails_and_this_keeps_the_red_re_runnable(
    db_session, clean_manager
):
    """**The defect, PINNED — not a log of a red I once saw.**

    Register the broker OBJECT, as `main.py` did before this task, and the position survives
    a kill switch that reports success. Measured at `7a2d5e3` before the fix and asserted
    here after it, so the red stays re-runnable instead of living in an artefact file.

    **Note what the report says while the position is open: `0 closed, 0 failed`.** Three
    causes render identically — closed nothing, closed nothing while throwing, and genuinely
    had nothing to close. *`assert positions_failed == 0` passes on the broken code, which is
    why ARM 1 asserts the WORLD.*
    """
    loop = LiveCryptoLoop()
    clean_manager.register_adapter("paper", loop.paper)   # THE OLD SHAPE — the object

    await loop._reset_broker_state()
    await _open_a_position(loop.paper, loop=loop)

    result = await kill_switch.trigger(db_session, "test-user", reason="arm 1b")

    assert loop.paper._positions != {}, (
        "the old shape no longer leaves the position open — if a re-registration was added "
        "elsewhere, this arm has lost its subject and the proxy may be untested"
    )
    assert result["positions_closed"] == 0 and result["positions_failed_to_close"] == 0, (
        f"the lying report, pinned: {result}"
    )


# ======================================================================================
# ARM 2 — THE ORPHAN CANNOT RECUR, AND THIS ARM NAMES NO CONSTRUCTION SITE
#
# This is the arm that decides the SHAPE. Re-registering at the end of `_reset_broker_state`
# would synchronise ONE site, and a direct rebind is not that site — so that shape fails here
# while the proxy passes by construction. The question dissolves only where the manager never
# holds a broker reference at all.
# ======================================================================================


async def test_arm2_a_DIRECT_REBIND_is_visible_to_the_manager(clean_manager):
    loop = LiveCryptoLoop()
    clean_manager.register_adapter("paper", LiveLoopBrokerProxy(loop))

    old = loop.paper
    await loop._reset_broker_state()
    await _open_a_position(loop.paper, loop=loop)

    assert loop.paper is not old, "the rebind must actually have happened"
    positions = await clean_manager.get_all_positions()
    assert len(positions) == 1, (
        f"the manager cannot see the CURRENT broker's position: {positions}"
    )


async def test_arm3_the_rebind_ACROSS_THE_CLASS_BOUNDARY_is_visible_too(clean_manager):
    """`PaperBroker` -> `SimPropFirmBroker`. **`:704` is the branch this deployment takes**,
    so a fix verified only against a same-class rebind has not been verified against the case
    that is running. The proxy forwards by ATTRIBUTE, never by type, which is what makes this
    hold."""
    from app.services.broker.cft_sim import SimPropFirmBroker
    from app.services.broker.paper import PaperBroker

    loop = LiveCryptoLoop()
    clean_manager.register_adapter("paper", LiveLoopBrokerProxy(loop))

    loop.paper = PaperBroker(starting_balance=5000.0, price_fn=lambda p: 70000.0)
    assert isinstance(loop.paper, PaperBroker)
    await _open_a_position(loop.paper, loop=loop)
    assert len(await clean_manager.get_all_positions()) == 1

    await loop._reset_broker_state()
    assert isinstance(loop.paper, SimPropFirmBroker), (
        "this deployment's broker_mode must produce the sim class, or ARM 3 is testing the "
        "branch that is NOT running"
    )
    await _open_a_position(loop.paper, loop=loop)

    positions = await clean_manager.get_all_positions()
    assert len(positions) == 1, f"a CLASS change broke the forward: {positions}"


# ======================================================================================
# ARM 4 — no regression of the real UUID-keyed adapters
# ======================================================================================


class _StubAdapter(BrokerAdapter):
    """A minimal real-shaped adapter, registered alongside the proxy."""

    broker_name = "stub"

    def __init__(self, *, simulation: bool = True, positions=()) -> None:
        self._simulation, self._pos = simulation, list(positions)

    @property
    def is_simulation(self) -> bool:
        return self._simulation

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def get_account(self): ...
    async def get_positions(self):
        return list(self._pos)
    async def get_orders(self, status=None):
        return []
    async def get_recent_trades(self, since=None):
        return []
    async def place_order(self, request):
        return {}
    async def close_position(self, position_id, lot_size=None):
        return {}
    async def close_all_positions(self):
        return [{"broker": "stub", "status": "closed"}]
    async def stream_prices(self, pairs, callback) -> None: ...


class _ThrowingAdapter(_StubAdapter):
    broker_name = "throwing"

    async def get_positions(self):
        raise RuntimeError("transport is down")


async def test_arm4_a_uuid_keyed_adapter_beside_the_proxy_still_works(clean_manager):
    loop = LiveCryptoLoop()
    clean_manager.register_adapter("paper", LiveLoopBrokerProxy(loop))
    clean_manager.register_adapter("11111111-2222-3333-4444-555555555555", _StubAdapter())

    await _open_a_position(loop.paper, loop=loop)

    assert len(await clean_manager.get_all_positions()) == 1
    results = await clean_manager.close_all_positions()
    assert any(r.get("broker") == "stub" for r in results), (
        f"the UUID-keyed adapter's rows must still be there: {results}"
    )


# ======================================================================================
# ARM 5 — `is_simulation` IS DYNAMIC, AND A HARD-CODED `True` MUST TURN THIS RED
# ======================================================================================


async def test_arm5_is_simulation_is_forwarded_and_a_live_broker_is_never_laundered():
    """`base.py:59-63`: *"a new real-money adapter can never silently pass as safe. Safety-
    critical chokepoints (ExecutionService, the kill switch, position-close routing) read
    this."* Hard-coding `True` here — tempting, since the loop holds a simulation today —
    would launder a live adapter past three named chokepoints."""

    class _Loop:
        paper = _StubAdapter(simulation=False)

    assert LiveLoopBrokerProxy(_Loop()).is_simulation is False, (
        "a hard-coded True would pass ARM 1 and every other arm in this file, and would be "
        "the single most dangerous line in the change"
    )

    class _SimLoop:
        paper = _StubAdapter(simulation=True)

    assert LiveLoopBrokerProxy(_SimLoop()).is_simulation is True


async def test_arm5b_with_NO_broker_is_simulation_is_FALSE_because_unknown_is_not_safe():
    class _Empty:
        paper = None

    assert LiveLoopBrokerProxy(_Empty()).is_simulation is False


# ======================================================================================
# ARM 6 — THE PROXY NEVER RAISES INTO THE SWALLOW
#
# `manager.py:373` swallows per-adapter exceptions and continues, so a proxy that threw when
# the loop had no broker would reproduce `[]` — same symptom, new cause.
# ======================================================================================


async def test_arm6_no_broker_returns_empty_without_raising_and_says_WHY(clean_manager):
    class _Empty:
        paper = None

    proxy = LiveLoopBrokerProxy(_Empty())
    clean_manager.register_adapter("paper", proxy)

    assert await clean_manager.get_all_positions() == []
    assert proxy.unavailable_reason == "the live loop is holding no broker", (
        "the cause must be a POSITIVE statement on the proxy — `[]` alone means three "
        "different things and closing that ambiguity is another task's"
    )
    assert await proxy.close_all_positions() == [], (
        "and NOT a synthetic status row: kill_switch.py:71 counts any row whose status is "
        "not error/failed as CLOSED, so a marker row would inflate the operator's number"
    )


async def test_arm6b_a_THROWING_adapter_is_distinguishable_from_a_proxy_with_no_broker(
    clean_manager,
):
    """The control. Both render as an empty aggregate; only one sets `unavailable_reason`."""
    class _Empty:
        paper = None

    proxy = LiveLoopBrokerProxy(_Empty())
    clean_manager.register_adapter("paper", proxy)
    clean_manager.register_adapter("99999999-0000-0000-0000-000000000000", _ThrowingAdapter())

    assert await clean_manager.get_all_positions() == [], "both contribute nothing"
    assert proxy.unavailable_reason is not None, "the proxy names its cause"

    loop = LiveCryptoLoop()
    live = LiveLoopBrokerProxy(loop)
    await live.get_positions()
    assert live.unavailable_reason is None, (
        "and a proxy that DID find a broker must not claim it did not"
    )


# ======================================================================================
# THE REGISTRATION ITSELF — otherwise the fix is one revert away from silent
# ======================================================================================


async def test_main_registers_the_PROXY_and_not_the_broker_object():
    """A structural arm on the ONE call site, because reverting it turns every behavioural
    arm above green while production is broken again: they all construct their own proxy."""
    import ast
    import inspect

    import app.main as main_mod

    tree = ast.parse(inspect.getsource(main_mod))
    calls = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_adapter"
    ]
    assert len(calls) == 1, f"expected exactly one registration site, found {calls}"
    assert "LiveLoopBrokerProxy" in calls[0], (
        f"main.py must register the proxy, not the broker object: {calls[0]}"
    )
    assert "live_loop.paper" not in calls[0], (
        "registering `live_loop.paper` hands the manager an object the loop will rebind — "
        "B221 exactly, and every behavioural arm in this file would stay green"
    )
