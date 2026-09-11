"""Alpaca — the venue Malek ruled on 2026-09-10, and the reason `T-0076` stopped being a blocker.

**WHY THIS ADAPTER CAN DO WHAT THE MT5 ONE COULD NOT.**

    TradingClient(key, secret, paper=True)      # `paper` is a CONSTRUCTOR FLAG WE PASS

`ExecutionService` refuses any adapter reporting `is_simulation=False` and `ExecMode` has no LIVE
member — both deliberately. An MT5 broker demo could not honestly answer that flag (`T-0076`,
unruled since 2026-08-24). **An Alpaca paper account can.**

⚠ **AND THE SENTENCE THAT USED TO FOLLOW WAS FALSE, IN THE SAFETY LAYER, FOR A WHOLE TASK CYCLE.**
It read: *"the flag is derived from a value we passed rather than a venue field we interpret — the
safety model is satisfied truthfully rather than bypassed."* **A value we passed is not a fact
about the world.** The SDK resolves the endpoint as

    base_url = url_override if url_override else (TRADING_PAPER if paper else TRADING_LIVE)

so `url_override` OUTRANKS `paper`, and `TradingClient(k, s, paper=True, url_override=<live>)`
points at real money while `is_simulation` returns `True` (`B389`, settled by construction). The
flag tracked an ARGUMENT that a second argument overrides.

**Worse, the parameter was in my own introspection output the whole time.**
`agents/tasks/T-0136/SDK_SHAPES.md:36` records the constructor signature INCLUDING
`url_override: Optional[str] = None`. The document built so the mock could not encode my own
reading captured the fact, and I wrote three lines about how trustworthy `paper` is without reading
it. **The instrument had no blind spot; the reader did** — which is the inverse of the usual failure
here, and it means *introspect before writing* only works if someone reads the output AGAINST the
claims it is supposed to check.

**`T-0138` removes the latency instead of documenting it:** the adapter reads where the client
actually points and REFUSES TO CONSTRUCT on a known disagreement.

**WRITTEN AFTER INTROSPECTING THE INSTALLED SDK, WHICH IS THE WHOLE DIFFERENCE FROM `T-0106`.**
That adapter was written from documentation and its mock encoded its own reading, so no arm could
fail on a fact the two shared — three defects came out of it and all three were ARRANGEMENT or
RETURN SHAPE rather than naming (`B341`, `B356`, `B359`). Nine of nine names were right. Every shape
this module relies on is recorded in `agents/tasks/T-0136/SDK_SHAPES.md` as `inspect` output.

**THE SDK IS NOT IMPORTED AT MODULE SCOPE**, for `B328`'s reason: the contract arm's discovery walk
does `except Exception: continue`, so an adapter whose module cannot be imported is skipped IN
SILENCE by the arm that exists to cover it. The client is injected, and the venue's vocabulary is
carried as the enum VALUES rather than the enum objects so that no import is needed to read it.

**FLAT MODULE, DELIBERATELY** — `B267`: `pkgutil.iter_modules` does not recurse, so an adapter one
directory deep is invisible to the discovery walk while the suite stays green.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.core.exceptions import BrokerError
from app.core.logging import logger
from app.db.enums import DirectionType
from app.schemas.broker import Position
from app.services.broker.base import (
    Account, BrokerAdapter, DirectionPolicy, OrderRequest,
)

#: `PositionSide` values, read from the installed package: `['short', 'long']`.
#:
#: **A POSITION is long/short and an ORDER is buy/sell — two vocabularies for one concept**, and
#: reading one with the other's set is `B336`/`B376`'s defect with a new surface. Both were the
#: ABSENCE of a mapping; here there are two mappings and this is the position one.
POSITION_SIDES: dict[str, DirectionType] = {
    "long": DirectionType.LONG,
    "short": DirectionType.SHORT,
}

#: `OrderSide` values: `['buy', 'sell']`. Kept apart from the above ON PURPOSE.
ORDER_SIDES: dict[str, DirectionType] = {
    "buy": DirectionType.LONG,
    "sell": DirectionType.SHORT,
}

#: The document recording every shape this module reads.
SHAPES = "agents/tasks/T-0136/SDK_SHAPES.md"

#: **MALEK'S RULING, 2026-09-10, EXPRESSED AS THE VENUE FACT IT IS** (`T-0137`).
#:
#: The platform trades LONG ONLY because *Alpaca crypto is non-marginable and not shortable*.
#: The constraint is the venue's, so the SENTENCE is the venue's too, and it is defined here —
#: in the Alpaca module — rather than where it is enforced. Nothing else may compose this text:
#: `paper.py` and `cft_sim.py` import this object, and a second copy of the reason is `B184`
#: with a string, drifting from this one the first time either is edited.
#:
#: **IT IS NOT A HYPOTHESIS.** 147 shorts against 146 longs were measured in real executed
#: trades, so a long-only venue removes roughly half of what this strategy does. That is exactly
#: why the refusals must be recorded and split by direction: a run whose strategy produced no
#: shorts and a run that produced 147 and had every one refused have the same trade list, and
#: only the refusal record tells them apart.
#:
#: **The wording names the CONSTRAINT, not the refusal.** "Order rejected" would be
#: indistinguishable from a transport failure in `DecisionRecord.rejection_reason` months later.
ALPACA_CRYPTO_LONG_ONLY = DirectionPolicy(
    venue="alpaca",
    supported=frozenset({DirectionType.LONG}),
    reason=(
        "Alpaca crypto is non-marginable and not shortable, so this venue cannot take a SHORT. "
        "The platform is LONG ONLY (ruled 2026-09-10). This is a permanent venue capability, "
        "not a transient failure: the same order will be refused every time it is sent."
    ),
)


#: **THE ENDPOINTS, AS THE SDK'S OWN ENUM VALUES** — read from the installed package, not typed
#: from memory: `BaseURL.TRADING_PAPER` / `BaseURL.TRADING_LIVE`.
#:
#: Hardcoded rather than imported because **`B328`**: this module must stay importable without
#: `alpaca-py`, and `BaseURL` lives inside it. `test_t0138_endpoint_agreement` pins these against
#: the installed enum, so a venue that changes its host turns an arm red instead of turning the
#: safety flag into a lie.
PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
LIVE_ENDPOINT = "https://api.alpaca.markets"


def _endpoint_of(client: Any) -> str | None:
    """WHERE THIS CLIENT ACTUALLY POINTS, or `None` if it cannot say (`B389`).

    **TWO TYPES FOR ONE CONCEPT, AND `str()` IS THE TRAP** — measured, not assumed:

    ```
    TradingClient(k, s, paper=True)                      _base_url -> BaseURL.TRADING_PAPER
    TradingClient(k, s, paper=True, url_override=<live>) _base_url -> 'https://api...'  (plain str)

    "paper-api" in BaseURL.TRADING_PAPER        -> True    the MEMBER is a string
    "paper-api" in str(BaseURL.TRADING_PAPER)   -> False   str() of it is not
    str(BaseURL.TRADING_PAPER)                  -> 'BaseURL.TRADING_PAPER'
    ```

    ⚠ **THE EXPLANATION HERE WAS WRONG BEFORE IT WAS RIGHT, AND THE WRONG VERSION WAS THE
    DANGEROUS ONE.** It said *"`BaseURL` is a plain `Enum`, not a `str, Enum`"*. **It IS a
    `str, Enum`** — `issubclass(BaseURL, str)` is `True`, the member compares equal to the URL and
    supports containment. **The actual mechanism is that `Enum.__str__` wins over `str.__str__` for
    a mixin enum**, so the member *is* a string while `str()` of it is the member NAME. The
    conclusion and the code were right for a reason that was not the real one — and a reader
    trusting the old sentence would believe the member is not string-comparable at all, which would
    send them to `.value` in places where plain comparison is fine. Corrected by the manager, who
    drove it. *The claim held, the reason was wrong, and the reason is the load-bearing half for
    whoever reads this next.*

    So a check written `"paper-api" in str(client._base_url)` is `False` for a genuine paper client
    and would refuse every legitimate construction while passing the override case it was written
    to catch. `getattr(raw, "value", raw)` handles both shapes: the enum yields its URL, a plain
    string yields itself. This is `Order.qty`'s `Union[str, float, None]` trap with a second
    surface.

    `None` means the question could not be asked — a test double, or an SDK that renamed a private
    attribute. **It is not an answer**, and the caller must not read it as one.
    """
    raw = getattr(client, "_base_url", None)
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


class AlpacaEndpointMismatch(BrokerError):
    """`is_simulation` would have disagreed with where the client is POINTED (`B389`).

    **The flag we passed is a record of our intent; the base URL is where the money is.** The SDK
    resolves them as

        base_url = url_override if url_override else (TRADING_PAPER if paper else TRADING_LIVE)

    so `url_override` outranks `paper` entirely, and `TradingClient(k, s, paper=True,
    url_override=<live>)` points at real money while `is_simulation` returns `True` — the assertion
    gating ALL execution passing on a real-money client. Settled by CONSTRUCTION, not by reading
    the constructor.

    **Raised at construction rather than reported by `is_simulation`.** A flag that quietly starts
    returning something else moves the failure away from the mistake; refusing to build the adapter
    puts it on the line that made it. Nothing downstream has to remember to check.
    """

    def __init__(self, *, paper: bool, endpoint: str) -> None:
        super().__init__(
            f"Alpaca adapter was constructed with paper={paper}, but its client points at "
            f"{endpoint!r}. `is_simulation` reports the flag, and ExecutionService refuses any "
            f"adapter reporting False — so this combination would have presented a client at "
            f"{endpoint!r} as a simulation. `url_override` takes precedence over `paper` in the "
            f"SDK (B389). Refusing to construct rather than reporting a flag that is not true.",
            broker="alpaca",
        )
        self.paper = paper
        self.endpoint = endpoint


class AlpacaFieldUnreadable(BrokerError):
    """A numeric field was PRESENT and could not be parsed (`B338`).

    **Alpaca sends numbers as STRINGS** — `Position.qty` is `str`, `Position.avg_entry_price` is
    `str` — and `Order.qty` is `Union[str, float, None]`, the same concept with two types. So
    coercion is unavoidable here, which means this distinction is needed from the first commit
    rather than retrofitted after an incident: **a value we cannot read is not a missing one, and
    neither of them is a zero.**
    """

    def __init__(self, field: str, value: Any) -> None:
        super().__init__(
            f"Alpaca sent {field}={value!r}, which is not a number. The venue types this field "
            f"numeric-as-string, so this is a contract violation rather than a missing optional — "
            f"and a value we cannot read must never be floored to zero (B338).",
            broker="alpaca",
        )
        self.field = field
        self.value = value


class AlpacaSideUnrecognised(BrokerError):
    """A position side outside the documented set (`B336`, `B376`).

    Both of those were the absence of a mapping — one over-matched with `endswith`, one
    under-matched with set membership. **There is no value of `DirectionType` that means *I could
    not tell***, so an unknown becomes a question rather than a direction.
    """

    def __init__(self, value: Any) -> None:
        super().__init__(
            f"Alpaca reported position side {value!r}, which is not one of "
            f"{tuple(POSITION_SIDES)}. Refusing to guess a direction. NOTE: an ORDER side is "
            f"buy/sell and a POSITION side is long/short — reading one with the other's "
            f"vocabulary is the same defect with a different surface.",
            broker="alpaca",
        )
        self.value = value


def _dec(value: Any, field: str) -> Decimal | None:
    """`None` stays `None`; a value we cannot READ raises (`B215`, `B338`)."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AlpacaFieldUnreadable(field, value) from exc


