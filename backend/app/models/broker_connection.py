import uuid
from datetime import datetime

from sqlalchemy import func, Boolean, DateTime, LargeBinary, String
from sqlalchemy import func, UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UserScopedMixin


class BrokerConnection(UserScopedMixin, Base):
    __tablename__ = "broker_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    broker: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    encrypted_creds: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    environment: Mapped[str | None] = mapped_column(String, nullable=True)
    connected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
