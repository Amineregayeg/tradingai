"""ExecutionService: approved strategy signal -> sized, risk-managed broker order.

This is the piece the engine was missing (place_order had zero callers). It:
  * sizes the position from account equity + risk-% + stop distance,
  * attaches SL/TP,
  * routes through a single MODE GATE (OBSERVE = compute only, PAPER = simulate).

Safety: there is NO real-money mode here. The former ExecMode.LIVE branch was
removed — this service only ever runs against a simulation broker. Real brokers
are reached (if at all) through the broker manager, which is separately guarded
by the is_simulation contract. Mode defaults to PAPER.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from app.core.logging import logger
from app.db.enums import DirectionType, OrderType
from app.services.broker.base import BrokerAdapter, OrderRequest


class ExecMode(str, Enum):
    OBSERVE = "observe"   # compute only, never place (current legacy default)
    PAPER = "paper"       # place against a SIMULATION broker (PaperBroker / SimPropFirmBroker)
    # NOTE: there is deliberately NO LIVE member. This service cannot place a
    # real-money order. Any adapter it receives must be is_simulation=True
    # (asserted in execute()).


@dataclass
class Signal:
    symbol: str
    direction: DirectionType
    entry: float
    sl: float
    #: THE FINAL TARGET, and it is `None` on every signal this engine produces today.
    #:
    #: It used to carry `entry + rr_partial * risk` — the 2R level — as a WHOLE-POSITION take
    #: profit, which is B162: `rr_partial` is the constant that names EXIT-001's PARTIAL, and
    #: spending it here collapsed a two-stage exit into one. Under EXIT-001 that price is the
    #: partial level and is carried in `partial_price`; the 30% runner has NO final target
    #: because TARGET-001 cannot select one, so it terminates on STOP_HIT or SESSION_CLOSE.
    tp: float | None = None
    risk_pct: float = 0.01
    order_type: OrderType = OrderType.MARKET
    approved: bool = False        # must be True for LIVE
    client_order_id: str | None = None
    #: EXIT-001's 2R partial level and the fraction banked there. BOTH or NEITHER.
    #:
    #: **APPENDED AT THE END, DELIBERATELY.** `Signal` is a positional dataclass with callers
    #: that pass `tp` and `risk_pct` positionally; inserting these after `tp` silently re-bound
    #: every one of them — `risk_pct` started arriving as `partial_price` and `order_type` as
    #: `partial_fraction`, which a test caught only because an `OrderType` will not cast to
    #: float. A field added mid-record to a positional structure is a caller-side change wearing
    #: the appearance of an additive one.
    partial_price: float | None = None
    partial_fraction: float | None = None


def size_position(equity: float, risk_pct: float, entry: float, sl: float) -> float:
    """Units = (equity * risk%) / per-unit stop distance. Leverage-independent."""
    risk_per_unit = abs(entry - sl)
    if risk_per_unit <= 0:
        return 0.0
    return (equity * risk_pct) / risk_per_unit


#: Reject a market entry once the market has drifted this far from the price the
#: strategy named, measured in R (drift / intended stop distance).
#:
#: The strategy picks an entry at a structural level (an FVG edge). By the time
#: the bar closes and the order goes in, the market has moved. A small drift is
#: ordinary slippage and is now sized for correctly. A LARGE drift means the
#: setup being filled is not the setup that was analysed — the reward-to-risk has
#: materially changed — and taking it anyway is closer to chasing than trading.
DEFAULT_MAX_ENTRY_DRIFT_R = 0.25


class ExecutionService:
    def __init__(
        self,
        broker: BrokerAdapter,
        mode: ExecMode = ExecMode.PAPER,
        max_entry_drift_r: float = DEFAULT_MAX_ENTRY_DRIFT_R,
    ) -> None:
        self.broker = broker
        self.mode = mode
        self.max_entry_drift_r = max_entry_drift_r

    async def execute(self, sig: Signal) -> dict:
        # HARD SAFETY: this service only ever runs against a simulation broker.
        # A non-simulation adapter here is a programming error, not a runtime
        # condition — fail loud rather than risk a real order.
        if not getattr(self.broker, "is_simulation", False):
            raise RuntimeError(
                "ExecutionService requires a simulation broker "
                f"(is_simulation=True); got {type(self.broker).__name__}"
            )

        acct = await self.broker.get_account()

        # ------------------------------------------------------------------
        # SIZE FROM THE PRICE THIS ORDER WILL ACTUALLY FILL AT.
        #
        # This used to size from `sig.entry` — the FVG edge the strategy named —
        # and then send a MARKET order, which fills at the mark. Whenever the two
        # differed (they almost always do), the position's real risk was not
        # risk_pct: it was risk_pct * |sig.entry - sl| / |fill - sl|. The account
        # silently took more or less than 1% depending on which way the market
        # had drifted, and every R recorded afterwards was measured against a
        # price that was never paid.
        #
        # `risk_pct` is pre-registered and fixed precisely so that risk is a
        # constant. Sizing off a hypothetical price made it a variable.
        # ------------------------------------------------------------------
        sizing_price = sig.entry
        drift_r: float | None = None

        if sig.order_type == OrderType.MARKET:
            mark = await self.broker.reference_price(sig.symbol)
            if mark is None or mark <= 0:
                # Abstain rather than size off a price we know we will not get.
                return {"status": "rejected",
                        "reason": "no reference price available; refusing to size a market order"}

            intended_risk = abs(sig.entry - sig.sl)
            if intended_risk <= 0:
                return {"status": "rejected", "reason": "non-positive size / stop"}

            drift_r = abs(mark - sig.entry) / intended_risk
            if drift_r > self.max_entry_drift_r:
                return {"status": "rejected",
                        "reason": (f"price moved {drift_r:.2f}R from the signal entry "
                                   f"({sig.entry:.2f} -> {mark:.2f}); "
                                   f"limit {self.max_entry_drift_r:.2f}R")}

            # The mark can drift past the stop entirely. Sizing would "succeed"
            # (the distance is still non-zero) and open a position that is
            # already beyond its own stop — a guaranteed instant loss, and on the
            # wrong side, so the trade thesis is dead regardless of distance.
            long = sig.direction == DirectionType.LONG
            if (long and mark <= sig.sl) or (not long and mark >= sig.sl):
                return {"status": "rejected",
                        "reason": (f"market {mark:.2f} is already through the stop {sig.sl:.2f}; "
                                   "the setup is invalidated")}

            sizing_price = mark

        units = size_position(acct.equity, sig.risk_pct, sizing_price, sig.sl)
        if units <= 0:
            return {"status": "rejected", "reason": "non-positive size / stop"}

        if self.mode == ExecMode.OBSERVE:
            return {"status": "observed", "would_size": round(units, 6),
                    "symbol": sig.symbol, "direction": sig.direction.value,
                    "sizing_price": sizing_price, "entry_drift_r": drift_r}

        req = OrderRequest(
            pair=sig.symbol, direction=sig.direction, order_type=sig.order_type,
            lot_size=round(units, 8),
            price=None if sig.order_type == OrderType.MARKET else sig.entry,
            sl=sig.sl, tp=sig.tp,
            client_order_id=sig.client_order_id or f"sig-{uuid.uuid4().hex[:8]}",
        )
        res = await self.broker.place_order(req)
        res.setdefault("status", "FILLED")
        res["mode"] = self.mode.value
        res["sized_units"] = round(units, 8)
        res["equity_at_entry"] = acct.equity
        # What we sized against, and how far the market had already moved.
        #
        # `B281`: this comment used to say **"Both are recorded on the DecisionRecord"** and
        # NEITHER WAS. `T-0084` gives `sizing_price` a column — it is the divisor
        # `size_position` used, and reconstructing a size from `fill` instead is wrong by
        # exactly the slippage (`B280`). **`entry_drift_r` is STILL discarded**, and is filed
        # rather than fixed here: it is a measurement of the market, not an input to the size.
        #
        # *A comment asserting a property the code does not have is `B238`'s class — a reader
        # checking whether the value was persisted found a sentence saying it was.*
        res["sizing_price"] = sizing_price
        res["entry_drift_r"] = drift_r
        # The broker reports the true fill. It should equal sizing_price for
        # these in-process sims, but trust the broker's number, not our estimate.
        fill = res.get("fill")
        if fill is not None:
            res["realized_risk_per_unit"] = abs(float(fill) - sig.sl)
        logger.info(f"ExecutionService[{self.mode.value}] {sig.symbol} {sig.direction.value} "
                    f"units={units:.6f} sized@{sizing_price:.2f} "
                    f"drift={drift_r if drift_r is None else round(drift_r, 3)}R "
                    f"-> {res.get('status')}")
        return res
