"""A market order must be sized from the price it will actually fill at.

THE DEFECT THIS PINS
The strategy picks an entry at a structural level (an FVG edge). The live path
sized the position from that level -- `(equity * risk_pct) / |sig.entry - sl|` --
and then sent a MARKET order, which fills at the mark. Whenever the two differed,
and with a market order they essentially always do, the real risk taken was:

    risk_pct * |sig.entry - sl| / |fill - sl|

So the account quietly risked more or less than 1% depending on which way price
had drifted between the bar close and the order. `risk_pct` is pre-registered and
frozen precisely so risk is a CONSTANT; sizing off a hypothetical price turned it
into a variable that nobody was measuring.

The same fiction propagated into the numbers: realized_r divided pnl by a dollar
risk the account never had, so every R -- and every gap_r the feedback loop reads
-- was off by the fill drift.
"""
from __future__ import annotations

import pytest

from app.db.enums import DirectionType, OrderType
from app.services.broker.base import Account, BrokerAdapter
from app.services.execution.service import (
    DEFAULT_MAX_ENTRY_DRIFT_R,
    ExecMode,
    ExecutionService,
    Signal,
    size_position,
)

EQUITY = 50_000.0
RISK_PCT = 0.01


class FakeBroker(BrokerAdapter):
    """Minimal sim broker: fills at whatever mark it is told to hold."""

    def __init__(self, mark: float | None = 100.0):
        self.mark = mark
        self.orders: list = []

    @property
    def is_simulation(self) -> bool:
        return True

    async def reference_price(self, pair: str) -> float | None:
        return self.mark

    async def get_account(self) -> Account:
        return Account(account_id="test", broker="fake", balance=EQUITY, equity=EQUITY,
                       currency="USD", unrealized_pl=0.0, open_trade_count=0)

    async def place_order(self, request) -> dict:
        self.orders.append(request)
        # Fill at the mark, exactly like PaperBroker/SimPropFirmBroker do.
        return {"status": "FILLED", "fill": float(self.mark), "units": request.lot_size}

    # --- unused abstract surface ---
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def get_positions(self) -> list: return []
    async def get_orders(self, status=None) -> list: return []
    async def get_recent_trades(self, since=None) -> list: return []
    async def close_position(self, position_id, lot_size=None) -> dict: return {}
    async def close_all_positions(self) -> list: return []
    async def stream_prices(self, pairs, callback) -> None: ...


def _sig(entry=100.0, sl=98.0, tp=104.0, direction=DirectionType.LONG) -> Signal:
    return Signal(symbol="BTC/USD", direction=direction, entry=entry, sl=sl, tp=tp,
                  risk_pct=RISK_PCT, order_type=OrderType.MARKET, approved=True)


def _risk_taken(units: float, fill: float, sl: float) -> float:
    """Actual dollars at risk = distance to stop x size."""
    return abs(fill - sl) * units


# ---------------------------------------------------------------------------
# The core property: risk is constant, whatever the market did
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mark", [100.0, 100.3, 99.7, 100.45, 99.55])
async def test_risk_taken_is_always_one_percent(mark):
    """However far the mark has drifted, the position risks exactly risk_pct."""
    broker = FakeBroker(mark=mark)
    res = await ExecutionService(broker).execute(_sig())

    assert res["status"] == "FILLED", res
    risk = _risk_taken(res["sized_units"], res["fill"], 98.0)
    assert risk == pytest.approx(EQUITY * RISK_PCT, rel=1e-6), (
        f"mark {mark}: risked ${risk:.2f}, expected ${EQUITY * RISK_PCT:.2f}"
    )


async def test_old_behaviour_would_have_failed_that():
    """Documents the bug quantitatively rather than in prose.

    Sizing off sig.entry while filling at the mark overshoots risk by exactly the
    ratio of the two stop distances. At a 0.2 drift on a 2.0 stop that is +11%
    more risk than configured -- invisible, and in the account's worst direction.
    """
    entry, sl, mark = 100.0, 98.0, 100.2
    units_old = size_position(EQUITY, RISK_PCT, entry, sl)   # the old, wrong basis
    risk_old = _risk_taken(units_old, mark, sl)              # but filled at the mark
    assert risk_old > EQUITY * RISK_PCT
    assert risk_old / (EQUITY * RISK_PCT) == pytest.approx(2.2 / 2.0, rel=1e-9)

    units_new = size_position(EQUITY, RISK_PCT, mark, sl)    # the fix
    assert _risk_taken(units_new, mark, sl) == pytest.approx(EQUITY * RISK_PCT, rel=1e-9)


