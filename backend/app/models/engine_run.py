"""A simulation run — one continuous period of the engine trading.

WHY RUNS EXIST (task 2.1)
Resetting the engine has to produce a genuinely clean slate: an equity curve and
trade count starting from zero. Without a way to scope results, there are only
two ways to do that, and both are wrong:

  * Leave the old rows and reset only the broker. The dashboard then shows a
    fresh 50,000 balance beside trades from before the reset — incoherent
    numbers, which is the defect this project was rebuilt to remove.
  * Delete the old rows. That destroys `decision_records`, which ARE the
    evidence of whether the strategy works. Backups exist precisely so that
    evidence survives; deleting it deliberately on a button press would be worse
    than any crash.

So a reset ENDS the current run and STARTS a new one. Nothing is deleted, and
current-run metrics genuinely start at zero because they are scoped to a run.

Surviving restarts matters as much as the reset itself: the active run is stored
here rather than in memory, so recreating the api container continues the same
run instead of silently resetting the numbers on every deploy.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

#: The run every row created before runs existed belongs to. Fixed, so the
#: migration's backfill and the loop's startup adoption agree without having to
#: look each other up.
LEGACY_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class EngineRun(Base):
    """One continuous period of engine operation."""

    __tablename__ = "engine_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: NULL means this is the ACTIVE run. Exactly one row should have a NULL
    #: ended_at at any time; the loop enforces that when it starts a new one.
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: What the engine was configured to do — broker mode, symbols, timeframe,
    #: risk, starting balance. Snapshotted at start so a result can never be
    #: read against the wrong settings later.
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    #: Why the run was started or ended, when a human said.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Free-form label so a run can be recognised without reading its config.
    label: Mapped[str | None] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "active" if self.ended_at is None else "ended"
        return f"<EngineRun {self.id} {state}>"
