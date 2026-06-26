import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.enums import ScreenshotTrigger


class ScreenshotRead(BaseModel):
    id: uuid.UUID
    user_id: str
    trade_id: uuid.UUID | None = None
    pair: str
    timeframe: str
    trigger_type: ScreenshotTrigger
    image_path: str
    image_hash: str | None = None
    captured_at: datetime

    model_config = {"from_attributes": True}


class ScreenshotUpload(BaseModel):
    trade_id: uuid.UUID | None = Field(
        default=None, description="Associated trade ID (optional)"
    )
    pair: str = Field(description="Currency pair e.g. EUR_USD")
    timeframe: str = Field(description="Chart timeframe e.g. H1")
    trigger_type: ScreenshotTrigger = Field(default=ScreenshotTrigger.MANUAL)
