import uuid
from datetime import datetime

from sqlalchemy import func, DateTime, ForeignKey, String, Text
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UserScopedMixin


class EditDiff(UserScopedMixin, Base):
    __tablename__ = "edit_diffs"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_path: Mapped[str] = mapped_column(String, nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    alert: Mapped["Alert"] = relationship(  # noqa: F821
        "Alert", back_populates="edit_diffs", lazy="select"
    )
