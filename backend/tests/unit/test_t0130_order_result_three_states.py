"""T-0130 (B316 + B317) — an order result is a fill, a refusal, or UNRESOLVED; never a default.

**THE TITLE IS HALF RIGHT, and the half it misses is the worse half.**

```
service.py      res.setdefault("status", "FILLED")        absence reported as a FILL
crypto_loop.py  `else:` after the fill branch             everything else reported as a REFUSAL
```

The default lived in `service.py`. The misclassification lived in `crypto_loop` and could not be
fixed in `service.py`: an acknowledged order (`NEW`, `ACCEPTED`) or a `CANCELED` one that carried a
fill arrived WITH a status, so no default ever touched it, and the loop's `else` filed it as a
rejection — a row denying a position the venue may hold, which nothing would then manage.

MEASURED at `34d4d03`, before any change (sockets blocked, `_ticker_price` patched):

```
{} from _handle_response(200, b"")  -> service: status FILLED, no size
                                    -> loop: HALT_PARTIAL_UNSIZED + an UNSIZED_FILL row
                                       (a partial fill that never happened; a row saying the venue acted)
status-less WITH units              -> FILLED -> signal decision + position-open push
None / "NEW" / "ACCEPTED"           -> a REJECTED row, rejection_code None
"CANCELED" with filled_units 0.4    -> a REJECTED row, denying a position that exists
```

And READ, not driven (review's K-4 and K-4b): a `place_order` returning `None` raised TypeError outside
the service's `try`, and Alpaca's `float(filled_qty)` raised ValueError on a blank quantity AFTER the order
was submitted — each reaching the loop's venue-raised backstop, which filed a REJECTED row.

**NO EXISTING ARM PINNED THE DEFAULT**: deleting it left all 35 order-path test files green
(723 passed). The containment the task recorded — "self.paper is always a simulator" — is stale;
`_build_broker` can return `AlpacaAdapter`. What keeps this latent today is `B430` (`BROKER_MODE`
is a `Final "sim"`) — which also means **the simulator path is the one that runs**, so the arms that
matter most prove an ordinary sim or paper fill and refusal never land in UNRESOLVED (`K-5`).

The design is the manager's ruling on review's registered kill set (`_runs/t0130/KILL_SET.md`):
one pure classifier (`K-11`), strings only (`K-3`), a non-dict result is unreadable not a crash
(`K-4`), no `DecisionRecord` on UNRESOLVED and an alert that can rebuild one (`K-6`, `K-8`).

#### WHAT IS NOT CLAIMED

No venue was consulted and no order is resolved here: resolving an unresolved order to a terminal
state is `B427`, and its bound is a trading decision. These arms prove the engine refuses to GUESS.
"""
from __future__ import annotations

import ast
import inspect
import socket

import pytest
from types import SimpleNamespace

from tests.unit.test_b429_stop_is_placed import _drive_tick


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """**`B432`. Every arm here is offline, and that is enforced rather than assumed.** A drive that
    reaches the network fails a positive arm on a blip and PASSES an absence arm for the wrong reason."""
    def _refuse(*a, **k):
        raise AssertionError(f"T-0130 arm attempted a network connection: {a[1:]!r}")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)


class _HostileStatus:
    """A status whose equality and hash RAISE — what a membership test does with an SDK object it
    cannot compare. Tuple membership calls `__eq__`, so only the classifier's `isinstance` guard
    keeps this from raising out of the tick."""

    def __eq__(self, other):
        raise TypeError("this status cannot be compared")

    __hash__ = None

    def __repr__(self):
        return "<HostileStatus>"


def _empty_200_payload(body: bytes):
    """What `CryptoFundTraderAdapter._handle_response` returns for a 200 with this body — DERIVED from
    the method, not transcribed, so the arm tracks what the adapter really produces."""
    import httpx

    from app.services.broker.cryptofundtrader import CryptoFundTraderAdapter

    adapter = object.__new__(CryptoFundTraderAdapter)
    return adapter._handle_response(httpx.Response(200, content=body), "place_order")


def _double_service(placed):
    from app.services.execution.service import ExecMode, ExecutionService

    class _Acct:
        equity = 10_000.0

    class _Broker:
        is_simulation = True

        async def get_account(self):
            return _Acct()

        async def reference_price(self, _symbol):
            return 100.0

        async def place_order(self, _request):
            return placed

    return ExecutionService(_Broker(), ExecMode.PAPER)


def _signal(entry=100.0, sl=99.0, tp=102.0, direction=None):
    from app.db.enums import DirectionType, OrderType
    from app.services.execution.service import Signal

    return Signal("BTC/USD", direction or DirectionType.LONG, entry, sl, tp, 0.01, OrderType.MARKET,
                  approved=True)


async def _service_result(placed):
    return await _double_service(placed).execute(_signal())


# ---------------------------------------------------------------------------------------------------
# THE CLASSIFIER — one pure function, total, never raises
# ---------------------------------------------------------------------------------------------------

def test_C1_the_classifier_maps_each_status_to_its_class():
    from app.services.live import crypto_loop as mod

    table = {
        "FILLED": mod.ORDER_FILLED, "PARTIALLY_FILLED": mod.ORDER_PARTIALLY_FILLED,
        "REJECTED": mod.ORDER_REFUSED, "rejected": mod.ORDER_REFUSED,
        "NEW": mod.ORDER_UNRESOLVED, "ACCEPTED": mod.ORDER_UNRESOLVED, "PENDING_NEW": mod.ORDER_UNRESOLVED,
        "CANCELED": mod.ORDER_UNRESOLVED, "SUBMITTED": mod.ORDER_UNRESOLVED, "observed": mod.ORDER_UNRESOLVED,
        "filled": mod.ORDER_UNRESOLVED, " FILLED": mod.ORDER_UNRESOLVED, "": mod.ORDER_UNRESOLVED,
    }
    got = {s: mod.classify_order_status(s) for s in table}
    assert got == table, {s: (got[s], table[s]) for s in table if got[s] != table[s]}


@pytest.mark.parametrize("status", [None, 0, 1.0, {}, [], ("FILLED",), b"FILLED", _HostileStatus()],
                         ids=["None", "int", "float", "dict", "list", "tuple", "bytes", "hostile"])
def test_C2_a_NON_STRING_status_is_UNRESOLVED_and_never_raises(status):
    """**K-3.** `{} in frozenset(...)` raises; so does any membership test against an object whose
    `__eq__` raises. The classifier must answer UNRESOLVED for every non-string without comparing."""
    from app.services.live import crypto_loop as mod

    assert mod.classify_order_status(status) == mod.ORDER_UNRESOLVED


@pytest.mark.parametrize("status", [None, 0, {}, [], _HostileStatus(), "NEW", "CANCELED"],
                         ids=["None", "int", "dict", "list", "hostile", "NEW", "CANCELED"])
def test_C3_position_units_NEVER_raises_and_maps_anything_but_a_fill_to_None(status):
    """**K-12.** The runbook's probe step runs `_position_units` on a RAW venue dict and tells the
    operator it maps anything else to `None`. A raise there breaks the one real venue dict the ladder
    will ever hand it — so it must hold after delegating to the classifier, too."""
    from app.services.live.crypto_loop import LiveCryptoLoop

    assert LiveCryptoLoop._position_units({"status": status, "units": 1.0, "filled_units": 1.0}) is None


# ---------------------------------------------------------------------------------------------------
# SERVICE — absent stays absent, and an unreadable result is not a crash
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"{truncated"], ids=["empty_body", "malformed_json"])
async def test_S1_an_EMPTY_or_MALFORMED_200_is_NOT_reported_as_FILLED(body):
    """**The exact value an empty or unparseable 200 becomes, fed through the real service.** A default
    of any value — FILLED, REJECTED, anything — is one of the answers the caller exists to tell apart,
    so the only correct result is a missing key."""
    payload = _empty_200_payload(body)
    assert type(payload) is dict and payload == {}, (
        f"premise: _handle_response no longer turns this 200 into an empty dict ({payload!r}); "
        f"re-derive what an unreadable reply becomes before trusting this arm"
    )

    res = await _service_result(payload)

    assert "mode" in res and "sized_units" in res, (
        f"the service returned before the order was placed, so 'no status' proves nothing: {res!r}"
    )
    assert "status" not in res, (
        f"an unreadable venue reply was given a status: {res.get('status')!r}. Absent must stay "
        f"absent so the loop classifies it UNRESOLVED instead of trusting a default."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"null", b"[]", b'"ok"'], ids=["json_null", "json_list", "json_str"])
