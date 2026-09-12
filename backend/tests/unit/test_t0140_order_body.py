"""T-0140 — `place_order`'s body, sized to what the VENUE says it will take.

Against `agents/tasks/T-0140/KILL_SET.md`, nine rows and one prohibition, registered before this
file existed.

**THE NUMBERS ARE MEASURED, NOT DOCUMENTED** (`T-0139`/`B409`). The programme said the minimum
was `0.0001` and the increment `0.0001`; the venue says BTC `0.000012941`, ETH `0.000397984`, and
`1e-9` for both increments. **The documented minimum was 7.7x too large and the documented
increment 100,000x too coarse** — so a body written from the document would refuse valid orders and
quantise every size to a grid the venue does not use.

**AND THE TWO FIELDS HAVE DIFFERENT NATURES.** The minimum is ~$1 of notional, so it MOVES WITH
PRICE; the increment is a constant. That is why the minimum is read per asset per order and why no
value is cached.

⚠ **`M-10`, THE PROHIBITION: nothing in this file has met a real Alpaca rejection.** The account has
placed zero orders. Every arm here pins OUR mapping — that this member's refusals become
`VENUE_DIRECTION_UNSUPPORTED` and `MIN_SIZE`, that a `BrokerError` becomes `VENUE_TRANSPORT` — and
says **nothing** about which exception Alpaca actually raises for an undersized order or a shorting
attempt. **A green run of this file is not evidence the venue boundary was tested.** The first real
order settles it; until then the register says *untested against the venue*, not *covered*.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.exceptions import DirectionNotSupported
from app.db.enums import DirectionType, OrderType
from app.models.decision_record import REJECTION_MIN_SIZE
from app.services.broker.alpaca import (
    ALPACA_CRYPTO_LONG_ONLY,
    AlpacaAdapter,
    AlpacaAssetUnusable,
    AlpacaBelowMinimumSize,
)
from app.services.broker.base import OrderRequest

pytestmark = pytest.mark.asyncio

#: The venue's own numbers, from `T-0139`. BTC and ETH differ by 31x, which is what makes `M-7`
#: (one asset's limits applied to all) catchable at all.
BTC_MIN = 0.000012941
ETH_MIN = 0.000397984
GRID = 0.000000001


def _asset(symbol: str, *, min_order_size: float, shortable: bool = False,
           min_trade_increment: float = GRID, price_increment: float = GRID):
    """A REAL `alpaca.trading.models.Asset`, not a stand-in.

    `T-0136`'s discipline: the mock encoding the author's reading is how three defects reached that
    adapter. Constructing the venue's own pydantic model means a field this code reads must exist
    on it, with the type the venue declares — including `Optional[float]` for all three limits, so
    absence is representable.
    """
    from alpaca.trading.enums import AssetClass, AssetExchange, AssetStatus
    from alpaca.trading.models import Asset

    return Asset(
        id=uuid.uuid4(), **{"class": AssetClass.CRYPTO}, exchange=AssetExchange.CRYPTO,
        symbol=symbol, status=AssetStatus.ACTIVE, tradable=True, marginable=False,
        shortable=shortable, easy_to_borrow=False, fractionable=True,
        min_order_size=min_order_size, min_trade_increment=min_trade_increment,
        price_increment=price_increment,
    )


def _order(qty: str):
    from alpaca.trading.enums import OrderClass, OrderStatus, TimeInForce
    from alpaca.trading.models import Order

    now = datetime.now(timezone.utc)
    return Order(
        id=uuid.uuid4(), client_order_id="sig-test", created_at=now, updated_at=now,
        submitted_at=now, status=OrderStatus.FILLED, time_in_force=TimeInForce.GTC,
        order_class=OrderClass.SIMPLE, extended_hours=False, symbol="BTC/USD", qty=qty,
        filled_qty=qty, filled_avg_price="70000",
    )


class Client:
    """Records every call, so an arm can assert the venue was read once PER ORDER."""

    def __init__(self, assets: dict, *, account_shorting_enabled: bool = True):
        self._assets = assets
        self.calls: list[tuple] = []
        self.account_shorting_enabled = account_shorting_enabled
        self.submitted: list = []

    def get_asset(self, symbol):
        self.calls.append(("get_asset", symbol))
        if symbol not in self._assets:
            # The venue answering for a DIFFERENT market is `M-5`'s case; an absent symbol here
            # would mask it, so this raises rather than returning something plausible.
            raise KeyError(symbol)
        return self._assets[symbol]

    def submit_order(self, order_data):
        self.calls.append(("submit_order", order_data.symbol, order_data.qty))
        self.submitted.append(order_data)
        return _order(str(order_data.qty))

    def get_account(self):
        self.calls.append(("get_account",))
        class _Acct:
            shorting_enabled = self.account_shorting_enabled
        return _Acct()


def _adapter(assets=None, **kw):
    assets = assets if assets is not None else {"BTC/USD": _asset("BTC/USD", min_order_size=BTC_MIN)}
    client = Client(assets, **kw)
    return AlpacaAdapter(client, paper=True), client


import contextlib


@contextlib.contextmanager
def _policy(replacement):
    """Swap the module-level policy for the duration of one arm.

    Patched on the MODULE rather than on the adapter instance, because `place_order` reads the
    module global — patching `adapter.direction_policy` would leave the gate untouched and the arm
    would pass for the wrong reason.
    """
    import app.services.broker.alpaca as mod

    before = mod.ALPACA_CRYPTO_LONG_ONLY
    mod.ALPACA_CRYPTO_LONG_ONLY = replacement
    try:
        yield
    finally:
        mod.ALPACA_CRYPTO_LONG_ONLY = before


def _req(direction=DirectionType.LONG, pair="BTC/USD", lot=0.01):
    return OrderRequest(pair=pair, direction=direction, order_type=OrderType.MARKET,
                        lot_size=lot, client_order_id="sig-test")


# =====================================================================================
# M-1 — THE MINIMUM IS READ PER ORDER, NOT PINNED
# =====================================================================================

async def test_the_minimum_is_read_from_the_venue_on_EVERY_order():
    """**`M-1` and `M-9` together.** The minimum is ~$1 of notional, so it moves with price: a
    pinned constant, or a cache with no expiry, refuses valid orders in one regime and admits
    sub-minimum ones in the other — **without ever failing.**

    The fixture makes the venue's answer CHANGE between orders, which a constant cannot reproduce
    and a cache would not notice.
    """
    assets = {"BTC/USD": _asset("BTC/USD", min_order_size=BTC_MIN)}
    adapter, client = _adapter(assets)

    await adapter.place_order(_req(lot=0.01))
    # Price doubles: the $1 floor halves. Same symbol, different answer.
    assets["BTC/USD"] = _asset("BTC/USD", min_order_size=BTC_MIN / 2)
    await adapter.place_order(_req(lot=0.01))

    reads = [c for c in client.calls if c[0] == "get_asset"]
    assert len(reads) == 2, (
        f"the venue was read {len(reads)} times for 2 orders — a cache with no expiry is a pinned "
        f"constant with extra steps, and this minimum is price-derived"
    )

    # **AND THE SECOND READ MUST BE THE ONE IN FORCE, not merely performed.** The call count alone
    # is satisfied by a body that reads the venue and then ignores it — the harness proved exactly
    # that: pinning `min_order_size` to a constant AFTER the read killed the per-asset arm and
    # left this one green. A read whose answer is discarded is not a read.
    assets["BTC/USD"] = _asset("BTC/USD", min_order_size=BTC_MIN * 4)
    with pytest.raises(AlpacaBelowMinimumSize) as exc:
        # Valid at the ORIGINAL minimum, below the CURRENT one. Only a body using the latest
        # answer refuses this.
        await adapter.place_order(_req(lot=BTC_MIN * 2))

    assert exc.value.minimum == Decimal(str(BTC_MIN * 4)), (
        f"refused against {exc.value.minimum} — a stale or pinned minimum, not the venue's latest"
    )


async def test_a_size_valid_at_the_MEASURED_minimum_is_not_refused_by_the_DOCUMENTED_one():
    """The programme said `0.0001`; the venue says `0.000012941`. **A size between them is valid at
    the venue and would have been refused by us** — 7.7x, and the whole reason `T-0139` ran."""
    adapter, client = _adapter()
    between = 0.00005  # > BTC_MIN, < the documented 0.0001

    result = await adapter.place_order(_req(lot=between))

    assert result["status"] == "FILLED"
    assert client.submitted, (
        "a size ABOVE the venue's published minimum was not submitted — `M-10`: published is not "
        "the same as accepted, and no order has been placed to find out"
    )


# =====================================================================================
# M-2 — ROUND DOWN, M-8 — IN DECIMAL
# =====================================================================================

async def test_the_quantity_is_quantised_DOWN_to_the_grid():
    """**Down, not nearest** (`T-0097`'s ruled direction for lots). Rounding up crosses the risk
    the size was computed for: `size_position` derived it from equity, risk-% and stop distance, so
    a larger quantity is a larger loss at the same stop."""
    adapter, client = _adapter(
        {"BTC/USD": _asset("BTC/USD", min_order_size=BTC_MIN, min_trade_increment=0.001)})

    await adapter.place_order(_req(lot=0.0129))

    sent = Decimal(str(client.submitted[0].qty))
    assert sent == Decimal("0.012"), f"quantised to {sent} — up or to nearest, not down"


async def test_the_quantisation_is_EXACT_where_float_arithmetic_is_not():
    """**`M-8`.** Nine decimal places is where binary floats stop being safe — `T-0097`'s
    `0.3 / 0.1 == 2.9999...` one module over. The fixture is a size where the two genuinely
    disagree, since a fixture where float happens to be right cannot catch this."""
    adapter, client = _adapter(
        {"BTC/USD": _asset("BTC/USD", min_order_size=BTC_MIN, min_trade_increment=0.1)})

    await adapter.place_order(_req(lot=0.3))

    sent = Decimal(str(client.submitted[0].qty))
    assert sent == Decimal("0.3"), f"sent {sent}"
    # The float form of the same computation is visibly wrong, which is why Decimal is required
    # rather than preferred.
    assert int(0.3 / 0.1) == 2, "if this ever becomes 3, the float hazard has changed shape"
    assert sent / Decimal("0.1") == 3


# =====================================================================================
# M-3 — REFUSE BELOW THE MINIMUM, WITH ITS OWN CODE
# =====================================================================================

async def test_a_sub_minimum_size_is_REFUSED_not_rounded_to_zero():
    """**`M-3`.** Rounding to zero sends a quantity the venue **would** reject — or one our own
    `lot_size > 0` guard rejects after the decision was already recorded as taken.

    **"would", not "does", and the correction is `M-10` enforcing itself.** Review caught this
    sentence asserting Alpaca's behaviour in a file whose header says none of it is known. Only the
    second half — our own guard — is tested; the venue's response to a zero quantity is a
    could-not-ask like every other venue response here, because this account has placed no orders.
    The hedge was already in the sentence and the indicative verb undid it."""
    adapter, client = _adapter()

    with pytest.raises(AlpacaBelowMinimumSize) as exc:
        await adapter.place_order(_req(lot=0.000001))   # positive, below BTC's floor

    assert exc.value.minimum == Decimal(str(BTC_MIN))
    assert not client.submitted, "a sub-minimum order was sent to the venue"
    assert "moves with price" in str(exc.value).lower(), (
        "the refusal must say the floor is not a constant, or a reader files it as our defect"
    )


async def test_the_sub_minimum_refusal_maps_to_MIN_SIZE_and_not_to_transport():
    """**Two causes, two remedies.** `NON_POSITIVE_SIZE` is `units <= 0` — arithmetic on our side.
    This is the venue's floor on a well-formed order, and the same size can be refused today and
    accepted tomorrow. Filing it as `VENUE_TRANSPORT` would make a deterministic floor look
    retryable: `B375` in a third place.

    ⚠ This pins OUR mapping only (`M-10`). Alpaca has never rejected an order from this account.
    """
    from app.services.broker.paper import PaperBroker
    from app.services.execution.service import ExecMode, ExecutionService, Signal

    class Undersized(PaperBroker):
        async def place_order(self, request):
            raise AlpacaBelowMinimumSize(
                symbol="BTC/USD", requested=Decimal("0.000001"),
                minimum=Decimal(str(BTC_MIN)))

    broker = Undersized(starting_balance=10_000.0, price_fn=lambda p: 70_000.0)
    broker.on_tick("BTC/USD", 70_000.0)
    res = await ExecutionService(broker, ExecMode.PAPER).execute(
        Signal(symbol="BTC/USD", direction=DirectionType.LONG, entry=70_000.0, sl=69_000.0,
               approved=True))

    assert res["rejection_code"] == REJECTION_MIN_SIZE
    assert res["rejection_code"] != "VENUE_TRANSPORT"
    assert res["rejection_code"] != "NON_POSITIVE_SIZE"


# =====================================================================================
# M-4 — THE ASSET'S `shortable`, AND THE ACCOUNT FLAG MUST NOT MATTER
# =====================================================================================

async def test_a_SHORT_is_refused_WITHOUT_TOUCHING_THE_VENUE():
    """**A permanent refusal must not need a successful network call to happen.**

    I wrote it the other way first, to deduplicate the venue read — and that made the refusal
    depend on the venue answering. On a timeout a SHORT returns `BrokerError` ->
    `VENUE_TRANSPORT`, which reads as *try again*, and the loop would retry forever an order this
    venue will never take. `B375`'s shape, produced by fixing the double read.

    And `ExecutionService` does not gate it upstream: `service.py:209` consults
    `direction_policy` only in the shadow branch, so **this raise is the only gate for a live
    order.** Hence zero venue calls, asserted rather than assumed.
    """
    adapter, client = _adapter()

    with pytest.raises(DirectionNotSupported) as exc:
        await adapter.place_order(_req(DirectionType.SHORT))

    assert exc.value.reason == ALPACA_CRYPTO_LONG_ONLY.reason
    assert not client.submitted
    assert client.calls == [], f"the refusal contacted the venue: {client.calls}"


async def test_a_SHORT_is_refused_when_the_VENUE_IS_UNREACHABLE():
    """The same property driven from the failure that motivates it, rather than from a call
    count — a client whose every member raises still yields the DIRECTION refusal."""
    adapter, client = _adapter()

    def unreachable(symbol):
        client.calls.append(("get_asset", symbol))
        raise ConnectionError("venue unreachable")

    client.get_asset = unreachable

    # The control: a LONG through the same dead client DOES fail, so the arm above is not passing
    # because nothing reaches the venue.
    with pytest.raises(Exception) as long_exc:
        await adapter.place_order(_req(DirectionType.LONG))
    assert not isinstance(long_exc.value, DirectionNotSupported)

    with pytest.raises(DirectionNotSupported):
        await adapter.place_order(_req(DirectionType.SHORT))


async def test_the_ASSET_flag_still_refuses_when_THE_POLICY_IS_WIDENED():
    """**`M-4` proper, and the policy gate is what makes this arm necessary.**

    With the policy refusing first, mutating `asset.shortable` changes nothing — the mutation
    would be INERT and its survival would measure nothing (`M-6`'s lesson on a different axis).
    So the fixture widens `supported` to include SHORT, which is the exact condition the second
    gate exists for: our policy and the venue's fact DIVERGING.

    Measured (`T-0139`/`D4a`): the account says `shorting_enabled: TRUE` while every crypto asset
    says `shortable: false`. **A check against the account flag concludes shorts are fine, and
    they are not** — `B386`'s shape, one instrument complete on the account axis and silent on the
    instrument axis.
    """
    import dataclasses

    widened = dataclasses.replace(
        ALPACA_CRYPTO_LONG_ONLY,
        supported=frozenset({DirectionType.LONG, DirectionType.SHORT}))

    adapter, client = _adapter()
    with _policy(widened):
        with pytest.raises(DirectionNotSupported) as exc:
            await adapter.place_order(_req(DirectionType.SHORT))

    assert exc.value.reason == ALPACA_CRYPTO_LONG_ONLY.reason
    assert not client.submitted
    assert any(c[0] == "get_asset" for c in client.calls), (
        "the second gate did not read the venue at all, so it is not the venue's answer"
    )


async def test_the_ACCOUNT_shorting_flag_MAKES_NO_DIFFERENCE():
    """**`M-4`'s negative control, and the kill set gives it `PREDICT 0`.**

    Mutating the ASSET's `shortable` must kill; mutating `account.shorting_enabled` must kill
    **nothing**. Only the two together prove which field is consulted — because both point the same
    way in effect today, an arm reading either one passes.
    """
    import dataclasses

    widened = dataclasses.replace(
        ALPACA_CRYPTO_LONG_ONLY,
        supported=frozenset({DirectionType.LONG, DirectionType.SHORT}))

    for account_flag in (True, False):
        adapter, client = _adapter(account_shorting_enabled=account_flag)
        with _policy(widened):
            with pytest.raises(DirectionNotSupported):
                await adapter.place_order(_req(DirectionType.SHORT))
        assert not any(c[0] == "get_account" for c in client.calls), (
            "the order path read the ACCOUNT to decide a per-asset question"
        )


async def test_a_SHORTABLE_asset_would_be_allowed_through_this_check():
    """The must-miss for the refusal: it must key on the flag, not refuse every SHORT
    unconditionally. Alpaca crypto is not shortable today, so this asset is deliberately
    counterfactual — it demonstrates the check reads the venue rather than asserting our policy."""
    import dataclasses

    widened = dataclasses.replace(
        ALPACA_CRYPTO_LONG_ONLY,
        supported=frozenset({DirectionType.LONG, DirectionType.SHORT}))

    adapter, client = _adapter(
        {"BTC/USD": _asset("BTC/USD", min_order_size=BTC_MIN, shortable=True)})

    with _policy(widened):
        await adapter.place_order(_req(DirectionType.SHORT))
    assert client.submitted, "the refusal is unconditional, so it measures nothing about the venue"


# =====================================================================================
# M-5 — EXACT SYMBOL, M-7 — PER ASSET
# =====================================================================================

async def test_the_venue_answering_for_a_DIFFERENT_market_is_refused():
    """**`M-5`.** The venue lists `BTC/USD`, `BTC/USDC`, `BTC/USDT`, `ETH/BTC` and more. Review's
    own probe used `startswith("BTC")`, which would have caught `BTC/USDT` and missed `ETH/BTC`.
    **A loose match does not fail — it prices the wrong market.**"""
    adapter, client = _adapter({"BTC/USD": _asset("BTC/USDT", min_order_size=BTC_MIN)})

    with pytest.raises(AlpacaAssetUnusable) as exc:
        await adapter.place_order(_req())

    assert "BTC/USDT" in str(exc.value) and not client.submitted


async def test_each_asset_uses_its_OWN_minimum():
    """**`M-7`.** BTC `0.000012941` against ETH `0.000397984` — **31x**. One asset's limits applied
    to every symbol passes any BTC-only arm and then refuses valid ETH orders."""
    assets = {"BTC/USD": _asset("BTC/USD", min_order_size=BTC_MIN),
              "ETH/USD": _asset("ETH/USD", min_order_size=ETH_MIN)}
    adapter, client = _adapter(assets)

    # Valid for BTC, BELOW ETH's floor. Only per-asset limits separate these.
    size = 0.0001
    await adapter.place_order(_req(pair="BTC/USD", lot=size))
    with pytest.raises(AlpacaBelowMinimumSize) as exc:
        await adapter.place_order(_req(pair="ETH/USD", lot=size))

    assert exc.value.minimum == Decimal(str(ETH_MIN))


# =====================================================================================
# M-6 — THE QUANTITY GRID, NOT THE PRICE GRID
# =====================================================================================

async def test_the_quantity_is_quantised_by_min_trade_increment_NOT_price_increment():
    """**`M-6`, and the fixture is deliberately UNREALISTIC on this axis.**

    Both increments are `1e-9` on this venue, so swapping them is **inert against a realistic
    fixture** — the mutation survives and its survival measures nothing. Realism is what makes the
    arm untestable, so the quantity grid is `1e-9` here and the price grid `0.01`: only then does
    quantising by the wrong field change the answer.

    > Where two fields hold the same value in reality, the fixture must make them differ.
    """
    adapter, client = _adapter({"BTC/USD": _asset(
        "BTC/USD", min_order_size=BTC_MIN, min_trade_increment=GRID, price_increment=0.01)})

    await adapter.place_order(_req(lot=0.012345678))

    sent = Decimal(str(client.submitted[0].qty))
    assert sent == Decimal("0.012345678"), (
        f"sent {sent} — quantised by the PRICE grid (0.01) instead of the quantity grid (1e-9)"
    )


# =====================================================================================
# ABSENT LIMITS — a real state, and the alarming reading is the only safe one
# =====================================================================================

@pytest.mark.parametrize("missing", ["min_order_size", "min_trade_increment", "price_increment"])
async def test_an_ABSENT_limit_refuses_rather_than_defaulting(missing):
    """All three are `Optional[float]` on the SDK model, so absence is representable. **A missing
    minimum treated as zero admits every size**, and treated as a constant rebuilds the defect this
    task removes."""
    asset = _asset("BTC/USD", min_order_size=BTC_MIN)
    object.__setattr__(asset, missing, None)
    adapter, client = _adapter({"BTC/USD": asset})

    with pytest.raises(AlpacaAssetUnusable) as exc:
        await adapter.place_order(_req())

    assert missing in str(exc.value) and not client.submitted


# =====================================================================================
# B411 — THE STATUS PREDICATE: blind to the real value, then too loose once it can see
# =====================================================================================

async def test_a_FILLED_order_reports_the_word_the_LOOP_reads():
    """**`B411`, and the consequence points the worst way.**

    `crypto_loop.py:1858` opens a position on `res["status"] == "FILLED"`. The predicate here was
    `str(placed.status).endswith("filled")`, and `OrderStatus` is a `str`-mixin enum, so `str()` of
    it is `'OrderStatus.FILLED'` — **the predicate never fired, and a real filled order was
    invisible to the platform.** The venue would hold a position the engine never recorded.

    This is the `BaseURL` trap from `test_t0138_order_path.py`, rebuilt one module later *by the
    author of that arm*. The arm below is the greppable form of the rule, so the next surface
    inherits it measured rather than argued.
    """
    from alpaca.trading.enums import OrderStatus

    adapter, client = _adapter()
    result = await adapter.place_order(_req())

    assert result["status"] == "FILLED"
    # The reason the old form failed, pinned so a "simplification" back to `str()` goes red.
    assert str(OrderStatus.FILLED) == "OrderStatus.FILLED", (
        "if this ever becomes 'filled', the str() hazard has gone and this guard can relax"
    )
    assert OrderStatus.FILLED.value == "filled"

    # The actual consumer, read from disk rather than from my memory of it — what the loop
    # accepts is what makes this arm's expected value the RIGHT one, and if the loop stops
    # accepting it this goes red rather than pinning a word nothing reads.
    #
    # **AND IT DID GO RED, ONE TASK LATER, EXACTLY AS INTENDED.** It pinned the literal
    # `res.get("status") == "FILLED"`. `T-0141` widened that gate to `FILL_BEARING_STATUSES`,
    # because a PARTIALLY_FILLED order is also a real position — so the literal disappeared and
    # this arm failed rather than going quietly stale. Re-derived against the constant, which is
    # the concept rather than one of its spellings.
    from app.services.live.crypto_loop import FILL_BEARING_STATUSES

    assert "FILLED" in FILL_BEARING_STATUSES, (
        "the loop no longer opens a position on this status — re-derive what it reads"
    )


async def test_a_PARTIAL_fill_is_NOT_reported_as_FILLED():
    """**The other half of `B411`, and fixing only the first half would have created it.**

    `partially_filled` also ends with `filled`. A suffix match reports a partial as full, so the
    engine records a position at the size we ASKED for while the venue filled less — a size
    mismatch on a real position, which no later reconciliation can distinguish from a slippage.

    It is deliberately not `FILLED`, so the loop does not open a full position from a partial.
    """
    adapter, client = _adapter()

    def partial(order_data):
        client.calls.append(("submit_order", order_data.symbol, order_data.qty))
        o = _order(str(order_data.qty))
        object.__setattr__(o, "status", __import__(
            "alpaca.trading.enums", fromlist=["OrderStatus"]).OrderStatus.PARTIALLY_FILLED)
        object.__setattr__(o, "filled_qty", "0.004")
        return o

    client.submit_order = partial
    result = await adapter.place_order(_req(lot=0.01))

    assert result["status"] == "PARTIALLY_FILLED"
    assert result["status"] != "FILLED", "a partial recorded as full is a phantom position size"
    assert result["filled_units"] == 0.004, "the venue's own filled quantity must survive"
    assert result["units"] == 0.01, "and the SUBMITTED size stays visible beside it"


async def test_a_status_the_venue_did_not_give_is_not_reported_as_a_FILL():
    """The must-miss. A `None` status must not fall through to the word that opens a position —
    **a default must be the alarming state**, and here the alarming reading is `SUBMITTED`."""
    adapter, client = _adapter()

    def statusless(order_data):
        o = _order(str(order_data.qty))
        object.__setattr__(o, "status", None)
        return o

    client.submit_order = statusless
    result = await adapter.place_order(_req())

    assert result["status"] == "SUBMITTED"
    assert result["status"] != "FILLED"


# =====================================================================================
# ORDER OF REFUSALS — a permanent policy refusal must not be maskable by a venue-shaped one
# =====================================================================================

async def test_a_SHORT_is_refused_for_its_DIRECTION_even_when_a_limit_is_ABSENT():
    """Sizing first would refuse this as `AlpacaAssetUnusable` — a venue-shaped complaint that
    sends the reader to Alpaca — when the real answer is that we will never take this direction.
    **`B375`'s shape with the two causes in the other order**, and the fixture makes both true at
    once so only the ordering separates them."""
    asset = _asset("BTC/USD", min_order_size=BTC_MIN)
    object.__setattr__(asset, "min_order_size", None)
    adapter, client = _adapter({"BTC/USD": asset})

    with pytest.raises(DirectionNotSupported):
        await adapter.place_order(_req(DirectionType.SHORT))


async def test_a_LONG_reads_the_venue_ONCE_not_twice():
    """**`M-9`.** The minimum moves with price, so two reads of one record can disagree with each
    other — the sizing and the direction confirmation must come from the SAME read."""
    adapter, client = _adapter()

    await adapter.place_order(_req(DirectionType.LONG))

    reads = [c for c in client.calls if c[0] == "get_asset"]
    assert len(reads) == 1, f"{len(reads)} reads for one order"


async def test_the_exception_the_refusal_NAMES_is_the_one_it_can_RAISE():
    """**This arm exists because the module raised a name it never imported.**

    `place_order` referenced `DirectionNotSupported` while `alpaca.py` imported only `BrokerError`,
    so the long-only refusal — the one ruling Malek made by hand — raised `NameError`. And
    `NameError` is not a `BrokerError`, so `ExecutionService`'s handler would not have caught it:
    the refusal would have escaped as an unhandled crash instead of a recorded rejection.

    A docstring naming an exception is not a guarantee the name resolves. This checks the module's
    namespace directly, so the next refusal added by docstring goes red.
    """
    import app.services.broker.alpaca as mod

    for name in ("DirectionNotSupported", "BrokerError", "AlpacaBelowMinimumSize",
                 "AlpacaAssetUnusable"):
        assert hasattr(mod, name), f"place_order names {name} and the module cannot resolve it"
        assert issubclass(getattr(mod, name), Exception)


async def test_an_ABSENT_filled_quantity_is_NOT_defaulted_to_THE_SIZE_WE_ASKED_FOR():
    """**THE ONE MUTATION THAT SURVIVED THE FIRST HARNESS RUN, and it is the class I keep a note
    about: a default must be the alarming state.**

    Every fixture in this file set `filled_qty`, because `_order()` sets it from the submitted
    quantity — so `filled_units`'s fallback branch was never executed and a mutation making it
    default to `float(quantity)` passed all 197 arms. *Unchanged-by-coincidence reads exactly like
    unchanged*; here it was untouched-by-coincidence.

    The fallback matters because `filled_units` exists to answer *how much did the venue actually
    fill* — and the submitted quantity is one of the two answers that question has to
    distinguish. Defaulting to it means the field **cannot report its own ignorance**: an order the
    venue has accepted but not filled would claim a full fill.
    """
    adapter, client = _adapter()

    def unsaid(order_data):
        o = _order(str(order_data.qty))
        object.__setattr__(o, "filled_qty", None)
        return o

    client.submit_order = unsaid
    result = await adapter.place_order(_req(lot=0.01))

    assert result["filled_units"] is None, (
        f"filled_units is {result['filled_units']!r} — the venue said nothing and we answered "
        f"with the size we ASKED for, which is the state this field exists to distinguish"
    )
    assert result["units"] == 0.01, "the submitted size is still reported, under its own key"
