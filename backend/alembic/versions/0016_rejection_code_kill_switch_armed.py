"""`KILL_SWITCH_ARMED` joins the rejection vocabulary — the switch was armed when the order reached the send.

`B442`. Every adapter the loop binds now reads the kill switch AT SUBMISSION (`app.core.kill_switch_state`),
and `ExecutionService` turns the refusal into a REJECTED result with this code. Before, an entry that had
passed the loop's gate before the switch was pulled was sent anyway — a position opened after the switch
reported the book closed. No position exists and nothing was sent, so REJECTED is true; the code says WHY.

**THIS MIGRATION ONLY WIDENS.** It drops the rejection-code CHECK and recreates it with `0015`'s twenty
values plus this one; it touches no other constraint, column, table or row. That is what keeps a rollback
of the deploy that carries it CODE-ONLY: the old code never writes the new value, and the wider CHECK
admits everything the old code does. An arm asserts both halves — the operations and the superset.

**DEPLOY ORDER IS LOAD-BEARING AND FAILS SILENTLY IF SPLIT (`B410`).** Code emitting this value against a
database still at `0015` would violate the CHECK, and `_record_rejected_signal` swallows every exception by
design — the entry correctly refused and the row silently lost. So this lands in the SAME COMMIT as the code
that writes it, as `0012`, `0014` and `0015` did.

**NOT RUN AGAINST A SERVER HERE** (review's K2-16): the arms read these tuples and record the operations; a
downgrade against rows carrying the new code fails loudly on Postgres (constraint validation) and is not
exercised in this tree.
"""
from __future__ import annotations

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_decision_records_rejection_code"

#: FROZEN at this revision (`B405`): written out, never derived from the live model.
_CODES_AT_0016: tuple[str, ...] = (
    "NO_REFERENCE_PRICE", "DEGENERATE_STOP", "ENTRY_DRIFT", "THROUGH_STOP",
    "NON_POSITIVE_SIZE", "VENUE_DIRECTION_UNSUPPORTED", "MIN_SIZE",
    "PROTECTION_NOT_ACCEPTED", "VENUE_ENDED_UNFILLED", "KILL_SWITCH_ARMED",
    "PROP_FIRM_TARGET_REACHED", "PROP_FIRM_HALTED_DAILY_LOSS",
    "PROP_FIRM_HALTED_MAX_DRAWDOWN", "PROP_FIRM_HALTED",
    "PROP_FIRM_WOULD_BREACH_DAILY_LOSS", "PROP_FIRM_WOULD_BREACH_MAX_DRAWDOWN",
    "BROKER_UNAVAILABLE", "VENUE_TRANSPORT", "VENUE_RAISED",
    "UNCODED_LEGACY", "UNCLASSIFIED",
)

#: The DOWNGRADE target: exactly `0015`'s twenty.
_CODES_AT_0015: tuple[str, ...] = tuple(c for c in _CODES_AT_0016 if c != "KILL_SWITCH_ARMED")


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', _CODES_AT_0016)}",
    )


def downgrade() -> None:
    # Rows carrying KILL_SWITCH_ARMED would violate the narrower constraint and are NOT rewritten: mapping
    # them onto any surviving code would assert a classification no decision site made. A downgrade against
    # such rows fails loudly — the shape `0011`, `0012`, `0014` and `0015` document.
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', _CODES_AT_0015)}",
    )
