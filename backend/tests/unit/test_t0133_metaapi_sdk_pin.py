"""T-0133 — the MetaApi SDK is pinned, installed, and STILL not imported by the adapter.

**The gap this closes.** `app/services/broker/mt5.py` deliberately does not import
`metaapi_cloud_sdk` (`B328`: an adapter whose module cannot be imported is silently skipped by the
discovery walk that exists to cover it, so it would ship uncovered with the suite green). That
design is right and it has a cost: **130 tests passed against a mock while the package was absent
from requirements AND from the venv**, so the first thing a real token would have met is an
`ImportError` inside a container.

**Nothing here skips.** A `pytest.skip` when the package is missing would say *asked and fine* when
the truth is *could not ask* — `B215` on the one condition this file exists to detect. If the SDK
is not installed these arms are RED, because that is the true state.
"""
from __future__ import annotations

import ast
import sys
import pathlib
import re

import pytest
from importlib.metadata import PackageNotFoundError, version

REQUIREMENTS = pathlib.Path(__file__).resolve().parents[2] / "requirements-prod.txt"
MT5_SOURCE = pathlib.Path(__file__).resolve().parents[2] / "app" / "services" / "broker" / "mt5.py"
SDK = "metaapi-cloud-sdk"
SDK_MODULE = "metaapi_cloud_sdk"


def _pinned_versions() -> dict[str, str]:
    """Every exact pin in the production file, keyed by normalised distribution name."""
    pins: dict[str, str] = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?==(.+)$", line)
        if m:
            pins[m.group(1).lower().replace("_", "-")] = m.group(2).strip()
    return pins


def _imported_modules(source: str) -> set[str]:
    """Top-level module names imported by `source`, read STRUCTURALLY.

    AST rather than a substring search: `mt5.py` names `metaapi_cloud_sdk` in prose in a dozen
    places, and a grep-shaped guard would either match those or be tuned until it did not.
    """
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


# ======================================================================================
# The pin exists, is exact, and matches what is actually installed
# ======================================================================================


def test_the_sdk_is_PINNED_in_the_production_requirements():
    """Absent from requirements is the state T-0133 found and fixed."""
    pins = _pinned_versions()
    assert SDK in pins, (
        f"{SDK} is not pinned in {REQUIREMENTS.name}. The adapter is built and nothing can "
        "connect: the container installs from this file and mt5.py does not import the package, "
        "so its absence is invisible to every other test in this suite."
    )


def test_the_pin_is_EXACT_and_not_a_range():
    """A range would let the image drift under a vendor release nobody ran the suite against.

    `_pinned_versions` only matches `==`, so a line that became `>=29.1.1` would fail the arm
    above rather than this one — this arm states the requirement where a reader looks for it, and
    pins the exact string so a silent bump is a diff.
    """
    assert _pinned_versions()[SDK] == "29.1.1"


def test_the_INSTALLED_version_matches_the_pin():
    """The pin and the environment are two encodings of one fact (`B184`).

    CI asserts this for four strategy-critical packages only. This adapter's whole safety argument
    rests on the SDK's behaviour, so it gets the same treatment.
    """
    try:
        installed = version(SDK)
    except PackageNotFoundError:  # pragma: no cover - the failure this file exists for
        pytest.fail(
            f"{SDK} is PINNED but NOT INSTALLED. This environment does not match "
            f"{REQUIREMENTS.name}. Not skipping: a skip here would report 'could not ask' as "
            "'asked and fine', which is the collapse B215 is about."
        )
    assert installed == _pinned_versions()[SDK]


def test_the_sdk_actually_IMPORTS():
    """Resolution is not execution. A package can pin, install and still fail to import."""
    import metaapi_cloud_sdk  # noqa: F401

    from metaapi_cloud_sdk import MetaApi

    assert callable(MetaApi)


# ======================================================================================
# Coexistence — the question a dependency resolution cannot answer
# ======================================================================================


def test_httpx_and_the_SDKs_OWN_http_stacks_coexist_in_ONE_interpreter():
    """Three HTTP stacks in one image, and `python-socketio` pinned to an OLD MAJOR by the SDK.

    Production used exactly one client (`httpx`) before this pin. The SDK declares `httpx`,
    `aiohttp` AND `requests`, and drags `python-socketio==4.6.1` (5.x is current) with
    `python-engineio==3.14.2`. **A `--dry-run` proves pip can compute that set and says nothing
    about whether it runs**, so this imports them together in one interpreter.
    """
    import metaapi_cloud_sdk  # noqa: F401
    import aiohttp
    import engineio
    import httpx
    import requests
    import socketio

    assert socketio.__version__.startswith("4."), (
        "python-socketio moved off the SDK's pinned 4.x major. Re-run the coexistence check "
        "rather than assuming a resolution that succeeds also runs."
    )
    assert httpx.Client is not None and aiohttp.ClientSession is not None
    assert requests.Session is not None and engineio is not None


# ======================================================================================
# THE DESIGN GUARD — and it matters MORE now that the package is installable
# ======================================================================================


