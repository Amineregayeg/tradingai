import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class AnalysisRead(BaseModel):
    id: uuid.UUID
    user_id: str
    screenshot_id: uuid.UUID
    model: str
    analysis_json: dict[str, Any]
    trend_assessment: str | None = None
    trade_bias: str | None = None
    confidence: Decimal | None = None
    raw_text: str | None = None
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    downgraded: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisRunRequest(BaseModel):
    screenshot_id: uuid.UUID = Field(description="ID of the screenshot to analyse")
    trade_context: dict[str, Any] | None = Field(
        default=None,
        description="Optional trade context to include in the prompt",
    )
