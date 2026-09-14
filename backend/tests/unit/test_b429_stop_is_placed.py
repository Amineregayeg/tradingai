"""B429 — the stop goes to the venue with the order, or the order does not stand.

`AlpacaAdapter.place_order` received `request.sl` and `request.tp` and **discarded both**: a plain
`MarketOrderRequest`, no bracket, nothing sent. And the only SL/TP enforcement in this codebase is
`PaperBroker.on_tick` and `cft_sim.on_tick`, both simulators — `AlpacaAdapter` has no `on_tick` at
all (`B428`). So a live position had **no stop at the venue and no stop in process**.

**AND THE STOP WAS STILL BEING USED.** `execution/service.py:174` sizes the position FROM `sig.sl`
and `:166` refuses to trade when price is already through it. The risk model was computed from a
stop nothing placed — worse than a dropped input, because the dropped input still justified the
quantity.

**THE CONTRACT WAS ALREADY IN THE FILE**, twenty lines below, on `close_position`: *"HONOUR
`lot_size` rather than ignore it — the contract is honour it or refuse loudly."* Same file, same
question, one honoured. `cryptofundtrader.py:666` and `oanda.py:420` both attach the stop; Alpaca
was the only adapter that dropped it.

#### THREE OUTCOMES, AND THE THIRD IS WHY DETECTION ALONE IS NOT A FIX

```
venue REFUSES the attachment    -> raises, no position, loud            already safe
venue ACCEPTS it                -> the stop exists at the venue         the happy path
venue accepts the ORDER and
IGNORES the attachment          -> cancel entry, close, OBSERVE flat    <- this entry
     observed flat              -> refuse: REJECTED, which is now true
     anything short of that     -> HALT. never a rejection row.
```

Refusing without closing leaves exactly the state this entry describes, now with an error beside
it — a louder version of the defect rather than a remedy. The invariant is therefore not *never
place what you cannot protect* (unachievable: placement and protection are not atomic here) but
**NEVER LEAVE AN UNPROTECTED POSITION OPEN.**

#### WHAT IS NOT CLAIMED

**Whether Alpaca accepts a bracket on CRYPTO is unestablished, and no arm below establishes it.**
The SDK imposes no asset-class restriction, so the answer lives on the server. Everything here is
driven against doubles; **the venue was not consulted.** A green run of this file means the adapter
sends the protection and reacts correctly to what it is told — not that Alpaca said yes.
"""
from __future__ import annotations

import re

import pytest

from app.core.exceptions import BrokerError
from app.db.enums import DirectionType, OrderType
from app.services.broker.alpaca import (
    AlpacaAdapter,
    AlpacaProtectionNotAccepted,
    AlpacaUnprotectedPositionOpen,
)
from app.services.broker.base import OrderRequest


class _O:
    """An order, a leg, or a position — whatever the venue double reports."""

    def __init__(self, *, id=None, symbol="BTC/USD", status=None, order_type=None, type=None,
                 stop_price=None, limit_price=None, legs=None, order_class=None, filled_qty="1"):
        self.id = id
        self.symbol = symbol
        self.status = status
        self.order_type = order_type
        self.type = type
        self.stop_price = stop_price
        self.limit_price = limit_price
        self.legs = legs
        self.order_class = order_class
        self.filled_qty = filled_qty
        self.client_order_id = "sig-x"
        self.filled_avg_price = 100.0
        self.qty = "1"


def _placed(order_class="bracket", legs=None, status="filled"):
    """The POST acknowledgement. **Never the verdict** — only logged."""
    return _O(id="order-1", status=status, order_class=order_class, legs=legs)


def _stop(status="held", **kw):
    return _O(id=kw.pop("id", "leg-stop"), status=status, order_type=kw.pop("order_type", "stop"),
              stop_price=kw.pop("stop_price", 99.0), **kw)


def _tp(status="new", **kw):
    return _O(id=kw.pop("id", "leg-tp"), status=status, order_type="limit", limit_price=103.0, **kw)


def _parent(status="filled", legs=None, **kw):
    return _O(id="order-1", status=status, legs=legs, **kw)


PROTECTED = _parent(legs=[_stop("held"), _tp("new")])
TERMINAL = _parent(status="filled", legs=[_stop("canceled"), _tp("canceled")])


def _req(sl=99.0, tp=103.0):
    return OrderRequest(
        pair="BTC/USD", direction=DirectionType.LONG, order_type=OrderType.MARKET,
        lot_size=1.0, price=None, sl=sl, tp=tp, client_order_id="sig-x",
    )


class _Asset:
    """What `place_order` needs from `get_asset` before it can size anything. **A double that
    returned the ORDER for every call** made `get_asset` answer with an order object, and eight arms
    went red for a reason unrelated to B429 — a double thin enough to crash the code measures the double."""
    symbol = "BTC/USD"
    min_order_size = 0.000001
    min_trade_increment = 0.000000001
    price_increment = 0.01


def _adapter(placed, *, reread=PROTECTED, reread_raises=False, reread_after=TERMINAL,
             reread_after_raises=False, cancel_raises_for=(), close_raises=False,
             positions_after=(), orders_after=(), positions_raise=False, orders_raise=False):
    """An adapter whose venue is a double **with state after remediation**.

    `get_order_by_id` is answered TWICE and differently: first as the protection EVIDENCE
    (`reread`), then as the post-remediation observation of this order (`reread_after`).

    **Earlier versions of this double modelled the defect twice.** First `close_position` returning
    was taken as the position being gone (an accepted close read as a filled one). Then the POST
    acknowledgement's class and legs were the evidence (a refused stop leg read as protection).
    """
    a = AlpacaAdapter.__new__(AlpacaAdapter)
    a.sent = []
    a._paper = True
    a._account_key = f"client:{id(a)}"      # `B442`: what __init__ sets — this double's order lock is its own

    async def _instant_sleep(_seconds):     # `B427`: the resolver never waits for real time in an arm
        return None

    a._sleep = _instant_sleep
    reads = {"n": 0}
    submitted = {"yes": False}

    async def _call(name, *args, **kwargs):
        a.sent.append((name, args, kwargs))
        if name == "get_asset":
            return _Asset()
        if name == "submit_order":
            submitted["yes"] = True
            return placed
        if name == "get_order_by_id":
            reads["n"] += 1
            if reads["n"] == 1:
                if reread_raises or reread is None:
                    raise RuntimeError("re-read timed out")
                return reread
            if reread_after_raises:
                raise RuntimeError("post-remediation re-read timed out")
            return reread_after
        if name == "cancel_order_by_id":
            if args and args[0] in cancel_raises_for:
                raise RuntimeError(f"cannot cancel {args[0]}")
            return None
        if name == "close_position":
            if close_raises:
                raise RuntimeError("venue refused the close")
            return {"close_order": "accepted"}
        if name == "get_all_positions":
            # the OBSERVATION after remediation fails; `T-0144` R5''s read BEFORE the send is flat (a failing one sends
            # nothing, which is T-0144's own arm)
            if positions_raise and submitted["yes"]:
                raise RuntimeError("position query timed out")
            return [_O(symbol=x) for x in positions_after]
        if name == "get_orders":
            if orders_raise:
                raise RuntimeError("order query timed out")
            if isinstance(orders_after, int):
                return [_O(symbol="OTHER/USD", status="new")] * orders_after
            return [x if isinstance(x, _O) else _O(symbol=x, status="new") for x in orders_after]
        raise AssertionError(f"unexpected venue call {name}")

    a._call = _call
    a._require_model = lambda v, _n: v
    return a