async def test_size_changes_with_the_mark():
    """Sanity: a fill closer to the stop must buy MORE units, not the same.

    Both marks are kept inside the drift guard (0.2R of a 2.0 stop); a wider
    spread would simply be refused, which is a different behaviour than the one
    under test here.
    """
    near = await ExecutionService(FakeBroker(mark=99.6)).execute(_sig())   # closer to sl
    far = await ExecutionService(FakeBroker(mark=100.4)).execute(_sig())   # further away
    assert near["status"] == far["status"] == "FILLED"
    assert near["sized_units"] > far["sized_units"]


# ---------------------------------------------------------------------------
# Refusals -- abstain rather than take a different trade than the one analysed
# ---------------------------------------------------------------------------
async def test_rejects_when_price_drifted_too_far():
    # stop distance 2.0, so 0.25R = 0.5. A mark 1.0 away is 0.5R -> refuse.
    res = await ExecutionService(FakeBroker(mark=101.0)).execute(_sig())
    assert res["status"] == "rejected"
    assert "0.50R" in res["reason"]


async def test_accepts_drift_just_inside_the_limit():
    """The guard must not be so tight that ordinary slippage blocks every trade."""
    inside = 100.0 + DEFAULT_MAX_ENTRY_DRIFT_R * 2.0 * 0.99
    res = await ExecutionService(FakeBroker(mark=inside)).execute(_sig())
    assert res["status"] == "FILLED"
    assert res["entry_drift_r"] < DEFAULT_MAX_ENTRY_DRIFT_R


@pytest.mark.parametrize(
    "direction,mark,sl",
    [(DirectionType.LONG, 97.9, 98.0), (DirectionType.SHORT, 102.1, 102.0)],
)
async def test_rejects_when_market_is_already_through_the_stop(direction, mark, sl):
    """A position opened beyond its own stop is a guaranteed instant loss.

    Sizing alone would not catch this: |mark - sl| is still non-zero, so the
    order would size cleanly and open a trade whose thesis is already dead.
    """
    tp = 104.0 if direction == DirectionType.LONG else 96.0
    sig = _sig(entry=100.0, sl=sl, tp=tp, direction=direction)
    svc = ExecutionService(FakeBroker(mark=mark), max_entry_drift_r=99.0)  # drift guard off
    res = await svc.execute(sig)
    assert res["status"] == "rejected"
    assert "through the stop" in res["reason"]


async def test_rejects_when_no_reference_price():
    """Unknown price -> abstain. Never fall back to sizing off the signal price."""
    res = await ExecutionService(FakeBroker(mark=None)).execute(_sig())
    assert res["status"] == "rejected"
    assert "reference price" in res["reason"]


async def test_still_refuses_a_non_simulation_broker():
    """The Tier-0 guarantee must survive this change."""

    class RealMoneyBroker(FakeBroker):
        @property
        def is_simulation(self) -> bool:
            return False

    with pytest.raises(RuntimeError, match="simulation broker"):
        await ExecutionService(RealMoneyBroker()).execute(_sig())


# ---------------------------------------------------------------------------
# What gets reported back
# ---------------------------------------------------------------------------
async def test_result_reports_fill_and_drift_for_the_record():
    res = await ExecutionService(FakeBroker(mark=100.2)).execute(_sig())
    assert res["fill"] == 100.2
    assert res["sizing_price"] == 100.2
    assert res["entry_drift_r"] == pytest.approx(0.1)
    assert res["realized_risk_per_unit"] == pytest.approx(2.2)


async def test_limit_orders_still_size_from_their_own_price():
    """A LIMIT order fills at its stated price, so that price IS the right basis."""
    sig = _sig()
    sig.order_type = OrderType.LIMIT
    broker = FakeBroker(mark=140.0)  # nowhere near; must be ignored for LIMIT
    res = await ExecutionService(broker).execute(sig)
    assert res["status"] == "FILLED"
    assert res["sizing_price"] == 100.0
    assert res["sized_units"] == pytest.approx(size_position(EQUITY, RISK_PCT, 100.0, 98.0))


async def test_observe_mode_places_nothing():
    broker = FakeBroker(mark=100.1)
    res = await ExecutionService(broker, ExecMode.OBSERVE).execute(_sig())
    assert res["status"] == "observed"
    assert broker.orders == [], "OBSERVE mode must not reach the broker"
