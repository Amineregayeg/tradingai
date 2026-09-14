"""T-0136 — the Alpaca adapter, with every shape read from the INSTALLED SDK first.

**WHY THIS FILE IS DIFFERENT FROM `test_t0106_mt5_adapter.py`.** That adapter was written from
documentation and its mock encoded the adapter's own reading, so **no arm could fail on a fact the
two shared** (`B334`). Three defects came out of it and all three were ARRANGEMENT or RETURN SHAPE
rather than naming — `B341`, `B356`, `B359`. Nine of nine names were right.

Every shape below was taken from `inspect`/`model_fields` on `alpaca-py==0.44.0` **before this file
existed**, and recorded in `agents/tasks/T-0136/SDK_SHAPES.md`. Where a fixture asserts a venue
fact, that document is the source and this file is the copy — not the other way round.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.core.exceptions import BrokerError, DirectionNotSupported
from app.db.enums import DirectionType, OrderType
from app.services.broker.alpaca import (
    ALPACA_CRYPTO_LONG_ONLY,
    ORDER_SIDES,
    POSITION_SIDES,
    AlpacaAdapter,
    AlpacaFieldUnreadable,
    AlpacaSideUnrecognised,
)
from app.services.broker.base import OrderRequest


class _Side:
    """The SDK's enums carry `.value`; the adapter reads through it."""

    def __init__(self, value: str) -> None:
        self.value = value


class _Position:
    """`alpaca.trading.models.Position`'s shape — **numerics are STRINGS**, which is the finding.

    `Position.qty` is `str` and `Position.avg_entry_price` is `str` on the real model, while
    `Order.qty` is `Union[str, float, None]` — the same concept with two types. A fixture using
    floats here would encode a reading the SDK contradicts.
    """

    def __init__(self, symbol="BTC/USD", side="long", qty="0.5",
                 avg_entry_price="100.0", current_price="110.0", unrealized_pl="5.0"):
        self.asset_id = f"asset-{symbol}"
        self.symbol = symbol
        self.side = _Side(side)
        self.qty = qty
        self.avg_entry_price = avg_entry_price
        self.current_price = current_price
        self.unrealized_pl = unrealized_pl


class _Account:
    def __init__(self, equity="10050.0", cash="10000.0", buying_power="9900.0"):
        self.account_number = "PA123"
        self.equity = equity
        self.cash = cash
        self.buying_power = buying_power
        self.currency = "USD"


def _close_order(symbol, status="filled", filled_qty="0.01"):
    """A REAL `alpaca.trading.models.Order` — what `TradingClient.close_position(symbol)` returns.

    **`B439`.** This double used to return a `ClosePositionResponse` look-alike (`body`, an HTTP `status`
    int) — the return type of `close_all_positions`, a DIFFERENT SDK method this adapter never calls. The
    adapter read the real Order the same way, `int(order.status)` raised for every status, and the kill
    switch ended after its first position; this file stayed green because its double answered for the
    other method. `test_the_close_double_returns_what_the_SDK_ANNOTATES` pins the double to the SDK.
    """
    import uuid
    from datetime import datetime, timezone

    from alpaca.trading.enums import OrderClass, OrderStatus, TimeInForce
    from alpaca.trading.models import Order

    now = datetime.now(timezone.utc)
    return Order(
        id=uuid.uuid4(), client_order_id=f"close-{symbol}", created_at=now, updated_at=now,
        submitted_at=now, status=OrderStatus(status), time_in_force=TimeInForce.GTC,
        order_class=OrderClass.SIMPLE, extended_hours=False, symbol=symbol, qty="0.01",
        filled_qty=filled_qty, filled_avg_price="70000" if status == "filled" else None,
    )


async def _instant_sleep(_seconds):
    """The resolver's sleep, replaced: no arm waits for real time (`B427`)."""
    return None


