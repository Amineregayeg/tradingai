import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, Boolean, DateTime, Numeric, String
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UserScopedMixin


class ScoringProfile(UserScopedMixin, Base):
    __tablename__ = "scoring_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    profile_name: Mapped[str] = mapped_column(String, nullable=False)
    ict_weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    ta_weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    price_action_weight: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    mtf_bonus: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    min_score_entry: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("65")
    )
    weights_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
