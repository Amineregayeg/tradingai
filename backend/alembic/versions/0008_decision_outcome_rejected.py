"""REJECTED outcome + its reason column, and the two sizing inputs (`B271` + `B279`, `T-0084`).

A signal the strategy PRODUCED and execution REFUSED had nowhere to go. Neither existing
writer could take it: `_record_signal_decision` asserts `OPEN` with `sized_units`,
`fill_price` and `expected_r` from a fill this bar does not have, and `_record_abstention`
asserts `abstained=True, outcome=ABSTAINED` — but the strategy DID produce a signal.

`ABSTAINED` was the tempting option and the dangerous one. It would make a bar where the
strategy committed indistinguishable from one where the detector never fired — `B215`'s
collapse rebuilt inside the one population that is currently correct, which is `B268`'s
denominator. So `REJECTED` is its own value, on `ABANDONED`'s own argument: *"deliberately
its own value rather than BE. Folding it into breakeven would put a fabricated zero into the
feedback loop's population."*

`outcome` is guarded by a CHECK constraint listing the legal values, so admitting a new one
is a schema change and not a code change. **That constraint is the reason this migration
exists and is also the point of it** — the set of things a decision can have concluded is not
something any caller should be able to widen. A typo'd outcome fails at insert rather than
entering the corpus.

The reason gets a COLUMN rather than a line in `reasons`, which `_with_exit_plan`'s own
docstring calls *"a JSON list nothing parses"* and which `B270` criticised `B268` for
parsing. Putting it only there would recreate the problem in the change that fixes it.

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

#: **FROZEN (`B405`/`B416`).** Measured at this migration's landing commit (`e8dd8da`,
#: 2026-08-24): seven values — `0006`'s six plus `REJECTED`.
#:
#: **THIS ONE'S DOWNGRADE WAS CORRECT ONLY BY COINCIDENCE.** It derived its target as the live
#: list minus `REJECTED`, which equals `0006`'s six **only while the live list is exactly seven**.
#: The moment an eighth value joins — which is what `T-0143` does — that subtraction returns seven
#: and the "`0006` vocabulary" gains a value `0006` never had. `0006`'s equivalent was already
#: wrong; this one was one addition away, and right-by-coincidence is not a property worth keeping.
_OUTCOMES_AT_0008: tuple[str, ...] = (
    "WIN", "LOSS", "BE", "OPEN", "ABSTAINED", "ABANDONED", "REJECTED",
)
_OUTCOMES_AT_0006: tuple[str, ...] = ("WIN", "LOSS", "BE", "OPEN", "ABSTAINED", "ABANDONED")

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_decision_records_outcome"


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.add_column(
        "decision_records",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )
    # `B279`. `size_position(acct.equity, sig.risk_pct, ...)` — NEITHER input was recorded
    # anywhere, and `prop_firm_snapshots`, which has an equity column, has zero rows. TWO
    # columns because one re-breaks: `risk_pct` is reconstructible today only because it is
    # the constant 1%, and wiring the risk matrix makes it per-trade variable.
    #
    # Numeric(18, 6) and NOT Numeric(14, 2): the finding this preserves lived in the fourth
    # decimal, 5000.9197 against 5000.00.
    #
    # Nullable, and NOT backfilled — see the module docstring's note on inventing rows.
    op.add_column(
        "decision_records",
        sa.Column("sizing_equity", sa.Numeric(18, 6), nullable=True),
    )
    op.add_column(
        "decision_records",
        sa.Column("sizing_risk_pct", sa.Numeric(9, 6), nullable=True),
    )
    # `B280`. THE DIVISOR. `size_position` takes four arguments; recording two left the
    # reconstruction exact only where `fill == sizing_price`, which is a property of
    # PaperBroker rather than of the system. Measured: 50 ticks of slip puts the recomputed
    # size 4.76% out, and the row cannot say it happened.
    op.add_column(
        "decision_records",
        sa.Column("sizing_price", sa.Numeric(18, 6), nullable=True),
    )
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "decision_records",
        f"outcome IS NULL OR {_sql_in('outcome', _OUTCOMES_AT_0008)}",
    )


def downgrade() -> None:
    # Rows already marked REJECTED would violate the narrower constraint. They become
    # ABSTAINED — WRONG, and knowably wrong: it is the collapse this migration exists to
    # prevent. It is chosen anyway because downgrading cannot invent a better value and
    # ABSTAINED is the only existing outcome that describes "no position resulted".
    #
    # `abstained` is deliberately left FALSE on those rows, so the collapse is still
    # detectable afterwards: a row with outcome=ABSTAINED and abstained=False is one this
    # downgrade rewrote, and nothing else in the system produces that combination.
    op.execute(
        "UPDATE decision_records SET outcome = 'ABSTAINED' WHERE outcome = 'REJECTED'"
    )
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "decision_records",
        "outcome IS NULL OR "
        + _sql_in("outcome", _OUTCOMES_AT_0006),
    )
    op.drop_column("decision_records", "rejection_reason")
    op.drop_column("decision_records", "sizing_price")
    op.drop_column("decision_records", "sizing_risk_pct")
    op.drop_column("decision_records", "sizing_equity")