class TradingClientMock:
    """`close_status` is the status every close order is created with and RE-READ as, per symbol when a
    dict — so an accepted close that never fills stays accepted on every re-read, as the venue would say."""

    def __init__(self, positions=None, account=None, close_status="filled", close_error=None):
        self._positions = positions if positions is not None else [_Position()]
        self._account = account if account is not None else _Account()
        self._close_status = close_status
        self._close_error = close_error or {}
        self._orders: dict[str, object] = {}
        self.closed: list[tuple] = []
        self.rereads: list[str] = []

    def get_account(self):
        if isinstance(self._account, Exception):
            raise self._account
        return self._account

    def get_all_positions(self):
        if isinstance(self._positions, Exception):
            raise self._positions
        return list(self._positions)

    def get_orders(self, filter=None):
        self.orders_filter = filter
        return []

    def close_position(self, symbol_or_asset_id, close_options=None):
        self.closed.append((symbol_or_asset_id, close_options))
        err = self._close_error.get(symbol_or_asset_id)
        if err is not None:
            raise err
        status = (self._close_status.get(symbol_or_asset_id, "filled")
                  if isinstance(self._close_status, dict) else self._close_status)
        order = _close_order(symbol_or_asset_id, status=status,
                             filled_qty="0.01" if status == "filled" else "0")
        self._orders[str(order.id)] = order
        if status == "filled" and isinstance(self._positions, list):
            # `B442`: A FILLED CLOSE LEAVES NO POSITION. This double used to keep listing it, which nothing read
            # twice until `close_all_positions` gained a second sweep — and against a book that never empties,
            # sweep (b) closed every confirmed position again. The venue would not list it.
            self._positions = [p for p in self._positions if getattr(p, "symbol", None) != symbol_or_asset_id]
        return order

    def get_order_by_id(self, order_id, filter=None):
        self.rereads.append(str(order_id))
        return self._orders[str(order_id)]


def _adapter(paper: bool = True, **kw) -> tuple[AlpacaAdapter, TradingClientMock]:
    mock = TradingClientMock(**kw)
    adapter = AlpacaAdapter(mock, paper=paper)
    adapter._sleep = _instant_sleep
    return adapter, mock


# ======================================================================================
# THE FLAG THE WHOLE VENUE CHANGE RESTS ON
# ======================================================================================


@pytest.mark.parametrize("paper", [True, False])
def test_is_simulation_REPORTS_THE_FLAG_WE_CONSTRUCTED_WITH(paper):
    """`T-0076` stopped being a blocker because this answer is TRUE rather than assumed.

    `ExecutionService` refuses any adapter reporting `False` and `ExecMode` has no LIVE member —
    both deliberately. An MT5 broker demo could not honestly answer this; **an Alpaca paper account
    can, because the flag is a value we PASSED and not a venue field we interpret.**

    Both directions, because an adapter that always says `True` would satisfy the paper case and
    silently certify a live account as a simulation.
    """
    adapter, _ = _adapter(paper=paper)
    assert adapter.is_simulation is paper


def test_is_simulation_is_NOT_derived_from_anything_the_venue_says():
    """The must-miss for the arm above: a venue field must not be able to move it.

    Deriving it from an account field would rebuild `T-0076` — a safety flag whose meaning depends
    on reading a third party's record.
    """
    adapter, mock = _adapter(paper=True)
    mock._account = _Account(equity="0.0")          # a venue answer that suggests nothing real
    assert adapter.is_simulation is True


def test_a_RAW_DICT_return_is_REFUSED_at_the_point_of_use():
    """**The `raw_data` finding, and my first arm for it asserted the wrong thing.**

    That version asserted the CONSTRUCTOR ARGUMENT — `TradingClient(..., raw_data=False)`. Measured
    since: **`_use_raw_data` is MUTABLE AT RUNTIME.** Assigning `client._use_raw_data = True` takes,
    and 28 SDK methods branch on it. So the constructor argument is a convention, and **an arm
    asserting it passes while the flag is flipped downstream.** I wrote that arm and called it the
    enforcement in the same message.

    There is no backend type-checker — `tsc` gates the frontend, nothing gates Python — so
    `Union[Model, Dict[str, Any]]` is unenforced. **This arm is the enforcement**, and it asserts
    the RETURNED OBJECT at the point of use.

    Why silence would be the outcome otherwise: every `getattr` on a dict returns its default, so a
    full raw payload reads as a payload of absences and `get_account` would refuse for *"no
    equity"* while the equity sits in the dict.
    """
    adapter, mock = _adapter()
    mock._account = {"equity": "10050.0", "cash": "10000.0", "account_number": "PA123"}
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.get_account())
    message = str(exc.value)
    assert "RAW DICT" in message and "_use_raw_data" in message, (
        f"the refusal does not name the cause, so a reader chases the wrong field: {message}"
    )
    assert "equity" not in message.split("See ")[0].replace("Every attribute", ""), (
        "the message blames a field when the shape is what is wrong"
    )


