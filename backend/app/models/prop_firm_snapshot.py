import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, DateTime, Enum, ForeignKey, Numeric
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UserScopedMixin
from app.db.enums import ComplianceState


class PropFirmSnapshot(UserScopedMixin, Base):
    __tablename__ = "prop_firm_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("prop_firm_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    equity: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    daily_loss: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_loss: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    state: Mapped[ComplianceState] = mapped_column(
        Enum(ComplianceState, name="compliance_t"),
        nullable=False,
        default=ComplianceState.ACTIVE,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    profile: Mapped["PropFirmProfile"] = relationship(
        "PropFirmProfile", back_populates="snapshots", lazy="select"
    )