async def test_S1b_a_parseable_NON_DICT_200_is_unreadable_not_a_crash(body):
    """**K-4.** `_handle_response` returns `response.json()` for any parseable body, so these arrive as
    `None`, a list and a str. The service used to raise TypeError outside its `try`, which the loop's
    backstop filed as a venue-raised REFUSAL for an order that may have been taken."""
    payload = _empty_200_payload(body)
    assert not isinstance(payload, dict), f"premise: this body now parses to a dict: {payload!r}"

    res = await _service_result(payload)

    assert "status" not in res, f"an unreadable result was given a status: {res!r}"
    assert type(payload).__name__ in res["unreadable_result"], (
        f"the record does not say what came back: {res.get('unreadable_result')!r}"
    )
    assert "mode" in res and "sized_units" in res, f"the sizing inputs were dropped: {res!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["FILLED", "PARTIALLY_FILLED", "REJECTED", "NEW"])
async def test_S2_a_status_the_adapter_DID_set_passes_through_UNCHANGED(status):
    res = await _service_result({"status": status, "units": 1.0})
    assert res["status"] == status, f"the service rewrote the adapter's status {status!r} to {res['status']!r}"


# ---------------------------------------------------------------------------------------------------
# LOOP — a caller that BRANCHES, observed by what each branch DOES
# ---------------------------------------------------------------------------------------------------

FILL, REFUSAL, UNRESOLVED = "fill", "refusal", "unresolved"

CASES = [
    ({"status": "FILLED", "units": 1.0, "fill": 100.0, "position_id": "p-1", "sized_units": 1.0},
     FILL, "filled"),
    ({"status": "PARTIALLY_FILLED", "filled_units": 0.4, "units": 1.0, "fill": 100.0,
      "position_id": "p-2", "sized_units": 1.0}, FILL, "partial"),
    ({"status": "REJECTED", "reason": "venue refused", "rejection_code": "VENUE_TRANSPORT"},
     REFUSAL, "REJECTED"),
    # `service.py`'s five pre-order refusals spell it lowercase; a refusal test on "REJECTED" alone
    # would halt the engine on every ordinary entry-drift refusal.
    ({"status": "rejected", "reason": "price moved", "rejection_code": "ENTRY_DRIFT"},
     REFUSAL, "rejected_lowercase"),
    ({"mode": "paper", "sized_units": 1.0, "equity_at_entry": 1e4, "sizing_price": 100.0},
     UNRESOLVED, "absent_as_the_service_now_returns_it"),
    ({"units": 1.0, "fill": 100.0, "position_id": "p-3", "sized_units": 1.0},
     UNRESOLVED, "absent_WITH_units_which_used_to_open_a_position"),
    ({"status": None, "units": 1.0}, UNRESOLVED, "present_None"),
    ({"status": "", "units": 1.0}, UNRESOLVED, "present_blank"),
    ({"status": 0, "units": 1.0}, UNRESOLVED, "int"),
    ({"status": {}, "units": 1.0}, UNRESOLVED, "unhashable_dict"),
    ({"status": [], "units": 1.0}, UNRESOLVED, "unhashable_list"),
    ({"status": _HostileStatus(), "units": 1.0}, UNRESOLVED, "hostile_eq"),
    ({"status": "NEW", "units": 1.0, "position_id": "oid-1"}, UNRESOLVED, "acknowledged_NEW"),
    ({"status": "ACCEPTED", "units": 1.0, "filled_units": None}, UNRESOLVED, "acknowledged_ACCEPTED"),
    ({"status": "PENDING_NEW", "units": 1.0}, UNRESOLVED, "acknowledged_PENDING_NEW"),
    ({"status": "CANCELED", "units": 1.0, "filled_units": 0.4, "position_id": "oid-2"},
     UNRESOLVED, "CANCELED_carrying_a_fill"),
    # No normalisation: a spelling no producer emits is not trusted as a fill.
    ({"status": "filled", "units": 1.0, "fill": 100.0}, UNRESOLVED, "unemitted_lowercase_filled"),
    ({"status": " FILLED", "units": 1.0, "fill": 100.0}, UNRESOLVED, "unemitted_padded_FILLED"),
    # K-9: OBSERVE is never this loop's mode (V3), but if "observed" arrives anyway it takes the halt
    # seam — it must not raise out of the tick, and the alert's status repr tells the operator.
    ({"status": "observed", "would_size": 0.4}, UNRESOLVED, "observed_arriving_anyway"),
]


def _instrument(monkeypatch, loop):
    """Record every branch-specific action; let the unresolved RECORDER run with only its session
    stubbed, so its alert is observed as written rather than assumed (`#49`'s lesson)."""
    import app.db.session as sess
    from app.services.live import crypto_loop as mod

    seen = {"signal_decision": 0, "rejected_row": [], "unsized_fill": 0, "push": 0, "alerts": []}

    async def _signal_row(*a, **k):
        seen["signal_decision"] += 1

    async def _rejected(*a, **k):
        seen["rejected_row"].append(a[5] if len(a) > 5 else k.get("code"))

    async def _unsized(*a, **k):
        seen["unsized_fill"] += 1

    async def _push(*a, **k):
        seen["push"] += 1

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, row):
            seen["alerts"].append(row)

        async def commit(self):
            return None

    monkeypatch.setattr(loop, "_record_signal_decision", _signal_row)
    monkeypatch.setattr(loop, "_record_rejected_signal", _rejected)
    monkeypatch.setattr(loop, "_record_unsized_fill", _unsized)
    monkeypatch.setattr(mod.ws_manager, "push_position_open", _push)
    monkeypatch.setattr(sess, "async_session_maker", lambda: _Session())
    return seen


async def _drive(monkeypatch, result=None, *, execute=None):
    async def _returns(_sig):
        return dict(result)

    loop, acts = _drive_tick(monkeypatch, execute or _returns)
    seen = _instrument(monkeypatch, loop)
    await loop._tick_symbol("BTC/USD", "BTCUSDT")
    return loop, acts, seen


def _signature(loop, seen):
    from app.services.live import crypto_loop as mod

    return {
        "signal_decision": seen["signal_decision"], "push": seen["push"],
        "rejected_rows": len(seen["rejected_row"]), "unsized_fill": seen["unsized_fill"],
        "halt": loop.halt_reason,
        "unresolved_alerts": sum(1 for r in seen["alerts"] if type(r).__name__ == "Alert"
                                 and (r.context_json or {}).get("halt_reason") == mod.HALT_ORDER_UNRESOLVED),
    }