def _called(a, name):
    return [args for n, args, _ in a.sent if n == name]


# =====================================================================================
# THE PROTECTION IS SENT AT ALL — the defect itself
# =====================================================================================

@pytest.mark.asyncio
async def test_a_stop_and_a_target_are_sent_as_a_BRACKET():
    """The order that reaches the venue must carry the stop. Before this it carried nothing."""
    a = _adapter(_placed())
    await a.place_order(_req(sl=99.0, tp=103.0))

    submitted = next(args[0] for name, args, _ in a.sent if name == "submit_order")
    assert submitted.stop_loss is not None, (
        "the order reaching Alpaca carries no stop — the position would have none at the venue, "
        "and AlpacaAdapter has no on_tick so it would have none in process either (B428)"
    )
    assert float(submitted.stop_loss.stop_price) == 99.0
    assert float(submitted.take_profit.limit_price) == 103.0
    assert str(getattr(submitted.order_class, "value", submitted.order_class)) == "bracket"


@pytest.mark.asyncio
async def test_a_stop_with_NO_target_is_sent_as_OTO_not_a_broken_bracket():
    """**`sig.tp` is legitimately `None` on the live path** while `sl` is what the size was computed
    from — so this is the case that must work. Alpaca needs both legs for a bracket."""
    a = _adapter(_placed("oto"), reread=_parent(legs=[_stop("held")]))
    await a.place_order(_req(sl=99.0, tp=None))

    submitted = next(args[0] for name, args, _ in a.sent if name == "submit_order")
    assert float(submitted.stop_loss.stop_price) == 99.0
    assert submitted.take_profit is None
    assert str(getattr(submitted.order_class, "value", submitted.order_class)) == "oto"


@pytest.mark.asyncio
async def test_an_order_with_NO_stop_is_unchanged():
    """**The control.** No stop requested -> an ordinary order, no PROTECTION re-read, nothing closed.

    `B427`: the order IS re-read now — once, by the resolver, which stops on a terminal parent. That read
    is resolution, not protection: no leg is inspected and nothing is cancelled or closed."""
    a = _adapter(_placed("simple"))
    res = await a.place_order(_req(sl=None, tp=None))

    submitted = next(args[0] for name, args, _ in a.sent if name == "submit_order")
    assert submitted.stop_loss is None and submitted.take_profit is None
    assert submitted.order_class is None
    assert res["status"] == "FILLED", "a plain order stopped working"
    assert len(_called(a, "get_order_by_id")) == 1, "the resolver did not read, or read past a terminal order"
    assert not _called(a, "cancel_order_by_id") and not _called(a, "close_position")


# =====================================================================================
# THE EVIDENCE — a WORKING stop leg on a nested RE-READ, and nothing weaker
# =====================================================================================

@pytest.mark.asyncio
async def test_P3_POST_omits_legs_and_the_RE_READ_shows_a_HELD_stop_so_it_is_PROTECTED():
    """**P-3, and the reachability of the protected path.** `Order.legs` is Optional and `nested` is
    GET-only, so a POST without legs is ordinary; the re-read supplies them. `held` is where
    bracket legs wait for the parent — omit it and every bracket is needlessly closed."""
    a = _adapter(_placed(legs=None), reread=_parent(legs=[_stop("held")]))
    res = await a.place_order(_req())
    assert res["status"] == "FILLED"
    assert not _called(a, "close_position"), "a correctly protected position was closed"
    (args,) = _called(a, "get_order_by_id")
    assert args[0] == "order-1" and args[1].nested is True, "the re-read is not by id with nested=True"


@pytest.mark.asyncio
async def test_P1_the_class_MATCHES_and_the_stop_leg_was_REJECTED_so_it_REMEDIATES():
    """**P-1, review's blocking FAIL.** A parent reporting `bracket` exited as protected without a
    leg ever being read. Order class alone is not evidence."""
    a = _adapter(_placed("bracket", legs=[_stop("new")]),
                 reread=_parent(legs=[_stop("rejected"), _tp("new")]))
    with pytest.raises(AlpacaProtectionNotAccepted):
        await a.place_order(_req())
    assert _called(a, "close_position"), "a bracket whose stop was REJECTED was read as protected"


@pytest.mark.asyncio
async def test_P2_a_CANCELED_stop_leg_with_a_stop_price_is_not_protection():
    """**P-2.** A canceled stop leg still has a stop type and a `stop_price`; only its STATUS says it
    protects nothing."""
    a = _adapter(_placed("simple"),
                 reread=_parent(legs=[_stop("canceled", stop_price=99.0)]))
    with pytest.raises(AlpacaProtectionNotAccepted):
        await a.place_order(_req())
    assert _called(a, "close_position")


@pytest.mark.asyncio
async def test_NO_SHORT_CIRCUIT_a_stop_leg_NEW_on_the_POST_is_not_evidence():
    """The POST is the acknowledgement. A leg reading `new` there and `rejected` on the re-read must
    remediate — reading protection off the POST is the false-PROTECTED direction."""
    a = _adapter(_placed("bracket", legs=[_stop("new")]), reread=_parent(legs=[_stop("rejected")]))
    with pytest.raises(AlpacaProtectionNotAccepted):
        await a.place_order(_req())
    assert _called(a, "close_position")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["accepted", "pending_new", "accepted_for_bidding",
                                    "partially_filled", "pending_replace", "calculated", ""])
async def test_the_ALLOW_LIST_is_new_and_held_ONLY_everything_else_remediates(status):
    """**Affirmatively working only.** Wrongly including a non-working status reads a refused stop
    as protected, which is B429; wrongly excluding one costs a needless close. Unknown and
    unreadable statuses remediate."""
    a = _adapter(_placed(), reread=_parent(legs=[_stop(status)]))
    with pytest.raises(AlpacaProtectionNotAccepted):
        await a.place_order(_req())
    assert _called(a, "close_position"), f"a stop leg in {status!r} was read as protection"


