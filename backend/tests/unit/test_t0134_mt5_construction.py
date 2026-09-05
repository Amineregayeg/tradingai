"""T-0134 — mt5 is CONSTRUCTIBLE from the broker manager, and constructible is not tradeable.

**What this task changed and why it is not "add a branch".** `_make_adapter` ended
`raise ValueError(f"Unsupported broker: {broker!r}")`, so nothing in the application could build
the MT5 adapter — it was reachable only from its own test file. The obvious fix is one branch.
Two things made it more than that:

* **`B341`** — the adapter assumed a client shape no SDK object has, so a branch constructing the
  documented object would have handed it something it could not use. The adapter now holds the
  `MetatraderAccount`.
* **The live-trading guard was INSIDE the CFT branch** while claiming to run on every construction
  path. That claim was true only while CFT was the only branch. **A second branch returning before
  it would have been a new unguarded real-money path**, which is precisely why OANDA was deleted
  from that function. It is hoisted above the dispatch here, so skipping it is impossible by
  construction rather than avoided by care.

**AND THIS DELIVERS READS ONLY.** `B346`: both `place_order` call sites pass the in-process paper
broker, so no adapter held by the manager is on any order path. That is asserted here rather than
assumed, because *constructible* reads as *tradeable* to anyone who has not traced it.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.core.exceptions import BrokerConnectionError
from app.services.broker import manager as manager_mod
from app.services.broker.manager import _make_adapter
from app.services.broker.mt5 import MetaTrader5Adapter

CREDS = {"token": "tok-123", "mt5_account_id": "acc-abc"}


def test_the_manager_can_BUILD_an_mt5_adapter_at_all():
    """Before T-0134 this raised ValueError: the adapter existed and nothing could construct it."""
    adapter = _make_adapter("mt5", CREDS, "acc-abc", "demo")
    assert isinstance(adapter, MetaTrader5Adapter)
    assert adapter.broker_name == "mt5"


@pytest.mark.parametrize("alias", ["mt5", "MT5", "metatrader5", "metaapi"])
def test_the_aliases_all_reach_the_same_branch(alias):
    assert isinstance(_make_adapter(alias, CREDS, "acc-abc", "demo"), MetaTrader5Adapter)


def test_an_unknown_broker_STILL_raises_and_the_branch_did_not_widen_the_door():
    """The must-miss half: adding a branch must not make the factory permissive."""
    with pytest.raises(ValueError, match="Unsupported broker"):
        _make_adapter("binance", CREDS, "acc", "demo")


@pytest.mark.parametrize("missing,creds", [
    ("token", {"mt5_account_id": "acc-abc"}),
    ("account id", {"token": "tok-123"}),
])
def test_missing_credentials_REFUSE_at_construction_rather_than_at_first_call(missing, creds):
    """A adapter built without a token fails later, further away, and less specifically."""
    with pytest.raises(BrokerConnectionError):
        _make_adapter("mt5", creds, "", "demo")


# ======================================================================================
# THE GUARD — hoisted, and the point is that a BRANCH cannot skip it
# ======================================================================================


def test_the_live_trading_guard_runs_BEFORE_the_broker_dispatch():
    """AST, not a substring: the guard must dominate every `return` in this function.

    The old arrangement put it inside the CFT branch. Its comment claimed it ran on every
    construction path — true of the paths INTO the function, false of the branches within it the
    moment a second one existed. **This asserts the structural property the comment asserts in
    prose**, which is the difference between a claim and a guard.
    """
    tree = ast.parse(inspect.getsource(manager_mod))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_make_adapter")

    guard_line = min(
        node.lineno for node in ast.walk(fn)
        if isinstance(node, ast.Name) and node.id == "allow_live"
    )
    first_return = min(node.lineno for node in ast.walk(fn) if isinstance(node, ast.Return))
    assert guard_line < first_return, (
        "ALLOW_LIVE_TRADING is evaluated after a branch can already have returned. A branch that "
        "returns before the guard is a new unguarded real-money construction path."
    )

    # And it is not merely EARLY — it must be at the function's own indentation level, not nested
    # inside one broker's `if`, or a second branch could still be added beside it.
    top_level = {n.lineno for stmt in fn.body for n in ast.walk(stmt)
                 if isinstance(stmt, (ast.Assign, ast.If)) and isinstance(n, ast.Name)
                 and n.id == "allow_live"}
    assert guard_line in top_level


def test_the_mt5_branch_does_not_take_observe_only_and_says_why():
    """It has no such parameter and no write to gate — but the decision must be VISIBLE.

    `B215`'s shape applied to a code path: an adapter constructed without the flag and an adapter
    for which the flag is meaningless look identical from the outside.
    """
    adapter = _make_adapter("mt5", CREDS, "acc-abc", "demo")
    assert not hasattr(adapter, "observe_only")
    source = inspect.getsource(manager_mod._make_adapter)
    assert "observe_only=observe_only" in source, "the CFT branch must still receive it"
    assert "B346" in source, "the mt5 branch must name why it does not"


# ======================================================================================
# CONSTRUCTIBLE IS NOT TRADEABLE — B346, asserted rather than assumed
# ======================================================================================


def test_the_adapter_this_branch_builds_REFUSES_to_place_an_order():
    """The one write refuses (`B302`), so putting MT5 on the manager puts it on no order path."""
    adapter = _make_adapter("mt5", CREDS, "acc-abc", "demo")
    assert adapter.is_simulation is False
    with pytest.raises(NotImplementedError) as exc:
        import asyncio
        asyncio.run(adapter.place_order(object()))
    assert "REFUSES" in str(exc.value)


def test_the_SDK_IS_NOT_IMPORTED_by_building_the_adapter():
    """`B328`, through the factory rather than through the adapter.

    `mt5.py` keeps the SDK out of module scope so the contract arm's discovery walk can see the
    adapter in an image without the package. **A factory that imported the SDK to construct the
    adapter would defeat that from the other side** — so the import lives inside the closure and
    only `connect()` can trigger it.
    """
    source = inspect.getsource(manager_mod)
    tree = ast.parse(source)
    module_level = {
        alias.name.split(".")[0]
        for node in tree.body if isinstance(node, ast.Import) for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in tree.body if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "metaapi_cloud_sdk" not in module_level, (
        "manager.py imports the SDK at module scope; mt5.py's deliberate non-import is then "
        "pointless, because importing manager imports the SDK anyway (B328)."
    )
    # Built, and the SDK still absent from the adapter's own namespace.
    _make_adapter("mt5", CREDS, "acc-abc", "demo")
    import app.services.broker.mt5 as mt5
    assert not hasattr(mt5, "MetaApi")


# ======================================================================================
# B352 — the gate's EFFECT, which nothing asserted until now
# ======================================================================================


def test_a_stored_observe_only_FALSE_is_FORCED_TRUE_when_live_trading_is_disabled(monkeypatch):
    """`B352`. **The single centralised check between a persisted live-write connection and a
    live-write adapter, and no arm exercised it.**

    Found while hoisting it for `T-0134`: nothing in `tests/` sets `ALLOW_LIVE_TRADING`, and the
    only references to it are docstring PROSE in `test_bridge_write_guard` and
    `test_cft_order_path` — both of which describe it as the thing they are defending in depth
    *behind*. Two files rely on it in their reasoning and none of them, or anything else, checks
    that it works.

    The arm above pins WHERE the guard sits. That is not the same property and does not imply
    this one: a guard in the right place that forces nothing passes it.
    """
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    adapter = _make_adapter(
        "cft", {"email": "e", "password": "p", "observe_only": False}, "acc", "live"
    )
    assert adapter.observe_only is True, (
        "a stored observe_only=False was honoured with ALLOW_LIVE_TRADING unset"
    )


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "", "  "])
def test_only_the_literal_true_opens_the_gate(monkeypatch, value):
    """Anything that is not `true` must leave it shut — the safe direction for a real-money flag."""
    monkeypatch.setenv("ALLOW_LIVE_TRADING", value)
    adapter = _make_adapter(
        "cft", {"email": "e", "password": "p", "observe_only": False}, "acc", "live"
    )
    assert adapter.observe_only is True


def test_the_gate_DOES_open_when_it_is_explicitly_set(monkeypatch):
    """The must-MISS half. Without it, a gate welded shut passes every arm above.

    This asserts the flag is load-bearing in BOTH directions — that the guard is a gate and not a
    hardcoded `True`, which is the version of this fix that would look correct and silently make
    the setting meaningless.
    """
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "true")
    adapter = _make_adapter(
        "cft", {"email": "e", "password": "p", "observe_only": False}, "acc", "live"
    )
    assert adapter.observe_only is False


def test_the_DEFAULT_is_observe_only_when_the_key_is_absent_entirely(monkeypatch):
    """A connection stored before the flag existed has no `observe_only` key at all."""
    monkeypatch.setenv("ALLOW_LIVE_TRADING", "true")
    adapter = _make_adapter("cft", {"email": "e", "password": "p"}, "acc", "live")
    assert adapter.observe_only is True, (
        "an absent key must default to observe-only even when live trading is permitted"
    )


def test_the_gate_RUNS_on_the_mt5_path_and_not_only_above_it(monkeypatch):
    """`B352`, second half. **All four gate-effect arms above drive the CFT branch.**

    The AST arm asserts the guard is POSITIONED before every return. **That is a different claim:
    a guard can be correctly placed and still not run for a branch**, and "mine is the second
    caller" is exactly when that stops being theoretical.

    **What this can honestly assert, and what it must not.** The MT5 adapter has no `observe_only`
    parameter and no write to gate — `place_order` refuses unconditionally — so there is no
    adapter attribute to check, and an arm claiming *the mt5 adapter is observe-only* would be
    asserting a property that does not exist. That is `B341`'s shape: a name that reads right for
    an object that has no such thing. What is real is that **the guard EXECUTED for this broker**,
    which is the property that must survive someone later giving the adapter a write.
    """
    # THE INSTRUMENT, AND THE FIRST ONE DID NOT WORK. Written with `caplog` it failed while the
    # warning was plainly in the captured stderr: this app logs through loguru and `caplog`
    # captures stdlib `logging`. **The arm was red because the instrument could not see, not
    # because the property was false** — the exact reading error this register keeps recording, so
    # the recorder below observes the call itself rather than a sink's rendering of it.
    calls: list[str] = []

    class _Recorder:
        def warning(self, message, **kw):
            calls.append(str(message))

        def info(self, message, **kw):
            calls.append(str(message))

    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    monkeypatch.setattr(manager_mod, "logger", _Recorder())
    adapter = _make_adapter("mt5", {**CREDS, "observe_only": False}, "acc-abc", "demo")

    assert isinstance(adapter, MetaTrader5Adapter)
    assert any("Forcing observe_only=True" in c for c in calls), (
        "the live-trading gate did not run on the mt5 construction path — it is positioned "
        f"before the dispatch but this branch reached a return without evaluating it. Saw: {calls}"
    )


def test_the_MetaApi_token_comes_ONLY_from_the_credential_blob_and_never_from_the_environment():
    """`B360`. T-0134 required the token's source to be *decided and recorded — a security
    property, not a style choice*. It was decided at the branch and recorded nowhere, so a DONE
    marker closed a half-met requirement.

    **The decision, now asserted rather than only written:** the token comes from the connection
    row's encrypted credential blob and from nowhere else. An environment variable is
    process-global while a token is per-connection, so one variable could hold exactly one
    account's token and a second MT5 account would silently authenticate as the first — and a live
    broker credential in `os.environ` is visible to `/proc`, to a crash dump, and to anything that
    logs the environment.
    """
    monkey_env = "METAAPI_TOKEN"

    # READ STRUCTURALLY, AND THE FIRST VERSION OF THIS ARM WAS WRONG IN THE WAY IT WARNS ABOUT.
    # It asserted the string `METAAPI_TOKEN` did not occur in the module — and went red on the
    # COMMENT that records this very decision, which names the variable in order to say it is not
    # consulted. **A substring scan cannot tell a use from a mention**, which is the same defect
    # B343's marker arm had. So this collects the names actually passed to `os.getenv` /
    # `os.environ.get` and checks those.
    def _is_env_read(func: ast.expr) -> bool:
        """`os.getenv(...)` or `os.environ.get(...)` — and NOTHING ELSE.

        The second version of this arm matched `func.attr in ("getenv", "get")`, which collected
        every `.get()` in the module including `creds.get("token")` — **the very dict lookup this
        decision says is the CORRECT source**, reported as a violation. A scan whose population is
        wider than its subject produces confident nonsense in the accusing direction.
        """
        if not isinstance(func, ast.Attribute):
            return False
        if func.attr == "getenv":
            return isinstance(func.value, ast.Name) and func.value.id == "os"
        if func.attr == "get":
            return (isinstance(func.value, ast.Attribute) and func.value.attr == "environ"
                    and isinstance(func.value.value, ast.Name) and func.value.value.id == "os")
        return False

    tree = ast.parse(inspect.getsource(manager_mod))
    env_names = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and _is_env_read(node.func)
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            env_names.append(node.args[0].value)
    assert env_names, "the scan found no environment reads at all, so it cannot be trusted to " \
                      "find a bad one — manager.py is known to read ALLOW_LIVE_TRADING"
    assert not any("TOKEN" in n.upper() and "BRIDGE" not in n.upper() for n in env_names), (
        f"manager.py reads a token from the environment: {env_names}. The decision recorded at "
        "the branch says the credential blob is the only source. CFT_BRIDGE_TOKEN is exempt — it "
        "addresses one process-level service, not a per-account credential."
    )

    # The behavioural half: with NOTHING in the blob, construction refuses. If an environment
    # variable were ever consulted as a fallback, this would quietly succeed.
    import os
    os.environ[monkey_env] = "tok-from-the-environment"
    try:
        with pytest.raises(BrokerConnectionError, match="MetaApi token"):
            _make_adapter("mt5", {"mt5_account_id": "acc-abc"}, "acc-abc", "demo")
    finally:
        os.environ.pop(monkey_env, None)


def test_api_token_is_a_fallback_KEY_in_the_same_blob_and_not_a_second_SOURCE():
    """`B360`. Rows predating MT5 store the credential under `api_token`.

    **One source, two key names, is not two sources** — the distinction the comment at the branch
    makes, asserted so a later reader cannot collapse it.
    """
    adapter = _make_adapter(
        "mt5", {"api_token": "legacy-key", "mt5_account_id": "acc-abc"}, "acc-abc", "demo"
    )
    assert isinstance(adapter, MetaTrader5Adapter)
