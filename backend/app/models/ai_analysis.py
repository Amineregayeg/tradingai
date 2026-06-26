import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UserScopedMixin


class AIAnalysis(UserScopedMixin, Base):
    __tablename__ = "ai_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    screenshot_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("screenshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    analysis_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    trend_assessment: Mapped[str | None] = mapped_column(String, nullable=True)
    trade_bias: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 5), nullable=False, default=Decimal("0")
    )
    downgraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    screenshot: Mapped["Screenshot"] = relationship(  # noqa: F821
        "Screenshot", back_populates="analyses", lazy="select"
    )
