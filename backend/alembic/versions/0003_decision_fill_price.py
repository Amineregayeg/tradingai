"""Add decision_records.fill_price — the price actually paid.

`signal_entry` records what the strategy asked for. Nothing recorded what it
actually got, so every R was computed against a price that was never paid: the
live path sized from the FVG edge and then sent a MARKET order, which fills at
the mark.

This column also revives the feedback loop's Rule B (adverse fill slippage),
which has been dormant since it was written — `feedback._slippage_r()` looks for
a fill price on the record and, finding none, returned None on every row.

Nullable with no backfill, deliberately: rows written before this existed have no
recoverable fill price, and inventing one — say by copying signal_entry — would
manufacture a slippage of exactly zero for every historical decision and teach
the feedback loop that fills are perfect. Readers fall back to signal_entry and
treat slippage as unknown, which is the truth.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None

TABLE = "decision_records"
COLUMN = "fill_price"


def _has_column() -> bool:
    """True if the column already exists.

    The deploy path (`deploy_migrate.py`) can bootstrap a fresh database from
    offline SQL and then run `alembic upgrade head` over it, so a migration can
    meet a schema that already contains its target. Adding it twice aborts the
    whole upgrade, taking the API container down on boot.
    """
    bind = op.get_bind()
    return COLUMN in {c["name"] for c in sa.inspect(bind).get_columns(TABLE)}


def upgrade() -> None:
    if _has_column():
        return
    op.add_column(TABLE, sa.Column(COLUMN, sa.Numeric(18, 6), nullable=True))


def downgrade() -> None:
    if not _has_column():
        return
    op.drop_column(TABLE, COLUMN)
