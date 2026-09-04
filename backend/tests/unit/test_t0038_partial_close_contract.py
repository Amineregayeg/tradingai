"""T-0038 half 1 — no adapter may accept a partial close and silently complete it.

`BrokerAdapter.close_position`'s abstract signature has carried
`lot_size: Partial close volume. None means close all units.` since it was written. **Both LIVE
adapters honour it; both SIMULATED adapters accepted the argument, never read it, settled the whole
position and returned success.**

> **So a 70/30 exit model validated in simulation was validated against a broker that cannot take a
> partial — and the broker reported success.** The realised-R distribution such a model produces in
> paper could not occur live, and nothing in the record said so. **A simulator that silently
> disagrees with production in the direction of the thing being tested.**

**THE CONTRACT ARM IS OVER EVERY ADAPTER, NOT THE TWO BEING FIXED.** Fixing two instances leaves the
class open: a third simulated broker reintroduces it, and the silent version is indistinguishable
from success. *Make the class unrepresentable, not its first instance absent.*
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
from pathlib import Path

import pytest

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import BrokerAdapter, OrderRequest


def _all_adapters() -> list[type]:
    """Every concrete `BrokerAdapter`, found by importing the package rather than listing them.

    **DERIVED, not enumerated:** a new adapter is covered on the day it is added, which is the
    whole point of a contract-level arm. `T-0032`'s lesson — a hand-written population excludes
    by construction exactly the member it most needs to catch.
    """
    import app.services.broker as pkg

    for module in pkgutil.iter_modules(pkg.__path__):
        try:
            importlib.import_module(f"app.services.broker.{module.name}")
        except Exception:  # noqa: BLE001 - an unimportable adapter is not this test's subject
            continue

    # RESTRICTED TO THE PRODUCTION PACKAGE, AND THE RESTRICTION IS A FIX RATHER THAN A
    # CONVENIENCE. `__subclasses__()` sees whatever has been IMPORTED, so an unrestricted
    # population changes with the pytest selection: `-k paper` gave four adapters and the full
    # suite gave five, because test doubles under `tests/` subclass BrokerAdapter too.
    #
    # **A guard whose denominator depends on what else ran is not a guard.** The population is
    # now every adapter defined under `app.services.broker`, which is deterministic, and
    # `test_there_are_adapters_to_check` pins the exact membership so a NEW production adapter
    # fails by name rather than joining silently.
    #
    # NOTED, NOT ENFORCED: `tests/unit/test_execution_fill_sizing.py`'s `FakeBroker` DOES accept
    # lot_size and discard it. It is a test double, so it is not a production risk -- but a
    # strategy test that validated a partial-exit model against it would reproduce exactly the
    # defect this task closed, in a fixture. Recorded in the work report.
    # TRANSITIVE. `B296`: this was `BrokerAdapter.__subclasses__()`, which returns DIRECT
    # subclasses only, so `CFTBridgeAdapter` — which subclasses `CryptoFundTraderAdapter` to
    # swap the transport, and is what `manager.py:70` returns whenever a bridge is configured —
    # was never in the population. It could not fail the membership pin below either: a class
    # that never enters the set cannot change it.
    #
    # **AND THE COUNT DID NOT MOVE.** The recursive derivation in
    # `test_broker_contract.py::_concrete_broker_subclasses` returned FIVE adapters and this one
    # returned FIVE, differing by two members in opposite directions — the bridge missing here,
    # the abstract proxy missing there. Two populations of the same size and different
    # membership, in the same suite, one of them advertised as the derived-not-enumerated fix.
    #
    # Measured before widening: the bridge overrides none of the contract methods today
    # (`_parse_group`, `bridge_status`, `connect`, `disconnect`, `broker_name` only), so it
    # passed on its parent's source the moment it was admitted. **The hole was latent, not
    # live** — and an override lands uncovered and silent, which is the state this file exists
    # to make impossible.
    seen: list[type] = []

    def _descend(cls: type) -> None:
        for sub in cls.__subclasses__():
            if sub.__module__.startswith("app.services.broker.") and sub not in seen:
                seen.append(sub)
            _descend(sub)

    _descend(BrokerAdapter)
    return seen


def _reads_lot_size(cls: type) -> bool:
    """Does this adapter's `close_position` body actually READ `lot_size`?

    AST over the method source. **A signature that accepts the parameter proves nothing** — that
    is exactly what both simulators had, and it is why this checks the body.
    """
    source = inspect.getsource(cls.close_position)
    tree = ast.parse(source.lstrip() if source.startswith(" ") else source)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return "lot_size" in names


# ---------------------------------------------------------------------------
# THE CONTRACT ARM — over every adapter
# ---------------------------------------------------------------------------


def test_there_are_adapters_to_check():
    """MUST-HIT. A contract arm over an empty set passes and guards nothing."""
    names = {c.__name__ for c in _all_adapters()}
    assert names == {
        "PaperBroker", "SimPropFirmBroker", "OANDAAdapter", "CryptoFundTraderAdapter",
        # T-0062/B221. A forwarding proxy, and it belongs in the guarded set precisely
        # BECAUSE it forwards: `close_position` passes `lot_size` straight through, so a
        # proxy that dropped it would complete a partial request in full and return success
        # — this contract's exact defect, reintroduced at a layer the original arms could
        # not see. Verified: `_reads_lot_size` is True for it.
        "LiveLoopBrokerProxy",
        # `B296`. Admitted when the derivation above became transitive. It reaches the SAME
        # venue as `CryptoFundTraderAdapter` through a different transport (a real browser,
        # because Cloudflare fingerprints the TLS handshake), inherits `close_position`
        # unchanged, and is the class `manager.py:70` constructs when a bridge is configured.
        "CFTBridgeAdapter",
        # `T-0106`. Named deliberately, which is what this pin is for — the arm FIRED AS
        # INTENDED when the module landed rather than being broken and repaired. Its
        # `close_position` refuses in this phase and READS `lot_size` to say which request it
        # refused: a caller asking for 30% and a caller asking for everything must not get the
        # identical message, which is the ambiguity this contract exists to prevent.
        "MetaTrader5Adapter",
    }, (
        f"the production adapter set changed: {sorted(names)}. A new adapter must be added here "
        "deliberately — joining the guarded set silently is how a member goes unwatched."
    )


@pytest.mark.parametrize("adapter", _all_adapters(), ids=lambda c: c.__name__)
def test_no_adapter_accepts_a_partial_request_and_ignores_it(adapter):
    """THE CLASS-LEVEL PROPERTY. Every adapter's `close_position` must READ `lot_size`.

    **An adapter that accepts it and does not read it completes a partial request in full and
    returns success** — which is indistinguishable from having honoured it, at the call site and
    in the response. That is the state both simulators were in.
    """
    signature = inspect.signature(adapter.close_position)
    assert "lot_size" in signature.parameters, (
        f"{adapter.__name__}.close_position does not accept lot_size — it no longer satisfies "
        "BrokerAdapter's abstract signature"
    )
    assert _reads_lot_size(adapter), (
        f"{adapter.__name__}.close_position ACCEPTS lot_size and never reads it. Either honour "
        "it (remainder open) or refuse loudly; silently completing a partial request in full is "
        "indistinguishable from success."
    )


def test_the_reader_check_can_actually_fail():
    """CONTROL PAIR on the instrument. An all-clean sweep proves nothing unless the sweep has
    been shown to find something."""

    class _Discards(BrokerAdapter):  # type: ignore[misc]
        async def close_position(self, position_id: str, lot_size: float | None = None) -> dict:
            return {"status": "closed", "position_id": position_id}

    assert not _reads_lot_size(_Discards), "the reader check cannot see a discarded parameter"
    assert _reads_lot_size(__import__(
        "app.services.broker.paper", fromlist=["PaperBroker"]
    ).PaperBroker), "the reader check cannot see a parameter that IS read"


def test_the_population_DESCENDS_and_is_not_merely_the_direct_children():
    """CONTROL ON THE DERIVATION ITSELF, and it is a different instrument from the one above.

    `test_the_reader_check_can_actually_fail` proves the PREDICATE can find something. It says
    nothing about the POPULATION the predicate is applied to, and `B296` was entirely in the
    population: `__subclasses__()` is not transitive, so an adapter that subclasses an adapter
    was never handed to the predicate at all. **A guard is only as wide as its scanner**, and
    every arm in this file was silently one member narrow.

    Keyed to a REAL grandchild rather than a fixture, because a locally-defined subclass is
    filtered out by the `app.services.broker.` restriction and would prove nothing here.
    """
    from app.services.broker.cft_bridge_adapter import CFTBridgeAdapter

    assert CFTBridgeAdapter not in BrokerAdapter.__subclasses__(), (
        "this control assumes CFTBridgeAdapter is a GRANDCHILD; if it became a direct subclass "
        "the assertion below would pass under a non-transitive derivation and stop guarding"
    )
    assert CFTBridgeAdapter in _all_adapters(), (
        "the population does not descend past the direct subclasses, so every contract arm in "
        "this file skips the adapter manager.py builds when a bridge is configured"
    )


def test_the_abstract_contract_still_declares_partial_close():
    """The arm above asserts adapters honour a contract. This asserts the contract is still
    there — without it the arm is enforcing a convention nobody declared."""
    doc = inspect.getdoc(BrokerAdapter.close_position) or ""
    assert "lot_size" in inspect.signature(BrokerAdapter.close_position).parameters
    assert "partial" in doc.lower(), f"the declared contract changed: {doc!r}"


@pytest.mark.parametrize("module,fragment", [
    ("app.services.broker.oanda", "longUnits"),
    ("app.services.broker.cryptofundtrader", "volume"),
])
def test_the_live_adapters_send_the_partial_to_the_venue(module, fragment):
    """MUST-HIT on the other side of the divergence: the LIVE adapters really do honour it, so
    the simulators' discard was a difference from PRODUCTION and not a shared limitation."""
    source = inspect.getsource(importlib.import_module(module))
    body = source[source.index("async def close_position"):]
    body = body[: body.index("\n    async def ", 10)] if "\n    async def " in body[10:] else body
    assert "lot_size" in body and fragment in body, (
        f"{module} no longer sends the partial volume to the venue"
    )


