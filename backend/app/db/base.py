from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    type_annotation_map: dict[Any, Any] = {}


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserScopedMixin:
    """Mixin that adds user_id scoping to a model.

    Every row is owned by a user. For single-user self-hosted deployments the
    value defaults to 'system'.  In a multi-tenant SaaS deployment the
    application layer MUST set this field before committing.
    """

    user_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="system",
        index=True,
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Sanity-check: subclasses should not override user_id with a non-string type.
        if hasattr(cls, "user_id") and not isinstance(
            getattr(cls.__dict__.get("user_id", cls.user_id), "type", String()),
            type(String()),
        ):
            raise TypeError(f"{cls.__name__}.user_id must be a String column")
