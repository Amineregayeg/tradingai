"""Abstract broker adapter base class."""
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from app.core.exceptions import DirectionNotSupported
from app.db.enums import DirectionType, OrderType
from app.schemas.broker import Position


def readable_quantity(raw) -> float | None:
    """A venue QUANTITY as a finite float, or `None` when it cannot be read.

    **WHAT IT CATCHES, EXACTLY** — no broader claim: `None`, a bool, a blank string, and anything whose
    `float()` raises TypeError, ValueError or OverflowError all return `None`; a non-finite result returns
    `None`. That covers every value `json.loads` can produce. An arbitrary object whose `__float__` raises
    some OTHER exception would still propagate — a venue reply cannot carry one, so it is stated, not guarded.

    The ONE decision about whether a venue number is readable (`B426`: one rule, not a copy per
    consumer). Absent, blank, unparseable and non-finite are all UNREADABLE; **zero is a reading** —
    nothing filled. `float("nan")` and `float("inf")` (and `"1e999"`) parse WITHOUT raising, which is
    why they are tested for explicitly rather than left to an `except`.

    **Two holes the first version had, both in the function written to end `K-4b`'s class** (review's
    finding on `b4e6e1f`, extended by the manager):

        a bool      `isinstance(True, int)` is True, so `True` read as 1.0 — a JSON `true` in filled_qty
                    would record a fill of ONE WHOLE UNIT, and `False` a confident "nothing filled".
                    A bool is not a number; it is rejected BEFORE any numeric handling.
        a huge int  `json.loads` of a 401-digit number is an int, and `float()` of it raises
                    OverflowError, which `except (TypeError, ValueError)` did not catch — so the
                    "never raises" claim was false for an input a venue reply can carry. The SAME digits
                    as a STRING go through `float()` to inf and then to `None`, so only the int form
                    raised — which is why an arm feeding strings could never have found it.

    Lives here, in the broker contract, because two layers need it and neither should import the
    other: `AlpacaAdapter.place_order` (`filled_units`, and the stored refusal's `_qty_token`) and
    `ExecutionService`, which normalises what ANY producer returns (`B433`).
    """
    if raw is None or isinstance(raw, bool) or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    return value


def readable_price(raw) -> float | None:
    """A venue PRICE as a positive finite float, or `None` when there is no usable price.

    Catches exactly what `readable_quantity` catches — it delegates the parse, and so the bool and
    overflow rules — and additionally returns `None` for a price at or below zero.

    The parse is `readable_quantity`'s; **the zero rule is per field, and reusing it blindly is `B426`'s
    lesson** (manager's correction to `B433`):

        filled quantity  0     a READING — nothing filled
        fill price      <= 0   NOT A PRICE — `None`

    The consumers are why (measured by review): `ExecutionService`'s `realized_risk_per_unit`,
    `_record_signal_decision`'s basis and `expected_r`, and the settle path's entry all use the fill
    whenever it is not `None` — so a `0.0` computes against an entry of ZERO, and NaN poisons all three.
    """
    value = readable_quantity(raw)
    return value if value is not None and value > 0 else None


@dataclass
class Account:
    """Normalised broker account summary."""

    account_id: str
    broker: str
    balance: float
    equity: float
    currency: str
    margin_used: float = 0.0
    margin_available: float = 0.0
    open_trade_count: int = 0
    unrealized_pl: float = 0.0

    #: WHICH key the venue's account payload carried `unrealized_pl` under, or `None` if it
    #: carried none (`B377`). The sibling of `Position.pnl_source`: `T-0114` gave the position
    #: field its provenance and left the account field twelve lines above it with a silent
    #: `profit` -> `netProfit` fallback, and those are not the same quantity (`B286`).
    unrealized_pl_source: str | None = None


