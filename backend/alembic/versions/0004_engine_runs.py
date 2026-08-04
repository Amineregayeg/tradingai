"""Add engine_runs, plus run_id on trades and decision_records.

Resetting the engine must produce a genuinely clean slate — an equity curve and
trade count starting at zero. Without run scoping the only options were to leave
old rows visible beside a reset balance (incoherent numbers) or to delete them
(destroying `decision_records`, which are the evidence of whether the strategy
works). Scoping to a run gives a clean slate while deleting nothing.

BACKFILL: existing rows are assigned LEGACY_RUN_ID and one matching active
`engine_runs` row is created. Without that, deploying this migration would make
every existing trade vanish from the dashboard the moment run filtering went
live — indistinguishable from data loss, and alarming for exactly the wrong
reason.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None

LEGACY_RUN_ID = "00000000-0000-0000-0000-000000000001"


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    # Idempotent throughout: deploy_migrate.py can bootstrap a fresh database
    # from offline SQL and then run `alembic upgrade head` over it, so a
    # migration can meet a schema that already contains its objects. Failing
    # there takes the api container down on boot.
    if "engine_runs" not in _tables():
        op.create_table(
            "engine_runs",
            sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
            sa.Column("started_at", sa.DateTime(timezone=True),
                      nullable=False, server_default=sa.func.now()),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("label", sa.String(), nullable=True),
        )

    for table in ("trades", "decision_records"):
        if table not in _tables():
            continue
        if "run_id" not in _cols(table):
            op.add_column(table, sa.Column("run_id", sa.UUID(as_uuid=True), nullable=True))
            op.create_index(f"ix_{table}_run_id", table, ["run_id"])

    # Seed the legacy run and adopt every existing row into it, so nothing
    # disappears from the dashboard when run filtering takes effect.
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT count(*) FROM engine_runs WHERE id = :i"), {"i": LEGACY_RUN_ID}
    ).scalar()
    if not existing:
        # The timestamp is bound from Python rather than using SQL now():
        # now() is Postgres-specific, and a migration that only runs on the
        # production dialect cannot be tested anywhere else.
        from datetime import datetime, timezone

        bind.execute(
            sa.text(
                "INSERT INTO engine_runs (id, started_at, ended_at, label, note) "
                "VALUES (:i, :ts, NULL, :l, :n)"
            ),
            {
                "ts": datetime.now(tz=timezone.utc),
                "i": LEGACY_RUN_ID,
                "l": "run-1",
                "n": "Everything recorded before runs existed. Left ACTIVE so the "
                     "engine adopts it on first start and no history disappears.",
            },
        )
    for table in ("trades", "decision_records"):
        if table in _tables() and "run_id" in _cols(table):
            bind.execute(
                sa.text(f"UPDATE {table} SET run_id = :i WHERE run_id IS NULL"),
                {"i": LEGACY_RUN_ID},
            )


def downgrade() -> None:
    for table in ("trades", "decision_records"):
        if table in _tables() and "run_id" in _cols(table):
            op.drop_index(f"ix_{table}_run_id", table_name=table)
            op.drop_column(table, "run_id")
    if "engine_runs" in _tables():
        op.drop_table("engine_runs")
