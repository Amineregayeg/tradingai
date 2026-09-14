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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from app.core.exceptions import BrokerError, DirectionNotSupported, KillSwitchArmed
# Imported lazily inside the module rather than at package import: `alpaca.py` must stay
# importable without the SDK (`B328`), and it is — the SDK lives inside its methods.
from app.services.broker.alpaca import AlpacaBelowMinimumSize
from app.core.logging import logger, redact_for_storage
from app.db.enums import DirectionType, OrderType
from app.models.decision_record import (
    REJECTION_DEGENERATE_STOP,
    REJECTION_ENTRY_DRIFT,
    REJECTION_NON_POSITIVE_SIZE,
    REJECTION_NO_REFERENCE_PRICE,
    REJECTION_THROUGH_STOP,
    REJECTION_VENUE_DIRECTION_UNSUPPORTED,
    REJECTION_MIN_SIZE,
    REJECTION_VENUE_TRANSPORT,
    REJECTION_KILL_SWITCH_ARMED,
)
from app.services.broker.base import BrokerAdapter, OrderRequest, readable_price
from app.services.execution.reference import ReferencePrice, choose_reference


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
    #: **`T-0144` R11': THE POSITION'S IDENTITY, CHOSEN BEFORE ANYTHING IS WRITTEN OR SENT.** The loop sets it; the
    #: entry's `client_order_id` is derived from it (`client_order_id_for`), and the `DecisionRecord` carries it as its
    #: id. Appended at the end for the reason the two fields above give.
    decision_id: uuid.UUID | None = None
    #: **The pre-send write** (R11', S5): awaited AFTER every refusal that sends nothing and immediately BEFORE
    #: `place_order`, with the request and the sizing facts. It must COMMIT the SUBMITTING record and RAISE on failure;
    #: if it raises, nothing is sent (`NOT_SENT`).
    before_send: "Callable[[OrderRequest, dict], Awaitable[None]] | None" = None


#: `T-0144` R11': the engine's client-order-id prefix. `tai-` + the decision id's full 32 hex = 36 characters, well inside
#: the venue's limit; `B440`'s 32-bit collision residual (`sig-` + 8 hex) ends for the engine's own orders.
ENGINE_CLIENT_ORDER_ID_PREFIX = "tai-"

#: The status `execute` returns when the pre-send write failed and NOTHING was sent. **Not a venue status**: the loop
#: branches on it BEFORE `classify_order_status` (manager's ruling G-5), so the classifier stays total over venue replies.
STATUS_NOT_SENT = "NOT_SENT"