def test_a_raw_dict_in_the_POSITION_list_is_also_refused():
    """The must-hit sibling: the shape flips for EVERY read, not just the account. A guard on one
    member would leave the position path silently returning rows of absences."""
    adapter, mock = _adapter()
    mock._positions = [{"symbol": "BTC/USD", "side": "long", "qty": "0.5"}]
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.get_positions())
    assert "RAW DICT" in str(exc.value)


def test_the_factory_still_constructs_with_raw_data_FALSE():
    """Kept as the SECOND half rather than the whole. The construction argument is still the right
    default and worth pinning — it is simply not sufficient on its own, which is the finding."""
    from app.services.broker.manager import _make_adapter

    captured: dict = {}

    class _Recorder:
        def __init__(self, key, secret, paper=True, raw_data=False, **kw):
            import requests

            captured.update(paper=paper, raw_data=raw_data)
            # `B440`/`B441`/`B442`: the builder sets two SDK attributes, reads a third, and REFUSES a client
            # without any of them.
            self._retry_codes = [429, 504]
            self._session = requests.Session()
            self._api_key = key
            captured["client"] = self

    import alpaca.trading.client as alpaca_client
    original = alpaca_client.TradingClient
    alpaca_client.TradingClient = _Recorder
    try:
        _make_adapter("alpaca", {"api_key": "k", "api_secret": "s"}, "acct", "practice")
    finally:
        alpaca_client.TradingClient = original

    assert captured.get("raw_data") is False and captured.get("paper") is True
    assert captured["client"]._retry_codes == [429], "the factory's client still retries on 504 (B440)"


def test_an_account_with_NO_cash_REFUSES_rather_than_substituting_equity():
    """**`B377` reproduced by the person who fixed it, and caught here.**

    `balance` fell back to `equity` in my first version of `get_account`. `cash` and `equity` differ
    by exactly the open P&L, so substituting one asserts that it is zero — the sentence I had
    written about CFT an hour earlier. All four of `equity`, `cash`, `buying_power` and
    `last_equity` are `Optional[str]` on `TradeAccount`: B377 four times over on this venue.
    """
    adapter, _ = _adapter(account=_Account(cash=None))
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.get_account())
    assert "cash" in str(exc.value)


@pytest.mark.parametrize("value,expected", [
    ("0.5", Decimal("0.5")),        # Position.qty            -> str
    (0.5, Decimal("0.5")),          # Order.qty               -> float
    (5, Decimal("5")),              # an int, which neither annotation forbids
])
def test_the_coercion_accepts_ALL_THREE_numeric_shapes(value, expected):
    """**Numerics are three shapes and they differ WITHIN a model.** `Position.qty` is `str`;
    `Order.qty` is `Union[str, float, None]`. A `_dec` assuming a string would break on the order
    path while passing every position arm."""
    from app.services.broker.alpaca import _dec

    assert _dec(value, "qty") == expected


# ======================================================================================
# THE TWO SIDE VOCABULARIES — B336/B376's shape with a new surface
# ======================================================================================


@pytest.mark.parametrize("side,expected", [("long", DirectionType.LONG),
                                           ("short", DirectionType.SHORT)])
def test_a_documented_POSITION_side_maps(side, expected):
    adapter, _ = _adapter(positions=[_Position(side=side)])
    assert asyncio.run(adapter.get_positions())[0].direction is expected


