import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.db.enums import DirectionType, OutcomeType, TradeStatus
from app.schemas.alert import AlertRead, EditDiffRead
from app.schemas.analysis import AnalysisRead
from app.schemas.screenshot import ScreenshotRead


class TradeRead(BaseModel):
    id: uuid.UUID
    user_id: str
    broker_id: str
    broker: str
    pair: str
    direction: DirectionType
    entry_price: Decimal
    exit_price: Decimal | None = None
    sl: Decimal | None = None
    tp: Decimal | None = None
    lot_size: Decimal
    entry_time: datetime
    exit_time: datetime | None = None
    r_multiple: Decimal | None = None
    outcome: OutcomeType
    session: str | None = None
    status: TradeStatus
    pnl_dollars: Decimal | None = None
    pnl_pips: Decimal | None = None
    notes: str | None = None
    setup_tag: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TradeUpdate(BaseModel):
    exit_price: Decimal | None = None
    sl: Decimal | None = None
    tp: Decimal | None = None
    exit_time: datetime | None = None
    r_multiple: Decimal | None = None
    outcome: OutcomeType | None = None
    status: TradeStatus | None = None
    pnl_dollars: Decimal | None = None
    pnl_pips: Decimal | None = None
    notes: str | None = None
    setup_tag: str | None = None
    session: str | None = None


class TradeDetailRead(TradeRead):
    """Extended trade read that includes related entities."""

    screenshots: list[ScreenshotRead] = Field(default_factory=list)
    analyses: list[AnalysisRead] = Field(default_factory=list)
    alerts: list[AlertRead] = Field(default_factory=list)
    edit_diffs: list[EditDiffRead] = Field(default_factory=list)
