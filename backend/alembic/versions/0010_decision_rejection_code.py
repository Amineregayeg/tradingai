"""`rejection_code` beside the prose, and existing rows marked UNCODED_LEGACY (`B392`, `T-0138`).

`GROUP BY signal_dir` over `outcome=REJECTED` cannot answer *M shorts refused by venue*, because
`rejection_reason` is free `Text` and `outcome` is a single `REJECTED` — so a venue refusal and a
drift rejection are the same row, and the only discriminator is PROSE. **A count keyed on a
sentence the venue chose returns a confident zero the day the wording changes rather than failing.**

**THE BACKFILL IS THE ONE-WAY DOOR, AND IT IS THE WHOLE RISK OF THIS FILE.**

Existing rows get `UNCODED_LEGACY` — **never a live code, and never a value parsed out of the
prose.** Both alternatives are irreversible in the same way: once a pre-existing row carries a code
that a decision site could also have produced, **nothing can ever tell it from a row that was
classified at the decision**. There is no second chance and no arm written afterwards recovers it.

Parsing the prose to backfill would be worse than a constant, not better: a count manufactured once
from vocabulary the venue chose, thereafter indistinguishable from a measurement. If a backfill is
ever wanted later, the code must carry its own provenance — `recorded` vs `inferred` — or a parsed
count becomes unreadable as a measured one.

**TWO UNKNOWNS, AND THEY MUST NOT SHARE A VALUE.** `UNCODED_LEGACY` predates the field: knowably
unknowable, **finite and shrinking**, a migration marker that decays to zero on its own.
`UNCLASSIFIED` is a NEW rejection nothing coded — a defect that must ALARM. Collapsing them means
the shrinking bucket never decays, so the alarm never fires, and the failure stays invisible for
exactly as long as the legacy rows exist. That is `B215`'s could-not-ask/did-not collapse on a new
field.

**Scope, measured rather than assumed:** `rejection_reason` is nullable `Text` with exactly ONE
writer (`crypto_loop.py:_record_rejected_signal`), so the surface this touches is small and
knowable.

**`0009`'s lesson is applied here.** That migration took production down by adding a value to a
Postgres ENUM inside a transaction. This column is `String` + `CheckConstraint` — no `CREATE TYPE`,
no `ALTER TYPE`, nothing that needs its own transaction — which is the arrangement the whole
`decision_records` table already uses and the reason it does.

Revision ID: 0010
Revises: 0009
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.decision_record import (
    OUTCOME_REJECTED,
    REJECTION_CODES,
    REJECTION_UNCODED_LEGACY,
)

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_decision_records_rejection_code"


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.add_column(
        "decision_records",
        sa.Column("rejection_code", sa.String(), nullable=True),
    )

    # BACKFILL ONLY ROWS THAT ARE ACTUALLY REJECTIONS.
    #
    # Scoped to `outcome = REJECTED` on purpose: an ABSTAINED or a WIN has no rejection to code,
    # and giving them `UNCODED_LEGACY` would put rows into a bucket meaning *"a rejection we
    # cannot classify"* that were never rejections at all. **The denominator this field exists to
    # make countable would then start out wrong** — inflated by every non-rejection ever written.
    op.execute(
        f"UPDATE decision_records "
        f"SET rejection_code = '{REJECTION_UNCODED_LEGACY}' "
        f"WHERE outcome = '{OUTCOME_REJECTED}' AND rejection_code IS NULL"
    )

    # The vocabulary is CLOSED at the database, like every other closed column on this table. A
    # value the constant allows and the database refuses — or the reverse — is a difference only a
    # real insert can find (`T-0084`), and a classifier that invents a code must fail at insert
    # rather than quietly creating a bucket nobody notices.
    op.create_check_constraint(
        _CONSTRAINT,
        "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', REJECTION_CODES)}",
    )


def downgrade() -> None:
    # Dropping the column DESTROYS every classification made at a decision site, and they are not
    # recoverable from `rejection_reason` — two decision sites emit one identical string, which is
    # the fact this column exists for. Recorded here rather than discovered later.
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.drop_column("decision_records", "rejection_code")