@pytest.mark.parametrize("side", ["buy", "sell", "", None, "LONGISH", 0, 1])
def test_an_ORDER_side_is_NOT_accepted_as_a_POSITION_side(side):
    """**A POSITION is long/short; an ORDER is buy/sell.** Two vocabularies for one concept.

    `buy` and `sell` are in this list deliberately: they are perfectly valid *order* sides, and
    accepting one here would be reading one enum with the other's set. `B336` over-matched with
    `endswith` and `B376` under-matched with set membership — **both were the absence of a
    mapping**, and here there are two mappings to keep apart rather than one to get right.
    """
    adapter, _ = _adapter(positions=[_Position(side=side)])
    with pytest.raises(AlpacaSideUnrecognised) as exc:
        asyncio.run(adapter.get_positions())
    assert "not one of" in str(exc.value)


def test_the_two_vocabularies_are_kept_APART_in_the_module():
    """The must-hit control: if one dict were reused for both, the arm above passes vacuously."""
    assert set(POSITION_SIDES) == {"long", "short"}
    assert set(ORDER_SIDES) == {"buy", "sell"}
    assert not set(POSITION_SIDES) & set(ORDER_SIDES), "one vocabulary is serving both concepts"


# ======================================================================================
# COERCION — strings, and inconsistently
# ======================================================================================


@pytest.mark.parametrize("field", ["qty", "avg_entry_price"])
def test_an_UNPARSEABLE_required_number_RAISES_rather_than_becoming_zero(field):
    """`B338`. Alpaca sends numerics as STRINGS, so coercion is unavoidable and this applies from
    the first commit rather than after an incident."""
    raw = _Position()
    setattr(raw, field, "1,234.50")
    adapter, _ = _adapter(positions=[raw])
    with pytest.raises(AlpacaFieldUnreadable) as exc:
        asyncio.run(adapter.get_positions())
    assert field in str(exc.value)


def test_an_ABSENT_pnl_is_DERIVED_and_SAYS_SO_rather_than_becoming_zero():
    """**`B215`, and this line was WRONG when I first wrote it** — `pl if pl is not None else 0`.

    A fabricated zero flows into every P&L sum downstream and nothing marks it. The venue types
    `unrealized_pl` as Optional, so its absence is a fact about the payload; the replacement uses
    only fields the venue DID send and the provenance records which it is.

    **Found by a mechanical sweep for the SHAPE, not by remembering** — I had fixed the
    `cash -> equity` fallback in this same file an hour earlier and did not see these two.
    """
    adapter, _ = _adapter(positions=[
        _Position(unrealized_pl=None, avg_entry_price="100", current_price="110", qty="2"),
    ])
    row = asyncio.run(adapter.get_positions())[0]
    assert row.unrealized_pnl == Decimal("20"), "(110-100)*2 for a long"
    assert row.pnl_source == "derived:(mark-entry)*qty", "a derived number must SAY it is derived"


def test_a_DERIVED_pnl_follows_the_DIRECTION():
    """The must-miss for the derivation: a SHORT gains when the mark FALLS.

    Deriving with the long formula for both would report a profitable short as a loss of the same
    size, and a sign error is not a smaller error than a fabricated zero.
    """
    adapter, _ = _adapter(positions=[
        _Position(side="short", unrealized_pl=None,
                  avg_entry_price="100", current_price="90", qty="2"),
    ])
    assert asyncio.run(adapter.get_positions())[0].unrealized_pnl == Decimal("20")


def test_a_REPORTED_pnl_is_used_and_NOT_recomputed():
    """The control: the venue's own number wins where it exists, and says so."""
    adapter, _ = _adapter(positions=[_Position(unrealized_pl="5.0")])
    row = asyncio.run(adapter.get_positions())[0]
    assert row.unrealized_pnl == Decimal("5.0") and row.pnl_source == "unrealized_pl"


def test_a_position_we_cannot_MARK_is_not_a_position_at_BREAKEVEN():
    """**The worse of the two, in kind.** `current_price` fell back to `entry`, which does not
    default a number — it ASSERTS the position is at breakeven, the most reassuring reading
    available. Our DTO has no value for *unpriceable*, so it refuses."""
    adapter, _ = _adapter(positions=[_Position(current_price=None)])
    with pytest.raises(AlpacaFieldUnreadable) as exc:
        asyncio.run(adapter.get_positions())
    assert "current_price" in str(exc.value)