def _want(expected):
    from app.services.live import crypto_loop as mod

    return {
        FILL: {"signal_decision": 1, "push": 1, "rejected_rows": 0, "unsized_fill": 0, "halt": None,
               "unresolved_alerts": 0},
        REFUSAL: {"signal_decision": 0, "push": 0, "rejected_rows": 1, "unsized_fill": 0, "halt": None,
                  "unresolved_alerts": 0},
        UNRESOLVED: {"signal_decision": 0, "push": 0, "rejected_rows": 0, "unsized_fill": 0,
                     "halt": mod.HALT_ORDER_UNRESOLVED, "unresolved_alerts": 1},
    }[expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("result,expected,_id", CASES, ids=[c[2] for c in CASES])
async def test_L1_the_THREE_classes_are_told_apart_by_what_the_loop_DOES(monkeypatch, result, expected, _id):
    """**Three exact action signatures, not "the outcomes differ".** Each class must do its own thing
    and NEITHER of the others' — a fill that also halts, or an unresolved result that also writes a
    rejection row, is two contradictory records of one event."""
    loop, acts, seen = await _drive(monkeypatch, result)
    kinds = [k for k, _ in acts]
    assert "signal" in kinds, f"the tick never reached the order path, so nothing below means anything: {acts}"

    done, want = _signature(loop, seen), _want(expected)
    assert done == want, f"{_id}: expected the {expected.upper()} signature {want}, the loop did {done}"
    if expected == UNRESOLVED:
        assert "halt" in kinds, f"the operator was not told the engine halted: {acts}"
        assert loop.halt_record_failed is None, (
            f"the alert was written but the missing-record alarm still reads {loop.halt_record_failed!r}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"{truncated", b"null", b"[]", b'"ok"'],
                         ids=["empty_body", "malformed_json", "json_null", "json_list", "json_str"])
async def test_L1b_an_unreadable_200_END_TO_END_halts_and_files_NO_refusal(monkeypatch, body):
    """**K-1 and K-4 end to end: the real service between the adapter's value and the loop's branch.**
    Before, `{}` became FILLED (then a false partial-fill halt and row) and a non-dict raised into the
    loop's venue-raised backstop (a false REJECTED row). Now each halts on the seam and nothing raises."""
    service = _double_service(_empty_200_payload(body))

    async def _execute(_drive_signal):
        # The drive's stand-in signal carries only what the loop reads; the real service needs a real one.
        return await service.execute(_signal())

    loop, _acts, seen = await _drive(monkeypatch, execute=_execute)

    assert _signature(loop, seen) == _want(UNRESOLVED), (body, _signature(loop, seen), seen["rejected_row"])


@pytest.mark.asyncio
async def test_L2_the_unresolved_halt_leaves_EXACTLY_ONE_row_the_PRE_SEND_one_SUBMITTING_and_NAMES_it(monkeypatch):
    """**`T-0144` T-5 (revision 3 superseded "no row").** The entry's SUBMITTING record is written BEFORE the send
    (R11'), and SUBMITTING is the engine's own pre-send state, not a claim about the venue — so on the unresolved path
    that record is the ONE row, it is left exactly as it is, and the halt names its decision id. The recorder still
    runs with only its session stubbed, and its alert must be observed.

        CATCHES      a second DecisionRecord constructed on this drive, in any spelling; the SUBMITTING row moved
                     away (any transition attempted); a halt, activity line or alert that does not name the decision
        DOES NOT     a path this drive never executes; a row inserted without constructing the model
    """
    import app.models.decision_record as dr_mod
    from app.services.live import crypto_loop as mod

    built: list[str] = []
    real = dr_mod.DecisionRecord

    def _recording(*a, **k):
        built.append(str(k.get("outcome", "?")))
        return real(*a, **k)

    monkeypatch.setattr(dr_mod, "DecisionRecord", _recording)
    ids: list = []

    async def _execute(sig):
        # the real service awaits the pre-send write immediately before `place_order`; this drive does the same
        ids.append(sig.decision_id)
        await sig.before_send(SimpleNamespace(client_order_id=f"tai-{sig.decision_id.hex}"),
                              {"sized_units": 1.0, "sizing_price": 100.0, "equity_at_entry": 10_000.0})
        return {"status": "NEW", "units": 1.0, "position_id": "oid-1"}

    transitions: list = []
    loop, acts, seen = None, None, None

    async def _no_transition(*a, **k):
        transitions.append((a, k))
        return True

    monkeypatch.setattr(mod.LiveCryptoLoop, "_transition_decision", _no_transition)
    # driven by hand rather than `_drive`: `_instrument` stubs the recorders, and a SECOND row inserted through one of them
    # (or the row moved away through one) would never be seen here. The recorders stay REAL; only the session is stubbed.
    loop, acts = _drive_tick(monkeypatch, _execute)
    seen = _instrument(monkeypatch, loop)
    for recorder in ("_record_signal_decision", "_record_rejected_signal", "_record_unsized_fill"):
        monkeypatch.setattr(loop, recorder, getattr(mod.LiveCryptoLoop, recorder).__get__(loop))
    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    assert len(ids) == 1, f"the entry never reached the send: {acts}"
    decision_id = str(ids[0])
    assert built == [dr_mod.OUTCOME_SUBMITTING], (
        f"expected exactly the pre-send SUBMITTING row on the unresolved-order path, constructed: {built}")
    assert transitions == [], f"the SUBMITTING row was moved away on the unresolved path: {transitions}"
    assert loop.halt_reason == mod.HALT_ORDER_UNRESOLVED
    alerts = [r for r in seen["alerts"] if type(r).__name__ == "Alert"]
    assert alerts and (alerts[0].context_json or {}).get("decision_id") == decision_id, (
        f"the recorder's alert does not name the decision {decision_id}: {[getattr(r, 'context_json', None) for r in alerts]}")
    assert any(decision_id in text for kind, text in acts if kind == "halt"), f"the halt line does not name it: {acts}"


def _signal_row_kwargs() -> set[str]:
    """The keyword names `_record_signal_decision` passes to `DecisionRecord`, read from its source."""
    from app.services.live.crypto_loop import LiveCryptoLoop

    tree = ast.parse(inspect.getsource(LiveCryptoLoop))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_record_signal_decision")
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
             and getattr(c.func, "id", None) == "DecisionRecord"]
    assert len(calls) == 1, f"expected one DecisionRecord(...) in _record_signal_decision, found {len(calls)}"
    return {k.arg for k in calls[0].keywords if k.arg is not None}


@pytest.mark.asyncio
async def test_L3_the_alert_carries_EVERYTHING_a_truthful_row_needs(monkeypatch):
    """**The manager's condition for writing no row: the row is DEFERRED to `B427`, not lost** (K-8).

    The required field list is DERIVED from `_record_signal_decision`'s own `DecisionRecord(...)` call,
    minus what that call computes or fixes rather than receives, so a new column added there fails
    this arm until the alert carries it too."""
    from app.services.live import crypto_loop as mod

    _loop, _acts, seen = await _drive(monkeypatch, {
        "units": 1.0, "position_id": "oid-7", "client_order_id": "coid-7", "sized_units": 0.5,
        "equity_at_entry": 10_000.0, "sizing_price": 100.25, "fill": 100.5,
    })
    alert = next(r for r in seen["alerts"] if type(r).__name__ == "Alert")
    ctx = alert.context_json

    assert ctx["halt_reason"] == mod.HALT_ORDER_UNRESOLVED
    assert ctx["position_id"] == "oid-7" and alert.suggested_action["order_id"] == "oid-7", (
        "the alert does not carry the handle to find the order at the venue"
    )
    assert ctx["client_order_id"] == "coid-7" and alert.suggested_action["client_order_id"] == "coid-7", (
        "the alert does not carry the client order id"
    )

    row = ctx["row_inputs"]
    derived_or_fixed = {"score", "abstained", "expected_r", "outcome", "cohort"}
    missing = (_signal_row_kwargs() - derived_or_fixed) - set(row)
    assert not missing, f"a truthful row could not be rebuilt from the alert; it lacks {sorted(missing)}"
    # VALUES, not only keys — each from its real source on this drive.
    assert (row["symbol"], row["signal_dir"], row["signal_entry"], row["signal_sl"], row["signal_tp"]) == \
        ("BTC/USD", "LONG", 100.0, 99.0, None), row
    assert (row["sized_units"], row["sizing_equity"], row["sizing_price"], row["fill_price"],
            row["sizing_risk_pct"]) == (0.5, 10_000.0, 100.25, 100.5, 0.01), row
    assert len(row["inputs_hash"]) == 16 and len(row["code_path_hash"]) == 16, row
    assert "b429" in row["reasons"], f"the strategy trace's reasons were not carried: {row['reasons']!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("result,status_repr,key_present", [
    ({"units": 1.0}, "None", False),
    ({"status": None, "units": 1.0}, "None", True),
    ({"status": "", "units": 1.0}, "''", True),
    ({"status": "observed", "would_size": 0.4}, "'observed'", True),
], ids=["absent", "present_None", "present_blank", "observed"])
async def test_L3b_ABSENT_None_and_BLANK_stay_distinguishable_in_the_record(monkeypatch, result, status_repr,
                                                                           key_present):
    """**Emptiness has three axes, and the record keeps all three.** `str()` would store absent, `None`
    and `""` as "None", "None" and "" — and absent-vs-None is exactly the pair `B419` separated. With
    absent alone, `str` and `repr` agree, so the blank case is what makes a `str()` edit visible."""
    _loop, _acts, seen = await _drive(monkeypatch, result)
    ctx = next(r for r in seen["alerts"] if type(r).__name__ == "Alert").context_json
    assert (ctx["status_repr"], ctx["status_key_present"]) == (status_repr, key_present), ctx


