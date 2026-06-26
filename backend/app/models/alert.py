import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, DateTime, Enum, Numeric, String, Text
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UserScopedMixin
from app.db.enums import AlertPriority, AlertStatus, AlertType


class Alert(UserScopedMixin, Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    type: Mapped[AlertType] = mapped_column(
        Enum(AlertType, name="alert_type_t"),
        nullable=False,
    )
    priority: Mapped[AlertPriority] = mapped_column(
        Enum(AlertPriority, name="alert_priority_t"),
        nullable=False,
    )
    pair: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_action: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    context_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    status: Mapped[AlertStatus] = mapped_column(
        Enum(AlertStatus, name="alert_status_t"),
        nullable=False,
        default=AlertStatus.PENDING,
    )
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationships
    edit_diffs: Mapped[list["EditDiff"]] = relationship(  # noqa: F821
        "EditDiff", back_populates="alert", lazy="select"
    )
    orders: Mapped[list["Order"]] = relationship(  # noqa: F821
        "Order", back_populates="alert", lazy="select"
    )