def test_the_allow_list_is_EXACTLY_new_and_held():
    """Membership is a ruling with an asymmetric cost, not a derivation — so it is pinned, and a
    widening has to be made deliberately (probe 3 is the evidence to widen it)."""
    from app.services.broker.alpaca import WORKING_STOP_LEG_STATUSES
    assert WORKING_STOP_LEG_STATUSES == {"new", "held"}


@pytest.mark.asyncio
async def test_a_FAILED_RE_READ_is_not_evidence_of_protection():
    a = _adapter(_placed("bracket", legs=[_stop("held")]), reread_raises=True)
    with pytest.raises(AlpacaProtectionNotAccepted) as caught:
        await a.place_order(_req())
    assert _called(a, "close_position")
    assert "re-read FAILED" in str(caught.value)
    # **SCOPED TO THE TOKEN** (review, A-2). The line above is also satisfied by the remediation step's
    # own "re-read FAILED (...)" — the text occurs TWICE — so a failed re-read stored as `legs=[none]`
    # killed nothing. `legs=[none]` is a probe-3 FINDING (the venue created no legs); recording a
    # transport failure as that finding, in the token read first, is the defect this line catches.
    assert "legs=[re-read FAILED]" in str(caught.value), str(caught.value)


@pytest.mark.asyncio
async def test_S1_a_take_profit_leg_alone_is_not_protection():
    """**S-1.** A working leg that is not a STOP protects nothing on the downside."""
    a = _adapter(_placed("simple"), reread=_parent(legs=[_tp("new")]))
    with pytest.raises(AlpacaProtectionNotAccepted):
        await a.place_order(_req())
    assert _called(a, "close_position")


@pytest.mark.asyncio
async def test_the_leg_STATUS_enum_is_read_by_VALUE():
    """`str(OrderStatus.HELD)` is `'OrderStatus.HELD'` (`B411`'s trap)."""
    from alpaca.trading.enums import OrderStatus

    a = _adapter(_placed(), reread=_parent(legs=[_stop(OrderStatus.HELD)]))
    res = await a.place_order(_req())
    assert res["status"] == "FILLED" and not _called(a, "close_position")


@pytest.mark.asyncio
@pytest.mark.parametrize("leg_name", ["stop_on_order_type", "stop_limit_on_order_type", "stop_on_type"])
async def test_C2b_C3_C4_a_stop_leg_is_recognised_BY_ITS_TYPE_alone(leg_name):
    """**C-2b, C-3, C-4.** The two evidence paths are OR'd, so a leg carrying both a stop type and a
    `stop_price` masks a broken type path. These legs carry an ENUM type and NO `stop_price`, so the
    type comparison alone decides — `str()` instead of `.value`, `"stop"`-only, or the wrong field
    each close a correctly protected position."""
    from alpaca.trading.enums import OrderType as T

    leg = {
        # IDS WITHOUT SPACES: the kill-set harness names arms by `\S+`, and "STOP on type" printed
        # as `[STOP`, so C-4a and C-4b could not be told apart by the arm that killed them.
        "stop_on_order_type":       _O(id="l", status="held", order_type=T.STOP),
        "stop_limit_on_order_type": _O(id="l", status="held", order_type=T.STOP_LIMIT),
        "stop_on_type":             _O(id="l", status="held", type=T.STOP),
    }[leg_name]
    a = _adapter(_placed(), reread=_parent(legs=[leg]))
    res = await a.place_order(_req())
    assert res["status"] == "FILLED", f"{leg_name}: a real stop leg was not recognised"
    assert not _called(a, "close_position"), f"{leg_name}: a protected position was closed"


@pytest.mark.asyncio
async def test_the_STOP_PRICE_path_alone_recognises_a_stop_leg():
    """The other evidence path, isolated: an unreadable type and only a `stop_price`."""
    a = _adapter(_placed(), reread=_parent(legs=[_O(id="l", status="held", stop_price=99.0)]))
    res = await a.place_order(_req())
    assert res["status"] == "FILLED" and not _called(a, "close_position")


# =====================================================================================
# REMEDIATION — cancel every live part, close, and the verdict comes only from observation
# =====================================================================================

@pytest.mark.asyncio
async def test_R6b_OBSERVED_FLAT_is_the_only_route_to_a_clean_REFUSAL():
    """**Reachability.** Everything cancelled, closed, and flat observed on all three observations."""
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]))
    with pytest.raises(AlpacaProtectionNotAccepted) as caught:
        await a.place_order(_req())
    assert _called(a, "get_all_positions") and _called(a, "get_orders")
    assert len(_called(a, "get_order_by_id")) == 2, "this order was not re-read after remediation"
    assert "flat OBSERVED" in str(caught.value)


@pytest.mark.asyncio
async def test_R2_the_ENTRY_is_cancelled_by_id():
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]))
    with pytest.raises(AlpacaProtectionNotAccepted):
        await a.place_order(_req())
    assert ("order-1",) in _called(a, "cancel_order_by_id")


@pytest.mark.asyncio
async def test_CL1_a_RESTING_TAKE_PROFIT_leg_is_cancelled_not_just_the_parent():
    """**The tree remediation now runs on:** parent filled, stop REFUSED, take-profit STILL RESTING.
    Cancelling a filled parent raises and leaves the TP live."""
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected"), _tp("new")]),
                 cancel_raises_for=("order-1",))
    with pytest.raises(AlpacaProtectionNotAccepted):
        await a.place_order(_req())
    assert "leg-tp" in [x[0] for x in _called(a, "cancel_order_by_id")], (
        "the resting take-profit leg was never cancelled"
    )


@pytest.mark.asyncio
async def test_CL2_a_TERMINAL_leg_is_not_cancelled():
    """Status is read, not ignored: a rejected leg cannot fill and is not a cancel target. (Its own
    arm, so CL-1 and CL-2 are each killed by the arm named for them.)"""
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected"), _tp("new")]))
    with pytest.raises(AlpacaProtectionNotAccepted):
        await a.place_order(_req())
    assert "leg-stop" not in [x[0] for x in _called(a, "cancel_order_by_id")], (
        "a terminal (rejected) leg was cancelled — leg status was ignored"
    )


@pytest.mark.asyncio
async def test_R9_a_parent_CANCEL_that_throws_is_not_the_verdict():
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]), cancel_raises_for=("order-1",))
    with pytest.raises(AlpacaProtectionNotAccepted) as caught:
        await a.place_order(_req())
    assert "cancel order-1 FAILED" in str(caught.value) and "flat OBSERVED" in str(caught.value)


@pytest.mark.asyncio
async def test_BRANCH_2_close_THROWS_because_nothing_filled_and_flat_is_observed():
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]), close_raises=True)
    with pytest.raises(AlpacaProtectionNotAccepted) as caught:
        await a.place_order(_req())
    assert "close FAILED" in str(caught.value) and "flat OBSERVED" in str(caught.value)


