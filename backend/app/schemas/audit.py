import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.db.enums import ActorType


class AuditEventRead(BaseModel):
    id: uuid.UUID
    user_id: str
    event_type: str
    entity_type: str
    entity_id: uuid.UUID | None = None
    actor: ActorType
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None
    result: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