def test_an_unpriceable_position_can_STILL_BE_CLOSED():
    """`B349`. The refusal above must not reach the kill switch — on a kill switch, refusing to
    act IS leaving every position open."""
    adapter, mock = _adapter(positions=[_Position(current_price=None)])
    report = asyncio.run(adapter.close_all_positions())
    assert [r["disposition"] for r in report] == ["CLOSED"]
    assert len(mock.closed) == 1


def test_spot_crypto_reports_swap_as_None_and_NEVER_zero():
    """Spot crypto charges no swap, so these are STRUCTURALLY absent rather than unread — `B261`'s
    question disappears on this venue rather than being answered. A zero would assert the venue
    charged nothing, which is a different claim from the field not existing."""
    row = asyncio.run(_adapter()[0].get_positions())[0]
    assert row.swap is None and row.commission is None


# ======================================================================================
# equity — B377 at a second venue
# ======================================================================================


def test_an_account_with_NO_equity_REFUSES_rather_than_substituting():
    """`B377`, same field, different venue. `TradeAccount.equity` is OPTIONAL on the model and it
    feeds the prop-firm compliance monitor, where a breach closes the account. Substituting `cash`
    or `portfolio_value` silently asserts that open P&L is zero."""
    adapter, _ = _adapter(account=_Account(equity=None))
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.get_account())
    assert "equity" in str(exc.value)


def test_a_complete_account_still_reads():
    """The control for the arm above — a refusal that never accepts anything is not a fix."""
    account = asyncio.run(_adapter()[0].get_account())
    assert account.equity == 10050.0 and account.balance == 10000.0
    assert account.broker == "alpaca"


# ======================================================================================
# THE ONE WRITE — and the ordering constraint it exists to respect
# ======================================================================================


def test_place_order_REFUSES_A_SHORT_WITH_THE_VENUE_REASON_and_a_LONG_AS_UNIMPLEMENTED():
    """**THIS ARM ASSERTED THE OPPOSITE UNTIL `T-0137` LANDED, AND IT WAS RIGHT BOTH TIMES.**

    It used to pin that BOTH directions refuse IDENTICALLY, and gave the reason: the live loop
    records whatever reason execution hands it, so an adapter refusing shorts before the
    venue-owned reason existed would write **147 records of the wrong shape — worse than none,
    because they look like coverage**. That was a statement about an ORDERING, and the ordering
    has now been discharged: `T-0137` built the reason, so the refusal is safe to make.

    **An arm that pins a phase boundary expires when the phase ends, and the expiry is the
    point** — it is what stopped the next task from being started in the wrong order. This is
    the third in this codebase (`test_unsupported_broker_explains_itself` asserted Alpaca could
    not be constructed at all). Rewritten rather than deleted, because the property worth
    keeping is the one underneath: **the two refusals must not collapse into one.**

    ```
    SHORT  -> DirectionNotSupported   the VENUE cannot take it, ever
    LONG   -> BrokerError naming the member    OUR client cannot answer (part D wrote the body)
    ```

    **AND IT EXPIRED A SECOND TIME, IN THE SAME PLACE.** Part D (`T-0140`) wrote the body, so the
    `NotImplementedError` half is gone — the third row of the table changed while the property did
    not. Twice rewritten, never deleted, because *the two refusals must not collapse* is what was
    worth keeping both times.

    Collapsing them is `B376-B`'s shape and it fails in the expensive direction: a permanent
    venue reason filed against an order Alpaca would happily accept, telling every later reader
    the strategy's longs are unplaceable too.
    """
    adapter, _ = _adapter()

    def _request(direction):
        return OrderRequest(pair="BTC/USD", direction=direction, order_type=OrderType.MARKET,
                            lot_size=0.5, price=None, sl=None, tp=None, client_order_id="x")

    # THE VENUE'S REFUSAL — permanent, and it must not need the client to answer anything.
    # `TradingClientMock` has no `get_asset`, which is exactly the condition under which a
    # direction refusal must still be a direction refusal.
    with pytest.raises(DirectionNotSupported) as short_exc:
        asyncio.run(adapter.place_order(_request(DirectionType.SHORT)))
    assert short_exc.value.reason == ALPACA_CRYPTO_LONG_ONLY.reason
    assert short_exc.value.venue == "alpaca"

    # OUR WIRING'S REFUSAL — a fact about the client, naming the member, and NOT a venue claim.
    with pytest.raises(BrokerError) as long_exc:
        asyncio.run(adapter.place_order(_request(DirectionType.LONG)))
    assert not isinstance(long_exc.value, DirectionNotSupported), (
        "the two refusals collapsed: a LONG is now refused for a reason about the venue"
    )
    assert "not shortable" not in str(long_exc.value)
    assert "get_asset" in str(long_exc.value), (
        "a missing client member must be named, or it reads as a venue outage"
    )


