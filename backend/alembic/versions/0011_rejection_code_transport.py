"""`VENUE_TRANSPORT` joins the rejection vocabulary (`B403`'s transport half).

`0010` closed `rejection_code` at sixteen values, so a seventeenth is a SCHEMA change and not a
code change — which is the entire point of a closed vocabulary and the reason `0008` exists for
`outcome`. A classifier that could widen its own vocabulary silently would create buckets nobody
notices.

**WHY A SEPARATE CODE RATHER THAN REUSING `VENUE_DIRECTION_UNSUPPORTED`.** Only
`DirectionNotSupported` was caught around `place_order`, so a connection error, an auth rejection,
a rate limit or a 5xx propagated, aborted the bar before the recorder ran, and became one log line.
Giving those the venue-rule code would make **a permanent rule and a temporary failure
indistinguishable — `B375` — inside the field built to prevent exactly that.** One will refuse the
same order forever; the other clears on its own.

**NO BACKFILL.** Existing rows keep whatever they have: `UNCODED_LEGACY` where `0010` put it, or a
code assigned at a decision. There is no row that can be known to be transport retrospectively —
the information was never captured — and inventing one would be the manufactured measurement
`0010`'s docstring refuses at greater length.

Revision ID: 0011
Revises: 0010
"""
from __future__ import annotations

from alembic import op

from app.models.decision_record import REJECTION_CODES

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_decision_records_rejection_code"


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    # Drop and recreate: a CHECK constraint cannot be widened in place. No `ALTER TYPE` and no
    # `CREATE TYPE` anywhere here — `0009` took production down doing that inside a transaction,
    # and the String + CheckConstraint arrangement this table uses is the reason it cannot happen
    # again on this column.
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', REJECTION_CODES)}",
    )


def downgrade() -> None:
    # Rows carrying VENUE_TRANSPORT would violate the narrower constraint. They are NOT rewritten:
    # mapping them to any surviving code would assert a classification no decision site made, and
    # the downgrade would silently manufacture the measurement this column exists to keep honest.
    # A downgrade against such rows fails, loudly, which is the correct outcome.
    narrower = tuple(c for c in REJECTION_CODES if c != "VENUE_TRANSPORT")
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', narrower)}",
    )
