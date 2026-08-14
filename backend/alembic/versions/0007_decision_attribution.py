"""Record WHICH ENGINE decided, and which rule — separably (T-0013, B31).

M9's exit criterion is "a decision record whose `deciding_rule_id` is a real
registry id, from a trade the engine actually took". That was unreachable for a
reason unrelated to how many rules exist: `decision_records` had no such column.
The DISCARDED shadow verdict has carried an attribution since M9 Stage A; the
acted-on decision that moves money has never carried one.

WHY TWO COLUMNS
A single nullable `deciding_rule_id` makes NULL mean three things at once — ICT
decided, the rule engine decided and the decider was LOST, or the rule engine
decided and no rule owned the verdict. The middle one is a defect and the others
are normal. `decided_by` separates them, and it is written independently of
whether an id was captured, so a plumbing failure in the rule path cannot
silently re-label the row as ICT-decided and delete the evidence of itself.

The two defect states are then found by one query each:

    SELECT * FROM decision_records
     WHERE decided_by = 'RULE_ENGINE' AND deciding_rule_id IS NULL;  -- decider lost
    SELECT * FROM decision_records WHERE decided_by = 'UNSET';       -- nobody said

WHY THE DEFAULT IS `UNSET` AND NOT `ICT`
Defaulting a new column to a REAL attribution would make "every decision names its
decider" satisfiable by a default — B31's shape, in the columns added to prevent
B31. The failure is not a missing row but a false one: after the cutover, a write
path that forgets this column would record a rule-engine decision as ICT-decided,
and the first query above would never find it because the row claims ICT.

WHY NEITHER DEFECT STATE IS FORBIDDEN BY A CONSTRAINT
Both write sites in `crypto_loop.py` swallow bookkeeping exceptions rather than
kill the trading loop. A constraint rejecting a defect state — or a NOT NULL with
no default — would make the insert raise, the handler would swallow it, and the
row would be DROPPED. The corpus would lose exactly the evidence that the defect
occurred. Storing it and finding it by query beats refusing it and losing it.

BACKFILL
Existing rows are set to ICT by an explicit UPDATE in the body, NOT by borrowing
the column default. Those are two different questions — "what were the old rows"
and "what happens when a new write forgets" — and one value must not answer both.
The backfill is true rather than convenient: every decision in this table was made
by the ICT path, because the rule engine's verdict has never been acted on. No
rule id is invented for any historical row.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models.decision_record import (
    DECIDED_BY_ICT,
    DECIDED_BY_RULE_ENGINE,
    DECIDED_BY_UNSET,
    DECIDED_BY_VALUES,
)

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None

_CK_DECIDED_BY = "ck_decision_records_decided_by"
_CK_ONLY_RULE_ENGINE_NAMES = "ck_decision_records_only_rule_engine_names_a_rule"
_IX_RULE = "ix_decision_records_deciding_rule"
_IX_BY = "ix_decision_records_decided_by"


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    # The column arrives defaulting to UNSET — which is what a FUTURE write that
    # forgets the attribution must record. The existing rows are a different
    # question with a different answer, and they are backfilled explicitly below
    # rather than by borrowing this default. One value must not answer both.
    op.add_column(
        "decision_records",
        sa.Column(
            "decided_by",
            sa.String(),
            nullable=False,
            server_default=DECIDED_BY_UNSET,
        ),
    )
    op.add_column(
        "decision_records",
        sa.Column("deciding_rule_id", sa.String(), nullable=True),
    )

    # CRITERION 7 — the backfill, explicit and separate from the default above.
    # Every row already in this table WAS decided by the ICT path: the rule
    # engine's verdict has never been acted on, so there is no row it could have
    # decided. That is knowable and true, so it is stated rather than left as
    # UNSET, which would claim we do not know.
    #
    # It adds a value where there was no column; it overwrites nothing
    # (`test_reset_deletes_nothing` — decision_records are evidence). No rule id
    # is invented for any historical row: `deciding_rule_id` stays NULL for all
    # of them, which reads as case 1 and not as a lost decider, because
    # `decided_by` says ICT.
    op.execute(
        f"UPDATE decision_records SET decided_by = '{DECIDED_BY_ICT}' "
        f"WHERE decided_by = '{DECIDED_BY_UNSET}'"
    )

    op.create_check_constraint(
        _CK_DECIDED_BY,
        "decision_records",
        _sql_in("decided_by", DECIDED_BY_VALUES),
    )
    op.create_check_constraint(
        _CK_ONLY_RULE_ENGINE_NAMES,
        "decision_records",
        f"decided_by = '{DECIDED_BY_RULE_ENGINE}' OR deciding_rule_id IS NULL",
    )

    op.create_index(_IX_RULE, "decision_records", ["deciding_rule_id"])
    op.create_index(_IX_BY, "decision_records", ["decided_by"])


def downgrade() -> None:
    # Dropping the columns discards attribution rather than corrupting it. There
    # is no narrower previous state to restore — before this migration the
    # information did not exist in any form, so unlike 0006 there is no value to
    # rewrite rows back to.
    op.drop_index(_IX_BY, table_name="decision_records")
    op.drop_index(_IX_RULE, table_name="decision_records")
    op.drop_constraint(_CK_ONLY_RULE_ENGINE_NAMES, "decision_records", type_="check")
    op.drop_constraint(_CK_DECIDED_BY, "decision_records", type_="check")
    op.drop_column("decision_records", "deciding_rule_id")
    op.drop_column("decision_records", "decided_by")