def client_order_id_for(decision_id: uuid.UUID) -> str:
    """The entry's client order id, derived from the decision id — the WHOLE hex, never a slice."""
    return f"{ENGINE_CLIENT_ORDER_ID_PREFIX}{decision_id.hex}"


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
        *,
        binance_mark: "Callable[[str], ReferencePrice | None] | None" = None,
    ) -> None:
        self.broker = broker
        self.mode = mode
        self.max_entry_drift_r = max_entry_drift_r
        #: `T-0144` R3': the loop's live Binance mark for a pair. When given, a market order's reference price is
        #: `reference.choose_reference(mark, venue quote)`; when absent (arms and probes that build this service
        #: directly), the broker's own `reference_price` is used as before.
        self.binance_mark = binance_mark

    async def _reference_price(self, symbol: str) -> ReferencePrice | None:
        """R3': the Binance mark first; the venue's quote mid only when the mark is not usable (no venue call otherwise)."""
        if self.binance_mark is None:
            price = await self.broker.reference_price(symbol)
            return None if price is None else ReferencePrice(price=price, source="broker_reference_price",
                                                             at=datetime.now(timezone.utc))
        mark = self.binance_mark(symbol)
        chosen = choose_reference(mark, None)
        if chosen is not None:
            return chosen
        reference_quote = getattr(self.broker, "reference_quote", None)
        if reference_quote is not None:
            # a VENUE declares its quote: the fallback is that quote's mid inside its age bound, and nothing else
            return choose_reference(None, await reference_quote(symbol))
        # a SIMULATOR declares no quote: its own `reference_price` is the mark it fills at, derived from the same feed
        price = await self.broker.reference_price(symbol)
        return None if price is None else ReferencePrice(price=price, source="broker_reference_price",
                                                         at=datetime.now(timezone.utc))

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

        reference: ReferencePrice | None = None
        if sig.order_type == OrderType.MARKET:
            reference = await self._reference_price(sig.symbol)
            mark = reference.price if reference is not None else None
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

        # ------------------------------------------------------------------
        # `T-0144` R6': A VENUE'S MINIMUM ENTRY NOTIONAL, PRICED BY THE REFERENCE PRICE.
        #
        # Asked of the adapter (`min_entry_notional_usd`), never keyed on its name: Alpaca refuses an OPENING order under
        # $10 of cost basis (403 "minimal amount of order 10", `B451`), and the engine requires $11 so a mark that moves
        # between sizing and the fill does not cross it. The simulators declare none. Closes and partials never come
        # through `execute`, so they are exempt by construction (measured: a $4.49 close filled).
        # ------------------------------------------------------------------
        min_notional = getattr(self.broker, "min_entry_notional_usd", None)
        if isinstance(min_notional, (int, float)) and not isinstance(min_notional, bool) and reference is not None:
            notional = lot_size * reference.price
            if notional < min_notional:
                return {"status": "rejected",
                        "rejection_code": REJECTION_MIN_SIZE,
                        "reason": (f"entry notional ${notional:.2f} ({lot_size} x {reference.price:.2f}, "
                                   f"{reference.source}) is under the venue minimum the engine enforces, "
                                   f"${float(min_notional):.2f} (venue: 'minimal amount of order 10', B451)"),
                        "pair": sig.symbol, "direction": sig.direction.value,
                        "sized_units": lot_size, "equity_at_entry": acct.equity,
                        "reference_source": reference.source}

        decision_id = getattr(sig, "decision_id", None)
        req = OrderRequest(
            pair=sig.symbol, direction=sig.direction, order_type=sig.order_type,
            lot_size=lot_size,
            price=None if sig.order_type == OrderType.MARKET else sig.entry,
            sl=sig.sl, tp=sig.tp,
            client_order_id=(client_order_id_for(decision_id) if decision_id is not None
                             else sig.client_order_id or f"sig-{uuid.uuid4().hex[:8]}"),
        )
        # ------------------------------------------------------------------
        # `T-0144` R11' / S5: THE PRE-SEND WRITE, AFTER EVERY REFUSAL THAT SENDS NOTHING AND IMMEDIATELY BEFORE THE SEND.
        #
        # The identity must exist durably before the order can: a crash after the send leaves a SUBMITTING record the
        # next boot resolves by its client id. **A write that fails means NOTHING IS SENT** — no identity, no send — and
        # the result says so as `NOT_SENT`, which is not a venue status and never reaches the classifier.
        # ------------------------------------------------------------------
        before_send = getattr(sig, "before_send", None)
        if before_send is not None:
            sizing = {"sized_units": lot_size, "sizing_price": sizing_price, "equity_at_entry": acct.equity,
                      "entry_drift_r": drift_r,
                      "reference_source": reference.source if reference is not None else None}
            try:
                await before_send(req, sizing)
            except Exception as exc:  # noqa: BLE001 - ANY failure of the pre-send write refuses the send
                detail = redact_for_storage(f"{type(exc).__name__}: {exc}")
                logger.error(
                    "ExecutionService: the pre-send record could not be written, so NOTHING was sent",
                    symbol=sig.symbol, direction=sig.direction.value, decision_id=str(decision_id),
                    client_order_id=req.client_order_id, error=detail,
                )
                return {"status": STATUS_NOT_SENT,
                        "reason": f"pre-send record failed: {detail}",
                        "pair": sig.symbol, "direction": sig.direction.value,
                        "decision_id": str(decision_id), "client_order_id": req.client_order_id,
                        "sized_units": lot_size, "equity_at_entry": acct.equity}
        try:
            res = await self.broker.place_order(req)
        except KillSwitchArmed as exc:
            # `B442`: THE KILL SWITCH, READ AT THE SEND. The loop's gate read it before suspending for data;
            # every adapter the loop binds reads it again at submission and raises this, having sent NOTHING.
            # It is a `ComplianceError`, not a `BrokerError` — so no clause below would catch it, and it
            # would escape to the loop's venue-raised backstop and be filed `VENUE_RAISED` (review's K2-7).
            # The mapping's EXISTENCE is what matters; it is first only so a reader meets it first.
            logger.warning(
                "ExecutionService: entry REFUSED at submission, the kill switch is armed; nothing was sent",
                mode=self.mode.value, symbol=sig.symbol, direction=sig.direction.value,
                client_order_id=req.client_order_id, reason=str(exc),
            )
            return {"status": "REJECTED", "reason": str(exc),
                    "rejection_code": REJECTION_KILL_SWITCH_ARMED,
                    "pair": sig.symbol, "direction": sig.direction.value,
                    "client_order_id": req.client_order_id,
                    "sized_units": round(units, 8), "equity_at_entry": acct.equity}
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
        except AlpacaBelowMinimumSize as exc:
            # ------------------------------------------------------------------
            # `MIN_SIZE` — THE VENUE'S FLOOR, AND IT MUST BE CAUGHT BEFORE `BrokerError`.
            #
            # `AlpacaBelowMinimumSize` subclasses `BrokerError`, so ORDER MATTERS exactly as it
            # does for `DirectionNotSupported` above: reversed, every sub-minimum order would be
            # filed as `VENUE_TRANSPORT` — a transient failure that clears on its own — when it
            # is a deterministic size floor that will refuse the same order every time. `B375` in
            # a third place.
            #
            # DISTINCT FROM `NON_POSITIVE_SIZE` too: that is `lot_size <= 0`, arithmetic on our
            # side. This is a well-formed order the venue will not take, and the minimum moves
            # with price (~$1 of notional, `T-0139`), so the same size can be refused today and
            # accepted tomorrow. Two causes, two remedies.
            # ------------------------------------------------------------------
            logger.info(f"ExecutionService[{self.mode.value}] {sig.symbol} "
                        f"{sig.direction.value} below the venue minimum: "
                        f"{exc.requested} < {exc.minimum}")
            return {"status": "REJECTED",
                    "reason": redact_for_storage(str(exc)),
                    "rejection_code": REJECTION_MIN_SIZE,
                    "pair": sig.symbol, "direction": sig.direction.value,
                    "venue": getattr(exc, "broker", None),
                    "requested_units": float(exc.requested),
                    "min_order_size": float(exc.minimum),
                    "sized_units": lot_size, "equity_at_entry": acct.equity}
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
        # **`T-0130` (`B316`/`B317`). NO DEFAULT STATUS — ABSENT STAYS ABSENT.**
        #
        # This line was `res.setdefault("status", "FILLED")`, applied to whatever `place_order`
        # returned. An adapter whose reply carried no status — an empty 200, which
        # `CryptoFundTraderAdapter._handle_response` turns into `{}`, or any return site that forgot
        # the key — was reported as a FILL. Measured at `34d4d03`: `{}` became `FILLED` with no
        # size and halted the loop as a *partial fill we could not size* that never happened; a
        # status-less reply that did carry `units` opened a position.
        #
        # A better default is not the fix: every value is one of the answers the caller exists to
        # tell apart. So the key is left absent and `crypto_loop` classifies absence as UNRESOLVED
        # — neither a fill nor a refusal — and halts on it (`_on_unresolved_order`).
        #
        # **AND A RESULT THAT IS NOT A DICT AT ALL IS THE SAME UNREADABLE REPLY** (review's K-4, ruled
        # in scope). `_handle_response` returns `response.json()` for any parseable body, so a 200 of
        # `null`, `[]` or `"ok"` comes back as `None`, a list or a str. The next line then raised
        # TypeError outside the `try` above, and the loop's venue-raised backstop filed a REJECTED row
        # for an order the venue may have taken — this task's defect by the exception route. No status
        # is invented here; the bounded, redacted repr is the only raw text kept.
        if not isinstance(res, dict):
            res = {"unreadable_result": redact_for_storage(f"{type(res).__name__}: {res!r}")}
        # **`B433` (FU-1b). THE FILL PRICE IS NORMALISED HERE, FOR EVERY PRODUCER.** Below, this read
        # `if fill is not None: abs(float(fill) - sig.sl)` — guarding `None` and nothing else, so a
        # forwarded "garbage" raised AFTER placement into the loop's venue-raised backstop (a false
        # refusal, `K-4b`'s class) and 0.0, NaN and negatives were computed from as prices. Only the
        # simulators and Alpaca can hold this slot today; relying on that is `B430`'s shape (safe by one
        # constructor argument), so every consumer downstream sees a positive float or `None` BY
        # CONSTRUCTION. The key's PRESENCE is kept: present-unreadable and absent stay distinct.
        if "fill" in res:
            res["fill"] = readable_price(res["fill"])
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
        # R3': what the size was computed against, BY NAME (a Binance mark, a venue quote mid, or the broker's own).
        res["reference_source"] = reference.source if reference is not None else None
        res["reference_at"] = reference.at.isoformat() if reference is not None else None
        # The broker reports the true fill. It should equal sizing_price for
        # these in-process sims, but trust the broker's number, not our estimate.
        fill = res.get("fill")          # a positive finite float or None — normalised above (B433)
        if fill is not None:
            res["realized_risk_per_unit"] = abs(fill - sig.sl)
        logger.info(f"ExecutionService[{self.mode.value}] {sig.symbol} {sig.direction.value} "
                    f"units={units:.6f} sized@{sizing_price:.2f} "
                    f"drift={drift_r if drift_r is None else round(drift_r, 3)}R "
                    f"-> {res.get('status')}")
        return res
