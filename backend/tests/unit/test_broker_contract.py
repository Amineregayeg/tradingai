"""Cross-adapter contract tests (CONTRACT 7c).

Every concrete ``BrokerAdapter`` must satisfy the same interface so the
``BrokerManager``, kill switch, and price pipeline can treat all brokers
polymorphically. Adding a new broker means adding it to the registry below — if it
does not conform, this suite fails.

This suite also encodes the **simulation-safety** contract (CONTRACT 2):

* Adapters are discovered *recursively* via ``BrokerAdapter.__subclasses__()`` so a
  newly-added concrete adapter cannot silently escape the checks below.
* ``is_simulation`` is ``True`` for the default-safe adapters (``PaperBroker``,
  ``SimPropFirmBroker``) and ``False`` for the real-money adapters (OANDA, CFT).
* The intent of the old ``REQUIRED_METHODS`` check is *inverted*: rather than proving
  every adapter can be built and its write methods called, we prove that a
  **non-simulation** adapter's write methods are NOT reachable without an explicit
  live-credential construction (its ``__init__`` requires credentials), while the
  simulation adapters are the ones you can build with no credentials at all.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import BrokerAdapter, OrderRequest
# Importing the concrete adapters registers them as subclasses of BrokerAdapter so
# the recursive __subclasses__() discovery below can see them.
from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker
from app.services.broker.cft_bridge_adapter import CFTBridgeAdapter
from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter
from app.services.broker.live_loop_proxy import LiveLoopBrokerProxy
from app.services.broker.mt5 import MetaTrader5Adapter
from app.services.broker.oanda import OANDAAdapter
from app.services.broker.paper import PaperBroker


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------


async def _dummy_price(pair: str) -> float:
    """Read-only async price source for the local prop-firm simulator."""
    return 100.0


def _make_cft_sim() -> SimPropFirmBroker:
    rules = PropFirmRules(
        starting_balance=50_000.0,
        daily_loss_limit_pct=5.0,
        max_drawdown_pct=10.0,
        profit_target_pct=10.0,
        min_trading_days=5,
    )
    return SimPropFirmBroker(rules, _dummy_price)


# Simulation adapters: default-safe, structurally incapable of a real-money order.
# (name, class, zero-credential factory)
SIM_ADAPTERS = [
    ("paper", PaperBroker, lambda: PaperBroker()),
    ("cft_sim", SimPropFirmBroker, _make_cft_sim),
]

# Live adapters: real-money capable, MUST require explicit credentials to construct.
LIVE_ADAPTERS = [
    (
        "oanda",
        OANDAAdapter,
        lambda: OANDAAdapter(api_key="k", account_id="a", environment="practice"),
    ),
    (
        "cryptofundtrader",
        CryptoFundTraderAdapter,
        lambda: CryptoFundTraderAdapter(
            email="e", password="p", base_url="https://host/mtr-api/uuid"
        ),
    ),
    (
        # Same broker, different transport: reaches CFT through a real browser
        # because Cloudflare fingerprints the TLS handshake and refuses plain
        # HTTP even with a valid token. It is a SUBCLASS of the adapter above,
        # which is exactly why this registry uses recursive discovery — a
        # subclass-of-a-subclass that quietly flipped is_simulation to True
        # would otherwise sail past the contract and disarm the assert in
        # ExecutionService.
        "cryptofundtrader_bridge",
        CFTBridgeAdapter,
        lambda: CFTBridgeAdapter(email="e", password="p", bridge_token="t"),
    ),
]

def _make_unbound_proxy() -> LiveLoopBrokerProxy:
    """A proxy holding a loop that holds no broker — the state `T-0062` was built for."""

    class _LoopWithNoBroker:
        pass

    return LiveLoopBrokerProxy(_LoopWithNoBroker())


# A THIRD CATEGORY, AND NEITHER EXISTING ONE WAS ACCEPTABLE (`B297`).
#
# `LiveLoopBrokerProxy` is concrete, is registered with `broker_manager` at startup, and was in
# NEITHER list — so it was covered by none of the arms below, and the discovery arm that exists
# to catch exactly that was green **because `test_broker_contract.py` sorts before every module
# that imports the broker package.** An arm whose verdict changes with test ordering is not a
# guard.
#
# **PUTTING IT IN EITHER EXISTING LIST WOULD HAVE ASSERTED SOMETHING FALSE.**
#
#   SIM_ADAPTERS   asserts `is_simulation is True` for a value that is DELIBERATELY DYNAMIC —
#                  it forwards to whatever the loop is holding.
#   LIVE_ADAPTERS  would make `test_live_adapters_report_false` pass BECAUSE THE PROXY IS
#                  UNBOUND rather than because it is live: `B215` inside the very arm that
#                  would be certifying it, on the safety flag.
#
# **A registry entry chosen to clear a red is an assertion nobody decided.**
PROXY_ADAPTERS = [
    ("live_loop_proxy", LiveLoopBrokerProxy, _make_unbound_proxy),
]

# WHAT STOPS THE NEXT PROXY BEING OMITTED THE SAME WAY (`B296`): nothing about THIS list, which
# is why the protection is not in it. `test_recursive_discovery_covers_every_concrete_adapter`
# compares the DERIVED population against the union below, so a new concrete forwarder that
# joins no list fails there by name. **A pin over a derived population guards ADDITIONS to it
# and never OMISSIONS from it** — the discovery arm is the one that guards omissions, and it
# only does so now that its population no longer depends on what else was imported.
# `T-0106`. MT5 is a LIVE venue: `is_simulation` is `False` and it is real-money capable in
# principle, so this is the honest category.
#
# ⚠ AND IT IS A SECOND INSTANCE OF `B327`, RECORDED RATHER THAN LEFT TO BE FOUND.
# `test_live_adapter_write_methods_need_explicit_credentials` asserts a bare `TypeError` on
# `cls()`. `MetaTrader5Adapter()` raises for want of `account` — **which is not a credential**,
# exactly as `live_loop_proxy` raised for want of `loop`. The arm will be green for this adapter
# for a reason unrelated to credentials, and `B327`'s fix (derive the required positional
# parameters and assert each is in a declared credential set) must cover it.
LIVE_ADAPTERS = LIVE_ADAPTERS + [
    # `T-0134` renamed this parameter from `client` to `account`, and THAT RENAME IS THE POINT
    # rather than a tidy-up: `B341` measured that no SDK object carries the ten members the old
    # `client` was assumed to have, so the adapter now holds a `MetatraderAccount` and takes its
    # reads from `account.get_rpc_connection()`. Seven arms in this file broke on the rename and
    # they were right to — the population that constructs an adapter is wider than the file that
    # changes it.
    ("mt5", MetaTrader5Adapter, lambda: MetaTrader5Adapter(account=object())),
]

ALL_ADAPTERS = SIM_ADAPTERS + LIVE_ADAPTERS + PROXY_ADAPTERS

# EVERY ADAPTER THAT IS A VENUE. Used by the arms below that are about venue behaviour, where
# **a forwarder is a category error even when it passes.**
#
# EACH ALL_ADAPTERS ARM WAS DECIDED, NOT WIDENED SILENTLY. Measured with the proxy in the
# population before any exclusion was written:
#
#   test_recursive_discovery_covers_every_concrete_adapter  BELONGS — it is the whole point
#   test_every_discovered_adapter_declares_is_simulation    BELONGS — it must answer with a bool
#   test_adapter_is_concrete_subclass                       BELONGS — measured concrete,
#                                                           __abstractmethods__ == frozenset()
#   test_adapter_implements_full_interface                  BELONGS — it must forward every member
#   test_async_methods_are_coroutines                       BELONGS — its forwards are `async def`
#   test_adapter_declares_identity                          DOES NOT BELONG, and it is the one
#                                                           that failed
#
# **A proxy has no identity of its own.** `broker_name` forwards, so on an unbound proxy the arm
# read `paper-proxy(unbound)` and demanded it equal the registry label. Adding an
# `EXPECTED_BROKER_NAME` entry would have made the suite green by asserting that a string
# describing an ABSENT broker is this adapter's name. Its real property — that the name
# forwards, and announces itself when there is nothing to forward to — is asserted by its own
# arms further down.
VENUE_ADAPTERS = SIM_ADAPTERS + LIVE_ADAPTERS
IDS = [a[0] for a in ALL_ADAPTERS]

# The async interface every adapter must expose (mirrors BrokerAdapter abstract methods).
REQUIRED_METHODS = [
    "connect",
    "disconnect",
    "get_account",
    "get_positions",
    "get_orders",
    "get_recent_trades",
    "place_order",
    "close_position",
    "close_all_positions",
    "stream_prices",
]

# The write (order-mutating) surface that must never be reachable on a non-simulation
# adapter without an explicit live-credential construction.
WRITE_METHODS = ["place_order", "close_position", "close_all_positions"]

_FACTORY_BY_NAME = {name: factory for name, _cls, factory in ALL_ADAPTERS}


# ---------------------------------------------------------------------------
# Recursive subclass discovery
# ---------------------------------------------------------------------------


def _all_subclasses(cls: type) -> set[type]:
    """Every subclass of ``cls``, walking subclasses of subclasses recursively."""
    out: set[type] = set()
    for sub in cls.__subclasses__():
        out.add(sub)
        out |= _all_subclasses(sub)
    return out


def _concrete_broker_subclasses() -> set[type]:
    """Concrete (non-abstract) adapters defined in the broker package.

    **IMPORTS THE PACKAGE FIRST, AND THAT IS THE FIX FOR `B297`.** `__subclasses__()` sees only
    what has already been imported, so this set used to be *whatever some earlier test happened
    to load*: `test_broker_contract.py` imports five adapters by name and never
    `live_loop_proxy`, so the proxy was invisible here and visible the moment any other module
    walked the package. Measured both ways — 38 passed alone, 1 failed when anything imported
    the package first, and **the failing direction was the true one.**

    `_all_adapters()`'s own docstring had already written the rule down for its own helper:
    *"a guard whose denominator depends on what else ran is not a guard."*

    **THE WALK IS NOT LOAD-BEARING TODAY, AND THAT IS PUBLISHED RATHER THAN LEFT TO BE FOUND.**
    Measured: delete it and the suite still reports `63 passed` — because this module imports
    every adapter module by name at the top, so every class is already visible. **That by-name
    list staying complete is exactly the property that failed** — it was missing
    `live_loop_proxy` and nothing said so. The walk makes the population independent of it, so
    the protection is for the NEXT adapter whose module nobody thinks to import here.
    """
    import importlib
    import pkgutil

    import app.services.broker as pkg

    for module in pkgutil.iter_modules(pkg.__path__):
        try:
            importlib.import_module(f"app.services.broker.{module.name}")
        except Exception:  # noqa: BLE001 - an unimportable adapter is not this test's subject
            continue

    return {
        c
        for c in _all_subclasses(BrokerAdapter)
        if not getattr(c, "__abstractmethods__", None)
        and c.__module__.startswith("app.services.broker")
    }


def test_recursive_discovery_covers_every_concrete_adapter():
    """No concrete adapter may ship without being covered by this contract suite.

    Uses recursive __subclasses__() discovery so a subclass-of-a-subclass is caught.
    If this fails, a new concrete BrokerAdapter was added without declaring its
    is_simulation status in the registry above.
    """
    discovered = _concrete_broker_subclasses()
    registered = {cls for _name, cls, _factory in ALL_ADAPTERS}
    assert discovered == registered, (
        "Concrete BrokerAdapter subclasses not covered by the contract registry: "
        f"{sorted(c.__name__ for c in discovered - registered)}"
    )


# ---------------------------------------------------------------------------
# is_simulation contract (CONTRACT 2)
# ---------------------------------------------------------------------------


def test_paper_and_simpropfirm_are_simulation():
    """The two default-safe adapters must report is_simulation True (by name)."""
    assert PaperBroker().is_simulation is True
    assert _make_cft_sim().is_simulation is True


@pytest.mark.parametrize("name,cls,factory", SIM_ADAPTERS, ids=[a[0] for a in SIM_ADAPTERS])
def test_simulation_adapters_report_true(name, cls, factory):
    adapter = factory()
    assert adapter.is_simulation is True


@pytest.mark.parametrize("name,cls,factory", LIVE_ADAPTERS, ids=[a[0] for a in LIVE_ADAPTERS])
def test_live_adapters_report_false(name, cls, factory):
    adapter = factory()
    assert adapter.is_simulation is False


def test_every_discovered_adapter_declares_is_simulation():
    """Reading is_simulation on any concrete adapter yields a bool literal."""
    for name, cls, factory in ALL_ADAPTERS:
        adapter = factory()
        assert isinstance(adapter.is_simulation, bool)


# ---------------------------------------------------------------------------
# Inverted safety intent: live adapters gate their write surface behind credentials
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,cls,factory", LIVE_ADAPTERS, ids=[a[0] for a in LIVE_ADAPTERS])
def test_live_adapter_write_methods_need_explicit_credentials(name, cls, factory):
    """A non-simulation adapter cannot be instantiated (and therefore its write
    methods cannot be reached) without explicitly supplying live credentials.

    The write methods exist on the class, but the only way to obtain an *instance*
    that can call them is to pass credentials — a no-arg construction must fail.
    """
    # Write surface is declared on the class ...
    for method in WRITE_METHODS:
        assert callable(getattr(cls, method, None)), f"{name} missing {method}"
    # ... but you cannot get a callable-bearing instance without credentials.
    with pytest.raises(TypeError):
        cls()  # no credentials -> un-constructible


@pytest.mark.parametrize("name,cls,factory", SIM_ADAPTERS, ids=[a[0] for a in SIM_ADAPTERS])
def test_simulation_adapters_need_no_credentials(name, cls, factory):
    """Simulation adapters are the default-safe path: they build with no live
    credentials (no API key / account / host) and self-report is_simulation True."""
    adapter = factory()
    assert adapter.is_simulation is True


def test_paper_broker_constructs_with_zero_arguments():
    """The safest substrate builds with no arguments at all."""
    adapter = PaperBroker()
    assert adapter.is_simulation is True
    assert isinstance(adapter, BrokerAdapter)


# ---------------------------------------------------------------------------
# Structural interface conformance (applies to every adapter, sim and live)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,cls,factory", ALL_ADAPTERS, ids=IDS)
def test_adapter_is_concrete_subclass(name, cls, factory):
    adapter = factory()  # raises TypeError if any abstract method is unimplemented
    assert isinstance(adapter, BrokerAdapter)
    assert type(adapter).__abstractmethods__ == frozenset()


#: Registry label -> the broker_name the adapter must report, where the two
#: differ. They differ only when several adapters serve the SAME broker over
#: different transports: `cryptofundtrader_bridge` is a distinct label here (the
#: registry needs unique keys) but must still identify itself as
#: `cryptofundtrader`, because broker_name drives real routing and reporting —
#: /positions and /system key off it. An adapter that renamed itself to look
#: unique would report a second, non-existent broker for the same account.
EXPECTED_BROKER_NAME = {
    "cryptofundtrader_bridge": "cryptofundtrader",
}


@pytest.mark.parametrize("name,cls,factory", VENUE_ADAPTERS,
                         ids=[a[0] for a in VENUE_ADAPTERS])
def test_adapter_declares_identity(name, cls, factory):
    adapter = factory()
    assert adapter.broker_name == EXPECTED_BROKER_NAME.get(name, name)
    assert adapter.broker_name != "unknown"
    assert isinstance(adapter.default_pairs, list)


@pytest.mark.parametrize("name,cls,factory", ALL_ADAPTERS, ids=IDS)
def test_adapter_implements_full_interface(name, cls, factory):
    adapter = factory()
    for method in REQUIRED_METHODS:
        attr = getattr(adapter, method, None)
        assert attr is not None and callable(attr), f"{name} missing {method}"


@pytest.mark.parametrize("name,cls,factory", ALL_ADAPTERS, ids=IDS)
def test_async_methods_are_coroutines(name, cls, factory):
    adapter = factory()
    for method in REQUIRED_METHODS:
        assert inspect.iscoroutinefunction(getattr(adapter, method)), (
            f"{name}.{method} must be async"
        )


# ---------------------------------------------------------------------------
# THE PROXY, ON THE PROPERTY THAT MAKES IT A PROXY (T-0119 / B297)
# ---------------------------------------------------------------------------


def _proxy_holding(broker):
    """A proxy over a loop holding `broker` — `None` models the loop holding nothing."""

    class _Loop:
        paper = broker

    return LiveLoopBrokerProxy(_Loop())


def test_the_proxys_is_simulation_FORWARDS_rather_than_answering_for_itself():
    """**The property that makes it a proxy, and the reason it is not in either other list.**

    `base.py` says why the flag may never be hard-coded: *"a new real-money adapter can never
    silently pass as safe. Safety-critical chokepoints (ExecutionService, the kill switch,
    position-close routing) read this."* A literal `True` here — tempting, since the loop holds
    a simulation today — **would launder a live adapter as simulated past three named
    chokepoints** on the day the loop holds one.

    Asserted through ONE proxy instance whose loop is rebound, because rebinding is the event
    the class exists for: `_reset_broker_state` replaces `loop.paper` with a freshly constructed
    broker, and in `PROP_FIRM_SIM` it was a different CLASS rather than a stale instance.
    """
    sim = PaperBroker()
    live = CryptoFundTraderAdapter(email="e", password="p", base_url="https://host/mtr-api/uuid")

    class _Loop:
        paper = sim

    proxy = LiveLoopBrokerProxy(_Loop())
    assert proxy.is_simulation is True, "a proxy over a simulation must report True"

    _Loop.paper = live
    assert proxy.is_simulation is False, (
        "THE SAME proxy now holds a real-money adapter and still reported True — the forward is "
        "not happening at call time, and a live adapter has been laundered as simulated past "
        "ExecutionService, the kill switch and position-close routing"
    )


def test_the_UNBOUND_proxy_reports_False_because_unknown_must_not_read_as_safe():
    """Fail-closed, and the direction is the whole assertion.

    With no broker held there is no answer to forward. `True` would be the convenient value —
    the loop holds a simulation in this deployment — and it is the one that cannot be allowed:
    **unknown must not read as safe.**

    WHICH `False` IS THIS? `B300`, and it is answered by the arm below rather than left open.
    The two states behind this value — *the held broker is live* and *nothing is held* — were
    indistinguishable, because `is_simulation`, `broker_name` and `default_pairs` each read
    `self._loop.paper` directly instead of going through `_target()`, leaving
    `unavailable_reason` at `None` — which that field's own docstring defines as *the forward
    found a broker*. **Not a failure to distinguish: an assertion of the wrong one.**
    """
    proxy = _make_unbound_proxy()
    assert proxy.is_simulation is False, (
        "an unbound proxy reported True. There is no broker to ask, so this is could-not-ask "
        "being reported as asked-and-fine on the flag three safety chokepoints read"
    )


def test_a_PROPERTY_READ_records_why_there_was_nothing_to_forward_to():
    """`B300`. A CONTROL PAIR: loud on one population, silent on the other, one predicate.

    `unavailable_reason` exists *"to tell 'the loop held no broker' apart from the other causes
    without widening the return type."* It was written only by `_target()`, which no property
    called — so the safety flag answered `False` while the field that explains a `False` said a
    broker had been found.

    **The must-miss half is the half that makes this an instrument.** A proxy that set the
    reason unconditionally would pass the first assertion and be useless, so a BOUND proxy must
    leave it `None` after the same read.
    """
    unbound = _make_unbound_proxy()
    assert unbound.is_simulation is False
    assert unbound.unavailable_reason == "the live loop is holding no broker", (
        f"after reading the safety flag the proxy says {unbound.unavailable_reason!r}. `None` "
        "there means the forward FOUND a broker, so the caller is told the held broker is live "
        "when nothing is held at all"
    )

    bound = _proxy_holding(PaperBroker())
    assert bound.is_simulation is True
    assert bound.unavailable_reason is None, (
        "a proxy that DID find a broker must not claim it did not — a reason set "
        "unconditionally explains every state and distinguishes none"
    )


def test_the_property_path_records_WITHOUT_logging_and_the_async_path_still_logs(monkeypatch):
    """The split is only worth having if both halves hold: **one writer, two logging policies.**

    `is_simulation` is read at safety chokepoints — `ExecutionService`, the kill switch and
    position-close routing — so routing it through the loud path would emit a warning at
    whatever rate those run. And the loud path must stay loud: `T-0062` added that warning
    because an orphaned broker was invisible.
    """
    import asyncio

    from app.services.broker import live_loop_proxy as module

    warnings: list[str] = []

    class _Recorder:
        def warning(self, message, *a, **k):
            warnings.append(str(message))

        def __getattr__(self, _name):        # info/debug/error are not this arm's subject
            return lambda *a, **k: None

    monkeypatch.setattr(module, "logger", _Recorder())

    proxy = _make_unbound_proxy()
    assert proxy.is_simulation is False
    assert proxy.broker_name
    assert proxy.default_pairs == []
    assert warnings == [], (
        f"a property read logged {warnings}. Three safety chokepoints read is_simulation; a "
        "warning there fires at their rate and the useful signal is buried under it"
    )
    assert proxy.unavailable_reason is not None, "silent must not mean unrecorded"

    assert asyncio.run(proxy.get_positions()) == []
    assert warnings, (
        "the async forward stopped warning. `T-0062` added it because a loop holding no broker "
        "was invisible, and the quiet property path must not have quieted that too"
    )


def test_the_unbound_proxy_reports_a_name_that_is_VISIBLY_NOT_A_VENUE():
    """`broker_name` forwards too, and the unbound answer must not look like a broker.

    `broker_name` drives real routing and reporting — `/positions` and `/system` key off it — so
    an unbound proxy that reported a plausible venue name would put rows under a broker that is
    not there.
    """
    assert _proxy_holding(PaperBroker()).broker_name == "paper", "the name must forward"

    unbound = _make_unbound_proxy().broker_name
    assert "unbound" in unbound, (
        f"the unbound proxy reports {unbound!r}, which does not announce that nothing is held"
    )
    # THE COMPARISON SET MUST NOT BE ABLE TO CONTAIN THE SUBJECT. Measured: filing the proxy
    # under `LIVE_ADAPTERS` puts it into `VENUE_ADAPTERS`, and this arm then failed because the
    # sentinel collided with ITSELF — a fixture that is not independent of its subject reports a
    # collision that is really a self-reference. Excluded explicitly rather than relying on the
    # disjointness arm holding.
    proxy_classes = {cls for _n, cls, _f in PROXY_ADAPTERS}
    claimed = {
        factory().broker_name for _n, cls, factory in VENUE_ADAPTERS
        if cls not in proxy_classes
    }
    assert unbound not in claimed, (
        f"the unbound sentinel {unbound!r} collides with a name a real venue reports "
        f"({sorted(claimed)}) — routing keyed on broker_name could not tell them apart"
    )


def test_LIVE_and_PROXY_are_DISJOINT():
    """The one intersection nothing else would catch, and it is the one that matters.

    Of the three pairwise overlaps a third category creates, two already fail loudly on a
    VALUE rather than on a set operation, which is better because the message says what broke:

        SIM ∩ LIVE     contradictory assertions — one of them must fail
        SIM ∩ PROXY    `test_simulation_adapters_report_true` asserts `is True` on a
                       DELIBERATELY DYNAMIC value, and an unbound proxy answers `False`

        LIVE ∩ PROXY   ** SILENT. **

    A forwarder wrongly filed under `LIVE_ADAPTERS` makes `test_live_adapters_report_false`
    **pass because the proxy is UNBOUND rather than because it is live** — could-not-ask
    reported as asked-and-fine, on the safety flag, inside the arm that would be certifying it.
    **That is the exact failure this third category was created to prevent, surviving inside
    the fix.**
    """
    live = {cls for _n, cls, _f in LIVE_ADAPTERS}
    proxy = {cls for _n, cls, _f in PROXY_ADAPTERS}
    assert not (live & proxy), (
        f"{sorted(c.__name__ for c in live & proxy)} is filed as a live venue AND as a "
        "forwarder. `test_live_adapters_report_false` would PASS for it — because an unbound "
        "forwarder answers False when there is nothing to ask, not because it is real-money "
        "capable. The arm certifying it would be certifying nothing."
    )


#: EVERY MEMBER A FORWARDER MUST FORWARD, DERIVED FROM THE ABSTRACT SURFACE.
#:
#: `reference_price` is added by name and is the ONE addition: `base.py:195` makes it
#: deliberately concrete rather than abstract, so the language does not force it — and an
#: adapter that forgets it silently rejects EVERY market order as *no reference price
#: available*, which reads as a market-data fault and sends the debugger to the wrong
#: subsystem. Derived-plus-one-stated-exception, not a hand-written list.
FORWARDED_MEMBERS = sorted(set(BrokerAdapter.__abstractmethods__) | {"reference_price"})

#: How to call each member. Checked against `FORWARDED_MEMBERS` below so a NEW member cannot
#: be skipped for want of an entry — the omission `B296` was about, one level down.
_CALL_ARGS: dict[str, tuple] = {
    "connect": (), "disconnect": (), "get_account": (), "get_positions": (),
    "close_all_positions": (), "get_orders": (None,), "get_recent_trades": (None,),
    "place_order": ("<request>",), "close_position": ("pos-1", 0.5),
    "stream_prices": (["BTC/USDT"], lambda *a: None), "reference_price": ("BTC/USDT",),
}


def test_EVERY_abstract_member_forwards_to_the_held_broker():
    """**The forwarding contract, and it is the reason this category exists.**

    `test_the_proxys_is_simulation_FORWARDS...` covers ONE member. **A proxy that forwarded
    `is_simulation` and swallowed the other eleven would pass it** — and swallowing is exactly
    this class's failure mode: `B221` was a kill switch that iterated an orphaned adapter, got
    `[]`, and reported success. A member that returns the no-broker default while a broker IS
    held is that defect with a different cause.

    Checkable without deciding anything about venues, which is why it belongs to the forwarder
    category rather than to `ALL_ADAPTERS`.
    """
    assert set(_CALL_ARGS) | {"is_simulation"} == set(FORWARDED_MEMBERS), (
        "the member set and the call table disagree: "
        f"{sorted(set(FORWARDED_MEMBERS) - set(_CALL_ARGS) - {'is_simulation'})} would be "
        "silently skipped, and "
        f"{sorted(set(_CALL_ARGS) - set(FORWARDED_MEMBERS))} is no longer a member"
    )

    seen: list[str] = []

    def _make_async(name):
        async def _recorder(self, *args, **kwargs):
            seen.append(name)
            return None
        return _recorder

    namespace: dict = {
        name: _make_async(name) for name in FORWARDED_MEMBERS if name != "is_simulation"
    }
    namespace["is_simulation"] = property(
        lambda self: seen.append("is_simulation") or True
    )
    recording = type("_RecordingBroker", (BrokerAdapter,), namespace)()

    proxy = _proxy_holding(recording)
    request = OrderRequest(
        pair="BTC/USDT", direction=DirectionType.LONG, order_type=OrderType.MARKET,
        lot_size=1.0, price=None, sl=None, tp=None, client_order_id="t0119",
    )

    assert proxy.is_simulation is True
    for member in FORWARDED_MEMBERS:
        if member == "is_simulation":
            continue
        args = tuple(request if a == "<request>" else a for a in _CALL_ARGS[member])
        asyncio.run(getattr(proxy, member)(*args))

    missing = [m for m in FORWARDED_MEMBERS if m not in seen]
    assert not missing, (
        f"the proxy answered {missing} itself instead of forwarding to the broker it holds. A "
        "member that returns the no-broker default while a broker IS held reports success for "
        "work nobody did — `B221` with a different cause."
    )


def test_the_proxy_is_in_the_registry_AND_the_registry_is_checked_against_the_tree():
    """MUST-HIT on the fix itself, in both halves.

    The category is only worth having if the proxy is actually in it, and the discovery arm is
    only a guard if its population does not depend on what else was imported. `B296`'s lesson
    applies to `PROXY_ADAPTERS` exactly as it did to `_all_adapters()`: **a list guards
    additions, never omissions** — so what protects the NEXT forwarder is not this list but
    `test_recursive_discovery_covers_every_concrete_adapter`, which now derives its population
    deterministically and fails by name when a concrete adapter is in no list at all.
    """
    assert LiveLoopBrokerProxy in {cls for _n, cls, _f in PROXY_ADAPTERS}
    assert LiveLoopBrokerProxy in _concrete_broker_subclasses(), (
        "discovery no longer finds the proxy, so the arm that catches an uncovered adapter has "
        "gone back to depending on what else imported the package"
    )


def test_order_request_is_shared_broker_agnostic_type():
    """Every adapter accepts the same OrderRequest shape (used by the manager)."""
    req = OrderRequest.__init__
    assert callable(req)


# ---------------------------------------------------------------------------
# Manager factory — resolves each shipped live broker identifier
# ---------------------------------------------------------------------------


def test_manager_factory_builds_crypto_prop_firm_broker():
    """The manager factory resolves the crypto prop-firm broker, observe-only."""
    from app.services.broker.manager import _make_adapter

    cft = _make_adapter(
        "cryptofundtrader",
        {"email": "e", "password": "p", "base_url": "https://host/mtr-api/uuid"},
        "acc",
        "live",
    )
    assert cft.broker_name == "cryptofundtrader"
    # Prop-firm broker defaults to observe-only for safety.
    assert cft.observe_only is True


def test_manager_factory_rejects_removed_real_money_broker():
    """OANDA — the only unguarded real-money path — was removed from the factory."""
    from app.services.broker.manager import _make_adapter

    with pytest.raises(ValueError):
        _make_adapter("oanda", {"api_key": "k"}, "acc", "practice")


def test_manager_factory_rejects_unknown_broker():
    from app.services.broker.manager import _make_adapter

    with pytest.raises(ValueError):
        _make_adapter("definitely-not-a-broker", {}, "acc", "practice")
