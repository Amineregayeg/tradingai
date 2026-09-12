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

#: **FROZEN (`B405`/`B416`), and this one's DOWNGRADE WAS ALREADY EMITTING A CONSTRAINT THAT
#: NEVER EXISTED.**
#:
#: The downgrade derived its target as the LIVE outcome list minus `ABANDONED`. Live is now seven,
#: so that evaluated to six values **including `REJECTED`** — while the real pre-`0006` constraint
#: (created by `0002`) admitted **five** and had never heard of `REJECTED`, which arrived two
#: revisions later at `0008`. Downgrading to `0005` was creating a vocabulary production never had
#: at any point in its history.
#:
#: Measured at this migration's landing commit (`7f51836`, 2026-08-09): six values. The downgrade
#: target is `0002`'s five, WRITTEN OUT rather than derived by subtraction — subtracting from a
#: live list is the defect itself, not merely a spelling of it.
_OUTCOMES_AT_0006: tuple[str, ...] = ("WIN", "LOSS", "BE", "OPEN", "ABSTAINED", "ABANDONED")
_OUTCOMES_AT_0002: tuple[str, ...] = ("WIN", "LOSS", "BE", "OPEN", "ABSTAINED")

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
        f"outcome IS NULL OR {_sql_in('outcome', _OUTCOMES_AT_0006)}",
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
        + _sql_in("outcome", _OUTCOMES_AT_0002),
    )
