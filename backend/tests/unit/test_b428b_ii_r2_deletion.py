"""B428b commit (ii), R2 — B429's crypto venue-protection code is DELETED (`T-0144` DESIGN §7).

Review's registered rows (`agents/tasks/_runs/b428b_ii/KILL_SET.md`, "R2" and "Q-9(ii)"):

```
R2-1     a crypto MarketOrderRequest carries NO order_class, stop_loss or take_profit (moved from test_b429...:217)
R2-2     REJECTION_PROTECTION_NOT_ACCEPTED is KEPT: it is in 0014's frozen CHECK list, and removing it needs a migration
R2-3     no dead protection path remains: the deleted names are referenced nowhere under backend/app
R2-4     ClosePositionRequest is gone from the adapter, and a partial close by position REFUSES without an SDK call
Q-9(ii)  entry_lock_normal_hold_bound_s is 8C + B again (the protection re-read is gone), read live
```

**WHY DELETE RATHER THAN LEAVE IT DORMANT.** Every configured symbol is crypto, the venue refuses the bracket/OTO order
class for crypto, and nothing branches on asset class — so the verification and its remediation had no reachable
success path. A safety gate with no production caller reads as live protection while providing none.

`test_b429_stop_is_placed.py` was deleted with the code. What still described LIVE behaviour moved: its `:217` control
became R2-1 (driven with a stop AND a target, the case that used to attach protection), `:595` (the terminal-status pin)
and `:982` (the DecisionRecord construction-site pin) are at the bottom of this file, and `_drive_tick` moved to
`test_t0130_order_result_three_states.py`, its main importer.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import math
from pathlib import Path

import pytest

from app.core.exceptions import BrokerError
from app.db.enums import DirectionType, OrderType
from app.services.broker.base import OrderRequest

#: The names `R2` deleted from `backend/app`, each checked unreferenced before it went (grep over app/ and tests/).
#: The two SDK request classes are included because attaching a stop or a target is the only thing either builds.
DELETED_NAMES = frozenset({
    "_require_protection", "_observe_flat", "_protection_class", "_is_working_stop_leg", "_is_stop_leg", "_leg_kind",
    "_qty_token", "AlpacaProtectionNotAccepted", "AlpacaUnprotectedPositionOpen", "WORKING_STOP_LEG_STATUSES",
    "FLAT_CHECK_ORDER_LIMIT", "FLAT_CHECK_ORDER_LIMIT_CEILING", "HALT_UNPROTECTED_POSITION",
    "_record_unprotected_position", "StopLossRequest", "TakeProfitRequest",
})

#: The fields of the SDK's order request that attach protection (or child legs) to an order.
PROTECTION_FIELDS = ("order_class", "stop_loss", "take_profit", "legs")


def _backend() -> Path:
    import app.services.broker.alpaca as alpaca

    return Path(alpaca.__file__).resolve().parents[3]


def _references(source: str, names: frozenset[str]) -> list[tuple[int, str, str]]:
    """Every SYNTACTIC use of one of `names` in `source`: a Name, an Attribute, an import (any dotted part or alias),
    a def/class of that name, a keyword argument, or a string constant that IS the name (`getattr(x, "_observe_flat")`).
    A mention inside a comment or prose is not a use and is not reported."""
    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name) and node.id in names:
            hits.append((node.lineno, "name", node.id))
        elif isinstance(node, ast.Attribute) and node.attr in names:
            hits.append((node.lineno, "attribute", node.attr))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                for part in [*alias.name.split("."), alias.asname or ""]:
                    if part in names:
                        hits.append((node.lineno, "import", part))
            if isinstance(node, ast.ImportFrom) and node.module:
                hits.extend((node.lineno, "import", p) for p in node.module.split(".") if p in names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
            hits.append((node.lineno, "definition", node.name))
        elif isinstance(node, ast.keyword) and node.arg in names:
            hits.append((node.lineno, "keyword", node.arg))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
            hits.append((node.lineno, "string", node.value))
    return hits


# =====================================================================================================================
# R2-1 — NO PROTECTION ON THE ORDER
# =====================================================================================================================

def _protection_on(order) -> list[str]:
    """The protection an SDK order request carries: each field set on the model, and each key in the body it sends."""
    found = [f"{field}={getattr(order, field)!r}" for field in PROTECTION_FIELDS if getattr(order, field) is not None]
    found += [f"body[{key!r}]" for key in order.to_request_fields() if key in PROTECTION_FIELDS]
    return found


def test_R2_1_control_the_protection_reader_SEES_protection_on_a_real_SDK_request():
    """The instrument, validated: the fields read exist on the SDK model (a renamed field would read as absent and pass
    in silence), and a request that DOES attach a stop is reported by name, field and body key both."""
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest, StopLossRequest

    assert set(PROTECTION_FIELDS) <= set(MarketOrderRequest.model_fields), sorted(MarketOrderRequest.model_fields)
    plain = MarketOrderRequest(symbol="BTC/USD", qty="0.01", side=OrderSide.BUY, time_in_force=TimeInForce.GTC)
    assert _protection_on(plain) == [], _protection_on(plain)
    protected = MarketOrderRequest(symbol="BTC/USD", qty="0.01", side=OrderSide.BUY, time_in_force=TimeInForce.GTC,
                                   order_class=OrderClass.OTO, stop_loss=StopLossRequest(stop_price=99.0))
    seen = _protection_on(protected)
    assert sorted(s.split("=")[0] for s in seen if not s.startswith("body")) == ["order_class", "stop_loss"], seen
    assert "body['order_class']" in seen and "body['stop_loss']" in seen, seen


def _recording_venue():
    """`test_t0140_order_body.Client` (REAL SDK `Asset` and `Order` models) whose re-read answers the order submission
    created, so the resolver stops on the first terminal read — and which records a cancel or a close if one is sent."""
    from tests.unit.test_t0140_order_body import BTC_MIN, Client, _asset

    class _Recording(Client):
        def submit_order(self, order_data):
            placed = super().submit_order(order_data)
            self.last_order = placed
            return placed

        def cancel_order_by_id(self, order_id):
            self.calls.append(("cancel_order_by_id", str(order_id)))

        def close_position(self, symbol_or_asset_id, close_options=None):
            self.calls.append(("close_position", symbol_or_asset_id, close_options))

    return _Recording({"BTC/USD": _asset("BTC/USD", min_order_size=BTC_MIN)})


@pytest.mark.asyncio
@pytest.mark.parametrize("sl,tp", [(69_000.0, 72_000.0), (69_000.0, None), (None, None)],
                         ids=["stop_and_target_was_BRACKET", "stop_only_was_OTO", "no_stop_the_moved_control"])
async def test_R2_1_a_crypto_MarketOrderRequest_carries_NO_order_class_stop_loss_or_take_profit(sl, tp):
    """**Moved from `test_b429_stop_is_placed.py:217`** (`test_an_order_with_NO_stop_is_unchanged`), and widened to
    the two requests that used to attach protection: a stop and a target (BRACKET), a stop alone (OTO). The order that
    reaches `submit_order` is read off the SDK object and off the body it would send. The moved control's other
    assertions are kept: a plain order FILLS, the resolver reads it ONCE and stops on the terminal order, and nothing
    is cancelled or closed."""
    from app.services.broker.alpaca import AlpacaAdapter
    from tests.unit.test_t0140_order_body import _instant_sleep

    venue = _recording_venue()
    adapter = AlpacaAdapter(venue, paper=True)
    adapter._sleep = _instant_sleep
    request = OrderRequest(pair="BTC/USD", direction=DirectionType.LONG, order_type=OrderType.MARKET, lot_size=0.01,
                           sl=sl, tp=tp, client_order_id="sig-r2-1")
    async with asyncio.timeout(10):
        res = await adapter.place_order(request)

    assert len(venue.submitted) == 1, venue.calls
    (order,) = venue.submitted
    assert type(order).__name__ == "MarketOrderRequest" and type(order).__module__.startswith("alpaca."), type(order)
    assert _protection_on(order) == [], (
        f"the crypto entry carries protection again ({_protection_on(order)}): the venue refuses that order class for "
        f"crypto, and the verification that went with it was deleted (T-0144 R2)")
    assert res["status"] == "FILLED", res
    names = [c[0] for c in venue.calls]
    assert names.count("get_order_by_id") == 1, f"the resolver did not read once and stop on a terminal order: {names}"
    assert "cancel_order_by_id" not in names and "close_position" not in names, names


# =====================================================================================================================
# R2-2 — THE REJECTION CODE STAYS
# =====================================================================================================================

def _migration(path: Path):
    spec = importlib.util.spec_from_file_location(f"_r2_mig_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_R2_2_PROTECTION_NOT_ACCEPTED_is_KEPT_in_the_vocabulary_and_in_0014s_frozen_CHECK():
    """`0014` put the code into `ck_decision_records_rejection_code`; every migration since froze a list containing it,
    and rows may carry it. Removing it from the vocabulary without a migration would make the model disagree with the
    CHECK — so R2 deletes the producer and keeps the code. Read from the model and from the migration modules, never a
    copied list."""
    from app.models.decision_record import REJECTION_CODES, REJECTION_PROTECTION_NOT_ACCEPTED

    assert REJECTION_PROTECTION_NOT_ACCEPTED in REJECTION_CODES, "the code left the vocabulary without a migration"

    versions = _backend() / "alembic" / "versions"
    m14 = _migration(next(versions.glob("0014_*.py")))
    assert len(m14._CODES_AT_0014) > 1, "the instrument read an empty 0014 list"
    assert REJECTION_PROTECTION_NOT_ACCEPTED in m14._CODES_AT_0014, m14._CODES_AT_0014

    # ...and the NEWEST frozen code list (derived: the highest revision defining its own `_CODES_AT_<revision>`).
    frozen = {}
    for path in sorted(versions.glob("[0-9][0-9][0-9][0-9]_*.py")):
        revision = path.name[:4]
        if f"_CODES_AT_{revision}" in path.read_text(encoding="utf-8"):
            frozen[revision] = getattr(_migration(path), f"_CODES_AT_{revision}")
    assert "0014" in frozen and len(frozen) >= 2, sorted(frozen)
    newest = max(frozen)
    assert REJECTION_PROTECTION_NOT_ACCEPTED in frozen[newest], (newest, frozen[newest])
    assert set(REJECTION_CODES) == set(frozen[newest]), (
        f"the vocabulary and the newest frozen CHECK list ({newest}) disagree: "
        f"{sorted(set(REJECTION_CODES) ^ set(frozen[newest]))}")


# =====================================================================================================================
# R2-3 — NO DEAD PROTECTION PATH REMAINS
# =====================================================================================================================

def _app_population() -> list[Path]:
    app = _backend() / "app"
    files = sorted(app.rglob("*.py"))
    expected = {app / "services" / "broker" / "alpaca.py", app / "services" / "execution" / "service.py",
                app / "services" / "live" / "crypto_loop.py"}
    missing = expected - set(files)
    if missing or len(files) < 100:
        raise AssertionError(f"REFUSING: the scan population is wrong ({len(files)} files; missing "
                             f"{sorted(missing)}) — a scan of nothing reads as health")
    return files


def test_R2_3_control_the_scanner_FINDS_every_deleted_name_in_every_syntactic_form_and_not_in_prose():
    for name in sorted(DELETED_NAMES):
        plants = {
            "name": f"x = {name}\n",
            "attribute": f"y = obj.{name}\n",
            "import": f"from app.services.broker.alpaca import {name}\n",
            "definition": f"def {name}():\n    pass\n" if name[0].islower() else f"class {name}:\n    pass\n",
            "keyword": f"f({name}=1)\n",
            "string": f"getattr(obj, {name!r})\n",
        }
        for form, source in plants.items():
            found = _references(source, DELETED_NAMES)
            assert found == [(1, form, name)], (name, form, found)
    prose = "# _require_protection was deleted\nNOTE = 'AlpacaUnprotectedPositionOpen is gone, see R2'\n"
    assert _references(prose, DELETED_NAMES) == [], _references(prose, DELETED_NAMES)


def test_R2_3_no_deleted_protection_name_is_referenced_ANYWHERE_under_backend_app():
    hits = []
    for path in _app_population():
        for line, form, name in _references(path.read_text(encoding="utf-8"), DELETED_NAMES):
            hits.append(f"{path.relative_to(_backend())}:{line} {form} {name}")
    assert hits == [], "B429's deleted protection path is referenced again:\n" + "\n".join(hits)


def test_R2_3_the_deleted_members_do_not_exist_at_runtime_either():
    import app.services.broker.alpaca as alpaca
    import app.services.execution.service as service
    import app.services.live.crypto_loop as loop

    owners = (alpaca, alpaca.AlpacaAdapter, service, loop, loop.LiveCryptoLoop)
    present = [f"{owner.__name__}.{name}" for owner in owners for name in sorted(DELETED_NAMES) if name in vars(owner)]
    assert present == [], present


# =====================================================================================================================
# R2-4 — B457's RESIDUAL: NO CLOSE REQUEST WITH A QUANTITY
# =====================================================================================================================

def test_R2_4_ClosePositionRequest_is_NOT_used_by_the_adapter_with_a_planted_control():
    import app.services.broker.alpaca as alpaca

    names = frozenset({"ClosePositionRequest"})
    planted = "from alpaca.trading.requests import ClosePositionRequest\noptions = ClosePositionRequest(qty='0.1')\n"
    assert [f for _l, f, _n in _references(planted, names)] == ["import", "name"], _references(planted, names)
    source = Path(alpaca.__file__).read_text(encoding="utf-8")
    assert "async def close_position" in source, "the instrument read the wrong file"
    assert _references(source, names) == [], _references(source, names)


def _strict_client():
    """A TradingClient double that RECORDS and REFUSES every SDK member — names read from `TradingClient` at test time,
    so no member can be called in silence. The record is taken BEFORE the refusal, because `_call` would wrap the
    AssertionError into a BrokerError that an arm expecting BrokerError would read as the refusal."""
    from alpaca.trading.client import TradingClient

    calls: list[str] = []

    def _member(name):
        def _refuse(*a, **k):
            calls.append(name)
            raise AssertionError(f"SDK member {name} was called")
        return _refuse

    members = {n: _member(n) for n, v in vars(TradingClient).items() if callable(v) and not n.startswith("_")}
    assert {"close_position", "submit_order", "get_all_positions"} <= set(members), sorted(members)
    client = type("StrictClient", (), {})()
    for name, fn in members.items():
        setattr(client, name, fn)
    client._api_key = "PK-R2-4-strict"
    return client, calls


@pytest.mark.asyncio
@pytest.mark.parametrize("lot_size", [0.001, 0.0], ids=["a_partial", "zero_is_still_a_size"])
async def test_R2_4_a_PARTIAL_close_by_position_REFUSES_and_calls_NOTHING(lot_size):
    from app.services.broker.alpaca import AlpacaAdapter

    client, calls = _strict_client()
    adapter = AlpacaAdapter(client, paper=True)
    async with asyncio.timeout(10):
        with pytest.raises(BrokerError) as refused:
            await adapter.close_position("BTCUSD", lot_size=lot_size)
    assert calls == [], f"a refused partial close called the SDK: {calls}"
    assert "partial closes are engine sell orders" in str(refused.value), str(refused.value)
    assert repr(lot_size) in str(refused.value) and "Nothing was sent" in str(refused.value), str(refused.value)

    # CONTROL: the same double DOES see a call through the adapter's worker — the whole close still goes out.
    async with asyncio.timeout(10):
        with pytest.raises(BrokerError):
            await adapter.close_position("BTCUSD")
    assert calls == ["close_position"], calls


# =====================================================================================================================
# Q-9(ii) — THE ESTIMATE IS 8C + B, READ LIVE
# =====================================================================================================================

def test_Q9_ii_the_entry_lock_estimate_is_8C_plus_B_from_PATCHED_constants_and_client(monkeypatch):
    """4 calls on the normal path (the position before, submit, one resolver read past the budget, the position
    after), each able to queue one call late. Two value sets, so the multipliers of C and of B are separated; patched
    values, so a literal (493 or 615, or any other) does not move with them and dies."""
    import app.services.broker.alpaca as alpaca

    class _Client:
        pass

    client = _Client()
    for retry, wait, connect, read, budget in ((3, 0.4, 0.7, 2.3, 1.3), (1, 5.0, 0.05, 0.6, 11.0)):
        monkeypatch.setattr(alpaca, "ALPACA_HTTP_CONNECT_TIMEOUT_S", connect)
        monkeypatch.setattr(alpaca, "ALPACA_HTTP_READ_TIMEOUT_S", read)
        monkeypatch.setattr(alpaca, "ORDER_RESOLUTION_BUDGET_S", budget)
        client._retry, client._retry_wait = retry, wait
        call = (retry + 1) * (connect + read) + retry * wait
        got = alpaca.entry_lock_normal_hold_bound_s(client)
        assert math.isclose(got, 8 * call + budget, rel_tol=1e-12), (got, 8 * call + budget)
        assert not math.isclose(got, 10 * call + budget, rel_tol=1e-9), "10C + B: the protection re-read still counts"


def test_Q9_ii_the_DOCSTRINGS_quote_the_number_the_live_function_gives_for_the_BUILDERS_client():
    """The docstring arithmetic for `build_trading_client`'s client (retry and sleep read from that client, constants
    live), with and without the 429 retry — numbers COMPUTED here from the function, so a docstring left at the old
    multiplier, or a function changed without its docstring, dies."""
    import app.services.broker.alpaca as alpaca

    client = alpaca.build_trading_client("PK-R2-Q9", "secret", paper=True)
    with_retry = alpaca.entry_lock_normal_hold_bound_s(client)
    retry, wait = alpaca._client_retry_settings(client)
    assert retry > 0, "premise: the builder's client retries a 429"
    call = (retry + 1) * (alpaca.ALPACA_HTTP_CONNECT_TIMEOUT_S + alpaca.ALPACA_HTTP_READ_TIMEOUT_S) + retry * wait
    client._retry = 0
    without_retry = alpaca.entry_lock_normal_hold_bound_s(client)

    estimate_doc = inspect.getdoc(alpaca.entry_lock_normal_hold_bound_s)
    for number in (with_retry, without_retry):
        assert f"{number:.0f}s" in estimate_doc, (f"{number:.0f}s", estimate_doc[-600:])
    assert f"{with_retry:.0f}s" in inspect.getdoc(alpaca.AlpacaAdapter.close_all_positions)
    stale = f"{10 * call + alpaca.ORDER_RESOLUTION_BUDGET_S:.0f}s"
    assert stale not in estimate_doc and stale not in inspect.getdoc(alpaca.AlpacaAdapter.close_all_positions), stale


# =====================================================================================================================
# MOVED from test_b429_stop_is_placed.py (deleted by R2) — they pin live behaviour, not protection
# =====================================================================================================================

def test_the_TERMINAL_set_is_pinned():
    """**Moved from `test_b429_stop_is_placed.py:595`.** A widening of the set that decides when an order's outcome is
    final — where `B427`'s resolver stops reading and what `_order_result` reports as terminal — must be deliberate."""
    from app.services.broker.alpaca import TERMINAL_ORDER_STATUSES
    assert TERMINAL_ORDER_STATUSES == {"filled", "canceled", "expired", "rejected", "replaced"}


