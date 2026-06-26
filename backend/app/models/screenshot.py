import uuid
from datetime import datetime

from sqlalchemy import func, DateTime, Enum, ForeignKey, String
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UserScopedMixin
from app.db.enums import ScreenshotTrigger


class Screenshot(UserScopedMixin, Base):
    __tablename__ = "screenshots"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    trade_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("trades.id", ondelete="SET NULL"),
        nullable=True,
    )
    pair: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    trigger_type: Mapped[ScreenshotTrigger] = mapped_column(
        Enum(ScreenshotTrigger, name="screenshot_trig_t"),
        nullable=False,
    )
    image_path: Mapped[str] = mapped_column(String, nullable=False)
    image_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    trade: Mapped["Trade | None"] = relationship(  # noqa: F821
        "Trade", back_populates="screenshots", lazy="select"
    )
    analyses: Mapped[list["AIAnalysis"]] = relationship(  # noqa: F821
        "AIAnalysis", back_populates="screenshot", lazy="select"
    )