@pytest.mark.asyncio
async def test_L4_the_recorder_CLEARS_the_alarm_only_on_success_and_NAMES_each_failure(monkeypatch):
    """`_declare_halt` arms `halt_record_failed`; the writer's last statement sets it from what failed."""
    import pandas as pd

    import app.db.session as sess
    from app.services.live import crypto_loop as mod

    added: list = []
    fail = {"commit": False}

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, row):
            added.append(row)

        async def commit(self):
            if fail["commit"]:
                raise RuntimeError("database unavailable")

    monkeypatch.setattr(sess, "async_session_maker", lambda: _Session())

    class _Dir:
        value = "LONG"

    class _Sig:
        direction, entry, sl, tp, risk_pct = _Dir(), 100.0, 99.0, None, 0.01

    res = {"status": "NEW", "position_id": "oid-1"}
    bars = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]},
                        index=pd.DatetimeIndex(["2026-09-13T00:00:00Z"]))

    loop = mod.LiveCryptoLoop()
    loop._declare_halt(mod.HALT_ORDER_UNRESOLVED)
    assert loop.halt_record_failed, "premise: declaring the halt did not arm the alarm"
    await loop._record_unresolved_order("BTC/USD", bars, _Sig(), res)
    assert added and loop.halt_record_failed is None, (
        f"a successful write left the alarm standing: {loop.halt_record_failed!r}"
    )

    fail["commit"] = True
    loop._declare_halt(mod.HALT_ORDER_UNRESOLVED)
    await loop._record_unresolved_order("BTC/USD", bars, _Sig(), res)
    assert loop.halt_record_failed and "alert: RuntimeError" in loop.halt_record_failed, loop.halt_record_failed
    assert loop.halt_reason == mod.HALT_ORDER_UNRESOLVED, "a failed record un-halted the engine"

    # An alert WITHOUT its row inputs is an incomplete record, and must say so while still being written.
    fail["commit"] = False
    added.clear()

    def _boom():
        raise RuntimeError("hash unavailable")

    monkeypatch.setattr(loop, "_code_path_hash", _boom)
    loop._declare_halt(mod.HALT_ORDER_UNRESOLVED)
    await loop._record_unresolved_order("BTC/USD", bars, _Sig(), res)
    assert added, "a failure assembling the row inputs stopped the alert being written"
    assert loop.halt_record_failed and "row_inputs: RuntimeError" in loop.halt_record_failed, (
        f"the alert lost its row inputs and the record reports healthy: {loop.halt_record_failed!r}"
    )


@pytest.mark.asyncio
async def test_L5_the_halt_is_IN_FORCE_even_when_the_recorder_RAISES(monkeypatch):
    """**K-7 / `M-7`.** The seam declares the halt before it records; a record that escapes its own
    guards must not leave the engine trading around a position it cannot see."""
    from app.services.live import crypto_loop as mod

    async def _execute(_sig):
        return {"status": "NEW", "units": 1.0}

    loop, _acts = _drive_tick(monkeypatch, _execute)
    _instrument(monkeypatch, loop)

    async def _explodes(*a, **k):
        raise RuntimeError("recorder escaped")

    monkeypatch.setattr(loop, "_record_unresolved_order", _explodes)
    with pytest.raises(RuntimeError, match="recorder escaped"):
        await loop._tick_symbol("BTC/USD", "BTCUSDT")
    assert loop.halt_reason == mod.HALT_ORDER_UNRESOLVED, "the halt was not in force before the record ran"


# ---------------------------------------------------------------------------------------------------
# PRODUCERS DRIVEN — the running engine never halts on ordinary operation (K-5)
# ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("broker_mode", ["paper", "sim"])
async def test_P1_the_loops_OWN_simulator_through_the_real_service_never_lands_in_UNRESOLVED(broker_mode):
    """**B430 keeps the engine on a simulator, so this is the path that runs when it is started.** If an
    ordinary fill or refusal there classified UNRESOLVED, this fix would halt the engine on its first
    refused signal. Driven, not transcribed: the real `LiveCryptoLoop`, its real broker, its real
    `ExecutionService`, and each outcome classified by the loop's own classifier."""
    from app.core.exceptions import BrokerError
    from app.db.enums import DirectionType
    from app.services.execution.service import ExecMode, ExecutionService
    from app.services.live import crypto_loop as mod

    # NO REFERENCE PRICE first, on a loop that has never seen a mark: `PaperBroker` caches the first
    # mark it reads, so removing one later does not reach this path (measured: it filled).
    bare = mod.LiveCryptoLoop(broker_mode=broker_mode)
    await bare.paper.connect()
    no_reference_price = await bare.execution.execute(_signal())

    loop = mod.LiveCryptoLoop(broker_mode=broker_mode)
    loop._marks["BTC/USD"] = 100.0
    await loop.paper.connect()
    classify = mod.classify_order_status

    fill = await loop.execution.execute(_signal())
    assert classify(fill.get("status")) in mod.FILL_OUTCOMES, (broker_mode, fill)

    refusals = {
        "venue_direction": await loop.execution.execute(_signal(100.0, 101.0, 98.0, DirectionType.SHORT)),
        "entry_drift": await loop.execution.execute(_signal(150.0, 149.0, 152.0)),
        "degenerate_stop": await loop.execution.execute(_signal(100.0, 100.0, 102.0)),
        "non_positive_size": await loop.execution.execute(_signal(100.0, 100.0 - 1e12, 102.0)),
        # Through the stop needs a drift limit above 1R, since a mark beyond the stop is at least 1R
        # from the entry — the same service class over the same broker, with only that limit raised.
        "through_stop": await ExecutionService(loop.paper, ExecMode.PAPER, max_entry_drift_r=10.0)
        .execute(_signal(100.5, 100.2, 101.0)),
    }
    refusals["no_reference_price"] = no_reference_price

    real_place = loop.paper.place_order

    async def _venue_error(_request):
        raise BrokerError("venue unavailable", broker=broker_mode)

    loop.paper.place_order = _venue_error
    refusals["venue_transport"] = await loop.execution.execute(_signal())
    loop.paper.place_order = real_place

    if broker_mode == "sim":
        loop.paper._halted, loop.paper._breach_reason = True, "max_drawdown_breached"
        refusals["prop_firm_halted"] = await loop.execution.execute(_signal())

    wrong = {k: (r.get("status"), r.get("rejection_code")) for k, r in refusals.items()
             if classify(r.get("status")) != mod.ORDER_REFUSED}
    assert not wrong, f"{broker_mode}: an ordinary refusal would HALT the engine instead of recording: {wrong}"
    assert all(r.get("rejection_code") for r in refusals.values()), (
        {k: r for k, r in refusals.items() if not r.get("rejection_code")}
    )


