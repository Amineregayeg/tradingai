from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SettingsRead(BaseModel):
    user_id: str
    ai_enabled: bool
    ai_primary_model: str
    ai_screening_model: str
    ai_monthly_budget_usd: Decimal
    ai_used_current_month_usd: Decimal
    alert_sound: bool
    desktop_notifications: bool
    auto_screenshot_on_open: bool
    auto_screenshot_interval: int
    max_risk_pct: Decimal
    max_daily_loss_pct: Decimal
    max_concurrent_positions: int
    require_checklist: bool
    timezone: str
    theme: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    """All fields are optional — only provided fields are updated."""

    ai_enabled: bool | None = None
    ai_primary_model: str | None = None
    ai_screening_model: str | None = None
    ai_monthly_budget_usd: Decimal | None = Field(default=None, ge=0)
    alert_sound: bool | None = None
    desktop_notifications: bool | None = None
    auto_screenshot_on_open: bool | None = None
    auto_screenshot_interval: int | None = Field(default=None, ge=1, le=1440)
    max_risk_pct: Decimal | None = Field(default=None, ge=0, le=100)
    max_daily_loss_pct: Decimal | None = Field(default=None, ge=0, le=100)
    max_concurrent_positions: int | None = Field(default=None, ge=1, le=100)
    require_checklist: bool | None = None
    timezone: str | None = None
    theme: str | None = None
