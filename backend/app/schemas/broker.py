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
    r_multiple: Decimal | None = None
    lot_size: Decimal
    sl: Decimal | None = None
    tp: Decimal | None = None
    duration_seconds: int
    open_time: datetime
