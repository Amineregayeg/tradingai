import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Numeric, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserScopedMixin
from app.db.enums import DirectionType, OutcomeType, TradeStatus


class Trade(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    broker_id: Mapped[str] = mapped_column(String, nullable=False)
    broker: Mapped[str] = mapped_column(String, nullable=False)
    pair: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[DirectionType] = mapped_column(
        Enum(DirectionType, name="direction_t"),
        nullable=False,
    )
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    sl: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    tp: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    lot_size: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    r_multiple: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    outcome: Mapped[OutcomeType] = mapped_column(
        Enum(OutcomeType, name="outcome_t"),
        nullable=False,
        default=OutcomeType.OPEN,
    )
    session: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[TradeStatus] = mapped_column(
        Enum(TradeStatus, name="trade_status_t"),
        nullable=False,
        default=TradeStatus.OPEN,
    )
    pnl_dollars: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    pnl_pips: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    setup_tag: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relationships
    screenshots: Mapped[list["Screenshot"]] = relationship(  # noqa: F821
        "Screenshot", back_populates="trade", lazy="select"
    )
    checklists: Mapped[list["Checklist"]] = relationship(  # noqa: F821
        "Checklist", back_populates="trade", lazy="select"
    )
    orders: Mapped[list["Order"]] = relationship(  # noqa: F821
        "Order", back_populates="trade", lazy="select"
    )
