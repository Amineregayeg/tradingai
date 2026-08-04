"""Stored engine-contract telemetry (M1).

WHY THIS IS A SEPARATE TABLE FROM `decision_records`

`decision_records` is what the existing ICT engine writes and what the dashboard and
feedback loop read. It is a good record and it stays.

This table is the Magic Strategy's evidence store, and its shape is not ours to choose —
it is fixed by `TELEMETRY_SCHEMA.json`, which the knowledge team's conformance suite reads.
Bending one table to serve both would mean either distorting the contract's shape or
changing what the dashboard already depends on, and would create two ways to answer "what
did the engine decide" that could drift apart. They are linked by `run_id` instead.

THE STORAGE DECISIONS THAT MATTER

* **The whole record is kept verbatim** in `payload`. The conformance suite is a pure
  function of stored records, so anything we normalise away is evidence we cannot produce
  later. The indexed columns beside it are duplicates for querying, never the source of
  truth.
* **Append-only.** No update path, no delete path. `sequence_no` is strictly increasing per
  (engine build, instrument, timeframe): a gap means records were suppressed, a repeat means
  they were rewritten, and both are findings the census is designed to expose.
* **Nothing is stored unvalidated.** The writer validates against the pinned schema first;
  an invalid record that reaches the store would make every downstream number a measurement
  of a population that does not match the contract.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base

RECORD_SETUP_EVALUATION = "setup_evaluation"
RECORD_TRADE_EXECUTION = "trade_execution"
RECORD_SCAN_CENSUS = "scan_census"
TELEMETRY_RECORD_TYPES: tuple[str, ...] = (
    RECORD_SETUP_EVALUATION,
    RECORD_TRADE_EXECUTION,
    RECORD_SCAN_CENSUS,
)


class TelemetryRecord(Base):
    """One engine-contract record, exactly as emitted."""

    __tablename__ = "telemetry_records"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: setup_evaluation | trade_execution | scan_census
    record_type: Mapped[str] = mapped_column(String, nullable=False)

    #: The contract's own id for this record (evaluation_id / trade_id / scan_id). Unique,
    #: because re-emitting one would mean a record was rewritten — which the append-only
    #: property exists to make impossible rather than merely discouraged.
    record_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    #: Ties this evidence to the run whose config produced it, so a result can never be read
    #: against the wrong settings.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True), nullable=True, index=True
    )

    #: Duplicated out of the payload purely for querying. The payload remains authoritative.
    instrument: Mapped[str | None] = mapped_column(String, nullable=True)
    signal_tf: Mapped[str | None] = mapped_column(String, nullable=True)
    #: NY-local ISO-8601 WITH offset, kept as the contract emitted it. Stored as text
    #: because the offset is evidence of which zone was used (HG-23) and a timestamptz
    #: column would normalise it away.
    timestamp_ny: Mapped[str | None] = mapped_column(String, nullable=True)

    #: Append-only ordering per (engine build, instrument, timeframe). A gap means
    #: suppression; a repeat means rewriting.
    sequence_no: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: What the engine decided, for setup_evaluation: TAKE | SKIP | STAND_ASIDE.
    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    #: The FIRST rule that failed on the fixed evaluation path — the attribution key.
    deciding_rule_id: Mapped[str | None] = mapped_column(String, nullable=True)

    engine_version: Mapped[str | None] = mapped_column(String, nullable=True)
    rule_registry_version: Mapped[str | None] = mapped_column(String, nullable=True)

    #: The record verbatim. Source of truth.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        Index("ix_telemetry_type_created", "record_type", "created_at"),
        Index("ix_telemetry_instrument_tf", "instrument", "signal_tf"),
        Index("ix_telemetry_deciding_rule", "deciding_rule_id"),
    )
