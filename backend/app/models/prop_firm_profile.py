import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy import UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UserScopedMixin


class PropFirmProfile(UserScopedMixin, TimestampMixin, Base):
    __tablename__ = "prop_firm_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    firm_name: Mapped[str] = mapped_column(String, nullable=False)
    challenge_type: Mapped[str | None] = mapped_column(String, nullable=True)
    rules_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    snapshots: Mapped[list["PropFirmSnapshot"]] = relationship(
        "PropFirmSnapshot", back_populates="profile", lazy="select"
    )
