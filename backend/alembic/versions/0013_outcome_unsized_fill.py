"""`UNSIZED_FILL` joins the outcome vocabulary — the venue filled something we cannot measure.

`B413`/`T-0143`. A market order can come back `PARTIALLY_FILLED` with no usable filled quantity, so
a position exists at the venue whose size we cannot establish. The run HALTS, and the decision that
produced it needs a durable record.

**IT NEEDS ITS OWN VALUE because all three nearest neighbours are a different fact.** `REJECTED`
says execution refused the signal — nothing was refused, the venue accepted the order and acted on
it. `OPEN` says a position exists at a known size, and `sized_units` is what the partial-close
accounting reads; we do not have that number, which is the entire condition. `ABANDONED` says a
position died before closing; this one may still be open and nobody knows. Same argument
`ABANDONED` and `REJECTED` each made for themselves.

**WHAT THIS REVISION IS FOR.** Before it, the loop had nowhere truthful to put the event: it wrote
`outcome=REJECTED`, `rejection_code=UNCLASSIFIED` for an order the venue had **partly filled** — an
affirmatively false row rather than a missing one, which is worse, because a row of the wrong shape
reads as coverage (`B399`).

**DEPLOY ORDER IS LOAD-BEARING AND FAILS SILENTLY IF SPLIT (`B410`).** Production's outcome CHECK
comes from `0008` and closes the vocabulary at seven. Code emitting `UNSIZED_FILL` before this
migration runs would violate the constraint, and the loop's recorder swallows by design — so the
halt would happen correctly and its record would vanish. This lands in the SAME COMMIT as the code
that writes it. Within one deploy the ordering is safe: `compose.vps.yaml`'s api command begins
`set -e` and runs `deploy_migrate.py` before `exec uvicorn`, so a failed migration stops the
container rather than serving un-migrated.

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_decision_records_outcome"

#: **FROZEN (`B405`/`B416`). THE EIGHT OUTCOMES THIS MIGRATION CREATES**, written out rather than
#: imported from `DECISION_OUTCOMES`.
#:
#: `0002`, `0006`, `0007` and `0008` all imported the live list and were frozen in this same commit
#: — and two of them were ALREADY WRONG, not merely at risk. `0002`'s CHECK was created with five
#: outcomes and a replay was producing seven; `0006`'s downgrade derived "the `0005` vocabulary" as
#: the live list minus `ABANDONED`, which evaluated to six values including `REJECTED` — a value
#: revision `0005` never knew. **Adding `UNSIZED_FILL` to the live list before that freeze would
#: have widened all three of their constraints by another member**, which is why the freeze went
#: first in the same commit.
_OUTCOMES_AT_0013: tuple[str, ...] = (
    "WIN", "LOSS", "BE", "OPEN", "ABSTAINED", "ABANDONED", "REJECTED", "UNSIZED_FILL",
)

#: What `0008` left behind — this migration's downgrade target, written out rather than derived as
#: "the live list minus one". That subtraction is the defect itself, not a spelling of it.
_OUTCOMES_AT_0008: tuple[str, ...] = (
    "WIN", "LOSS", "BE", "OPEN", "ABSTAINED", "ABANDONED", "REJECTED",
)


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    # Drop and recreate: a CHECK cannot be widened in place. No `CREATE TYPE`/`ALTER TYPE` — that
    # took production down in `0009`, and String + CheckConstraint is why it cannot recur here.
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "decision_records",
        f"outcome IS NULL OR {_sql_in('outcome', _OUTCOMES_AT_0013)}",
    )


def downgrade() -> None:
    # Rows carrying UNSIZED_FILL would violate the narrower constraint and are NOT rewritten:
    # mapping them onto any surviving outcome would assert something no decision site concluded,
    # and the nearest candidates are each a different fact. A downgrade against such rows fails
    # loudly, which is correct — the same shape `0011` and `0012` document.
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "decision_records",
        f"outcome IS NULL OR {_sql_in('outcome', _OUTCOMES_AT_0008)}",
    )