@dataclass(frozen=True)
class DirectionPolicy:
    """WHICH DIRECTIONS A VENUE CAN TAKE, and the venue's own words for why not.

    Malek ruled 2026-09-10 that the platform trades **LONG ONLY**, because Alpaca crypto is
    non-marginable and not shortable. That is a fact about the VENUE, so it is expressed as one
    rather than as a flag on the strategy or a branch in the loop.

    **THIS OBJECT EXISTS SO THE SIMULATOR CAN BE WRONG THE SAME WAY THE VENUE IS.** The live
    loop does not execute against `AlpacaAdapter` — it executes against `PaperBroker` or
    `SimPropFirmBroker` (`crypto_loop.py:168`, `:794`) — so a refusal implemented only in the
    Alpaca module would never fire in a paper run, and 147 shorts would go on filling in
    simulation against a venue that cannot take one of them. *A simulator that permits what the
    venue forbids is not a simulation of that venue*, which is `paper.py`'s own `lot_size`
    lesson with the direction substituted for the size.

    `reason` IS THE VENUE'S AND MUST NAME THE CONSTRAINT. It is carried, unaltered, all the way
    into `DecisionRecord.rejection_reason`. A reason that merely restates the refusal
    (*"order rejected"*) makes a permanent venue rule indistinguishable from a transient
    failure, and 147 records of that shape are worse than none because they look like coverage.
    """

    venue: str
    supported: frozenset[DirectionType]
    reason: str

    def refusal(self, direction: DirectionType) -> str | None:
        """The venue's reason for refusing `direction`, or `None` if it can take it.

        Returns rather than raises because the two callers need different shapes and BOTH are
        correct: an in-process simulator answers with a rejection dict (the shape `cft_sim`
        already uses for a halted account), and a remote adapter raises, because it has no fill
        to describe for an order it never sent.
        """
        if direction in self.supported:
            return None
        return self.reason

    def enforce(self, direction: DirectionType) -> None:
        """Raise `DirectionNotSupported` if the venue cannot take this direction."""
        reason = self.refusal(direction)
        if reason is not None:
            raise DirectionNotSupported(
                venue=self.venue, direction=direction.value, reason=reason
            )


@dataclass
class OrderRequest:
    """Broker-agnostic order request."""

    pair: str
    direction: DirectionType
    order_type: OrderType
    lot_size: float
    price: float | None = None  # None for MARKET orders
    sl: float | None = None
    tp: float | None = None
    client_order_id: str | None = None