def test_a_PARTIAL_close_is_HONOURED_and_carries_the_size():
    """`T-0038`: honour it or refuse loudly. **Ignoring it is not theoretical here** — the ladder is
    70%-at-2R plus a 30% runner and `crypto_loop.py:1006` passes a size on every partial exit, so
    silently closing everything would liquidate the runner and make the ladder unobservable."""
    adapter, mock = _adapter()
    result = asyncio.run(adapter.close_position("BTC/USD", lot_size=0.3))
    assert result["partial"] is True and result["qty"] == "0.3"
    symbol, options = mock.closed[-1]
    assert symbol == "BTC/USD"
    from decimal import Decimal

    sent = str(getattr(options, "qty", "")) if options is not None else ""
    assert sent and Decimal(sent) == Decimal("0.3"), "the size was dropped on the way to the venue"
    assert "e" not in sent.lower(), f"`B457`: the quantity went out in exponent form: {sent!r}"


def test_a_WHOLE_close_sends_no_size():
    """The must-miss: a fix that always sends a qty would close 100% as a partial."""
    adapter, mock = _adapter()
    result = asyncio.run(adapter.close_position("BTC/USD"))
    assert result["partial"] is False
    assert mock.closed[-1][1] is None


# ======================================================================================
# close_all_positions — the ruled property, third venue
# ======================================================================================


def test_the_close_double_returns_what_the_SDK_ANNOTATES():
    """**`B439`'s guard, read from the SDK at test time rather than named here** (manager): a type written
    into this file records today's SDK and passes silently the day the SDK changes its annotation."""
    import typing

    from alpaca.trading.client import TradingClient

    annotated = typing.get_type_hints(TradingClient.close_position)["return"]
    models = [t for t in typing.get_args(annotated) or (annotated,) if isinstance(t, type)
              and t.__module__.startswith("alpaca.")]
    assert models, f"the SDK's close_position annotation names no alpaca model: {annotated!r}"
    returned = TradingClientMock().close_position("BTC/USD")
    assert isinstance(returned, tuple(models)), (
        f"the double returns {type(returned).__name__}; the SDK annotates {annotated!r}")
    assert "ClosePositionResponse" not in {m.__name__ for m in models}, (
        "the SDK now annotates close_position with the close-ALL response type — re-derive B439")


def test_an_ACCEPTED_close_that_never_FILLS_is_FAILED_not_CLOSED_and_the_loop_CONTINUES():
    """**`B439` + `B427`/`B438` on the kill switch's path.** Driven with real SDK Orders: before, the first
    close raised inside the classifier and every later position was NOT_ATTEMPTED. An accepted close that
    is still accepted when the budget is spent is FAILED WITH A REASON — never CLOSED — and the loop goes on."""
    adapter, mock = _adapter(
        positions=[_Position(symbol=s) for s in ("BTC/USD", "ETH/USD", "LTC/USD")],
        close_status={"BTC/USD": "filled", "ETH/USD": "accepted", "LTC/USD": "filled"},
    )
    report = asyncio.run(adapter.close_all_positions())
    by_pair = {r["pair"]: r for r in report}
    assert [by_pair[p]["disposition"] for p in ("BTC/USD", "ETH/USD", "LTC/USD")] == ["CLOSED", "FAILED", "CLOSED"]
    assert by_pair["ETH/USD"]["status"] == "failed"
    assert "SUBMITTED and NOT CONFIRMED" in by_pair["ETH/USD"]["reason"], by_pair["ETH/USD"]["reason"]
    assert by_pair["ETH/USD"]["close"]["resolution"]["resolved"] is False
    assert by_pair["BTC/USD"]["close"]["close_confirmed"] is True
    assert len(mock.closed) == 3, "the loop did not reach every position"


