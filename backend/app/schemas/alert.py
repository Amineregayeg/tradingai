import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.db.enums import AlertPriority, AlertStatus, AlertType


class EditDiffRead(BaseModel):
    id: uuid.UUID
    user_id: str
    alert_id: uuid.UUID
    field_path: str
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertRead(BaseModel):
    id: uuid.UUID
    user_id: str
    type: AlertType
    priority: AlertPriority
    pair: str | None = None
    message: str
    suggested_action: dict[str, Any] | None = None
    context_json: dict[str, Any]
    status: AlertStatus
    ai_confidence: Decimal | None = None
    score: Decimal | None = None
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    edit_diffs: list[EditDiffRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AlertActionRequest(BaseModel):
    """Request body for acting on an alert (approve / reject / edit)."""

    action: Literal["approve", "reject", "edit"]
    changes: dict[str, Any] | None = Field(
        default=None,
        description="Field-level changes when action='edit'",
    )
    reason: str | None = Field(
        default=None,
        description="Trader's reason for the action",
    )
