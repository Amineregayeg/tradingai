import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.db.enums import ComplianceState


class PropFirmProfileCreate(BaseModel):
    firm_name: str = Field(description="Name of the prop firm e.g. 'FTMO'")
    challenge_type: str | None = Field(
        default=None, description="Challenge phase e.g. 'Phase 1', 'Funded'"
    )
    rules_json: dict[str, Any] = Field(description="Firm-specific rule parameters")
    account_id: str | None = Field(default=None, description="Prop firm account ID")


class PropFirmProfileRead(BaseModel):
    id: uuid.UUID
    user_id: str
    firm_name: str
    challenge_type: str | None = None
    rules_json: dict[str, Any]
    account_id: str | None = None
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PropFirmStatusRead(BaseModel):
    profile_id: uuid.UUID
    firm_name: str
    state: ComplianceState
    equity: Decimal
    balance: Decimal
    daily_loss: Decimal
    total_loss: Decimal
    daily_loss_limit_pct: Decimal | None = None
    total_loss_limit_pct: Decimal | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class KillSwitchRequest(BaseModel):
    profile_id: uuid.UUID = Field(description="Prop firm profile to arm kill switch for")
    reason: str | None = Field(
        default=None, description="Reason for manually arming the kill switch"
    )
    close_all_positions: bool = Field(
        default=True, description="Whether to immediately close all open positions"
    )


class KillSwitchTriggerResponse(BaseModel):
    profile_id: uuid.UUID
    armed: bool
    positions_closed: int
    state: ComplianceState
    message: str