REAL_ORDER_ID = "7f3c2a91-4b8e-4d1a-9c55-0e6b2f8d1a37"   # UUID length, as Alpaca issues them


async def _stored_refusal(settled_status, settled_qty, *, before_status="new", **kw):
    """The refusal as the service STORES it, at a REAL order-id length.

    `before_status` is the parent on the PROTECTION re-read (before remediation); `settled_status` and
    `settled_qty` are the parent on the POST-remediation read, which is what the `entry=` token must
    be built from.
    """
    from app.core.logging import redact_for_storage

    oid = REAL_ORDER_ID
    before = _O(id=oid, status=before_status, legs=[_stop("rejected"), _tp("new")])
    settled = _O(id=oid, status=settled_status, filled_qty=settled_qty,
                 legs=[_stop("rejected"), _tp("canceled")])
    a = _adapter(_O(id=oid, status=before_status, order_class="bracket"),
                 reread=before, reread_after=settled, **kw)
    with pytest.raises(AlpacaProtectionNotAccepted) as caught:
        await a.place_order(_req())
    return str(caught.value), redact_for_storage(str(caught.value))


@pytest.mark.asyncio
async def test_MSG1_the_STORED_row_distinguishes_a_FILLED_entry_from_an_UNFILLED_one_at_real_id_length():
    """**The event B429 exists to prevent must be distinguishable in the durable row** — and
    `rejection_reason` is the row's ONLY durable link to the venue order: none of `DecisionRecord`'s
    29 columns holds an order id.

    a4b9a34 certified this budget with the fixture id "order-1". At a real 36-character id,
    "entry filled, a real unprotected position existed, remediation closed it" and "entry never
    filled" stored BYTE-IDENTICAL rows. So every fact now has a compact token ahead of the prose.
    """
    filled_full, filled = await _stored_refusal("filled", "1", cancel_raises_for=(REAL_ORDER_ID,))
    unfilled_full, unfilled = await _stored_refusal("canceled", "0", close_raises=True)

    assert len(filled_full) > 300 and len(unfilled_full) > 300, "premise: the bound must actually cut"
    assert filled != unfilled, (
        "a filled entry whose unprotected position was closed stores the SAME row as an entry that "
        "never filled"
    )
    assert "entry=filled/1" in filled and "entry=canceled/0" in unfilled
    # The parent's cancel fails (it filled) and the resting take-profit leg's cancel succeeds.
    assert "cancel=1ok/1failed" in filled and "close=submitted" in filled
    assert "close=failed" in unfilled
    # **A COUNT WITH A DIRECTION** (review, A-3). `1ok/1failed` is a FIXED POINT of swapping the counts,
    # so the line above cannot see a swap; the unfilled row's parent and take-profit cancels both succeed.
    assert "cancel=2ok/0failed" in unfilled, f"cancel counts for the unfilled row: {unfilled!r}"
    for stored in (filled, unfilled):
        assert f"order={REAL_ORDER_ID}" in stored, f"the full venue order id was cut: {stored!r}"
        assert "rejected/stop" in stored and "new/limit" in stored, f"leg statuses cut: {stored!r}"
        assert "too narrow" in stored, f"the allow-list pointer was cut: {stored!r}"


@pytest.mark.asyncio
async def test_ENTRY1_the_token_comes_from_the_POST_remediation_read_not_the_protection_re_read():
    """**A market entry can read `new` on the protection re-read and fill before the cancel lands.**
    A token taken from that earlier read says "unfilled" about a position that existed — the timing
    false case, in the direction that understates the event."""
    _full, stored = await _stored_refusal("filled", "1", before_status="new",
                                          cancel_raises_for=(REAL_ORDER_ID,))
    assert "entry=filled/1" in stored, f"the token reflects the pre-remediation read: {stored!r}"


@pytest.mark.asyncio
async def test_ENTRY2_a_PARTIAL_fill_with_the_remainder_cancelled_carries_its_NONZERO_quantity():
    """`canceled` alone reads "never filled". A partial fill whose remainder was cancelled ends
    `canceled` with a non-zero filled quantity — a real position existed."""
    _full, stored = await _stored_refusal("canceled", "0.0005")
    assert "entry=canceled/0.0005" in stored, f"the partial fill's quantity was dropped: {stored!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,token", [
    (None, "?"), ("", "?"), ("nan", "?"), (float("nan"), "?"), ("inf", "?"), ("garbage", "?"),
    ("0", "0"), ("0.000", "0.000"), (0.0, "0.0"),
    ("0.00001294", "0.00001294"), (0.00001294, "0.00001294"),
    # **BELOW 1e-6, where the two spellings DIVERGE** (manager). str(Decimal) switches to scientific
    # notation once the adjusted exponent drops below -6, so at 0.00001294 `str(d)` and `format(d, "f")`
    # agree and a later edit to `str(d)` survives. The venue's measured min_trade_increment is 1e-9,
    # so sub-micro partial quantities are reachable.
    (1.2e-07, "0.00000012"), (1e-09, "0.000000001"),
])
async def test_ENTRY3_the_filled_quantity_has_THREE_states_and_none_collapses(raw, token):
    """**Absent, unparseable and non-finite are `?`; a number is recorded AS THE VENUE SENT IT.**

    Rendering `None` as `0` stores "never filled" for a quantity nobody read (review). NaN compares
    neither equal to zero nor greater than it, so any zero test files it on one side (manager). And
    `str(float("0.00001294"))` is `1.294e-05` — a crypto fill quantity that no longer matches the venue."""
    _full, stored = await _stored_refusal("canceled", raw)
    assert f"entry=canceled/{token} " in stored, f"filled_qty {raw!r}: {stored!r}"
    qty = stored.split("entry=", 1)[1].split(" ", 1)[0].split("/", 1)[1]
    # EITHER CASE: float formatting gives `1.2e-07`, Decimal's str gives `1.2E-7`. The first version of
    # this guard looked for lowercase "e-0" and could not see the uppercase form at all.
    assert not re.search(r"[eE][+-]?\d", qty), f"the quantity {qty!r} was written in scientific notation"


@pytest.mark.asyncio
async def test_ENTRY3b_an_UNREADABLE_quantity_never_stores_the_same_row_as_a_confirmed_ZERO():
    _z, zero_row = await _stored_refusal("canceled", "0.000")
    _u, unknown_row = await _stored_refusal("canceled", None)
    assert zero_row != unknown_row, "a confirmed zero and an unreadable quantity store the same row"
    # **NOT ONE ZERO SPELLING — EVERY NUMBER** (review, A-1). The line above compares against "0.000"
    # alone, so an unreadable quantity rendered "0" or "0.0" still differs from it and passes: A != B on
    # an incidental difference of spelling. The unknown token must not parse as a number at all.
    token = unknown_row.split("entry=canceled/", 1)[1].split(" ", 1)[0]
    try:
        float(token)
    except ValueError:
        pass
    else:
        raise AssertionError(f"an unreadable quantity stored a NUMBER: {token!r}")


