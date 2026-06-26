"""Cross-adapter contract tests.

Every concrete BrokerAdapter must satisfy the same interface so the BrokerManager,
kill switch, and price pipeline can treat all brokers polymorphically. Adding a new
broker means adding it here — if it doesn't conform, this suite fails.
"""
from __future__ import annotations

import inspect

import pytest

from app.services.broker.base import BrokerAdapter
from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter
from app.services.broker.oanda import OANDAAdapter

# (broker_name, factory) for every concrete adapter the app ships.
ADAPTERS = [
    ("oanda", lambda: OANDAAdapter(api_key="k", account_id="a", environment="practice")),
    (
        "cryptofundtrader",
        lambda: CryptoFundTraderAdapter(
            email="e", password="p", base_url="https://host/mtr-api/uuid"
        ),
    ),
]
IDS = [a[0] for a in ADAPTERS]

# The interface every adapter must expose (mirrors BrokerAdapter abstract methods).
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


@pytest.mark.parametrize("name,factory", ADAPTERS, ids=IDS)
def test_adapter_is_concrete_subclass(name, factory):
    adapter = factory()  # raises TypeError if any abstract method is unimplemented
    assert isinstance(adapter, BrokerAdapter)
    assert type(adapter).__abstractmethods__ == frozenset()


@pytest.mark.parametrize("name,factory", ADAPTERS, ids=IDS)
def test_adapter_declares_identity(name, factory):
    adapter = factory()
    assert adapter.broker_name == name
    assert adapter.broker_name != "unknown"
    assert isinstance(adapter.default_pairs, list)


@pytest.mark.parametrize("name,factory", ADAPTERS, ids=IDS)
def test_adapter_implements_full_interface(name, factory):
    adapter = factory()
    for method in REQUIRED_METHODS:
        attr = getattr(adapter, method, None)
        assert attr is not None and callable(attr), f"{name} missing {method}"


@pytest.mark.parametrize("name,factory", ADAPTERS, ids=IDS)
def test_async_methods_are_coroutines(name, factory):
    adapter = factory()
    for method in REQUIRED_METHODS:
        assert inspect.iscoroutinefunction(getattr(adapter, method)), (
            f"{name}.{method} must be async"
        )


def test_manager_factory_builds_every_broker():
    """The manager factory must resolve each shipped broker identifier."""
    from app.services.broker.manager import _make_adapter

    oanda = _make_adapter("oanda", {"api_key": "k"}, "acc", "practice")
    assert oanda.broker_name == "oanda"

    cft = _make_adapter(
        "cryptofundtrader",
        {"email": "e", "password": "p", "base_url": "https://host/mtr-api/uuid"},
        "acc",
        "live",
    )
    assert cft.broker_name == "cryptofundtrader"
    # Prop-firm broker defaults to observe-only for safety.
    assert cft.observe_only is True


def test_manager_factory_rejects_unknown_broker():
    from app.services.broker.manager import _make_adapter

    with pytest.raises(ValueError):
        _make_adapter("definitely-not-a-broker", {}, "acc", "practice")
