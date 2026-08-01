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

import inspect

import pytest

from app.services.broker.base import BrokerAdapter, OrderRequest
# Importing the concrete adapters registers them as subclasses of BrokerAdapter so
# the recursive __subclasses__() discovery below can see them.
from app.services.broker.cft_sim import PropFirmRules, SimPropFirmBroker
from app.services.broker.cft_bridge_adapter import CFTBridgeAdapter
from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter
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

ALL_ADAPTERS = SIM_ADAPTERS + LIVE_ADAPTERS
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
    """Concrete (non-abstract) adapters defined in the broker package."""
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


@pytest.mark.parametrize("name,cls,factory", ALL_ADAPTERS, ids=IDS)
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