@pytest.mark.asyncio
async def test_R3_an_ACCEPTED_CLOSE_is_not_a_FILLED_close():
    """**R-1 / R-3, `B427` inside `B429`.** The close was accepted and the position is still there."""
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]), positions_after=["BTC/USD"])
    with pytest.raises(AlpacaUnprotectedPositionOpen) as caught:
        await a.place_order(_req())
    assert "close SUBMITTED" in caught.value.detail
    assert "position(s) still open" in caught.value.detail


@pytest.mark.asyncio
async def test_R4_a_RESTING_ORDER_is_not_flat_even_with_no_position():
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]), orders_after=["BTC/USD"])
    with pytest.raises(AlpacaUnprotectedPositionOpen) as caught:
        await a.place_order(_req())
    assert "open order(s) still resting" in caught.value.detail


@pytest.mark.asyncio
async def test_a_live_CHILD_LEG_in_the_order_list_is_not_flat():
    """The list is fetched nested, so an order whose own symbol does not identify it can still
    carry a live leg for this symbol — that must be seen."""
    parent = _O(id="p-x", symbol=None, status="new", legs=[_tp("new", id="tp-x")])
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]), orders_after=[parent])
    with pytest.raises(AlpacaUnprotectedPositionOpen) as caught:
        await a.place_order(_req())
    assert "child leg(s) still live" in caught.value.detail


@pytest.mark.asyncio
async def test_THIS_ORDER_re_read_after_remediation_with_a_LIVE_LEG_is_not_flat():
    """**A filled parent may be excluded by `status=OPEN`,** taking its rolled-up resting TP leg out
    of the list with it. The orders this remediation created are therefore re-read by id, and every
    part must be terminal."""
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected"), _tp("new")]),
                 reread_after=_parent(status="filled", legs=[_stop("rejected"), _tp("new")]))
    with pytest.raises(AlpacaUnprotectedPositionOpen) as caught:
        await a.place_order(_req())
    assert "non-terminal part" in caught.value.detail


@pytest.mark.asyncio
async def test_DONE_FOR_DAY_is_not_terminal_so_it_is_not_flat():
    """**`done_for_day` names its own impermanence** — it can fill on a later day. This set decides
    FLAT, so counting a resumable status as terminal is a false flat: B429."""
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected"), _tp("new")]),
                 reread_after=_parent(status="filled", legs=[_stop("rejected"), _tp("done_for_day")]))
    with pytest.raises(AlpacaUnprotectedPositionOpen) as caught:
        await a.place_order(_req())
    assert "non-terminal part" in caught.value.detail


def test_the_TERMINAL_set_is_pinned():
    """A widening of the set that decides FLAT must be deliberate."""
    from app.services.broker.alpaca import TERMINAL_ORDER_STATUSES
    assert TERMINAL_ORDER_STATUSES == {"filled", "canceled", "expired", "rejected", "replaced"}


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["positions", "orders", "reread_after"])
async def test_R5_a_FAILED_OBSERVATION_is_not_evidence_of_flat(which):
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]),
                 positions_raise=(which == "positions"), orders_raise=(which == "orders"),
                 reread_after_raises=(which == "reread_after"))
    with pytest.raises(AlpacaUnprotectedPositionOpen) as caught:
        await a.place_order(_req())
    assert "failed" in caught.value.detail


@pytest.mark.asyncio
async def test_R10_a_FULL_order_page_is_not_evidence_of_flat_and_one_short_is():
    from app.services.broker.alpaca import FLAT_CHECK_ORDER_LIMIT

    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]), orders_after=FLAT_CHECK_ORDER_LIMIT)
    with pytest.raises(AlpacaUnprotectedPositionOpen) as caught:
        await a.place_order(_req())
    assert "full" in caught.value.detail

    b = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]),
                 orders_after=FLAT_CHECK_ORDER_LIMIT - 1)
    with pytest.raises(AlpacaProtectionNotAccepted):
        await b.place_order(_req())


def test_R10b_the_order_limit_is_BOUNDED_under_the_cap_argument():
    """**A property arm, because a test double never caps.** A BOUND, never an equality."""
    from app.services.broker.alpaca import FLAT_CHECK_ORDER_LIMIT, FLAT_CHECK_ORDER_LIMIT_CEILING

    assert 0 < FLAT_CHECK_ORDER_LIMIT <= FLAT_CHECK_ORDER_LIMIT_CEILING, (
        f"FLAT_CHECK_ORDER_LIMIT is {FLAT_CHECK_ORDER_LIMIT}. Fullness is tested against the REQUESTED "
        f"limit, so the guard only works while the request sits under the server's cap — which is "
        f"unmeasured. Keep it modest, at or below {FLAT_CHECK_ORDER_LIMIT_CEILING}."
    )


async def _order_query():
    """The `GetOrdersRequest` the flat check actually sent. The double ignores it, so each field is
    asserted directly — one arm per field, so each kill-set row dies on the arm named for it."""
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]))
    with pytest.raises(AlpacaProtectionNotAccepted):
        await a.place_order(_req())
    (req,) = _called(a, "get_orders")[0]
    return req


@pytest.mark.asyncio
async def test_R10d_the_order_query_states_status_OPEN():
    from alpaca.trading.enums import QueryOrderStatus
    assert (await _order_query()).status == QueryOrderStatus.OPEN, "status left to the server's default"


@pytest.mark.asyncio
async def test_R10c_the_order_query_is_NEWEST_FIRST():
    from alpaca.common.enums import Sort
    assert (await _order_query()).direction == Sort.DESC, (
        "not newest-first, so the orders just created can be the ones truncation drops"
    )


@pytest.mark.asyncio
async def test_R10_the_order_query_sends_the_limit_fullness_is_tested_against():
    from app.services.broker.alpaca import FLAT_CHECK_ORDER_LIMIT
    assert (await _order_query()).limit == FLAT_CHECK_ORDER_LIMIT


@pytest.mark.asyncio
async def test_NL1_the_order_query_is_NESTED_so_legs_are_visible():
    assert (await _order_query()).nested is True, "legs are invisible to the flat check without nested=True"


@pytest.mark.asyncio
async def test_R7b_the_order_query_filters_NOTHING_by_symbol_server_side():
    req = await _order_query()
    assert not req.symbols, (
        f"server-side symbol filter {req.symbols!r} — it matches on a spelling nobody has measured (R-7)"
    )