@pytest.mark.asyncio
async def test_P2_the_ALPACA_adapter_driven_fills_are_fills_and_its_refusals_are_refusals():
    """**The venue adapter, driven through its own doubles (`test_t0140`'s).** A fill and a partial come
    back as fills; a SHORT raises its direction refusal, which the real service turns into a REFUSAL.
    An ACKNOWLEDGEMENT is deliberately UNRESOLVED and halts — that is `B427`'s seam, stated here so it
    reads as the design rather than an accident."""
    from alpaca.trading.enums import OrderStatus

    from app.db.enums import DirectionType
    from app.services.execution.service import ExecMode, ExecutionService
    from app.services.live import crypto_loop as mod
    from tests.unit.test_t0140_order_body import _adapter, _order, _req

    classify = mod.classify_order_status

    adapter, _client = _adapter()
    filled = await adapter.place_order(_req())
    assert classify(filled["status"]) == mod.ORDER_FILLED, filled

    def _with_status(status, filled_qty):
        def submit(order_data):
            o = _order(str(order_data.qty))
            object.__setattr__(o, "status", status)
            object.__setattr__(o, "filled_qty", filled_qty)
            return o
        return submit

    adapter, client = _adapter()
    client.submit_order = _with_status(OrderStatus.PARTIALLY_FILLED, "0.004")
    partial = await adapter.place_order(_req())
    assert classify(partial["status"]) == mod.ORDER_PARTIALLY_FILLED, partial

    adapter, client = _adapter()
    client.submit_order = _with_status(OrderStatus.NEW, "0")
    acknowledged = await adapter.place_order(_req())
    assert classify(acknowledged["status"]) == mod.ORDER_UNRESOLVED, acknowledged

    adapter, _client = _adapter()

    class _Acct:
        equity = 10_000.0

    class _Venue:
        is_simulation = True

        async def get_account(self):
            return _Acct()

        async def reference_price(self, _symbol):
            return 100.0

        async def place_order(self, request):
            return await adapter.place_order(request)

    refused = await ExecutionService(_Venue(), ExecMode.PAPER).execute(
        _signal(100.0, 101.0, 98.0, DirectionType.SHORT))
    assert classify(refused.get("status")) == mod.ORDER_REFUSED, refused


@pytest.mark.asyncio
@pytest.mark.parametrize("filled_qty,expected", [
    ("", None), ("nan", None), ("garbage", None),
    # Review's K-4b': these parse WITHOUT raising, to +/-inf, so a fix that special-cases NaN alone
    # still stores an infinity. "1e999" does not look like one to a reader, which is why it is here.
    ("1e999", None), ("-inf", None),
    ("0.5", 0.5),
], ids=["blank", "nan", "garbage", "1e999_is_infinity", "minus_inf", "readable_must_miss"])
async def test_P3_an_UNREADABLE_filled_qty_is_REPORTED_unreadable_not_RAISED_after_submission(filled_qty, expected):
    """**K-4b, at the adapter.** The quantity is read AFTER the order is submitted, so a raise here reaches
    the loop's venue-raised backstop and files a REFUSAL for an order that exists. `"nan"` is kept on
    purpose: a bare `float()` returns NaN without raising, so it is the case that separates the
    three-state parse from a try/except around `float()`.

    The loop half is not re-armed here: `_position_units` decides the FILLED fallback by KEY PRESENCE,
    and `test_t0141_partial_fill` already pins present-`None` against absent (manager's narrowing)."""
    from alpaca.trading.enums import OrderStatus

    from tests.unit.test_t0140_order_body import _adapter, _order, _req

    adapter, client = _adapter()

    def submit(order_data):
        o = _order(str(order_data.qty))
        object.__setattr__(o, "status", OrderStatus.FILLED)
        object.__setattr__(o, "filled_qty", filled_qty)
        return o

    client.submit_order = submit
    result = await adapter.place_order(_req())

    assert "filled_units" in result, "the key must be PRESENT, so the loop reads 'the venue spoke' by membership"
    if expected is None:
        assert result["filled_units"] is None, f"unreadable filled_qty {filled_qty!r} was reported as {result['filled_units']!r}"
    else:
        assert result["filled_units"] == expected, f"filled_qty {filled_qty!r} was reported as {result['filled_units']!r}"


# ---------------------------------------------------------------------------------------------------
# B433 — THE FILL PRICE (F-1, FU-1b, FU-1c) AND THE ENTRY LINE (F-2)
#
# Found by review beside T-0130: `float(filled_avg_price or 0) or None` one line below the K-4b fix, the
# same class. The consumers are why zero and non-finite must be `None` (review measured three):
# `ExecutionService`'s realized_risk_per_unit, `_record_signal_decision`'s basis and expected_r, and the
# settle path's entry — each uses the fill whenever it is not `None`.
# ---------------------------------------------------------------------------------------------------

UNREADABLE_PRICES = ["garbage", "nan", "inf", "-inf", "1e999", "", "   ", None, "0", 0.0, "-5", -5.0]
PRICE_IDS = ["garbage", "nan", "inf", "minus_inf", "1e999", "blank", "spaces", "None", "zero_str", "zero_float",
             "negative_str", "negative_float"]


@pytest.mark.parametrize("raw", UNREADABLE_PRICES, ids=PRICE_IDS)
def test_B1_a_venue_PRICE_is_positive_and_finite_or_None(raw):
    """**The zero rule is per field** (manager): a zero quantity is a reading, a zero price is not a
    price, and neither is a negative one — `or None` kept a truthy -5.0."""
    from app.services.broker.base import readable_price

    assert readable_price(raw) is None, f"{raw!r} was read as a price: {readable_price(raw)!r}"


@pytest.mark.parametrize("helper", ["readable_quantity", "readable_price"])
@pytest.mark.parametrize("raw", [
    __import__("json").loads("1" + "0" * 400), "1" + "0" * 400, True, False,
], ids=["json_int_401_digits", "string_401_digits", "true", "false"])
def test_B7_NEITHER_helper_raises_or_reads_a_BOOL_as_a_number(helper, raw):
    """**The contract covers every value `json.loads` can produce, not only plausible ones** (manager, from
    review's finding on `b4e6e1f`). `float()` of a 401-digit INT raises OverflowError, which the first
    version's `except` did not catch — the same digits as a STRING read as inf and were already `None`, so a
    string-only arm could never have found it. And `isinstance(True, int)` made `True` a fill of one unit."""
    import app.services.broker.base as base

    assert getattr(base, helper)(raw) is None, f"{helper}({type(raw).__name__}) did not read as unreadable"


def test_B7b_real_numbers_still_read_after_the_bool_rule():
    from app.services.broker.base import readable_price, readable_quantity

    assert [readable_quantity(x) for x in (1, 1.0, "0")] == [1.0, 1.0, 0.0]
    assert [readable_price(x) for x in (1, 1.0)] == [1.0, 1.0]


@pytest.mark.parametrize("res", [
    {"status": "FILLED", "filled_units": __import__("json").loads("1" + "0" * 400)},
    {"status": "FILLED", "units": __import__("json").loads("1" + "0" * 400)},
    {"status": "PARTIALLY_FILLED", "filled_units": __import__("json").loads("1" + "0" * 400)},
    {"status": "FILLED", "filled_units": True},
    {"status": "FILLED", "units": True},
], ids=["filled_units_401_digits", "units_401_digits", "partial_401_digits", "filled_units_true", "units_true"])
def test_B8_position_units_NEVER_raises_and_never_sizes_a_BOOL(res):
    """**The fourth site of the class** (execute, sweeping for sibling "never raises" claims):
    `_position_units`' own `positive()` had the same `except (TypeError, ValueError)` and read `True` as
    one unit. K-12's contract — the runbook's probe runs it on a raw venue dict."""
    from app.services.live.crypto_loop import LiveCryptoLoop

    assert LiveCryptoLoop._position_units(res) is None


def test_B8b_an_ordinary_size_still_reads_and_WHICH_KEY_is_read_is_unchanged():
    """The delegation changes how a value is PARSED and must not change which key is read (manager):
    `filled_units` ABSENT on a paper FILLED result still falls back to `units`; PRESENT-None does not."""
    from app.services.live.crypto_loop import LiveCryptoLoop

    assert LiveCryptoLoop._position_units({"status": "FILLED", "units": 0.004}) == 0.004
    assert LiveCryptoLoop._position_units({"status": "FILLED", "units": 0.004, "filled_units": None}) is None
    assert LiveCryptoLoop._position_units({"status": "FILLED", "units": 0.004, "filled_units": 0.003}) == 0.003
    assert LiveCryptoLoop._position_units({"status": "PARTIALLY_FILLED", "filled_units": "0.0005"}) == 0.0005