class BrokerAdapter(ABC):
    """Abstract base class every broker integration must implement."""

    broker_name: str = "unknown"

    # ------------------------------------------------------------------
    # THE KILL-SWITCH DISPOSITION VOCABULARY — Malek's ruled property, 2026-08-31
    # ------------------------------------------------------------------
    # > Every position open when the switch was pulled must be reported as CLOSED,
    # > FAILED WITH A REASON, or NOT ATTEMPTED. A position in none of those three
    # > states is a bug by construction.
    #
    # HERE RATHER THAN ON EACH ADAPTER, and `T-0132` is why. These were defined on
    # `MetaTrader5Adapter` alone, so bringing CFT to the same property meant either a
    # second copy of three string literals or an import from one venue's module into
    # another's. **A ruled property that lives in one implementation is a property of
    # that implementation** — `B184` waiting to happen, since two copies of a
    # vocabulary drift and the consumer (`kill_switch.py`) reads only strings.
    #
    # FAILED IS "FAILED WITH A REASON", and the reason clause is PART of the ruled
    # state rather than decoration: it is where *outcome unknown* belongs, which is
    # what makes three states sufficient and why no fourth disposition exists
    # (`B337`, ruled by the manager 2026-09-05).
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"

    #: The most recent `close_all_positions` report, published BEFORE that member's loop runs so a
    #: partial record survives an abnormal exit (`B303`). `None` until the switch is pulled.
    #: **On the base class for the same reason as the vocabulary above**: two adapters now satisfy
    #: the ruled property and a caller reading the record should not have to know which venue it
    #: is talking to.
    last_close_all_report: dict[str, dict] | None = None

    # Instruments this broker should stream by default. Empty ⇒ use the caller's
    # requested list. Lets a crypto broker (CFT) stream crypto while a forex
    # broker (OANDA) streams the forex pairs passed in from startup.
    default_pairs: list[str] = []

    #: The venue's direction capability, or `None` for a venue that takes both.
    #:
    #: **ON THE BASE CLASS FOR THE KILL-SWITCH VOCABULARY'S REASON**, one paragraph up: a ruled
    #: property that lives in one implementation is a property of that implementation. The
    #: consumer here is `ExecutionService`, which holds a `BrokerAdapter` and must not have to
    #: know which venue it received.
    #:
    #: `None` is the honest default rather than "both directions": an adapter that has never
    #: been asked the question has not answered it, and defaulting to a permissive *policy
    #: object* would let a venue with a real constraint pass as one that had declared it has
    #: none. Nothing reads this without a `None` check.
    direction_policy: "DirectionPolicy | None" = None

    # ------------------------------------------------------------------
    # Simulation contract (SAFETY)
    # ------------------------------------------------------------------
    # Every adapter MUST declare whether it is a simulation. There is NO default:
    # a subclass that forgets to implement this cannot be instantiated (abstract),
    # so a new real-money adapter can never silently pass as safe.
    #
    # `ExecutionService` refuses to send writes to a non-simulation adapter
    # (`execution/service.py:96`). THE KILL SWITCH AND POSITION-CLOSE ROUTING DO NOT
    # CHECK THIS — closing is the safe direction and is deliberately unguarded.
    # See `T-0067`/`B238`.
    #
    # THIS SENTENCE USED TO NAME ALL THREE AS ENFORCING, AND TWO OF THEM DO NOT.
    # `close_all_positions` (`manager.py`) and `DELETE /positions/{id}`
    # (`api/routers/positions.py`) never read this flag. The claim was load-bearing
    # in the wrong direction: a reader checking whether the close path was guarded
    # found a contract saying it was.
    #
    # THE SCOPE IS RECORDED WITH ITS REASON, AND THE REASON IS THE LOAD-BEARING HALF.
    # A scope note without one rots into the next `B238`: the next seat reads
    # "does not check" as an oversight and closes it. It is not an oversight. A kill
    # switch that REFUSES to close a real position is `B221` with a different report
    # — "reports refusal, closes nothing" against "reports success, closes nothing"
    # — and it would fire exactly when a real book is the thing you most want flat.
    #
    # AND A REFUSAL HERE WOULD BE KEYED ON THE WRONG FLAG (`B241`). `is_simulation`
    # describes the VENUE; `observe_only` (`manager.py:44-50`, forced True unless
    # `ALLOW_LIVE_TRADING` is set) is the WRITE GATE. They have come apart, so the
    # registerable non-simulation adapter is one that cannot write anyway.
    #
    # NOT HYPOTHETICAL: one such adapter is REGISTERED RIGHT NOW. `broker_connections`
    # holds a single row — `cryptofundtrader`, `environment: live`, `connected: true`
    # — and `main.py:216` loads it into `_adapters` at startup, where
    # `close_all_positions` iterates it. Measured 2026-08-24, not reasoned.
    @property
    @abstractmethod
    def is_simulation(self) -> bool:
        """True iff this adapter can never place a real-money order."""
        ...

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Open connection and validate credentials."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close all open connections gracefully."""
        ...

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_account(self) -> Account:
        """Return current account summary."""
        ...

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""
        ...

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_orders(self, status: str | None = None) -> list[dict]:
        """Return pending / historical orders.

        Args:
            status: Optional filter (e.g. ``"PENDING"``). Broker-specific values.
        """
        ...

    # ------------------------------------------------------------------
    # Trade history
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_recent_trades(self, since: datetime | None = None) -> list[dict]:
        """Return recently closed trades.

        Args:
            since: Only return trades closed after this timestamp.
        """
        ...

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> dict:
        """Place a new order and return the broker response."""
        ...

    @abstractmethod
    async def close_position(
        self,
        position_id: str,
        lot_size: float | None = None,
    ) -> dict:
        """Close an open position.

        Args:
            position_id: Broker instrument identifier (e.g. ``"EUR_USD"``).
            lot_size: Partial close volume.  ``None`` means close all units.
        """
        ...

    @abstractmethod
    async def close_all_positions(self) -> list[dict]:
        """Close every open position.  Returns list of per-position results."""
        ...

    # ------------------------------------------------------------------
    # Price streaming
    # ------------------------------------------------------------------

    @abstractmethod
    async def stream_prices(
        self,
        pairs: list[str],
        callback: Callable,
    ) -> None:
        """Stream live price ticks.

        Args:
            pairs: List of instrument identifiers.
            callback: Async or sync callable called with each price tick dict.
        """
        ...

    # ------------------------------------------------------------------
    @property
    def simulation_source(self) -> str:
        """WHERE `is_simulation`'s answer CAME FROM. Every adapter must say (`B395`).

        `is_simulation` gates all execution. For a remote venue the adapter can VERIFY it
        against the client's real endpoint; when that endpoint cannot be read the flag is
        believed rather than confirmed — **and that is the only state worth surfacing**,
        because it is exactly the case where nothing refused.

        **THIS RAISES INSTEAD OF RETURNING A DEFAULT, AND THAT IS THE WHOLE POINT.** The first
        version read `getattr(broker, "simulation_source", "in-process ...")`, so every way of
        LOSING the value — a rename, a refactor, a wrapper that does not forward it — resolved
        to the most reassuring sentence in the vocabulary. **Absence rendered as health.**

        > When a fallback is one of the states a field exists to distinguish, the field cannot
        > report its own failure. If a default is unavoidable it must be the ALARMING state,
        > never the benign one.

        **Declared HERE rather than only on the subclasses so the proxy contract arm can
        ENUMERATE it.** Found by running that arm rather than trusting it: the member lived only
        on `AlpacaAdapter`, so a check over `BrokerAdapter`'s members passed while the omission
        it exists to catch sat in the tree. An instrument that cannot see the defect it was
        built for is not a weaker instrument — it is a green light.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not declare simulation_source. is_simulation gates "
            f"every execution, and a run must record whether that flag was CHECKED against the "
            f"venue or only believed. A benign default here would make a lost value look safe."
        )

    # ------------------------------------------------------------------
    def order_path_status(self) -> str | None:
        """Why this adapter CANNOT place orders yet, or `None` if it can.

        **A RUN THAT CANNOT PLACE AN ORDER MUST REFUSE TO START, NOT FAIL 146 TIMES** (`T-0138`).
        `AlpacaAdapter.place_order` refuses every LONG while its body is unwritten (part D, which
        measures the minimum order size the body has to round to). Pointing a run at it anyway
        produces a wall of per-order failures that an operator reads as *the venue is broken* —
        `B380`'s shape, a correct record turned into the wrong conclusion by the surface it
        reaches. **One refusal at startup cannot be mistaken for a market condition.**

        Deliberately NOT abstract, and `None` is the default for the same reason
        `reference_price` returns `None`: adding an abstract member here would make every existing
        adapter un-instantiable.

        **The override must be DELETED when the body lands, and an arm enforces that rather than a
        comment asking for it.** `test_t0138_order_path_gate` asserts the biconditional for Alpaca
        — a reason here AND `place_order` raising `NotImplementedError` — so implementing the body
        turns that arm RED and the override cannot survive it. *An arm pinning a phase boundary
        expires when the phase ends, and the expiry is the point.*
        """
        return None

    # ------------------------------------------------------------------
    async def reference_price(self, pair: str) -> float | None:
        """Price a MARKET order would fill at right now, or None if unknown.

        Deliberately NOT abstract. Adding an abstract method here would make
        every existing adapter un-instantiable, and the ``is_simulation``
        contract already uses that lever for the one property worth enforcing
        that way. Returning None is a safe default: ``ExecutionService`` refuses
        to size a market order without a reference price rather than guessing.

        Why this exists: a market order does not fill at the price the strategy
        named, it fills at the market. Sizing off the strategy's intended price
        makes the position's real risk differ from the configured risk_pct by
        however far the market has moved — silently, and in whichever direction
        the market happened to go.
        """
        return None
