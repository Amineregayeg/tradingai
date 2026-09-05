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
    # `B378`. NULLABLE, so an UNAVAILABLE row carries NO FIGURES.
    #
    # The alternative was writing the last known values into the new row, and that is the defect
    # rather than the fix: it is exactly *showing the last good value* with a fresh timestamp on
    # it. Zeros would be worse still — a manufactured drawdown on the number a breach is computed
    # from. **A row that says we could not evaluate must not also say what the equity was**, and
    # NULL is the only value that says nothing (`B215`, `B338`).
    equity: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    daily_loss: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_loss: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
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