# ---------------------------------------------------------------------------
# BEHAVIOUR — the two adapters that can be driven
# ---------------------------------------------------------------------------


async def _open(broker, *, units=10.0, entry=100.0):
    broker._marks["BTC/USD"] = entry
    result = await broker.place_order(OrderRequest(
        pair="BTC/USD", direction=DirectionType.LONG, order_type=OrderType.MARKET,
        lot_size=units, sl=entry * 0.9, tp=entry * 1.2,
    ))
    return result["position_id"]


@pytest.mark.asyncio
async def test_a_partial_close_leaves_the_remainder_open():
    """THE MUST-FIRE ARM. Before this task the same call closed everything and said `status: ok`."""
    from app.services.broker.paper import PaperBroker

    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker)
    broker._marks["BTC/USD"] = 120.0

    event = await broker.close_position(pid, lot_size=7.0)

    assert event["units"] == 7.0
    assert event["remaining_units"] == 3.0
    assert event["partial"] is True
    assert event["pnl"] == pytest.approx(140.0), "pnl must be on the CLOSED units only"

    still_open = await broker.get_positions()
    assert [float(p.lot_size) for p in still_open] == [3.0], (
        "the remainder did not stay open — this is the defect the task exists to close"
    )


@pytest.mark.asyncio
async def test_the_record_distinguishes_a_partial_from_a_full_close():
    """A record in which the two look alike is the defect one layer up: the caller could not tell
    a honoured partial from a silent full close, and neither could an auditor."""
    from app.services.broker.paper import PaperBroker

    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker)
    broker._marks["BTC/USD"] = 120.0

    partial = await broker.close_position(pid, lot_size=7.0)
    remainder = await broker.close_position(pid)

    assert partial["partial"] is True and remainder["partial"] is False
    assert remainder["units"] == 3.0 and remainder["remaining_units"] == 0.0
    assert await broker.get_positions() == []
    assert broker.balance == pytest.approx(10_200.0), (
        "the two settlements must total the whole position's pnl"
    )