@pytest.mark.asyncio
async def test_R7_a_position_reported_WITHOUT_the_slash_still_counts_as_held():
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]), positions_after=["BTCUSD"])
    with pytest.raises(AlpacaUnprotectedPositionOpen):
        await a.place_order(_req())


@pytest.mark.asyncio
async def test_R8_symbols_are_compared_EXACTLY_not_by_substring():
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]),
                 orders_after=["BTC/USDT", "BTC/USDC", "ETH/BTC"], positions_after=["BTC/USDT"])
    with pytest.raises(AlpacaProtectionNotAccepted) as caught:
        await a.place_order(_req())
    assert "flat OBSERVED" in str(caught.value)


@pytest.mark.asyncio
async def test_a_FAILED_CLOSE_with_a_position_still_held_raises_the_UNPROTECTED_type():
    """The two outcomes must not share a type: `crypto_loop` HALTS only on the second."""
    a = _adapter(_placed(), reread=_parent(legs=[_stop("rejected")]), close_raises=True,
                 positions_after=["BTC/USD"])
    with pytest.raises(AlpacaUnprotectedPositionOpen) as caught:
        await a.place_order(_req())
    exc = caught.value
    assert exc.symbol == "BTC/USD" and exc.order_id == "order-1"
    assert "close FAILED" in exc.detail and "venue refused the close" in exc.detail
    assert not isinstance(exc, AlpacaProtectionNotAccepted)


def test_both_exceptions_are_BrokerError_so_nothing_escapes_the_order_path():
    """`place_order` once raised `DirectionNotSupported` without importing it — a NameError that
    `except BrokerError` could not catch. Both new types must sit under the umbrella every caller
    already handles, or a raise here aborts the bar instead of being recorded."""
    assert issubclass(AlpacaProtectionNotAccepted, BrokerError)
    assert issubclass(AlpacaUnprotectedPositionOpen, BrokerError)


# =====================================================================================
# THE LOOP'S SIDE — and the precondition the "no row" argument rests on
# =====================================================================================

def _drive_tick(monkeypatch, execute):
    """Drive `_tick_symbol` to the order path with every venue and I/O dependency replaced.

    **INCLUDING THE PRICE FETCH, which the first version of these arms did not replace.**
    `_tick_symbol` begins `price = await asyncio.to_thread(_ticker_price, bsym)` — a real call to
    the Binance API over two mirrors with 8-second timeouts. When it returns `None` the tick exits
    before the order path, nothing halts, and the arm fails. In one kill-set run an arm driven this
    way failed under a mutation it has no connection to, and did not reproduce in sixteen runs
    after; a network failure is the MECHANISM that explains it, not an observed OCCURRENCE (the
    harness keeps no traceback). Either way a network-dependent arm hands a mutation table false
    kills and false passes, so the fetch is replaced here.
    """
    from app.db.enums import DirectionType
    from app.services.live import crypto_loop as mod

    import pandas as pd

    loop = mod.LiveCryptoLoop()
    acts: list[tuple[str, str]] = []

    class _S:
        symbol, direction = "BTC/USD", DirectionType.LONG
        entry, sl, tp = 100.0, 99.0, None
        risk_pct, approved, client_order_id = 0.01, True, "sig-x"
        partial_price = partial_fraction = None

    class _T:
        reasons = ["b429"]

        def __getattr__(self, _):
            return None

    base = [100.0 + i for i in range(60)]
    bars = pd.DataFrame({"open": base, "high": [b + 1 for b in base],
                         "low": [b - 1 for b in base], "close": base, "volume": [10.0] * 60})

    async def _noop(*a, **k):
        return None

    async def _fetch(*a, **k):
        return bars

    async def _false(*a, **k):
        return False

    async def _zero(*a, **k):
        return 0

    async def _act(kind, msg):
        acts.append((kind, msg))

    monkeypatch.setattr(mod, "_ticker_price", lambda _bsym: 100.0)
    monkeypatch.setattr(mod, "evaluate_latest_bar_traced", lambda *a, **k: (_S(), _T()))
    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_act", _act)
    monkeypatch.setattr(loop, "_shadow_evaluate", _noop)
    monkeypatch.setattr(loop, "_maybe_emit_census", _noop)
    monkeypatch.setattr(loop, "_news_context", _noop)
    monkeypatch.setattr(loop, "_has_position", _false)
    monkeypatch.setattr(loop, "_open_count", _zero)
    monkeypatch.setattr(loop.execution, "execute", execute)
    return loop, acts


async def _raise_unprotected(sig):
    raise AlpacaUnprotectedPositionOpen(
        symbol="BTC/USD", order_id="order-9", detail="flat NOT OBSERVED: position(s) still open")


