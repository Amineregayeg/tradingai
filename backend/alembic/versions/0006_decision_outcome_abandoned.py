"""Allow the ABANDONED decision outcome (KNOWN_ISSUES A11).

A decision that opened a position and whose process then died has no result. Until
now the only way to say that was to leave `outcome = 'OPEN'`, which claims the
opposite — that the trade is still running — and there was no way to tell the two
apart afterwards. Run `7d788ad6` reported "0 trades" for exactly this reason: it
took one, and the record still says OPEN.

`outcome` is guarded by a CHECK constraint listing the legal values, so admitting a
new one is a schema change and not a code change. That constraint is the reason
this migration exists and is also the point of it — the set of things a decision
can have concluded is not something any caller should be able to widen.

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

from alembic import op

from app.models.decision_record import DECISION_OUTCOMES

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_decision_records_outcome"


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "decision_records",
        f"outcome IS NULL OR {_sql_in('outcome', DECISION_OUTCOMES)}",
    )


def downgrade() -> None:
    # Rows already marked ABANDONED would violate the narrower constraint. They
    # become OPEN again — wrong, but it is the value they carried before this
    # migration and downgrading cannot invent a better one.
    op.execute(
        "UPDATE decision_records SET outcome = 'OPEN' WHERE outcome = 'ABANDONED'"
    )
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "decision_records",
        "outcome IS NULL OR "
        + _sql_in("outcome", tuple(v for v in DECISION_OUTCOMES if v != "ABANDONED")),
    )
