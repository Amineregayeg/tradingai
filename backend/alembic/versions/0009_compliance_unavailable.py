"""`UNAVAILABLE` compliance state, and snapshot figures that may be absent (`B378`).

**THE DEFECT THIS EXISTS FOR.** `observe_sync` skipped an adapter it could not reach, so no
`PropFirmSnapshot` was written and the compliance state did not update. The surface reads snapshot
HISTORY, so **a missing snapshot is indistinguishable from a quiet period** — the drawdown monitor
for a funded account showed the last good value indefinitely, every two minutes, and a prop-firm
breach closes the account.

**WHY A NEW STATE RATHER THAN REUSING ONE.** `UNAVAILABLE` is not a compliance verdict, it is the
absence of one. Folding *we did not evaluate* into `ACTIVE` makes a stale all-clear identical to a
fresh one — `B215`'s collapse on the control that stands in front of the breach. Same argument
`0008` made for `REJECTED` over `ABSTAINED`.

**WHY THE FIGURES BECOME NULLABLE, which is the load-bearing half.** An `UNAVAILABLE` row must
carry no equity, balance or loss. Writing the last known values in would BE the defect — *showing
the last good value*, now with a fresh timestamp. Writing zeros would be worse: a manufactured
drawdown on the exact number a breach is computed from. **NULL is the only value that says
nothing.** Existing rows are untouched and no backfill is performed; a row written before this
migration was a real evaluation and still is.

Revision ID: 0009
Revises: 0008
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels = None
depends_on = None

_FIGURES = ("equity", "balance", "daily_loss", "total_loss")


def upgrade() -> None:
    bind = op.get_bind()
    # `getattr`, because the schema suite REPLAYS these offline against a bind with no dialect —
    # and a migration that can only run against a live connection is one the suite cannot check.
    # The enum step is PostgreSQL-only; everything below it is portable and runs either way.
    if getattr(getattr(bind, "dialect", None), "name", None) == "postgresql":
        # `ALTER TYPE ... ADD VALUE` DOES run inside a transaction here — `alembic/env.py` wraps
        # it — and `IF NOT EXISTS` guards a RE-RUN rather than the transaction. PG12+ permits the
        # statement in a transaction **provided the new value is not USED in the same one.**
        #
        # THIS COMMENT USED TO END "and nothing below uses it". That was TRUE WHEN WRITTEN and
        # false by the time it shipped: the `CheckConstraint` added afterwards names 'UNAVAILABLE'
        # in its predicate. **The analysis was not re-run when the file changed**, and production
        # went down on the sentence rather than on the code. The `COMMIT` below is what makes the
        # remaining half of the claim true.
        #
        # `deploy_migrate.py` warns: *"0002+ are hand-written enum-free… If a future revision adds
        # an enum, revisit this."* READ AND CHECKED: that script strips duplicate CREATE TYPE, and
        # `ADD VALUE` is not `CREATE TYPE`, so the stripping is not implicated. Recorded because a
        # note written to be triggered is worthless if nobody records having read it.
        op.execute("ALTER TYPE compliance_t ADD VALUE IF NOT EXISTS 'UNAVAILABLE'")
        # ------------------------------------------------------------------------------
        # **COMMIT HERE OR THE CHECK CONSTRAINT BELOW CANNOT REFERENCE THE VALUE.**
        #
        # This migration failed in production with
        # `UnsafeNewEnumValueUsageError: unsafe use of new value "UNAVAILABLE"`. PG12+ permits
        # `ALTER TYPE ... ADD VALUE` inside a transaction **provided the value is not USED in the
        # same one** — and the constraint's predicate uses it. The earlier analysis was correct
        # when written and went stale when the constraint was added: nobody re-ran the
        # transaction argument after the file changed.
        #
        # SPLITTING INTO 0009 + 0010 DOES NOT FIX IT, which is worth stating because it is the
        # obvious remedy. `env.py` does `with context.begin_transaction(): context.run_migrations()`
        # — **ONE transaction for ALL migrations** — so a constraint in 0010 would still run in the
        # same transaction as this ALTER. It would need `transaction_per_migration=True`, which
        # changes the semantics of every migration in the tree to fix one.
        #
        # `BEGIN` immediately after, so the nullability changes and the constraint remain ATOMIC
        # together. Committing and leaving the rest outside a transaction would let a constraint
        # failure land on top of four already-applied column alterations.
        op.execute("COMMIT")
        op.execute("BEGIN")

    for column in _FIGURES:
        op.alter_column(
            "prop_firm_snapshots", column,
            existing_type=sa.Numeric(14, 2),
            nullable=True,
        )

    # THE CONSTRAINT THAT MAKES THE DOWNGRADE'S REASONING TRUE RATHER THAN CURRENTLY-TRUE.
    # Nullable columns are now nullable for EVERY state, so "the rows this migration created" and
    # "the rows with NULL figures" coincide only while an invariant holds that nothing enforces.
    # This enforces it: figures are absent IF AND ONLY IF the state is UNAVAILABLE.
    op.create_check_constraint(
        "ck_prop_firm_snapshots_unavailable_has_no_figures",
        "prop_firm_snapshots",
        "(state = 'UNAVAILABLE') = (equity IS NULL AND balance IS NULL "
        "AND daily_loss IS NULL AND total_loss IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_prop_firm_snapshots_unavailable_has_no_figures",
                       "prop_firm_snapshots", type_="check")
    # DELETE BY STATE, NOT BY `equity IS NULL`. The two coincide today and they do not MEAN the
    # same thing: this downgrade removes *the rows this migration made possible*, and any future
    # path writing a partial row for another state would be deleted by a statement that believed
    # it was removing only unevaluated ones. The constraint above makes them equivalent while it
    # exists; the predicate should say what it means anyway.
    op.execute("DELETE FROM prop_firm_snapshots WHERE state = 'UNAVAILABLE'")
    for column in _FIGURES:
        op.alter_column(
            "prop_firm_snapshots", column,
            existing_type=sa.Numeric(14, 2),
            nullable=False,
        )
    # PostgreSQL cannot drop a value from an enum type; `UNAVAILABLE` remains declared and unused.