def test_B1b_the_price_and_quantity_rules_DIFFER_only_at_zero_and_below():
    from app.services.broker.base import readable_price, readable_quantity

    assert (readable_price("70000.5"), readable_price(70000)) == (70000.5, 70000.0)
    assert (readable_quantity("0"), readable_quantity(0.0)) == (0.0, 0.0), "a zero QUANTITY is a reading"
    assert readable_quantity("nan") is None and readable_quantity("1e999") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", UNREADABLE_PRICES, ids=PRICE_IDS)
async def test_B2_the_ALPACA_fill_price_is_PARSED_never_raised_after_submission(raw):
    """F-1 at the adapter: "garbage" raised ValueError AFTER the order was submitted (a false refusal
    through the venue-raised backstop), and NaN and inf passed through as prices."""
    from alpaca.trading.enums import OrderStatus

    from tests.unit.test_t0140_order_body import _adapter, _order, _req

    adapter, client = _adapter()

    def submit(order_data):
        o = _order(str(order_data.qty))
        object.__setattr__(o, "status", OrderStatus.FILLED)
        object.__setattr__(o, "filled_avg_price", raw)
        return o

    client.submit_order = submit
    result = await adapter.place_order(_req())
    assert "fill" in result and result["fill"] is None, f"filled_avg_price {raw!r} gave fill {result.get('fill')!r}"


@pytest.mark.asyncio
async def test_B2b_a_READABLE_fill_price_survives_the_adapter():
    from tests.unit.test_t0140_order_body import _adapter, _req

    adapter, _client = _adapter()          # the double's order fills at "70000"
    assert (await adapter.place_order(_req()))["fill"] == 70000.0


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", UNREADABLE_PRICES, ids=PRICE_IDS)
async def test_B3_the_SERVICE_normalises_the_fill_for_EVERY_producer(raw):
    """**FU-1b.** `if fill is not None: abs(float(fill) - sig.sl)` guarded `None` only. Only the simulators
    and Alpaca hold the slot today, and that is `B430`'s shape, so the service makes a readable price true
    BY CONSTRUCTION for whatever a producer forwards."""
    res = await _service_result({"status": "FILLED", "units": 1.0, "fill": raw})
    assert "fill" in res and res["fill"] is None, f"fill {raw!r} reached the loop as {res.get('fill')!r}"
    assert "realized_risk_per_unit" not in res, f"a risk was computed from fill {raw!r}: {res!r}"


@pytest.mark.asyncio
async def test_B3b_a_READABLE_fill_is_used_and_an_ABSENT_one_stays_absent():
    readable = await _service_result({"status": "FILLED", "units": 1.0, "fill": "100.5"})
    assert readable["fill"] == 100.5 and readable["realized_risk_per_unit"] == pytest.approx(1.5), readable
    absent = await _service_result({"status": "FILLED", "units": 1.0})
    assert "fill" not in absent and "realized_risk_per_unit" not in absent, absent


def _capture_rows(monkeypatch):
    """Let `_record_signal_decision` RUN and capture what it builds; only the database session is stubbed."""
    import app.db.session as sess

    rows: list = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, row):
            rows.append(row)

        async def commit(self):
            return None

    monkeypatch.setattr(sess, "async_session_maker", lambda: _Session())
    return rows


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["garbage", "nan", 0.0], ids=["garbage", "nan", "zero"])
async def test_B4_an_unreadable_fill_THROUGH_THE_LOOP_still_records_the_OPEN_decision(monkeypatch, raw):
    """**FU-1c — the silent site.** `_record_signal_decision` does `float(fill_price)` inside a blanket
    `except` that logs a warning, so "garbage" did not raise: it DROPPED THE OPEN ROW for a position that
    opened, and NaN wrote `Decimal('NaN')`. Driven through the real service and the real recorder, because
    an arm on the service's dict alone cannot show the loop is covered, and there is no raise to catch."""
    from app.services.live import crypto_loop as mod

    service = _double_service({"status": "FILLED", "units": 1.0, "fill": raw, "position_id": "p-9"})

    async def _execute(_drive_signal):
        return await service.execute(_signal())

    loop, acts = _drive_tick(monkeypatch, _execute)
    rows = _capture_rows(monkeypatch)

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(mod.ws_manager, "push_position_open", _noop)
    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    decisions = [r for r in rows if type(r).__name__ == "DecisionRecord"]
    assert decisions, f"fill {raw!r}: the OPEN decision row for a position that opened was not recorded: {acts}"
    assert decisions[0].outcome == "OPEN" and decisions[0].fill_price is None, (
        decisions[0].outcome, decisions[0].fill_price)


@pytest.mark.asyncio
@pytest.mark.parametrize("result,shown", [
    ({"status": "FILLED", "units": 1.0, "sized_units": 1.0, "fill": None, "position_id": "p-1"}, None),
    ({"status": "FILLED", "units": 1.0, "sized_units": 1.0, "position_id": "p-1"}, None),
    ({"status": "FILLED", "units": 1.0, "sized_units": 1.0, "fill": 70000.0, "position_id": "p-1"}, "@ 70000"),
], ids=["present_None", "absent", "readable_must_miss"])
async def test_B5_the_ENTRY_line_never_presents_the_SIGNAL_entry_as_a_fill(monkeypatch, result, shown):
    """**F-2.** `res.get('fill', sig.entry):.0f` raised TypeError on a PRESENT `None` — after the decision
    was recorded and the position pushed — and where the default did apply it printed the signal's entry
    after "@", a fill price nobody reported."""
    async def _execute(_sig):
        return dict(result)

    loop, acts = _drive_tick(monkeypatch, _execute)
    seen = _instrument(monkeypatch, loop)
    recorded: list = []

    async def _signal_row(*a, **k):
        recorded.append(k.get("fill_price", "MISSING"))

    monkeypatch.setattr(loop, "_record_signal_decision", _signal_row)
    await loop._tick_symbol("BTC/USD", "BTCUSDT")

    entry = [m for kind, m in acts if kind == "entry"]
    assert entry and seen["push"] == 1, f"the fill branch did not complete: {acts}"
    if shown is None:
        assert "@ 100" not in entry[0] and "fill price unreported" in entry[0], entry[0]
        assert recorded == [None], f"the decision was given a fill price nobody reported: {recorded}"
    else:
        assert shown in entry[0], entry[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("units", __import__("decimal").Decimal("1.5")), ("filled_units", float("nan")), ("filled_units", float("inf")),
], ids=["decimal", "nan", "inf"])
async def test_B6_the_unresolved_ALERT_is_strict_JSON_whatever_the_result_carries(monkeypatch, field, value):
    """**FU-5.** A Decimal or a NaN in `context_json` fails the write (or stores non-standard JSON), and the
    alert for a position nobody tracks is the record that must not fail."""
    import json

    _loop, _acts, seen = await _drive(monkeypatch, {"status": "NEW", field: value, "position_id": "oid-1"})
    ctx = next(r for r in seen["alerts"] if type(r).__name__ == "Alert").context_json
    json.dumps(ctx, allow_nan=False)
    assert isinstance(ctx[field], str), f"{field}={value!r} was stored as {ctx[field]!r}"


# ---------------------------------------------------------------------------------------------------
# VOCABULARY AND STRUCTURE
# ---------------------------------------------------------------------------------------------------

def test_V1_the_status_sets_are_DISJOINT():
    """**Shape eight.** A status in two sets is a fill AND a refusal, and whichever branch is tested
    first wins silently; a union-only consumer could never see the move."""
    from app.services.live import crypto_loop as mod

    fill, refusal, elsewhere = (set(mod.FILL_BEARING_STATUSES), set(mod.REFUSAL_STATUSES),
                                set(mod.NOT_FROM_THIS_LOOP_STATUSES))
    assert not fill & refusal, f"fill-bearing AND refusal: {fill & refusal}"
    assert not (fill | refusal) & elsewhere, f"classified AND not-from-this-loop: {(fill | refusal) & elsewhere}"
    classes = [mod.ORDER_FILLED, mod.ORDER_PARTIALLY_FILLED, mod.ORDER_REFUSED, mod.ORDER_UNRESOLVED]
    assert len(set(classes)) == 4 and mod.ORDER_REFUSED not in mod.FILL_OUTCOMES \
        and mod.ORDER_UNRESOLVED not in mod.FILL_OUTCOMES, classes