@pytest.mark.asyncio
async def test_the_unprotected_halt_leaves_NO_DECISION_ROW_AT_ALL(monkeypatch):
    """**"No NEW row" and "no row" are different states, and the argument needs the second.**

    Declining to write a `DecisionRecord` is justified by `B399` — a row is worse than none when every
    available value is affirmatively wrong. That assumes no row exists yet. Traced, then driven:
    `_record_signal_decision` has one call site, inside the fill branch, after `execute()` returns, and
    the unprotected handler fires in the `except` around that call.

    # TWO NETS, AND THE SECOND IS THE LOAD-BEARING ONE.
    The first version patched the four known writers by name and asserted the list was empty — and
    described that as protecting against a writer added tomorrow. It is the opposite: a fifth writer
    is not patched, writes its row, and the test passes. Naming them buys diagnostics only. So the
    assertion that carries the weight is at the boundary every row must cross, the `DecisionRecord`
    constructor, and the construction sites are pinned below.

    **WHAT THIS ARM CATCHES, PRECISELY** — because its earlier message said "it sees any writer, named
    or not", which was false for exactly the case that mattered (it no-opped the recorder, so a writer
    inside the recorder was invisible to it):

        CATCHES      any DecisionRecord construction that EXECUTES during this drive — real name,
                     alias, or module-attribute access — including inside _record_unprotected_position,
                     which now runs with only its database session stubbed
        DOES NOT     a writer on a path this drive never executes
                     a row inserted WITHOUT constructing the model (core `insert(...)`, raw SQL,
                     bulk mappings) — the constructor is never called
    """
    loop, acts = _drive_tick(monkeypatch, _raise_unprotected)

    # ------------------------------------------------------------------
    # **PATCHED ON THE MODEL MODULE, NOT ON `crypto_loop`.** Every writer does
    # `from app.models.decision_record import DecisionRecord` INSIDE the function, and a local
    # `from X import Y` resolves on module `X` at call time — so that is where the patch belongs.
    #
    # What a patch on `crypto_loop` would do, stated as MEASURED rather than as first claimed:
    # TODAY `crypto_loop` has no `DecisionRecord` attribute and `monkeypatch.setattr` defaults to
    # `raising=True`, so it would ERROR AT SETUP — loud. It would pass VACUOUSLY only from the day
    # someone adds a module-level import, because it would then patch an attribute no writer reads.
    # The first version of this comment said "passes vacuously" outright, which fails
    # re-derivation (corrected by the manager, who measured both halves).
    # ------------------------------------------------------------------
    import app.models.decision_record as dr_mod

    built: list[str] = []
    real_ctor = dr_mod.DecisionRecord

    def _recording_ctor(*a, **k):
        built.append(str(k.get("outcome", "?")))
        return real_ctor(*a, **k)

    monkeypatch.setattr(dr_mod, "DecisionRecord", _recording_ctor)

    wrote: list[str] = []
    for name in ("_record_signal_decision", "_record_rejected_signal", "_record_abstention",
                 "_record_unsized_fill"):
        async def _w(*a, _n=name, **k):
            wrote.append(_n)
        monkeypatch.setattr(loop, name, _w)

    # ------------------------------------------------------------------
    # **THE RECORDER RUNS. Only its database session is stubbed.** (Review's REVIEW_FAIL on 7f0ee09.)
    #
    # The first version no-opped `_record_unprotected_position`, so a DecisionRecord written INSIDE
    # the recorder never reached the constructor patch above — the net had a hole exactly where a
    # future "record this halt properly" edit would land. The site pin below catches only the literal
    # name `DecisionRecord`, so measured on the committed tree: a writer in the recorder by its real
    # name died only on the pin, and by ALIAS or ATTRIBUTE access it died on NOTHING. Letting the
    # recorder run puts every construction, however it is spelled, through the patched class.
    # ------------------------------------------------------------------
    import app.db.session as sess

    alerts: list = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, row):
            alerts.append(row)

        async def commit(self):
            return None

    monkeypatch.setattr(sess, "async_session_maker", lambda: _Session())

    with pytest.raises(AlpacaUnprotectedPositionOpen):
        await loop._tick_symbol("BTC/USD", "BTCUSDT")

    # THE RECORDER DID RUN — otherwise "no row" is satisfied by it never executing.
    assert any(type(r).__name__ == "Alert" for r in alerts), (
        f"the recorder did not write its alert, so it may not have run at all: {alerts!r}"
    )
    assert built == [], (
        f"a DecisionRecord was CONSTRUCTED on the unprotected-position path: {built}. This is the "
        f"assertion that carries the weight: it sees any construction EXECUTED on this drive, in any "
        f"spelling, the recorder included — not a path the drive skips, and not a core/raw insert."
    )
    assert wrote == [], f"a known writer fired on the unprotected-position path: {wrote} (diagnostic)"
    assert acts, "the tick never reached the order path, so 'no row' would be true for the wrong reason"


@pytest.mark.asyncio
async def test_L1_the_unprotected_state_HALTS_and_the_operator_is_told(monkeypatch):
    loop, acts = _drive_tick(monkeypatch, _raise_unprotected)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(loop, "_record_unprotected_position", _noop)
    monkeypatch.setattr(loop, "_record_rejected_signal", _noop)

    with pytest.raises(AlpacaUnprotectedPositionOpen):
        await loop._tick_symbol("BTC/USD", "BTCUSDT")

    from app.services.live import crypto_loop as mod
    assert loop.halt_reason == mod.HALT_UNPROTECTED_POSITION, f"the halt did not fire: {acts}"
    assert any("HALTED" in m for _, m in acts), f"the operator was not told: {acts}"


@pytest.mark.asyncio
async def test_L2_the_unprotected_state_is_NOT_recorded_as_a_REJECTION(monkeypatch):
    """**DRIVEN — its predecessor asserted an empty list it never gave a chance to fill.** A rejection
    row asserts the engine did not trade; here a position may be live with no stop."""
    loop, _acts = _drive_tick(monkeypatch, _raise_unprotected)
    rejected: list = []

    async def _rejected(*a, **k):
        rejected.append((a, k))

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(loop, "_record_rejected_signal", _rejected)
    monkeypatch.setattr(loop, "_record_unprotected_position", _noop)

    with pytest.raises(AlpacaUnprotectedPositionOpen):
        await loop._tick_symbol("BTC/USD", "BTCUSDT")
    assert rejected == [], f"the unprotected state was filed as a rejection: {rejected!r}"


@pytest.mark.asyncio
async def test_L4_the_recorder_CLEARS_the_alarm_on_success_and_NAMES_a_failure(monkeypatch):
    """**The kill set's only survivor.** `_declare_halt` arms `halt_record_failed`; the writer's LAST
    statement must clear it unconditionally on success, or a successfully recorded halt reports its
    record missing forever — the alarm that cries wolf and then gets ignored."""
    import app.db.session as sess
    from app.services.live import crypto_loop as mod

    added: list = []
    fail = {"on": False}

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, row):
            added.append(row)

        async def commit(self):
            if fail["on"]:
                raise RuntimeError("database unavailable")

    monkeypatch.setattr(sess, "async_session_maker", lambda: _Session())

    class _Sig:
        sl, tp = 99.0, None

    exc = AlpacaUnprotectedPositionOpen(symbol="BTC/USD", order_id="o-1", detail="d")

    loop = mod.LiveCryptoLoop()
    loop._declare_halt(mod.HALT_UNPROTECTED_POSITION)
    assert loop.halt_record_failed, "premise: the halt did not arm the alarm"
    await loop._record_unprotected_position("BTC/USD", _Sig(), exc)
    assert added, "no alert was written"
    assert loop.halt_record_failed is None, (
        f"the alert was written and the alarm still reads {loop.halt_record_failed!r}"
    )

    fail["on"] = True
    loop._declare_halt(mod.HALT_UNPROTECTED_POSITION)
    await loop._record_unprotected_position("BTC/USD", _Sig(), exc)
    assert loop.halt_record_failed and "alert" in loop.halt_record_failed, (
        f"a failed alert write is not named on the alarm: {loop.halt_record_failed!r}"
    )


