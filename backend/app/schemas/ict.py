import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.db.enums import ICTDir, ICTStatus, ICTType


class ICTDetectionRead(BaseModel):
    id: uuid.UUID
    user_id: str
    pair: str
    timeframe: str
    detection_type: ICTType
    direction: ICTDir
    price_high: Decimal
    price_low: Decimal
    confidence: Decimal
    strength: Decimal
    candle_index: int
    status: ICTStatus
    detected_at: datetime
    mitigated_at: datetime | None = None

    model_config = {"from_attributes": True}