def test_a_per_position_failure_is_FAILED_and_the_loop_CONTINUES():
    """`B303`, third venue. Abandoning the rest because one timed out would MANUFACTURE
    NOT_ATTEMPTED rows for positions we could have closed."""
    adapter, mock = _adapter(
        positions=[_Position(symbol=s) for s in ("BTC/USD", "ETH/USD", "LTC/USD")],
        close_error={"ETH/USD": TimeoutError("connect timeout")},
    )
    report = asyncio.run(adapter.close_all_positions())
    by_pair = {r["pair"]: r for r in report}
    assert set(by_pair) == {"BTC/USD", "ETH/USD", "LTC/USD"}
    assert by_pair["ETH/USD"]["disposition"] == "FAILED"
    assert "TimeoutError" in by_pair["ETH/USD"]["reason"]
    assert [by_pair[p]["disposition"] for p in ("BTC/USD", "LTC/USD")] == ["CLOSED"] * 2


def test_the_report_survives_an_ABNORMAL_EXIT_and_names_the_in_flight_row():
    """`B337`. The row whose close was already in the air says SENT rather than never-reached."""
    adapter, _ = _adapter(
        positions=[_Position(symbol=s) for s in ("BTC/USD", "ETH/USD", "LTC/USD")],
        close_error={"ETH/USD": asyncio.CancelledError()},
    )
    # `B446` (manager's ruling): a CANCELLATION leaves close_all_positions AS ITSELF, carrying the report. It was
    # converted into a BrokerError, which the manager stepped past; the non-cancellation path is armed in
    # test_b445_b446_kill_switch_report.py.
    with pytest.raises(asyncio.CancelledError) as exc:
        asyncio.run(adapter.close_all_positions())
    rows = {r["pair"]: r for r in exc.value.partial_report}
    assert rows["ETH/USD"]["disposition"] == "FAILED"
    assert "CancelledError" in rows["ETH/USD"]["reason"] and "SENT" in rows["ETH/USD"]["reason"]
    assert rows["LTC/USD"]["disposition"] == "NOT_ATTEMPTED"
    # `B442`: every row's reason names its sweep (manager's ruling 3a); this position was in sweep (a).
    assert rows["LTC/USD"]["reason"] == "[sweep a] the close loop never reached this position"
    assert rows["LTC/USD"]["sweep"] == "a"


def test_it_RAISES_rather_than_reporting_nothing_when_it_cannot_enumerate():
    """Returning `[]` would say *there was nothing to close* — `B292`'s collapse on the kill
    switch's own path."""
    adapter, _ = _adapter(positions=TimeoutError("cannot reach the venue"))
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.close_all_positions())
    assert "could not enumerate" in str(exc.value).lower()


def test_the_close_path_does_NOT_depend_on_the_numeric_coercion():
    """`B349`, ported before it could bite rather than after.

    One unreadable field on one position must not stop the others closing. **On a kill switch,
    refusing to act IS leaving every position open.**
    """
    positions = [_Position(symbol=s) for s in ("BTC/USD", "ETH/USD", "LTC/USD")]
    positions[1].qty = "not-a-number"
    adapter, mock = _adapter(positions=positions)
    report = asyncio.run(adapter.close_all_positions())
    assert [r["disposition"] for r in report] == ["CLOSED"] * 3
    assert len(mock.closed) == 3

    # The must-miss: get_positions STILL refuses that payload. On a FRESH venue — the one above has closed
    # (and, since `B442`'s double models it, no longer lists) every position.
    fresh, _ = _adapter(positions=positions)
    with pytest.raises(AlpacaFieldUnreadable):
        asyncio.run(fresh.get_positions())