def test_the_SET_of_DecisionRecord_CONSTRUCTION_SITES_is_pinned():
    """**`M-2`'s shape — DEFENCE IN DEPTH, and narrower than it looks.**

    **WHAT THIS ARM CATCHES, PRECISELY:** a call spelled with the bare name `DecisionRecord(...)` in
    `crypto_loop.py`. It does NOT catch an alias (`from ... import DecisionRecord as DR; DR(...)`),
    module-attribute access (`dr_mod.DecisionRecord(...)`), `getattr`, or a core/raw insert. Measured
    on 7f0ee09 with a writer planted inside `_record_unprotected_position`: by real name this arm died,
    by alias or attribute nothing died — until the driven no-row arm was made to run the recorder.
    Chasing every spelling statically is open-ended; **the driven arm is the robust net, and this one
    only makes a new bare-name construction site a deliberate edit.**

    The constructor patch is the boundary every row must cross — but only while every writer
    actually builds a `DecisionRecord`. A fifth writer is a deliberate decision someone should
    have to make explicitly, not one acquired by adding a method, so the FUNCTIONS that construct
    one are pinned by name.

    Names rather than a count: a count says four and cannot say WHICH, so moving a construction
    from one writer to a new one would leave it green — the identity-not-count lesson from
    `B424`'s residual, applied to the thing that makes this file's central arm meaningful.
    """
    import ast
    import inspect

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
        # `T-0144` R11': the pre-send SUBMITTING record, written before EVERY send — so on the unprotected path the one
        # row that exists is that SUBMITTING row, which the halt leaves as it is (no outcome is true there)
        "_write_submitting",
    }, (
        f"the set of functions constructing a DecisionRecord changed to "
        f"{sorted(set(where.values()))}. A new one must be added to the arm above's expectations "
        f"deliberately — that arm proves no row is written on the unprotected path, and it can "
        f"only mean that while every row still passes through a construction this file knows."
    )


# =====================================================================================
# REACHABILITY — the no-halt path must RUN in the suite, because it will rarely run in production
# =====================================================================================
#
# With one immediate observation, a market close submitted a moment earlier is usually still an
# OPEN ORDER, so observed-flat will be rare at the venue. That over-halts, which is accepted — but it
# means `AlpacaProtectionNotAccepted` could rot with nothing noticing. So the clean refusal is driven
# end to end: adapter -> ExecutionService -> the loop, asserting REJECTED with its own code and NO
# halt; and the unprotected type is driven through ExecutionService to show it is NOT converted.

from app.models.decision_record import REJECTION_PROTECTION_NOT_ACCEPTED  # noqa: E402


class _RaisingBroker:
    """A broker whose place_order raises the given exception — everything else a FakeBroker does."""

    def __init__(self, exc):
        self.exc = exc

    @property
    def is_simulation(self):
        return True

    async def reference_price(self, pair):
        return 100.0

    async def get_account(self):
        from app.services.broker.base import Account
        return Account(account_id="t", broker="fake", balance=10_000.0, equity=10_000.0,
                       currency="USD", unrealized_pl=0.0, open_trade_count=0)

    async def place_order(self, request):
        raise self.exc


def _signal():
    from app.services.execution.service import Signal
    return Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=100.0, sl=98.0, tp=104.0,
                  risk_pct=0.01, order_type=OrderType.MARKET, approved=True)


@pytest.mark.asyncio
async def test_REACHABILITY_service_files_observed_flat_as_REJECTED_with_its_OWN_code():
    """The clean refusal reaches the result shape the loop reads — `REJECTED`, and the code that
    tells an operator this is a venue capability rather than a transient blip."""
    from app.services.execution.service import ExecutionService

    exc = AlpacaProtectionNotAccepted("flat OBSERVED after remediation", broker="alpaca")
    res = await ExecutionService(_RaisingBroker(exc)).execute(_signal())

    assert res["status"] == "REJECTED", res
    assert res["rejection_code"] == REJECTION_PROTECTION_NOT_ACCEPTED, (
        f"filed under {res.get('rejection_code')!r} — as VENUE_TRANSPORT it reads as transient and "
        f"clears on its own, when it recurs while its condition holds"
    )


@pytest.mark.asyncio
async def test_REACHABILITY_service_does_NOT_convert_UNPROTECTED_into_a_rejection():
    """The opposite state must pass straight through. Caught by `except BrokerError` it would become
    a `REJECTED` row — a position possibly open, recorded as the engine declining to trade."""
    from app.services.execution.service import ExecutionService

    exc = AlpacaUnprotectedPositionOpen(symbol="BTC/USD", order_id="o-1", detail="flat NOT OBSERVED")
    with pytest.raises(AlpacaUnprotectedPositionOpen):
        await ExecutionService(_RaisingBroker(exc)).execute(_signal())


@pytest.mark.asyncio
async def test_REACHABILITY_the_loop_records_the_clean_refusal_and_does_NOT_HALT(monkeypatch):
    """**The no-halt path, end to end at the loop.** A `REJECTED` result carrying
    `PROTECTION_NOT_ACCEPTED` is an ordinary refusal: a rejection row, the engine keeps running."""
    from app.services.live import crypto_loop as mod

    import pandas as pd

    loop = mod.LiveCryptoLoop()
    rejected: list = []

    class _S:
        symbol, direction = "BTC/USD", DirectionType.LONG
        entry, sl, tp = 100.0, 99.0, None
        risk_pct, approved, client_order_id = 0.01, True, "sig-x"
        partial_price = partial_fraction = None

    class _T:
        reasons = ["b429"]

        def __getattr__(self, _):
            return None

    base = [100.0 + i for i in range(60)]
    bars = pd.DataFrame({"open": base, "high": [b + 1 for b in base],
                         "low": [b - 1 for b in base], "close": base, "volume": [10.0] * 60})

    async def _noop(*a, **k):
        return None

    async def _fetch(*a, **k):
        return bars

    async def _false(*a, **k):
        return False

    async def _zero(*a, **k):
        return 0

    async def _exec(sig):
        return {"status": "REJECTED", "rejection_code": REJECTION_PROTECTION_NOT_ACCEPTED,
                "reason": "flat OBSERVED after remediation", "pair": "BTC/USD", "direction": "LONG"}

    async def _rejected(*a, **k):
        rejected.append((a, k))

    monkeypatch.setattr(mod, "_ticker_price", lambda _bsym: 100.0)   # no network (see _drive_tick)
    monkeypatch.setattr(mod, "evaluate_latest_bar_traced", lambda *a, **k: (_S(), _T()))
    monkeypatch.setattr(loop, "_fetch_bars", _fetch)
    monkeypatch.setattr(loop, "_act", _noop)
    monkeypatch.setattr(loop, "_shadow_evaluate", _noop)
    monkeypatch.setattr(loop, "_maybe_emit_census", _noop)
    monkeypatch.setattr(loop, "_news_context", _noop)
    monkeypatch.setattr(loop, "_has_position", _false)
    monkeypatch.setattr(loop, "_open_count", _zero)
    monkeypatch.setattr(loop, "_record_rejected_signal", _rejected)
    monkeypatch.setattr(loop.execution, "execute", _exec)

    await loop._tick_symbol("BTC/USD", "BTCUSDT")          # must not raise

    assert loop.halt_reason is None, f"a clean refusal HALTED the engine: {loop.halt_reason!r}"
    assert rejected, "the clean refusal wrote no rejection row, so the no-halt path recorded nothing"
    assert REJECTION_PROTECTION_NOT_ACCEPTED in repr(rejected[0]), (
        f"the rejection row does not carry its own code: {rejected[0]!r}"
    )
