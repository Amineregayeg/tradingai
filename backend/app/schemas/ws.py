import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.db.enums import AlertPriority, AlertStatus, AlertType, ComplianceState, DirectionType

T = TypeVar("T")


class WSChannel(str, enum.Enum):
    PRICES = "prices"
    POSITIONS = "positions"
    ALERTS = "alerts"
    ICT = "ict"
    PROPFIRM = "propfirm"
    SYSTEM = "system"


class WSMessage(BaseModel, Generic[T]):
    """Generic WebSocket message envelope."""

    channel: WSChannel
    event: str = Field(description="Event name within the channel")
    data: T
    ts: datetime = Field(default_factory=datetime.utcnow)
    request_id: str | None = None


# ---- Event Data Models ----


class TickData(BaseModel):
    """Live price tick."""

    pair: str
    bid: Decimal
    ask: Decimal
    spread: Decimal
    timestamp: datetime


class PositionEvent(BaseModel):
    """Position opened, updated, or closed."""

    event: str  # "opened" | "updated" | "closed"
    position_id: str
    pair: str
    direction: DirectionType
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    r_multiple: Decimal | None = None
    lot_size: Decimal
    sl: Decimal | None = None
    tp: Decimal | None = None
    open_time: datetime


class AlertEvent(BaseModel):
    """New alert or alert status change."""

    alert_id: uuid.UUID
    type: AlertType
    priority: AlertPriority
    status: AlertStatus
    pair: str | None = None
    message: str
    ai_confidence: Decimal | None = None
    score: Decimal | None = None


class ICTEvent(BaseModel):
    """New ICT structure detected or status change."""

    detection_id: uuid.UUID
    pair: str
    timeframe: str
    detection_type: str
    direction: str
    price_high: Decimal
    price_low: Decimal
    confidence: Decimal
    status: str


class PropFirmEvent(BaseModel):
    """Prop firm compliance state change."""

    profile_id: uuid.UUID
    firm_name: str
    state: ComplianceState
    equity: Decimal
    daily_loss: Decimal
    total_loss: Decimal
    kill_switch_armed: bool = False


class SystemEvent(BaseModel):
    """System-level events (startup, broker connect/disconnect, errors)."""

    level: str  # "info" | "warning" | "error"
    code: str
    message: str
    context: dict[str, Any] | None = None
