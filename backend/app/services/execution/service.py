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

from app.core.exceptions import BrokerError, DirectionNotSupported
from app.core.logging import logger, redact_for_storage
from app.db.enums import DirectionType, OrderType
from app.models.decision_record import (
    REJECTION_DEGENERATE_STOP,
    REJECTION_ENTRY_DRIFT,
    REJECTION_NON_POSITIVE_SIZE,
    REJECTION_NO_REFERENCE_PRICE,
    REJECTION_THROUGH_STOP,
    REJECTION_VENUE_DIRECTION_UNSUPPORTED,
    REJECTION_VENUE_TRANSPORT,
)
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
                        "rejection_code": REJECTION_NO_REFERENCE_PRICE,
                        "reason": "no reference price available; refusing to size a market order"}

            intended_risk = abs(sig.entry - sig.sl)
            if intended_risk <= 0:
                # DEGENERATE_STOP, not NON_POSITIVE_SIZE. The string below is byte-identical to
                # the one at the sizing guard, and the two are different decisions with opposite
                # remedies: this is `entry == sl` — a STRATEGY DEFECT — while the other is equity
                # against stop width. The prose cannot separate them; the code must.
                return {"status": "rejected",
                        "rejection_code": REJECTION_DEGENERATE_STOP,
                        "reason": "non-positive size / stop"}

            drift_r = abs(mark - sig.entry) / intended_risk
            if drift_r > self.max_entry_drift_r:
                return {"status": "rejected",
                        "rejection_code": REJECTION_ENTRY_DRIFT,
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
                        "rejection_code": REJECTION_THROUGH_STOP,
                        "reason": (f"market {mark:.2f} is already through the stop {sig.sl:.2f}; "
                                   "the setup is invalidated")}

            sizing_price = mark

        units = size_position(acct.equity, sig.risk_pct, sizing_price, sig.sl)

        # **THE GUARD MUST TEST WHAT IS ACTUALLY PASSED, NOT WHAT WAS COMPUTED.**
        #
        # This read `if units <= 0` while the order below sends `round(units, 8)`, so a value in
        # `(0, 5e-9)` passed the check and arrived at the broker as `0.0` — where both running
        # simulators raise `ValueError("lot_size must be > 0")`, the bar aborts, and **no row is
        # written at all** (`B403`). Measured: a stop distance of 1e12 on a 70k instrument gives
        # `units=5e-11`, `units > 0` True, `round(units, 8)` 0.0.
        #
        # That takes a corrupt signal rather than a market condition, so it is rare — **which is
        # exactly why the record matters**: nobody reconstructs a 1e12 stop from a log line six
        # weeks later. Rounding first makes the guard and the argument agree.
        lot_size = round(units, 8)
        if lot_size <= 0:
            return {"status": "rejected",
                    "rejection_code": REJECTION_NON_POSITIVE_SIZE,
                    "reason": "non-positive size / stop"}

        if self.mode == ExecMode.OBSERVE:
            # ----------------------------------------------------------------
            # THE LONG-ONLY PROPERTY IS `PAPER`-SCOPED, AND THIS IS WHERE THE SCOPE COMES FROM.
            #
            # This returns ABOVE `place_order`, so in OBSERVE a SHORT is neither sent nor
            # refused — it is reported as *observed*, with a size. **Recording a venue refusal
            # here would record an event that did not occur** (the manager's ruling, and it is
            # `B215`'s shape: a value nobody observed written as though someone had).
            #
            # BUT SILENCE IS THE OTHER FAILURE. *Observed* and *refused by the venue* are the
            # two readings this property exists to keep apart, and an OBSERVE row that says
            # "would size 0.42 units SHORT" and nothing else reads as a trade the engine would
            # have taken. So the venue's capability is stated as the COUNTERFACTUAL it is:
            # `venue_would_refuse` is the reason the venue WOULD have given, or `None`. It
            # asserts nothing about what happened, because nothing happened.
            # ----------------------------------------------------------------
            policy = getattr(self.broker, "direction_policy", None)
            return {"status": "observed", "would_size": round(units, 6),
                    "symbol": sig.symbol, "direction": sig.direction.value,
                    "sizing_price": sizing_price, "entry_drift_r": drift_r,
                    "venue_would_refuse": (
                        None if policy is None else policy.refusal(sig.direction)
                    )}

        req = OrderRequest(
            pair=sig.symbol, direction=sig.direction, order_type=sig.order_type,
            lot_size=lot_size,
            price=None if sig.order_type == OrderType.MARKET else sig.entry,
            sl=sig.sl, tp=sig.tp,
            client_order_id=sig.client_order_id or f"sig-{uuid.uuid4().hex[:8]}",
        )
        try:
            res = await self.broker.place_order(req)
        except DirectionNotSupported as exc:
            # A VENUE CAPABILITY REFUSAL IS A RESULT, NOT AN ERROR — so it is turned back into
            # the rejection shape every other refusal on this path already uses, and the
            # venue's own sentence is carried through UNALTERED into
            # `DecisionRecord.rejection_reason` (`crypto_loop.py:1553`).
            #
            # **Only this type is caught.** Widening it to `BrokerError` would fold a network
            # failure into "the venue refused", which is the exact confusion the dedicated type
            # exists to prevent — and it would file a permanent-sounding reason for a condition
            # that clears on its own.
            #
            # THE IN-PROCESS SIMULATORS DO NOT REACH HERE: they return the rejection dict
            # directly, because a raise would abort the bar (the loop has no handler around
            # this call). This branch is for an adapter that RAISES — `AlpacaAdapter` does, as
            # it has no fill to describe for an order it never sent — and `ExecutionService`
            # accepts any adapter reporting `is_simulation=True`, which an Alpaca paper client
            # does truthfully.
            logger.info(f"ExecutionService[{self.mode.value}] {sig.symbol} "
                        f"{sig.direction.value} refused by {exc.venue}: {exc.reason}")
            return {"status": "REJECTED", "reason": exc.reason,
                    "rejection_code": REJECTION_VENUE_DIRECTION_UNSUPPORTED,
                    "pair": sig.symbol, "direction": exc.direction,
                    "venue": exc.venue,
                    "sized_units": round(units, 8), "equity_at_entry": acct.equity}
        except BrokerError as exc:
            # ------------------------------------------------------------------
            # `B403`'s TRANSPORT HALF. THE VENUE WAS REACHED AND FAILED.
            #
            # Only `DirectionNotSupported` was caught here, so a connection error, an auth
            # rejection, a rate limit or a 5xx **propagated, aborted the bar before
            # `_record_rejected_signal` ran, and became one log line.** Part 3 built the
            # vocabulary; this is the catch that uses it.
            #
            # **A DISTINCT CODE, NOT THE VENUE-RULE ONE**, and that is the whole point: `B375` is
            # a permanent rule made indistinguishable from a transient failure, and folding a 5xx
            # into `VENUE_DIRECTION_UNSUPPORTED` would rebuild that confusion *inside the field
            # built to prevent it*. One will refuse the same order forever; the other clears on
            # its own, and they demand opposite responses.
            #
            # NARROW BY TYPE, not by message. `BrokerError` is the venue's own family — a message
            # match would key the classification on prose the venue chose, which is exactly what
            # `rejection_code` exists to stop. Anything OUTSIDE that family still raises and is
            # recorded by `_tick_symbol` as `VENUE_RAISED`, unclassified rather than guessed at.
            #
            # `DirectionNotSupported` subclasses `BrokerError`, so ORDER MATTERS: it is caught
            # above and can never reach here. Reversed, every venue rule would be filed as
            # transport and the permanent condition would look retryable.
            # ------------------------------------------------------------------
            # ------------------------------------------------------------------
            # THE MESSAGE IS REDACTED AND BOUNDED BEFORE IT IS PERSISTED.
            #
            # `reason` lands in `DecisionRecord.rejection_reason` — a DATABASE COLUMN — and the
            # loguru secrets filter does not run there: it sits on the way to a log sink, and a
            # value written to a column never passes through it. An SDK error can carry request
            # headers, a URL with query parameters, or a response body, so the venue's own text
            # would reach a table nothing redacts, in rows that outlive every log rotation.
            #
            # **THE TYPE IS THE PRIMARY FACT AND THE MESSAGE IS SECONDARY**, deliberately: the
            # pattern list behind `redact_for_storage` is an allow-list of shapes someone thought
            # of and cannot recognise a credential format nobody added. A name like
            # `BrokerConnectionError` diagnoses most of what this row is for and can carry
            # nothing.
            #
            # Raised by review while Malek was generating an Alpaca key and secret — the window
            # in which this would have mattered was open at the time the code was written.
            # ------------------------------------------------------------------
            detail = redact_for_storage(str(exc))
            logger.warning(f"ExecutionService[{self.mode.value}] {sig.symbol} "
                           f"{sig.direction.value} — venue error: "
                           f"{type(exc).__name__}: {detail}")
            return {"status": "REJECTED",
                    "reason": f"{type(exc).__name__}: {detail}",
                    "rejection_code": REJECTION_VENUE_TRANSPORT,
                    "pair": sig.symbol, "direction": sig.direction.value,
                    "venue": getattr(exc, "broker", None),
                    "sized_units": lot_size, "equity_at_entry": acct.equity}
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