def _literal_strings(expr) -> set[str]:
    """The string constants an expression can EVALUATE to without a call: a constant, either arm of a
    conditional, or any operand of `and`/`or` (B433, FU-4 — `"A" if c else "X"` and `x or "X"`)."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if isinstance(expr, ast.IfExp):
        return _literal_strings(expr.body) | _literal_strings(expr.orelse)
    if isinstance(expr, ast.BoolOp):
        return set().union(*(_literal_strings(v) for v in expr.values))
    return set()


def _status_literals(source: str, function_names: set[str]) -> dict[str, set[str]]:
    """Every string constant a function can put under a `status` key or into a `status` variable.

    Reach, stated (B433, FU-4 widened it): a dict-literal `"status"` key; `status = ...`;
    `status: T = ...`; `x["status"] = ...`; a `status=` keyword; each through conditionals and
    `and`/`or`. NOT seen: a status built by a call, an f-string, or a variable whose name is not
    `status` — Alpaca's `str(raw).upper()` is the first, and UNRESOLVED exists for it."""
    found: dict[str, set[str]] = {}

    def _is_status_target(t) -> bool:
        return (isinstance(t, ast.Name) and t.id == "status") or (
            isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == "status")

    for fn in ast.walk(ast.parse(source)):
        if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in function_names):
            continue
        for node in ast.walk(fn):
            values = []
            if isinstance(node, ast.Dict):
                values = [v for k, v in zip(node.keys, node.values)
                          if isinstance(k, ast.Constant) and k.value == "status"]
            elif isinstance(node, ast.Assign):
                if any(_is_status_target(t) for t in node.targets):
                    values = [node.value]
            elif isinstance(node, ast.AnnAssign) and node.value is not None and _is_status_target(node.target):
                values = [node.value]
            elif isinstance(node, ast.Call):
                values = [k.value for k in node.keywords if k.arg == "status"]
            for v in values:
                for literal in _literal_strings(v):
                    found.setdefault(literal, set()).add(f"{fn.name}:{node.lineno}")
    return found


#: **A BOUNDED, REASONED EXEMPTION, keyed by (literal, the SITES allowed to emit it)** — not a list of unresolved
#: statuses (UNRESOLVED stays the complement), and not keyed by literal alone: review planted SUBMITTED in
#: `paper.place_order` and a literal-keyed exemption passed it, though a simulator emitting it would halt a running
#: engine. Each literal is allowed only where its reason applies.
DELIBERATELY_UNRESOLVED: dict[str, tuple[frozenset, str]] = {
    "SUBMITTED": (frozenset({"alpaca._order_result"}),
                  "Alpaca's result for an order returned with no readable status — not a known outcome, so it halts"),
    "SUBMISSION_UNCONFIRMED": (frozenset({"alpaca._unconfirmed_submission"}),
                               "Alpaca's result when a failed submission's order could not be found or matched "
                               "(B440/B441) — its existence is unknown, so it halts, never a refusal"),
}


def _unclassified_status_literals(emitted: dict[str, set[str]], known: set[str]) -> dict[str, list[str]]:
    """Literals a producer emits that are neither classified nor exempt AT THAT SITE. Sites are
    `module.function:line`; the exemption compares `module.function`."""
    out: dict[str, list[str]] = {}
    for literal, sites in emitted.items():
        if literal in known:
            continue
        allowed = DELIBERATELY_UNRESOLVED.get(literal, (frozenset(), ""))[0]
        stray = sorted(site for site in sites if site.rsplit(":", 1)[0] not in allowed)
        if stray:
            out[literal] = stray
    return out


def test_V2b_an_exemption_holds_ONLY_at_its_own_site():
    """The plant review ran: SUBMITTED emitted from `paper.place_order` must FAIL, and the real site must pass."""
    known = {"FILLED", "PARTIALLY_FILLED", "REJECTED", "rejected", "observed"}
    assert _unclassified_status_literals({"SUBMITTED": {"alpaca._order_result:10"}}, known) == {}
    assert _unclassified_status_literals({"SUBMITTED": {"paper.place_order:3"}}, known) == {
        "SUBMITTED": ["paper.place_order:3"]}
    assert _unclassified_status_literals(
        {"SUBMISSION_UNCONFIRMED": {"alpaca._unconfirmed_submission:9", "cft_sim.place_order:4"}}, known) == {
        "SUBMISSION_UNCONFIRMED": ["cft_sim.place_order:4"]}


def test_V2_every_status_LITERAL_a_producer_can_emit_is_CLASSIFIED():
    """**A new literal forces a decision instead of landing in whichever branch is the complement.**

    Scope, stated: string CONSTANTS only, in the loop's producers — `ExecutionService.execute` and the
    `place_order` of the three brokers its slot can hold (plus `cft_sim._reject`) — and, separately,
    `LiveLoopBrokerProxy.place_order`, which is NOT a loop producer (it serves the API and kill-switch
    path, and resolves the loop's broker at call time); its literals are pinned so the day it is wired
    in, a new one forces a decision. Its `close_position` vocabulary ("error") is a different axis and
    is deliberately not read. Alpaca passes the venue's own status through `str(raw).upper()`, which no
    scan can enumerate — that is exactly what UNRESOLVED is for."""
    import app.services.broker.alpaca as alpaca
    import app.services.broker.cft_sim as cft_sim
    import app.services.broker.live_loop_proxy as proxy
    import app.services.broker.paper as paper
    import app.services.execution.service as service
    from app.services.live import crypto_loop as mod

    known = set(mod.FILL_BEARING_STATUSES) | set(mod.REFUSAL_STATUSES) | set(mod.NOT_FROM_THIS_LOOP_STATUSES)

    # CONTROL FIRST: the instrument flags an unclassified literal, and finds a dict key and a variable.
    planted = _status_literals(
        "def place_order():\n    status = 'SUBMITTED'\n    return {'status': 'FILLED'}\n", {"place_order"})
    assert set(planted) == {"SUBMITTED", "FILLED"} and set(planted) - known == {"SUBMITTED"}, planted
    # FU-4: each widened form is SEEN, one planted literal per form.
    for form, literal in (("    rec['status'] = 'X_SUBSCRIPT'\n", "X_SUBSCRIPT"),
                          ("    status: str = 'X_ANNASSIGN'\n", "X_ANNASSIGN"),
                          ("    rec = {'status': 'FILLED' if ok else 'X_IFEXP'}\n", "X_IFEXP"),
                          ("    rec = {'status': raw or 'X_BOOLOP'}\n", "X_BOOLOP"),
                          ("    rec = dict(status='X_KEYWORD')\n", "X_KEYWORD")):
        seen = _status_literals("def place_order(rec, ok, raw):\n" + form, {"place_order"})
        assert literal in seen, f"the scan does not see {form.strip()!r}: {seen}"

    emitted: dict[str, set[str]] = {}
    for module, names in ((service, {"execute"}), (paper, {"place_order"}),
                          (cft_sim, {"place_order", "_reject"}), (alpaca, {"place_order", "_order_result", "_unconfirmed_submission"})):
        for value, sites in _status_literals(inspect.getsource(module), names).items():
            emitted.setdefault(value, set()).update(f"{module.__name__.rsplit('.', 1)[-1]}.{s}" for s in sites)

    # THE DENOMINATOR IS THE IDENTITY OF WHAT WAS FOUND, not a count: each producer must be seen.
    # `B427` moved Alpaca's status mapping out of place_order into `_order_result`, the one mapping.
    for must in ("service.execute", "paper.place_order", "cft_sim._reject", "alpaca._order_result"):
        assert any(s.startswith(must) for sites in emitted.values() for s in sites), (
            f"the scan found no status literal in {must}; it may be scanning nothing"
        )
    assert {"rejected", "REJECTED", "FILLED", "observed"} <= set(emitted), sorted(emitted)

    unclassified = _unclassified_status_literals(emitted, known)
    assert not unclassified, (
        f"a producer emits a status the loop does not classify: {unclassified}. Decide whether it is a "
        f"fill, a refusal, or not reachable from the loop — do not let it fall into UNRESOLVED by accident."
    )

    not_a_loop_producer = _status_literals(inspect.getsource(proxy), {"place_order"})
    assert set(not_a_loop_producer) == {"rejected"}, (
        f"LiveLoopBrokerProxy.place_order's vocabulary changed: {not_a_loop_producer}. It is not a loop "
        f"producer today; if it is becoming one, classify what it emits first."
    )


