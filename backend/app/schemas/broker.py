import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.db.enums import DirectionType


class BrokerConnectionRead(BaseModel):
    id: uuid.UUID
    user_id: str
    broker: str
    label: str | None = None
    account_id: str | None = None
    environment: str | None = None
    connected: bool
    last_connected_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BrokerConnectRequest(BaseModel):
    broker: str = Field(description="Broker identifier e.g. 'oanda' or 'cryptofundtrader'")
    label: str | None = Field(default=None, description="Human-friendly label")
    api_key: str = Field(default="", description="API key / access token (token brokers, e.g. OANDA)")
    api_secret: str | None = Field(
        default=None, description="API secret (if required by broker)"
    )
    account_id: str = Field(default="", description="Broker account ID")
    environment: str = Field(
        default="practice", description="'practice' or 'live'"
    )
    # Match-Trader / Crypto Fund Trader credentials (email + password + API base URL).
    email: str | None = Field(default=None, description="Login email (Match-Trader brokers)")
    password: str | None = Field(default=None, description="Login password (Match-Trader brokers)")
    server: str | None = Field(
        default=None,
        description="API base URL incl. system path, e.g. https://<host>/mtr-api/<system-uuid>",
    )
    # MetaTrader 5 through MetaApi (`B368`). **These are NOT `api_key` under another name**, and
    # the decision not to overload it is deliberate: `api_key` means an EXCHANGE API KEY on every
    # other broker here, and one field carrying two unrelated credentials is `B184` at the
    # inbound surface — precisely the argument `B360` makes for the token having exactly one
    # source. `mt5_account_id` is MetaApi's PROVISIONED ACCOUNT ID, which is not the broker login
    # and not `account_id`.
    token: str | None = Field(
        default=None, description="MetaApi token (MetaTrader 5 connections)"
    )
    mt5_account_id: str | None = Field(
        default=None,
        description="MetaApi provisioned account id — NOT the broker login, NOT account_id",
    )
    observe_only: bool | None = Field(
        default=None,
        description="If true, the connection is read-only (no order placement). Default true for prop-firm brokers.",
    )


class Position(BaseModel):
    """Live position from broker."""

    id: str = Field(description="Broker-assigned position ID")
    pair: str
    direction: DirectionType
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    #: WHICH QUANTITY `unrealized_pnl` ACTUALLY IS (`B286`). **Required: a position carrying a
    #: P&L value must be unconstructible without saying where the number came from.**
    #:
    #: `cryptofundtrader.py` read it as
    #: `raw.get("profit", raw.get("netProfit", raw.get("openNetProfit")))` — a three-deep
    #: silent fallback across keys that **are not the same quantity**. `profit` is
    #: conventionally GROSS and `netProfit` is net of costs, so the field held one of three
    #: different measurements with nothing recording which. **No definition of this field can
    #: be honoured while a caller cannot tell them apart.**
    #:
    #: THREE STATES, AND THE THIRD IS THE POINT. Four adapters build a `Position` and `paper`
    #: COMPUTES its P&L with no key involved, so two states would make `None` mean both
    #: *"computed locally, correctly"* and *"nothing was read, which is a fault"* — the same
    #: could-not-ask collapse this field exists to prevent (`B215`).
    #:
    #:     "profit" | "netProfit" | "openNetProfit"   the key ACTUALLY present and read
    #:     "computed"                                 derived locally — paper, cft_sim
    #:     None                                       nothing read and nothing computed: a
    #:                                                FAULT, and the value is not to be trusted
    #:
    #: **A `.get(key, default)` IS NOT A KEY READ.** The key may be absent while a value still
    #: appears, so a provenance recorded from a defaulted read would name a key the payload
    #: never carried. Either the key was PRESENT — record it — or nothing was read.
    #:
    #: **It must never default to `"profit"`.** That reintroduces the ambiguity one layer
    #: down, in a field whose entire purpose is to remove it.
    pnl_source: str | None
    #: WHICH ADAPTER BUILT THIS ROW. **Required.**
    #:
    #: `B286` found two adapter-specific meanings while asking about P&L; `B289` found a third
    #: while asking about staleness. **Neither was looking for the pattern.** They are not
    #: three bugs: `Position` had no notion of who produced it, so every field was free to mean
    #: something adapter-specific because nothing ever had to agree.
    #:
    #:     unrealized_pnl     paper = gross price movement | CFT = whichever key arrived
    #:     r_multiple         paper = a price ratio        | CFT = derived from the P&L
    #:     duration_seconds   oanda/CFT = computed         | paper/cft_sim = the literal 0
    #:
    #: **REQUIRED, because a provenance field that can be absent reintroduces the problem it
    #: exists to solve.** Optional would mean nothing breaks and no adapter has to answer.
    #:
    #: **IT IS A POINTER, NOT A DEFINITION**, which is why `T-0102`'s `pnl_source` still
    #: exists. `produced_by="cryptofundtrader"` says whose convention; it cannot say WHICH of
    #: `profit` / `netProfit` / `openNetProfit` was read, and those are different quantities
    #: chosen per response. Adapter provenance answers *whose convention*; only the field-level
    #: record answers *which key*.
    produced_by: str

    #: MT5 reports swap and commission as first-class money fields; nothing here did.
    #:
    #: **`Decimal | None`, NEVER `Decimal = 0` (`B215`).** `None` means *this venue does not
    #: report it*; `0` means *reported, and zero*. A default of `0` makes a venue that cannot
    #: say indistinguishable from one that said nothing was charged.
    #:
    #: **A SWAP-FREE ADAPTER REPORTS `None`, NOT `0`** — and that is the same fact that makes
    #: `unrealized_pnl` gross for those adapters rather than net: *gross-versus-net only exists
    #: where costs exist, so `paper` and `cft_sim` are not gross rather than net — they cannot
    #: be either.* Two decisions, one fact.
    #:
    #: **FOUR OF `B261`'S NINE MT5 MONEY FIELDS ARE DELIBERATELY DROPPED.** MT5 reports
    #: profit, commission and swap each in TOTAL / REALIZED / UNREALIZED. A `Position` is an
    #: OPEN position, so it has no realized component and no total — those belong to the closed
    #: `Trade` record, and carrying them here would invite a reader to total an open row.
    #: Taken: the unrealized profit (already `unrealized_pnl`), the swap accrued, and the
    #: commission charged to open.
    swap: Decimal | None = None
    commission: Decimal | None = None

    #: `unrealized_pnl` is GROSS — the components above stay inspectable rather than folded in.
    #:
    #: **It is the only option under which `None` still means "not reported".** Fold costs in
    #: and a venue that reports no swap becomes indistinguishable from one that charges none,
    #: which is `B215` again in the field that carries the money.
    #:
    #: **AND THE ASSERTION DEPENDS ON `T-0102`.** CFT's `unrealized_pnl` is whichever of three
    #: keys arrived, so "gross" is either false for CFT or true only by accident — `pnl_source`
    #: is what makes it checkable rather than assumed.
    r_multiple: Decimal | None = None
    lot_size: Decimal
    sl: Decimal | None = None
    tp: Decimal | None = None
    #: `int | None`. It was a required `int`, so `paper` and `cft_sim` — which do not track it
    #: — passed the literal `0`, the only value the type allowed. **A row saying a position has
    #: been open for zero seconds is a claim, and it was false on every one of them** (`B289`).
    duration_seconds: int | None
    open_time: datetime