def test_mt5_does_NOT_import_the_sdk_at_module_scope():
    """`B328`. The reason for the injected client, pinned now that breaking it is easy.

    Before T-0133 an `import metaapi_cloud_sdk` in this file would have raised immediately and
    been noticed. **Now the package is installed, so adding that import would WORK locally and in
    CI** — and would reintroduce exactly the condition B328 measured: the discovery walk in
    `test_broker_contract` does `except Exception: continue`, so if this module ever becomes
    unimportable in an environment that lacks the SDK, the adapter is skipped IN SILENCE by the
    arm that exists to cover it.
    """
    modules = _imported_modules(MT5_SOURCE.read_text(encoding="utf-8"))
    assert SDK_MODULE not in modules, (
        f"mt5.py imports {SDK_MODULE} at module scope. The client is INJECTED on purpose (B328): "
        "an adapter whose module cannot be imported is skipped in silence by the contract arm's "
        "discovery walk, so it would ship uncovered with the suite green."
    )


def test_the_import_scanner_would_CATCH_an_import_if_one_were_added():
    """The must-hit half. A guard is only as wide as its scanner (`B250`).

    The fixture is a synthetic source string and **not** `mt5.py`, so this control cannot pass
    because of a property of the subject it is guarding.
    """
    both_forms = (
        "import metaapi_cloud_sdk\n"
        "from metaapi_cloud_sdk.clients.error_handler import TooManyRequestsException\n"
    )
    assert _imported_modules(both_forms) == {SDK_MODULE}

    aliased = "import metaapi_cloud_sdk as sdk\n"
    assert SDK_MODULE in _imported_modules(aliased)

    # THE SCANNER'S BLIND SPOT, WRITTEN DOWN RATHER THAN LEFT TO BE FOUND: it reads `import`
    # statements, so a dynamic `importlib.import_module("metaapi_cloud_sdk")` is INVISIBLE to it.
    # That is not a hypothetical hole worth closing today — nothing in this tree imports
    # dynamically — but an unstated bound is how a guard comes to be trusted past its width.
    dynamic = 'import importlib\nsdk = importlib.import_module("metaapi_cloud_sdk")\n'
    assert SDK_MODULE not in _imported_modules(dynamic), (
        "if this ever fails the scanner grew a capability and this comment is stale"
    )


def test_mt5_still_imports_WITHOUT_the_sdk_being_reachable_from_it():
    """The property the injected client buys, stated as behaviour rather than as a docstring."""
    import app.services.broker.mt5 as mt5

    assert not hasattr(mt5, "MetaApi"), "the SDK leaked into the adapter's namespace"
    assert mt5.SDK_RATE_LIMIT_EXCEPTION == "TooManyRequestsException"


# ======================================================================================
# B345 — the class, made mechanical rather than found by luck
# ======================================================================================


def test_no_INSTALLED_package_is_SHADOWED_by_a_hollow_stub_in_sys_modules():
    """`B345`. A test that stubs a real dependency into `sys.modules` cripples it for everyone.

    **How this was found the first time, which is the argument for automating it:** the
    coexistence arm above passed alone and failed in the suite, because
    `test_bridge_write_guard.py` installed a bare `ModuleType("aiohttp")` **at collection time**
    and never removed it. Both run orders failed — being *collected* was enough — so the usual
    reorder experiment pointed nowhere.

    **THIS ARM IS DELIBERATELY WEAKER ALONE THAN IN THE SUITE, and that asymmetry is the point.**
    Run by itself it observes an almost-empty `sys.modules` and can find nothing; run in the suite
    it observes what every collected module did to the interpreter. **It is an integration arm
    wearing a unit test's clothes**, and it is written here rather than in a `conftest` hook so
    that its failure names a subject a reader can act on.

    `PathFinder` is used instead of `importlib.util.find_spec` on purpose: the latter answers out
    of `sys.modules`, so for a stub it raises rather than reporting the package on disk — it would
    consult the very state this arm exists to distrust.
    """
    from importlib.machinery import PathFinder

    offenders = []
    for name, module in list(sys.modules.items()):
        if module is None or "." in name or name in sys.builtin_module_names:
            continue
        # A real module has a __file__ (or a __path__, for a package). A `types.ModuleType(...)`
        # placed in sys.modules by a test has neither.
        if getattr(module, "__file__", None) is not None or hasattr(module, "__path__"):
            continue
        try:
            spec = PathFinder().find_spec(name)
        except Exception:  # pragma: no cover - a broken finder is not this arm's subject
            continue
        if spec is not None and spec.origin not in (None, "built-in", "frozen"):
            offenders.append(f"{name} (really installed at {spec.origin})")

    assert not offenders, (
        "these modules are hollow stubs in sys.modules while the REAL package is installed on "
        f"disk, so every later test sees the stub: {offenders}. A stub must be installed only "
        "when the dependency is genuinely absent, and removed once the import it exists for is "
        "done — see B345."
    )