def _required_dec(source: Any, field: str) -> Decimal:
    """A field the venue's model marks REQUIRED. Absent is a violation, not a zero."""
    value = _dec(getattr(source, field, None), field)
    if value is None:
        raise AlpacaFieldUnreadable(field, None)
    return value


class AlpacaAdapter(BrokerAdapter):
    """Alpaca paper trading. Reads work; the one write refuses in this phase."""

    broker_name = "alpaca"

    #: `BTC/USD` is Alpaca's native symbol format **and already our canonical pair name** in
    #: `fixed_config.SYMBOLS`, so unlike MT5 there is no symbol vocabulary to invent (`B305`'s
    #: problem does not arise). Left empty so the caller's list is used.
    default_pairs: list[str] = []

    def __init__(self, client: Any, *, paper: bool = True) -> None:
        """`client` is an `alpaca.trading.client.TradingClient` — or the mock presenting its shape.

        **`paper` IS PASSED IN RATHER THAN READ BACK.** It is the same value handed to
        `TradingClient(..., paper=paper)`, so `is_simulation` reports what we CONSTRUCTED WITH and
        not something interpreted from an account field. Deriving it from the venue would rebuild
        `T-0076` — a flag whose meaning depends on reading a third party's record.
        """
        self._client = client
        self._paper = bool(paper)
        self.connected: bool = False

        #: WHERE THIS CLIENT POINTS, or `None` if it could not say (`B389`, `T-0138`).
        #:
        #: **A POSITIVE RECORD OF WHICH ANSWER `is_simulation` IS GIVING**, the same shape as
        #: `Position.pnl_source`: *derived from the endpoint* and *taken from the flag because the
        #: endpoint was unreadable* are different claims, and a reader must not have to guess
        #: which one they have.
        self.endpoint: str | None = _endpoint_of(client)
        #: Stored privately and exposed through the property below, because `B395`'s amendment
        #: made `simulation_source` a PROPERTY on `BrokerAdapter` — a data descriptor, which an
        #: instance attribute cannot shadow. The base raising is what makes absence loud; this is
        #: the cost of that, and it is the right trade.
        self._simulation_source: str = (
            "endpoint" if self.endpoint is not None else "flag (client endpoint unreadable)"
        )

        # THE ASSERTION THAT REMOVES `B389` RATHER THAN DOCUMENTING IT.
        #
        # Only a KNOWN disagreement refuses. An unreadable endpoint is a question, not a licence:
        # it is recorded above and left to `is_simulation`'s flag, because raising on it would
        # take the platform down the day the SDK renames a private attribute — trading a latent
        # risk for a certain outage. Test doubles land here too, which is why the mock in
        # `test_t0136_alpaca_adapter.py` now carries a `_base_url`.
        if self.endpoint is not None and (self.endpoint == PAPER_ENDPOINT) != self._paper:
            raise AlpacaEndpointMismatch(paper=self._paper, endpoint=self.endpoint)

        #: `T-0137`. Declared on the INSTANCE so a reader of `manager.py` sees the constraint
        #: attached to the adapter it constructs, and so `ExecutionService` can read it through
        #: the `BrokerAdapter` contract without importing this module.
        self.direction_policy: DirectionPolicy | None = ALPACA_CRYPTO_LONG_ONLY

        #: How many positions the last `get_positions` could not read, by reason. **A positive
        #: statement**: a silent skip and a venue with nothing to report are otherwise identical.
        self.last_unreadable: list[dict] = []

    # ------------------------------------------------------------------
    # Simulation contract — TRUE, and truthfully
    # ------------------------------------------------------------------
    @property
    def is_simulation(self) -> bool:
        """**The `paper` flag — which `__init__` has already checked against the real endpoint.**

        Not derived from an account field and not per-call. `T-0106`'s `is_simulation` returned a
        hardcoded `False` with a docstring explaining that no value was correct for an MT5 demo.

        **THIS USED TO SAY "the value is correct and is simply reported", AND THAT WAS THE WHOLE
        DEFECT** (`B389`). The value is our INTENT; `url_override` can point the client somewhere
        else entirely and this flag would not notice. It is trustworthy now only because
        construction refuses on a known disagreement — so read `simulation_source` to see WHICH
        answer you have: `endpoint` means the client was asked, `flag (...)` means it could not be.

        Kept as a plain flag read rather than a live lookup on purpose: this gates every execution
        and must not be able to raise or to change answer between two calls.
        """
        return self._paper

    @property
    def simulation_source(self) -> str:
        """`endpoint` when the client was ASKED where it points; the unreadable sentence when it
        could not be. See `BrokerAdapter.simulation_source` — the base raises, so every adapter
        must answer and a lost value cannot resolve to something reassuring."""
        return self._simulation_source

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """Alpaca is REST and stateless — one call proves the credentials.

        A documented act rather than a no-op: `get_account` is the cheapest call that fails on bad
        credentials, so "connected" means "the venue answered us", which is what a caller assumes
        the word means.
        """
        await self.get_account()
        self.connected = True
        logger.info("Alpaca adapter connected", paper=self._paper)

    async def disconnect(self) -> None:
        """**A DOCUMENTED NO-OP** (`B285`). `TradingClient` holds no session to close; the
        docstring is the difference between a no-op and an omission for whoever debugs a
        connection that will not close.
        """
        self.connected = False

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    def _require_model(value: Any, member: str) -> Any:
        """**The venue's answer must be a MODEL, not a dict** (`B356`, and worse than it).

        `TradingClient(..., raw_data=False)` is what we construct with, and **`_use_raw_data` is
        MUTABLE AT RUNTIME** — measured: assigning `client._use_raw_data = True` takes, and 28
        methods branch on it. So the constructor argument is a CONVENTION and anything holding the
        client can flip it. **An arm asserting the constructor call passes while the flag is
        flipped downstream**, which is what my first version of that arm did.

        There is no backend type-checker either — `tsc` gates the frontend and nothing gates Python
        — so `Union[Model, Dict[str, Any]]`, the one external fact that could catch a raw-dict
        access, is unenforced. **This check is the enforcement.**

        Without it the failure is silent and misdirected: every `getattr` on a dict returns the
        default, so a raw payload full of good data reads as a payload full of absences, and
        `get_account` would refuse for "no equity" while the equity is right there in the dict.
        """
        if isinstance(value, dict):
            raise BrokerError(
                f"Alpaca {member} returned a RAW DICT rather than a model. The client's "
                f"`_use_raw_data` is set — it is mutable at runtime and 28 SDK methods branch on "
                f"it. Every attribute read in this adapter would silently return None, so a full "
                f"payload would read as an empty one. See {SHAPES}.",
                broker="alpaca",
            )
        return value

    async def _call(self, name: str, *args, **kwargs) -> Any:
        """One place where a venue call becomes our error (`B340`).

        `T-0106` grew seven copies of its rate-limit dispatch and five of them could be INVERTED
        with the suite green. One dispatch from the start.
        """
        method = getattr(self._client, name, None)
        if method is None:
            raise BrokerError(
                f"the Alpaca client has no {name!r}. Every member this adapter calls is on "
                f"TradingClient — see {SHAPES}.", broker=self.broker_name,
            )
        try:
            result = method(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except BrokerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(
                f"Alpaca {name} failed: {type(exc).__name__}: {exc}", broker=self.broker_name,
            ) from exc

    async def get_account(self) -> Account:
        acct = self._require_model(await self._call("get_account"), "get_account")
        # `B377`, SAME FIELD AND A DIFFERENT VENUE. `TradeAccount.equity` is OPTIONAL on the
        # model, and it feeds the prop-firm compliance monitor where a breach closes the account.
        # Substituting another field silently asserts that open P&L is zero.
        equity = getattr(acct, "equity", None)
        if equity is None:
            raise BrokerError(
                "the Alpaca account payload carried no `equity`. Refusing to substitute "
                "`cash` or `portfolio_value`: equity feeds the drawdown monitor and they are not "
                "the same quantity (B377).", broker=self.broker_name,
            )
        # ⚠ `balance` USED TO FALL BACK TO `equity` HERE, WHICH IS `B377` REPRODUCED BY THE PERSON
        # WHO FIXED IT. `cash`, `equity`, `buying_power` and `last_equity` are ALL Optional[str] on
        # this model — B377 four times over — and cash is not equity: substituting one silently
        # asserts that open P&L is zero, which is the exact sentence I wrote about CFT an hour ago.
        cash = _dec(getattr(acct, "cash", None), "cash")
        if cash is None:
            raise BrokerError(
                "the Alpaca account payload carried no `cash`. Refusing to substitute `equity`: "
                "they differ by exactly the open P&L, so falling back asserts that it is zero "
                "(B377). Both are Optional[str] on TradeAccount.",
                broker=self.broker_name,
            )
        return Account(
            account_id=str(getattr(acct, "account_number", "") or ""),
            broker=self.broker_name,
            balance=float(cash),
            equity=float(_dec(equity, "equity")),
            currency=str(getattr(acct, "currency", "USD") or "USD"),
            margin_used=0.0,
            margin_available=float(_dec(getattr(acct, "buying_power", None), "buying_power") or 0),
            unrealized_pl=0.0,
        )

    async def _raw_positions(self) -> list[Any]:
        """The venue's position objects, UNCOERCED (`B349`).

        `close_all_positions` needs a symbol and nothing else. Building a full `Position` per row
        runs every numeric through `_dec`, and after `B349` we know what that costs on a kill
        switch: one unreadable field on one position left every position open. **A position we
        cannot fully PARSE is not a position we cannot CLOSE.**
        """
        rows = await self._call("get_all_positions") or []
        self._require_model(rows, "get_all_positions")
        return [self._require_model(r, "get_all_positions[]") for r in rows]

    async def get_positions(self) -> list[Position]:
        return [self._to_position(raw) for raw in await self._raw_positions()]

    @staticmethod
    def _read_direction(raw: Any) -> DirectionType:
        """`PositionSide` -> ours, mapping what is documented and RAISING on the rest."""
        side = getattr(raw, "side", None)
        value = getattr(side, "value", side)
        if value is None or str(value).strip() == "":
            raise AlpacaSideUnrecognised(None)
        key = str(value).strip().lower()
        if key not in POSITION_SIDES:
            raise AlpacaSideUnrecognised(value)
        return POSITION_SIDES[key]

    @staticmethod
    def _require_mark(current: Decimal | None, raw: Any) -> Decimal:
        """A position we cannot MARK is not a position at breakeven (`B215`)."""
        if current is None:
            raise AlpacaFieldUnreadable("current_price", None)
        return current

    def _to_position(self, raw: Any) -> Position:
        entry = _required_dec(raw, "avg_entry_price")
        qty = _required_dec(raw, "qty")
        current = _dec(getattr(raw, "current_price", None), "current_price")
        reported = _dec(getattr(raw, "unrealized_pl", None), "unrealized_pl")
        direction = self._read_direction(raw)
        if reported is not None:
            pnl, pnl_source = reported, "unrealized_pl"
        else:
            # DERIVED FROM WHAT THE VENUE DID SEND, and marked as such. Sign follows the
            # direction: a SHORT gains when the mark falls.
            mark = self._require_mark(current, raw)
            move = (mark - entry) if direction is DirectionType.LONG else (entry - mark)
            pnl, pnl_source = move * qty, "derived:(mark-entry)*qty"
        return Position(
            id=str(getattr(raw, "asset_id", "") or ""),
            pair=str(getattr(raw, "symbol", "UNKNOWN")),
            direction=direction,
            entry_price=entry,
            # `B215`, AND BOTH OF THESE WERE WRONG WHEN FIRST WRITTEN — in this file, by the seat
            # that had just filed an entry about reproducing this class. Found by a mechanical
            # sweep for the SHAPE, not by remembering.
            #
            # `current_price` FELL BACK TO `entry`, which does not merely default a number — it
            # ASSERTS THE POSITION IS AT BREAKEVEN. A position we cannot mark is not a position
            # worth zero P&L; it is one we cannot price, and our DTO has no value for that, so it
            # raises. `close_all_positions` is unaffected: it reads raw rows and never builds these
            # (`B349`), so an unpriceable position can still be CLOSED.
            current_price=self._require_mark(current, raw),
            unrealized_pnl=pnl,
            # WHICH KEY, recorded (`B286`) — and now it can also say DERIVED. `unrealized_pl` is
            # Optional on the venue's model, so its absence is a fact about the payload. A zero
            # would be a fabricated number flowing into every P&L sum; the derivation uses only
            # fields the venue DID send, and the provenance says which it is.
            pnl_source=pnl_source,
            produced_by=self.broker_name,
            # SPOT CRYPTO CHARGES NO SWAP, so these are structurally absent rather than unread —
            # `B261`'s question disappears on this venue rather than being answered.
            swap=None,
            commission=None,
            r_multiple=None,
            lot_size=qty,
            sl=None,
            tp=None,
            duration_seconds=None,
            open_time=datetime.now(timezone.utc),
        )

    async def get_orders(self, status: str | None = None) -> list[dict]:
        orders = await self._call("get_orders") or []
        return [
            {
                "id": str(getattr(o, "id", "")),
                "pair": str(getattr(o, "symbol", "") or ""),
                "status": str(getattr(getattr(o, "status", None), "value", getattr(o, "status", ""))),
                "side": str(getattr(getattr(o, "side", None), "value", getattr(o, "side", ""))),
                "qty": str(getattr(o, "qty", "") or ""),
            }
            for o in orders
        ]

    async def get_recent_trades(self, since: datetime | None = None) -> list[dict]:
        """Filled orders are this venue's trade record — there is no separate deals endpoint.

        **`get_orders` returns ORDERS, and only a FILLED one is a trade.** Mapping every order as a
        trade would put unfilled intent into the record, which is `B365`'s shape: a predicate
        ranging over the wrong population.
        """
        orders = await self._call("get_orders") or []
        trades: list[dict] = []
        for o in orders:
            state = str(getattr(getattr(o, "status", None), "value", getattr(o, "status", "")))
            if state.lower() != "filled":
                continue
            trades.append({
                "id": str(getattr(o, "id", "")),
                "pair": str(getattr(o, "symbol", "") or ""),
                "side": str(getattr(getattr(o, "side", None), "value", getattr(o, "side", ""))),
                "qty": _dec(getattr(o, "filled_qty", None), "filled_qty"),
                "price": _dec(getattr(o, "filled_avg_price", None), "filled_avg_price"),
            })
        return trades

    async def reference_price(self, pair: str) -> float | None:
        """**Not abstract on the base class, and that asymmetry is a trap** (`base.py:195`).

        An adapter that forgets this rejects EVERY market order as *"no reference price
        available"*, which reads as a market-data fault and sends the debugger to the wrong
        subsystem.
        """
        try:
            position = await self._call("get_open_position", pair)
        except BrokerError:
            return None
        price = _dec(getattr(position, "current_price", None), "current_price")
        return float(price) if price is not None else None

    # ------------------------------------------------------------------
    # The one write — REFUSES, and refuses EVERY direction in this phase
    # ------------------------------------------------------------------
    def order_path_status(self) -> str | None:
        """This adapter cannot place orders yet, and a run must not START pointed at it.

        **DELETE THIS OVERRIDE WHEN `place_order`'s BODY LANDS.** `test_t0138_order_path_gate`
        asserts the biconditional — this reason present AND `place_order` raising
        `NotImplementedError` — so writing the body turns that arm red and forces the removal.
        A comment asking a future reader to remember would not.
        """
        return (
            "Alpaca's order path is not written yet: `place_order` refuses every LONG with "
            "NotImplementedError. Its body is scoped to part D of ALPACA_PROGRAMME.md, which "
            "measures the minimum order size and increment the body must round to and refuse "
            "below. Starting a run against this venue would fail every entry one at a time, and "
            "the failures would read as the venue being down."
        )

    async def place_order(self, request: OrderRequest) -> dict:
        """**REFUSES A SHORT WITH THE VENUE'S REASON. REFUSES A LONG AS UNIMPLEMENTED.**

        Two refusals, deliberately DIFFERENT (`T-0137`). Malek ruled the platform trades LONG
        ONLY because Alpaca crypto is non-marginable and not shortable — a permanent venue
        capability — while order placement itself is simply not built yet. **Collapsing the two
        into one refusal is `B376-B`'s shape**: a raise-on-anything satisfies raise-on-shorts and
        proves nothing about the direction, and the record it leaves says the venue refused an
        order it would in fact accept once the member is written.

        So the distinction is asserted, not just intended:

        ```
        SHORT  -> DirectionNotSupported, reason = ALPACA_CRYPTO_LONG_ONLY.reason
        LONG   -> NotImplementedError,   which names the MEMBER and NOT the venue (body: part D)
        ```

        **WHY THIS IS SAFE TO KEY ON DIRECTION AT ALL — measured, not assumed.** The two side
        vocabularies set a trap here: on a spot venue **closing a long is also a `sell`**, so a
        refusal written as *"refuse sells"* would refuse every EXIT and leave positions
        unclosable, the kill switch included. Whether that matters depends on whether any exit
        reaches this member:

        ```
        place_order callers          execution/service.py:167   -- ExecutionService.execute(sig)
                                                                   takes a SIGNAL and builds the
                                                                   OrderRequest from sig.direction
                                                                   => THE ENTRY PATH
                                     live_loop_proxy.py:142     -- a FORWARDER: it passes the same
                                                                   request to whatever broker the
                                                                   loop holds. Not an independent
                                                                   caller and not an exit.

        every exit call site         positions.py:154           close_position   (manual close)
                                     kill_switch.py:67          close_all_positions
                                     crypto_loop.py:1006        close_position   (partial exit)
                                     crypto_loop.py:1077        close_position   (full exit)
                                     crypto_loop.py:1650        close_all_positions
        ```

        **NO EXIT PATH REACHES `place_order`.** Two callers, one entry and one forwarder — so
        refusing `OrderRequest.direction == SHORT` cannot refuse a close, and closing a long (a
        `sell` at the venue) is untouched. Had one exit routed through here, the refusal would
        have had to discriminate on POSITION CONTEXT rather than on side, which is a different
        task.

        ⚠ **AND MY FIRST RUN OF THAT SCAN WAS NARROWER THAN THE QUESTION.** It excluded
        `app/services/broker/` to drop the adapters' own `def place_order`, and that exclusion
        also hid `live_loop_proxy.py:142`. The conclusion is unchanged — a forwarder is not an
        exit — but **I reported "the only one" from a population that could not have contained
        the second one.** Kept because it is the recurring shape: a scan whose population is
        narrower than its question returns a confident answer to a question it did not ask.

        ---

        **THIS IS NOT WHERE THE LONG-ONLY PROPERTY IS ENFORCED FOR A PAPER RUN, AND THAT IS THE
        FACT MOST WORTH KNOWING HERE.** The live loop does not execute against this adapter. It
        builds `PaperBroker` or `SimPropFirmBroker` (`crypto_loop.py:168`, `:794`) and hands
        THAT to `ExecutionService`. A refusal implemented only here would be unreachable in
        every paper run — green arms, and 147 shorts still filling. The policy object is shared
        with the simulators for exactly that reason; this member is the gate for the day the
        real client is wired, not the gate the engine passes through today.
        """
        # ORDER MATTERS: the venue's constraint is checked BEFORE the not-implemented refusal.
        # Reversed, every SHORT would report "not implemented" — the true statement that hides
        # the permanent one — and the record would say to try again later.
        if self.direction_policy is not None:
            self.direction_policy.enforce(request.direction)

        raise NotImplementedError(
            "Alpaca place_order is not implemented yet — its body is scoped to part D of "
            "ALPACA_PROGRAMME.md, because D measures the minimum order size and increment that "
            "the body must round to and refuse below; writing it before D means writing it on "
            "assumptions. This refusal is about the "
            "MEMBER, not about the venue or the direction: a LONG is acceptable to Alpaca and "
            "will be placed here once this is written. A SHORT is refused above, permanently, "
            "with the venue's own reason."
        )

    async def close_position(self, position_id: str, lot_size: float | None = None) -> dict:
        """Close by symbol, and **HONOUR `lot_size` rather than ignore it** (`T-0038`).

        The contract is *honour it or refuse loudly*, and silently closing everything when a
        caller asked for 30% is the ambiguity that contract exists to prevent. **This is not
        theoretical here:** the exit ladder is 70% at 2R with a 30% runner (`EXIT-001`), and
        `crypto_loop.py:1006` calls this with a `lot_size` on every partial exit — so ignoring it
        would liquidate the runner and make the ladder unobservable.

        Alpaca expresses it as `ClosePositionRequest(qty=...)`. **Imported inside the method**, for
        `B328`'s reason: this module must stay importable without the SDK.
        """
        if lot_size is None:
            result = await self._call("close_position", position_id)
            return {"position_id": position_id, "partial": False, "result": str(result)}

        from alpaca.trading.requests import ClosePositionRequest

        # `qty` IS A STRING ON THIS VENUE. Passing a float would send `0.30000000000000004` for a
        # third of a position; the venue types it as a string and the SDK does not coerce.
        options = ClosePositionRequest(qty=str(lot_size))
        result = await self._call("close_position", position_id, options)
        return {"position_id": position_id, "partial": True, "qty": str(lot_size),
                "result": str(result)}

    async def close_all_positions(self) -> list[dict]:
        """**Malek's ruled property, on its third venue** — the shape is reused, not rebuilt.

        > Every position open when the switch was pulled must be reported as CLOSED, FAILED WITH A
        > REASON, or NOT ATTEMPTED.

        The dispositions come from `BrokerAdapter` (`T-0132`) rather than being redefined here — a
        ruled property that lives in one implementation is a property of that implementation.

        **AND THIS VENUE CAN EXPRESS A PER-POSITION FAILURE, WHICH CFT COULD NOT.**
        `ClosePositionResponse.body` is an `Order` on success and `FailedClosePositionDetails` —
        carrying `code` and `message` — on failure, with an HTTP `status` int alongside. On CFT I
        had to record *"a partial close would still read as CLOSED"* as an unclosable gap because
        that venue's response shape is unobserved. Here it is typed, so a failed row carries the
        venue's own reason instead of an inference.
        """
        report: dict[str, dict] = {}
        try:
            positions = await self._raw_positions()
        except Exception as exc:  # noqa: BLE001
            raise BrokerError(
                f"Alpaca close_all_positions could not enumerate the open positions, so it cannot "
                f"report on them: {exc}. Nothing was attempted.", broker=self.broker_name,
            ) from exc

        for index, raw in enumerate(positions):
            report[f"#{index}"] = {
                "position_id": str(getattr(raw, "symbol", "") or "").strip(),
                "pair": str(getattr(raw, "symbol", "UNKNOWN")),
                "disposition": self.NOT_ATTEMPTED,
                "status": "failed",
                "reason": "the close loop never reached this position",
            }
        self.last_close_all_report = report

        try:
            for index, _raw in enumerate(positions):
                row = report[f"#{index}"]
                symbol = row["position_id"]
                if not symbol:
                    row.update(
                        disposition=self.FAILED, status="failed",
                        reason="the venue sent no symbol, so this position could not be addressed "
                               "and no close was sent for it",
                    )
                    continue
                row.update(
                    disposition=self.FAILED, status="failed", _in_flight=True,
                    reason="the close for this position was SENT and the outcome was never "
                           "observed. The position may or may not be closed and MUST be checked "
                           "at the venue.",
                )
                try:
                    result = await self._call("close_position", symbol)
                except Exception as exc:  # noqa: BLE001 - ANY exception, loop CONTINUES
                    row.update(
                        disposition=self.FAILED, status="failed", _in_flight=False,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                    continue
                row.update(**self._classify_close(result), result=str(result), _in_flight=False)
        except BaseException as exc:  # noqa: BLE001 - CancelledError is not an Exception
            for _row in report.values():
                if _row.pop("_in_flight", False):
                    _row["reason"] = (
                        f"{type(exc).__name__}: the close for this position was SENT and the "
                        f"outcome was NEVER OBSERVED — the loop did not survive to record it "
                        f"({exc}). It MUST be checked at the venue."
                    )
            failure = BrokerError(
                f"Alpaca close_all_positions ended abnormally after "
                f"{sum(1 for r in report.values() if r['disposition'] != self.NOT_ATTEMPTED)} of "
                f"{len(report)} position(s): {type(exc).__name__}: {exc}",
                broker=self.broker_name,
            )
            failure.partial_report = list(report.values())  # type: ignore[attr-defined]
            raise failure from exc

        for row in report.values():
            row.pop("_in_flight", None)
        return list(report.values())

    def _classify_close(self, result: Any) -> dict:
        """Read the venue's own answer. **A response is not a close** (`B367`).

        `ClosePositionResponse.body` is `FailedClosePositionDetails` when the close failed, and the
        SDK does not raise for it — so a row marked CLOSED on the strength of "no exception" would
        be stating something false, which is `B337`'s shape by a different cause.
        """
        body = getattr(result, "body", None)
        code = getattr(body, "code", None)
        message = getattr(body, "message", None)
        if code is not None or message is not None:
            return {
                "disposition": self.FAILED, "status": "failed",
                "reason": f"the venue refused this close: code={code} {message}",
            }
        http = getattr(result, "status", None)
        if http is not None and int(http) >= 300:
            return {
                "disposition": self.FAILED, "status": "failed",
                "reason": f"the venue answered HTTP {http} for this close, which is not a success",
            }
        return {"disposition": self.CLOSED, "status": "closed", "reason": None}

    async def stream_prices(self, pairs: list[str], callback: Callable) -> None:
        """Poll per pair. Alpaca has a websocket feed; this shape is what the contract requires."""
        while self.connected:
            for pair in pairs:
                price = await self.reference_price(pair)
                if price is not None:
                    result = callback(pair, price)
                    if asyncio.iscoroutine(result):
                        await result
            await asyncio.sleep(1)
