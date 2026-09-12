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


class _FailedBody:
    """`FailedClosePositionDetails` — `code` and `message` are REQUIRED on the real model."""

    def __init__(self, code=422, message="insufficient qty"):
        self.code = code
        self.message = message


class _CloseResponse:
    """`ClosePositionResponse`: `body` is an `Order` on success, `FailedClosePositionDetails` on
    failure, alongside an HTTP `status` int. **This venue can express a per-position failure and
    CFT could not** — there I had to record "a partial close would still read as CLOSED" as an
    unclosable gap."""

    def __init__(self, body=None, status=200):
        self.body = body if body is not None else object()
        self.status = status


class TradingClientMock:
    def __init__(self, positions=None, account=None, close_result=None, close_error=None):
        self._positions = positions if positions is not None else [_Position()]
        self._account = account if account is not None else _Account()
        self._close_result = close_result
        self._close_error = close_error or {}
        self.closed: list[tuple] = []

    def get_account(self):
        if isinstance(self._account, Exception):
            raise self._account
        return self._account

    def get_all_positions(self):
        if isinstance(self._positions, Exception):
            raise self._positions
        return list(self._positions)

    def get_orders(self, filter=None):
        return []

    def close_position(self, symbol_or_asset_id, close_options=None):
        self.closed.append((symbol_or_asset_id, close_options))
        err = self._close_error.get(symbol_or_asset_id)
        if err is not None:
            raise err
        return self._close_result if self._close_result is not None else _CloseResponse()


def _adapter(paper: bool = True, **kw) -> tuple[AlpacaAdapter, TradingClientMock]:
    mock = TradingClientMock(**kw)
    return AlpacaAdapter(mock, paper=paper), mock


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
            captured.update(paper=paper, raw_data=raw_data)

    import alpaca.trading.client as alpaca_client
    original = alpaca_client.TradingClient
    alpaca_client.TradingClient = _Recorder
    try:
        _make_adapter("alpaca", {"api_key": "k", "api_secret": "s"}, "acct", "practice")
    finally:
        alpaca_client.TradingClient = original

    assert captured.get("raw_data") is False and captured.get("paper") is True


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
    assert options is not None and str(getattr(options, "qty", "")) == "0.3", (
        "the size was dropped on the way to the venue"
    )


def test_a_WHOLE_close_sends_no_size():
    """The must-miss: a fix that always sends a qty would close 100% as a partial."""
    adapter, mock = _adapter()
    result = asyncio.run(adapter.close_position("BTC/USD"))
    assert result["partial"] is False
    assert mock.closed[-1][1] is None


# ======================================================================================
# close_all_positions — the ruled property, third venue
# ======================================================================================


def test_a_FAILED_close_body_is_reported_FAILED_and_not_CLOSED():
    """**This venue can express a per-position failure and CFT could not.**

    `ClosePositionResponse.body` is `FailedClosePositionDetails` — `code` and `message` — when the
    close failed, and the SDK does NOT raise for it. A row marked CLOSED on the strength of "no
    exception" would state something false, which is `B337`'s shape by a different cause. On CFT I
    had to record that gap as unclosable because its response shape is unobserved.
    """
    adapter, _ = _adapter(
        positions=[_Position(symbol="BTC/USD")],
        close_result=_CloseResponse(body=_FailedBody(code=422, message="insufficient qty")),
    )
    report = asyncio.run(adapter.close_all_positions())
    assert report[0]["disposition"] == "FAILED"
    assert "422" in report[0]["reason"] and "insufficient qty" in report[0]["reason"]


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
    with pytest.raises(BrokerError) as exc:
        asyncio.run(adapter.close_all_positions())
    rows = {r["pair"]: r for r in exc.value.partial_report}
    assert rows["ETH/USD"]["disposition"] == "FAILED"
    assert "CancelledError" in rows["ETH/USD"]["reason"] and "SENT" in rows["ETH/USD"]["reason"]
    assert rows["LTC/USD"]["disposition"] == "NOT_ATTEMPTED"
    assert rows["LTC/USD"]["reason"] == "the close loop never reached this position"


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

    # The must-miss: get_positions STILL refuses that payload.
    with pytest.raises(AlpacaFieldUnreadable):
        asyncio.run(adapter.get_positions())
