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
async def test_L2_the_unresolved_halt_CONSTRUCTS_NO_DECISION_ROW_and_its_recorder_RAN(monkeypatch):
    """**No row, by ruling — so the arm watches the boundary every row must cross.** The recorder runs
    with only its session stubbed, and its alert must be observed, or "no row" is satisfied by the
    recorder never executing.

        CATCHES      any DecisionRecord construction EXECUTED on this drive, in any spelling, the
                     seam and its recorder included
        DOES NOT     a path this drive never executes; a row inserted without constructing the model
    """
    import app.models.decision_record as dr_mod

    built: list[str] = []
    real = dr_mod.DecisionRecord

    def _recording(*a, **k):
        built.append(str(k.get("outcome", "?")))
        return real(*a, **k)

    monkeypatch.setattr(dr_mod, "DecisionRecord", _recording)

    loop, acts, seen = await _drive(monkeypatch, {"status": "NEW", "units": 1.0, "position_id": "oid-1"})

    assert any(type(r).__name__ == "Alert" for r in seen["alerts"]), (
        f"the recorder wrote no alert, so it may not have run: {seen['alerts']!r}"
    )
    assert built == [], f"a DecisionRecord was constructed on the unresolved-order path: {built}"
    assert acts, "the tick never ran"


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


def _status_literals(source: str, function_names: set[str]) -> dict[str, set[str]]:
    """Every string constant a function can put under a `status` key or into a `status` variable."""
    found: dict[str, set[str]] = {}
    for fn in ast.walk(ast.parse(source)):
        if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in function_names):
            continue
        for node in ast.walk(fn):
            values = []
            if isinstance(node, ast.Dict):
                values = [v for k, v in zip(node.keys, node.values)
                          if isinstance(k, ast.Constant) and k.value == "status"]
            elif isinstance(node, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == "status" for t in node.targets):
                    values = [node.value]
            for v in values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    found.setdefault(v.value, set()).add(f"{fn.name}:{node.lineno}")
    return found


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

    emitted: dict[str, set[str]] = {}
    for module, names in ((service, {"execute"}), (paper, {"place_order"}),
                          (cft_sim, {"place_order", "_reject"}), (alpaca, {"place_order"})):
        for value, sites in _status_literals(inspect.getsource(module), names).items():
            emitted.setdefault(value, set()).update(f"{module.__name__.rsplit('.', 1)[-1]}.{s}" for s in sites)

    # THE DENOMINATOR IS THE IDENTITY OF WHAT WAS FOUND, not a count: each producer must be seen.
    for must in ("service.execute", "paper.place_order", "cft_sim._reject", "alpaca.place_order"):
        assert any(s.startswith(must) for sites in emitted.values() for s in sites), (
            f"the scan found no status literal in {must}; it may be scanning nothing"
        )
    assert {"rejected", "REJECTED", "FILLED", "observed"} <= set(emitted), sorted(emitted)

    unclassified = {v: sorted(s) for v, s in emitted.items() if v not in known}
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
    """Membership tests against the classifier's own sets, and comparisons with an ORDER-RESULT literal,
    anywhere except inside `classify_order_status`. Raw reads (`"status": res.get("status")`) are
    records, not decisions, and are not flagged; nor are other vocabularies (`TradeStatus.CLOSED`, the
    close path's `"refused"`)."""
    sets = {"FILL_BEARING_STATUSES", "REFUSAL_STATUSES", "NOT_FROM_THIS_LOOP_STATUSES"}
    inside = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == "classify_order_status":
            inside |= {id(n) for n in ast.walk(fn)}
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or id(node) in inside:
            continue
        operands = [node.left, *node.comparators]
        uses_set = any(isinstance(o, ast.Name) and o.id in sets for o in operands)
        literals = {c.value for o in operands for c in ast.walk(o)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        if uses_set or literals & vocabulary:
            found.append(f"line {node.lineno}: {ast.unparse(node)}")
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

    # CONTROLS. A planted decision FIRES, in both shapes; the legitimate neighbours stay QUIET.
    fires = ("def elsewhere(res):\n    if res.get('status') == 'FILLED':\n        pass\n"
             "    if res.get('status') in REFUSAL_STATUSES:\n        pass\n")
    assert len(_status_decisions_outside_classifier(ast.parse(fires), vocabulary)) == 2
    quiet = ("def neighbours(res, t, event):\n    payload = {'status': res.get('status')}\n"
             "    if t.status == TradeStatus.CLOSED:\n        pass\n"
             "    if event.get('status') == 'refused':\n        pass\n")
    assert _status_decisions_outside_classifier(ast.parse(quiet), vocabulary) == []
    # And the classifier itself IS seen, so "nothing outside" is not "nothing anywhere".
    everywhere = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)
                  and any(isinstance(o, ast.Name) and o.id in {"FILL_BEARING_STATUSES", "REFUSAL_STATUSES"}
                          for o in [n.left, *n.comparators])]
    assert len(everywhere) == 2, f"expected the classifier's two membership tests, found {len(everywhere)}"


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
