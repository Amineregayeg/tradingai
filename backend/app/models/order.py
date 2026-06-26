import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserScopedMixin
from app.db.enums import DirectionType, OrderStatus, OrderType


class Order(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    broker_order_id: Mapped[str] = mapped_column(String, nullable=False)
    broker: Mapped[str] = mapped_column(String, nullable=False)
    pair: Mapped[str] = mapped_column(String, nullable=False)
    order_type: Mapped[OrderType] = mapped_column(
        Enum(OrderType, name="order_type_t"),
        nullable=False,
    )
    direction: Mapped[DirectionType] = mapped_column(
        Enum(DirectionType, name="direction_t"),
        nullable=False,
    )
    lot_size: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    requested_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    filled_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    filled_volume: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    sl: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    tp: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status_t"),
        nullable=False,
        default=OrderStatus.PENDING,
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("alerts.id", ondelete="SET NULL"),
        nullable=True,
    )
    trade_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("trades.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    alert: Mapped["Alert | None"] = relationship(  # noqa: F821
        "Alert", back_populates="orders", lazy="select"
    )
    trade: Mapped["Trade | None"] = relationship(  # noqa: F821
        "Trade", back_populates="orders", lazy="select"
    )
