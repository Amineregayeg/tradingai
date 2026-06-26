import uuid
from datetime import datetime

from sqlalchemy import func, DateTime, Enum, String
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UserScopedMixin
from app.db.enums import ActorType


class AuditLog(UserScopedMixin, Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True), nullable=True
    )
    actor: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_t"),
        nullable=False,
    )
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
