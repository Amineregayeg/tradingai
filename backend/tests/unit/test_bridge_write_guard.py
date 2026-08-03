"""The bridge's write guard — the last line before a real order (task 4.5).

This tests `is_write_request` from deploy/cft-bridge/bridge.py, loaded directly
from the deploy directory: the bridge runs as its own container and is not an
importable part of the backend package, but its guard is the single most
safety-critical function in the repo and must not go untested for that reason.

WHY THE BRIDGE GUARDS AT ALL
The other three protections — ExecutionService's is_simulation assert,
_make_adapter's ALLOW_LIVE_TRADING gate, and the adapter's observe_only check —
all sit UPSTREAM of the bridge process. The bridge is the last hop before a
funded account, so "the backend will have checked" is exactly the assumption
defence in depth exists to refuse.

THE ASYMMETRY THAT SHAPES THE DESIGN
A false negative places a real order on real money. A false positive blocks a
read the app can retry. So the guard is deliberately over-broad: any non-GET is
a write, and any write-shaped path is a write even over GET.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_BRIDGE = Path(__file__).resolve().parents[2].parent / "deploy" / "cft-bridge" / "bridge.py"


def _load_guard():
    """Import bridge.py without its aiohttp/playwright dependencies.

    Those are installed in the bridge container, not the backend venv. The guard
    is pure logic, so stub the imports rather than skip the tests — a
    safety-critical function that is only tested "when convenient" is untested.
    """
    import sys
    import types

    stubs = {}
    for name in ("aiohttp", "playwright", "playwright.async_api"):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            if name == "aiohttp":
                mod.web = types.SimpleNamespace(
                    Application=object, Request=object, Response=object,
                    json_response=lambda *a, **k: None, get=None, post=None,
                    run_app=lambda *a, **k: None,
                )
            if name == "playwright.async_api":
                mod.async_playwright = lambda: None
            sys.modules[name] = mod
            stubs[name] = mod

    spec = importlib.util.spec_from_file_location("cft_bridge_under_test", _BRIDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bridge = _load_guard()


# ---------------------------------------------------------------------------
# Writes must be recognised
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "/mtr-api/uuid/position/open",
    "/mtr-api/uuid/position/close",
    "/mtr-api/uuid/position/edit",
    "/mtr-api/uuid/position/modify",
    "/mtr-api/uuid/order",
    "/mtr-api/uuid/positions/close",
])
def test_position_paths_are_writes(path):
    assert bridge.is_write_request("POST", path) is True


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post", "put"])
def test_any_non_get_method_is_a_write(method):
    """Enumerating only POST would be an obvious gap — a write dressed as PUT is
    still a write."""
    assert bridge.is_write_request(method, "/mtr-api/uuid/balance") is True


def test_a_write_path_over_get_is_still_a_write():
    """Some Match-Trader routes accept actions over GET. A method-only check
    would sail straight past that."""
    assert bridge.is_write_request("GET", "/mtr-api/uuid/position/open") is True


def test_case_and_query_do_not_evade_the_guard():
    assert bridge.is_write_request("GET", "/mtr-api/uuid/Position/Open?x=1") is True
    assert bridge.is_write_request("POST", "/MTR-API/uuid/ORDER") is True


# ---------------------------------------------------------------------------
# Reads must still work — an over-tight guard breaks the dashboard
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "/mtr-api/uuid/balance",
    "/mtr-api/uuid/open-positions",
    "/mtr-api/uuid/active-orders",
    "/mtr-api/uuid/group",
    "/mtr-api/uuid/candles?symbol=BTCUSDT.cft&interval=H1",
    "/mtr-api/uuid/symbol-categories",
])
def test_read_paths_are_not_writes(path):
    assert bridge.is_write_request("GET", path) is False


def test_active_orders_read_is_allowed():
    """'/order' is a write fragment, but '/active-orders' is the READ the
    dashboard depends on. If this ever flips to True, positions stop displaying.
    """
    assert bridge.is_write_request("GET", "/mtr-api/uuid/active-orders") is False


# ---------------------------------------------------------------------------
# Default posture
# ---------------------------------------------------------------------------
def test_trading_is_disabled_by_default():
    """With BRIDGE_ALLOW_TRADING unset, the bridge must not permit writes.

    The test environment sets no such variable, so this asserts the real
    out-of-the-box posture rather than a contrived one.
    """
    import os
    assert os.getenv("BRIDGE_ALLOW_TRADING") is None
    assert bridge.BRIDGE_ALLOW_TRADING is False


def test_the_flag_needs_an_explicit_true(monkeypatch):
    """Anything other than a deliberate "true" must leave trading off — a
    half-set variable ("1", "yes", "") must not arm a funded account."""
    for value in ["", "0", "1", "yes", "TRUE ", "no", "false", "maybe"]:
        monkeypatch.setenv("BRIDGE_ALLOW_TRADING", value)
        reloaded = _load_guard()
        expected = value.strip().lower() == "true"
        assert reloaded.BRIDGE_ALLOW_TRADING is expected, (
            f"BRIDGE_ALLOW_TRADING={value!r} produced {reloaded.BRIDGE_ALLOW_TRADING}"
        )


def test_every_known_cft_write_endpoint_is_covered():
    """The adapter's own docstring lists the trading endpoints. If one is added
    there without a matching fragment here, the guard has a hole."""
    from app.services.broker import cryptofundtrader as cft

    documented = [
        line for line in (cft.__doc__ or "").splitlines()
        if "POST" in line and "position/" in line
    ]
    assert documented, "the adapter no longer documents its write endpoints"
    for line in documented:
        path = line.split()[1]
        assert bridge.is_write_request("POST", path) is True, f"unguarded: {path}"
