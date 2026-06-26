from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserSettings(Base):
    """Per-user settings. Primary key is user_id (one row per user)."""

    __tablename__ = "settings"

    user_id: Mapped[str] = mapped_column(
        String, primary_key=True, default="system"
    )
    ai_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ai_primary_model: Mapped[str] = mapped_column(
        String, nullable=False, default="claude-sonnet-4-6"
    )
    ai_screening_model: Mapped[str] = mapped_column(
        String, nullable=False, default="claude-haiku-4-5"
    )
    ai_monthly_budget_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("30.00")
    )
    ai_used_current_month_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00")
    )
    alert_sound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    desktop_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    auto_screenshot_on_open: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    auto_screenshot_interval: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15
    )
    max_risk_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("1.00")
    )
    max_daily_loss_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("3.00")
    )
    max_concurrent_positions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    require_checklist: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="UTC")
    theme: Mapped[str] = mapped_column(String, nullable=False, default="dark")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