@pytest.mark.asyncio
async def test_a_zero_or_negative_lot_size_is_REFUSED_rather_than_read_as_close_everything():
    """`lot_size=0` means the caller asked for nothing. Returning a full close would be the same
    silent substitution this method was changed to remove."""
    from app.services.broker.paper import PaperBroker

    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker)

    for bad in (0, -1.0):
        result = await broker.close_position(pid, lot_size=bad)
        assert result["status"] == "refused", f"lot_size={bad} was not refused"

    assert len(await broker.get_positions()) == 1, "a refused close must not close anything"


@pytest.mark.asyncio
async def test_a_lot_size_at_or_above_the_position_closes_it_whole():
    """MUST-MISS on the partial path: asking for everything is not a partial."""
    from app.services.broker.paper import PaperBroker

    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker, units=10.0)
    broker._marks["BTC/USD"] = 120.0

    event = await broker.close_position(pid, lot_size=999.0)
    assert event["partial"] is False
    assert event["units"] == 10.0
    assert await broker.get_positions() == []


@pytest.mark.asyncio
async def test_the_sim_prop_broker_honours_a_partial_too():
    """The same fix in the other simulator — two instances of one defect, both closed."""
    from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker

    price = {"BTC/USD": 100.0}

    async def _price(pair: str) -> float:
        return price[pair]

    broker = SimPropFirmBroker(
        rules=PropFirmRules(starting_balance=10_000.0), price_source=_price
    )
    result = await broker.place_order(OrderRequest(
        pair="BTC/USD", direction=DirectionType.LONG, order_type=OrderType.MARKET,
        lot_size=10.0, sl=90.0, tp=120.0,
    ))
    price["BTC/USD"] = 120.0

    event = await broker.close_position(result["position_id"], lot_size=7.0)
    assert event["partial"] is True and event["remaining_units"] == 3.0
    assert len(await broker.get_positions()) == 1


@pytest.mark.asyncio
async def test_the_remainder_keeps_its_stop_and_target_untouched():
    """EXIT-003 IS `OPEN`. Moving the runner's stop after a partial is behaviour nobody has
    ruled on, and inventing it here would be `GATE-014`'s shape — a placeholder cited later as
    doctrine. The remainder rides with the levels it was opened with."""
    from app.services.broker.paper import PaperBroker

    broker = PaperBroker(starting_balance=10_000.0)
    pid = await _open(broker, units=10.0, entry=100.0)
    before = broker._positions[pid]
    sl, tp = before.sl, before.tp
    broker._marks["BTC/USD"] = 120.0

    await broker.close_position(pid, lot_size=7.0)
    after = broker._positions[pid]

    assert (after.sl, after.tp) == (sl, tp), "the runner's levels moved — that is EXIT-003, OPEN"
    assert after.entry == before.entry, "the remainder keeps its original entry for R maths"
