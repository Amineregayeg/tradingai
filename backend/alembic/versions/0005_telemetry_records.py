"""Engine-contract telemetry store (M1).

Creates `telemetry_records`, the evidence store for the Magic Strategy contract.

WHY NOT AN EXTENSION OF `decision_records`
Its shape is fixed by TELEMETRY_SCHEMA.json, which the knowledge team's conformance suite
reads. Bending the existing table to serve both would either distort the contract's shape or
change what the dashboard already depends on, and would leave two ways to answer "what did
the engine decide" that could drift. They are linked by run_id.

The whole record is stored verbatim in `payload`; the columns beside it are duplicates for
querying. The conformance suite is a pure function of stored records, so anything normalised
away is evidence that cannot be produced later.

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_records",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("record_type", sa.String(), nullable=False),
        # Unique: re-emitting a record id would mean a record was rewritten, which the
        # append-only property exists to make impossible rather than merely discouraged.
        sa.Column("record_id", sa.String(), nullable=False, unique=True),
        sa.Column("run_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("instrument", sa.String(), nullable=True),
        sa.Column("signal_tf", sa.String(), nullable=True),
        # Text, not timestamptz: the offset is the evidence of which timezone was used
        # (GATE-023 / HG-23), and a timestamptz column would normalise it away.
        sa.Column("timestamp_ny", sa.String(), nullable=True),
        sa.Column("sequence_no", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("deciding_rule_id", sa.String(), nullable=True),
        sa.Column("engine_version", sa.String(), nullable=True),
        sa.Column("rule_registry_version", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_telemetry_records_run_id", "telemetry_records", ["run_id"])
    op.create_index("ix_telemetry_type_created", "telemetry_records", ["record_type", "created_at"])
    op.create_index("ix_telemetry_instrument_tf", "telemetry_records", ["instrument", "signal_tf"])
    op.create_index("ix_telemetry_deciding_rule", "telemetry_records", ["deciding_rule_id"])


def downgrade() -> None:
    op.drop_index("ix_telemetry_deciding_rule", table_name="telemetry_records")
    op.drop_index("ix_telemetry_instrument_tf", table_name="telemetry_records")
    op.drop_index("ix_telemetry_type_created", table_name="telemetry_records")
    op.drop_index("ix_telemetry_records_run_id", table_name="telemetry_records")
    op.drop_table("telemetry_records")