def _status_decisions_outside_classifier(tree: ast.AST, vocabulary: set[str]) -> list[str]:
    """Every way this module could decide what a status MEANS outside `classify_order_status`.

    Flagged (B433, FU-3 widened it beyond `Compare`):
      * ANY read of the classifier's own sets — a membership test, `.__contains__`, `set(...)` of them
      * a comparison with an ORDER-RESULT literal
      * a `match` whose case pattern is an ORDER-RESULT literal
      * a dict literal KEYED by an order-result literal (a dispatch table)
      * `.startswith` / `.endswith` with a non-empty prefix or suffix of an order-result literal
    Quiet: raw reads (`"status": res.get("status")` records, it does not decide) and other vocabularies
    (`TradeStatus.CLOSED`, the close path's `"refused"`). NOT seen: a decision made through a helper in
    ANOTHER module, or through a regex — stated rather than claimed."""
    sets = {"FILL_BEARING_STATUSES", "REFUSAL_STATUSES", "NOT_FROM_THIS_LOOP_STATUSES"}
    inside = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "classify_order_status":
            inside |= {id(n) for n in ast.walk(fn)}

    def _vocab_literal(expr) -> bool:
        return isinstance(expr, ast.Constant) and isinstance(expr.value, str) and expr.value in vocabulary

    found = []
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        hit = False
        if isinstance(node, ast.Name) and node.id in sets and isinstance(node.ctx, ast.Load):
            hit = True
        elif isinstance(node, ast.Compare):
            hit = any(_vocab_literal(c) for o in [node.left, *node.comparators] for c in ast.walk(o))
        elif isinstance(node, ast.match_case):
            hit = any(isinstance(p, ast.MatchValue) and _vocab_literal(p.value) for p in ast.walk(node.pattern))
        elif isinstance(node, ast.Dict):
            hit = any(k is not None and _vocab_literal(k) for k in node.keys)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("startswith", "endswith")
              and not isinstance(node.func.value, ast.Constant)):
            # SCOPED BY RECEIVER, NOT BY LENGTH (manager's ruling). A LITERAL receiver provably is not a
            # status (review measured 'loaded'.endswith('d') firing), so it is ignored. Any other receiver
            # with a non-empty prefix/suffix of an order-result word FIRES — `status.endswith("ED")` matches
            # FILLED, REJECTED and CANCELED, and a suffix match is `B411`'s own defect. There are ZERO
            # startswith/endswith calls in crypto_loop today (manager, AST-measured), so a strict rule has no
            # false positives; a benign one added later should fail here and be exempted by name, with a
            # reason, rather than be silenced by a threshold. (An EMPTY prefix is always true and decides
            # nothing, so it is not a status comparison.)
            args = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value]
            test = str.startswith if node.func.attr == "startswith" else str.endswith
            hit = any(test(v, a) for a in args for v in vocabulary)
        if hit:
            line = getattr(node, "lineno", None) or getattr(getattr(node, "pattern", None), "lineno", "?")
            found.append(f"line {line}: {ast.unparse(node)[:80]}")
    return found


def test_V4_what_a_status_MEANS_is_decided_ONLY_in_the_classifier():
    """**K-11.** Five decision sites became one. A membership test or literal comparison anywhere else
    is a second classifier that can disagree with the first — `B184` — so it fails here."""
    from app.services.live import crypto_loop as mod

    vocabulary = set(mod.FILL_BEARING_STATUSES) | set(mod.REFUSAL_STATUSES)
    source = inspect.getsource(mod)
    tree = ast.parse(source)

    outside = _status_decisions_outside_classifier(tree, vocabulary)
    assert not outside, f"a status decision outside classify_order_status: {outside}"

    # CONTROLS. Each planted decision FIRES on its own, and the legitimate neighbours stay QUIET.
    plants = {
        "compare": "if status == 'FILLED':\n        pass",
        "membership": "if status in REFUSAL_STATUSES:\n        pass",
        "contains": "if FILL_BEARING_STATUSES.__contains__(status):\n        pass",
        "match": "match status:\n        case 'FILLED':\n            pass",
        "dispatch": "kind = {'FILLED': 1, 'REJECTED': 2}.get(status)",
        "startswith": "if status.startswith('FILL'):\n        pass",
    }
    for shape, body in plants.items():
        planted = ast.parse(f"def elsewhere(status):\n    {body}\n")
        assert _status_decisions_outside_classifier(planted, vocabulary), f"the {shape} plant was not seen"
    quiet = ("def neighbours(res, t, event):\n    payload = {'status': res.get('status')}\n"
             "    if t.status == TradeStatus.CLOSED:\n        pass\n"
             "    if event.get('status') == 'refused':\n        pass\n"
             "    if 'loaded'.endswith('d') or 'LOADED'.endswith('ED'):\n        pass\n")
    assert _status_decisions_outside_classifier(ast.parse(quiet), vocabulary) == [], (
        _status_decisions_outside_classifier(ast.parse(quiet), vocabulary))
    # And the B411 shape fires, at full length AND at two characters — the case a length threshold hid.
    for suffix in ("FILLED", "ED"):
        planted = ast.parse(f"def b411(status):\n    if status.endswith('{suffix}'):\n        pass\n")
        assert _status_decisions_outside_classifier(planted, vocabulary), f"status.endswith({suffix!r}) was not seen"
    # And the classifier itself IS seen, so "nothing outside" is not "nothing anywhere".
    everywhere = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                  and n.id in {"FILL_BEARING_STATUSES", "REFUSAL_STATUSES"}]
    assert len(everywhere) == 2, f"expected the classifier's two reads of its sets, found {len(everywhere)}"


def test_V3_the_loops_execution_service_is_NEVER_in_OBSERVE_mode():
    """**"observed" is safe only because of one constructor argument** (manager; `B430`'s shape). In
    OBSERVE the service sends no order and returns `"observed"`, which this loop would classify
    UNRESOLVED and halt on — "find the order at the venue" for an order never sent. So the mode is
    pinned at every assignment, and on a constructed loop."""
    from app.services.execution.service import ExecMode, ExecutionService
    from app.services.live import crypto_loop as mod

    tree = ast.parse(inspect.getsource(mod))
    constructions = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ExecutionService"
    ]
    assert constructions, "no ExecutionService construction found in crypto_loop; the scan is blind"
    for call in constructions:
        mode = ast.unparse(call.args[1]) if len(call.args) > 1 else next(
            (ast.unparse(k.value) for k in call.keywords if k.arg == "mode"), None)
        assert mode == "ExecMode.PAPER", f"crypto_loop builds its ExecutionService in {mode!r} at line {call.lineno}"
    # In CODE, not in text: a substring search over the source is answered by this module's own
    # comment explaining OBSERVE, which is the unscoped-query shape — measured, it failed exactly so.
    observe_refs = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "OBSERVE"
                    and isinstance(n.value, ast.Name) and n.value.id == "ExecMode"]
    assert not observe_refs, f"crypto_loop references ExecMode.OBSERVE in code at lines {observe_refs}"

    loop = mod.LiveCryptoLoop()
    assert isinstance(loop.execution, ExecutionService) and loop.execution.mode == ExecMode.PAPER, (
        f"a constructed loop's execution mode is {getattr(loop.execution, 'mode', None)!r}"
    )