def test_the_SET_of_DecisionRecord_CONSTRUCTION_SITES_is_pinned():
    """**Moved from `test_b429_stop_is_placed.py:982`.** `M-2`'s shape — DEFENCE IN DEPTH, and narrower than it looks.

    **WHAT THIS ARM CATCHES, PRECISELY:** a call spelled with the bare name `DecisionRecord(...)` in `crypto_loop.py`.
    It does NOT catch an alias (`from ... import DecisionRecord as DR; DR(...)`), module-attribute access
    (`dr_mod.DecisionRecord(...)`), `getattr`, or a core/raw insert. Measured on 7f0ee09 with a writer planted inside
    the (since deleted) unprotected-position recorder: by real name this arm died, by alias or attribute nothing died
    until a driven no-row arm ran the recorder. **The driven no-row arms are the robust net** (the unresolved-order
    halt's, in `test_t0130_order_result_three_states.py`); this one only makes a new bare-name construction site a
    deliberate edit.

    Names rather than a count: a count says five and cannot say WHICH, so moving a construction from one writer to a
    new one would leave it green — the identity-not-count lesson from `B424`'s residual.
    """
    from app.services.live import crypto_loop as mod

    tree = ast.parse(inspect.getsource(mod))
    where = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                    if n.func.id == "DecisionRecord":
                        where[n.lineno] = fn.name

    assert set(where.values()) == {
        "_record_signal_decision",
        "_record_rejected_signal",
        "_record_abstention",
        "_record_unsized_fill",
        # `T-0144` R11': the pre-send SUBMITTING record, written before EVERY send — so on a no-row halt (an unresolved
        # order) the one row that exists is that SUBMITTING row, which the halt leaves as it is
        "_write_submitting",
    }, (
        f"the set of functions constructing a DecisionRecord changed to "
        f"{sorted(set(where.values()))}. A new one must be added here deliberately — the no-row halts prove no row is "
        f"written only while every row still passes through a construction this file knows."
    )
