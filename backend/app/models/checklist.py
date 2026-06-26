import uuid
from datetime import datetime

from sqlalchemy import func, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UserScopedMixin


class Checklist(UserScopedMixin, Base):
    __tablename__ = "checklists"

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
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    steps_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    trade: Mapped["Trade | None"] = relationship(  # noqa: F821
        "Trade", back_populates="checklists", lazy="select"
    )
