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
    r_multiple: Decimal | None = None
    lot_size: Decimal
    sl: Decimal | None = None
    tp: Decimal | None = None
    duration_seconds: int
    open_time: datetime
