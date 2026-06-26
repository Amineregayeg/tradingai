import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, DateTime, Enum, Integer, Numeric, String
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UserScopedMixin
from app.db.enums import ICTDir, ICTStatus, ICTType


class ICTDetection(UserScopedMixin, Base):
    __tablename__ = "ict_detections"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    pair: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    detection_type: Mapped[ICTType] = mapped_column(
        Enum(ICTType, name="ict_type_t"),
        nullable=False,
    )
    direction: Mapped[ICTDir] = mapped_column(
        Enum(ICTDir, name="ict_dir_t"),
        nullable=False,
    )
    price_high: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price_low: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    strength: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    candle_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ICTStatus] = mapped_column(
        Enum(ICTStatus, name="ict_status_t"),
        nullable=False,
        default=ICTStatus.ACTIVE,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    mitigated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
