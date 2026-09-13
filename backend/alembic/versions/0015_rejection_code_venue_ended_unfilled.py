"""`VENUE_ENDED_UNFILLED` joins the rejection vocabulary — the venue took the order, then ended it unfilled.

`B427`. `AlpacaAdapter.place_order` now RESOLVES the order toward a terminal state before returning,
instead of reporting the submission acknowledgement. One terminal outcome had no true code: the venue
acknowledged the order and then cancelled, expired or rejected it with a READABLE filled quantity of
exactly ZERO. No position exists, so REJECTED is true — and a halt, the only other honest answer,
would stop the engine over a certain fact (manager's ruling C). An UNREADABLE quantity is not this
code: exposure unknown stays UNRESOLVED and halts.

**THIS MIGRATION ONLY WIDENS.** It drops the rejection-code CHECK and recreates it with `0014`'s
nineteen values plus this one; it touches no other constraint, column, table or row. That is what
keeps a rollback of the deploy that carries it CODE-ONLY: the old code never writes the new value,
and the wider CHECK admits everything the old code does. An arm asserts both halves — the
operations and the superset.

**DEPLOY ORDER IS LOAD-BEARING AND FAILS SILENTLY IF SPLIT (`B410`).** Code emitting this value
against a database still at `0014` would violate the CHECK, and `_record_rejected_signal` swallows
every exception by design — the order correctly refused and the row silently lost. So this lands in
the SAME COMMIT as the code that writes it, as `0012` and `0014` did.
"""
from __future__ import annotations

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_decision_records_rejection_code"

#: FROZEN at this revision (`B405`): written out, never derived from the live model.
_CODES_AT_0015: tuple[str, ...] = (
    "NO_REFERENCE_PRICE", "DEGENERATE_STOP", "ENTRY_DRIFT", "THROUGH_STOP",
    "NON_POSITIVE_SIZE", "VENUE_DIRECTION_UNSUPPORTED", "MIN_SIZE",
    "PROTECTION_NOT_ACCEPTED", "VENUE_ENDED_UNFILLED",
    "PROP_FIRM_TARGET_REACHED", "PROP_FIRM_HALTED_DAILY_LOSS",
    "PROP_FIRM_HALTED_MAX_DRAWDOWN", "PROP_FIRM_HALTED",
    "PROP_FIRM_WOULD_BREACH_DAILY_LOSS", "PROP_FIRM_WOULD_BREACH_MAX_DRAWDOWN",
    "BROKER_UNAVAILABLE", "VENUE_TRANSPORT", "VENUE_RAISED",
    "UNCODED_LEGACY", "UNCLASSIFIED",
)

#: The DOWNGRADE target: exactly `0014`'s nineteen.
_CODES_AT_0014: tuple[str, ...] = tuple(c for c in _CODES_AT_0015 if c != "VENUE_ENDED_UNFILLED")


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', _CODES_AT_0015)}",
    )


def downgrade() -> None:
    # Rows carrying VENUE_ENDED_UNFILLED would violate the narrower constraint and are NOT rewritten:
    # mapping them onto any surviving code would assert a classification no decision site made. A
    # downgrade against such rows fails loudly — the shape `0011`, `0012` and `0014` document. Run
    # here only against the unit probe that reads these tuples, not against a real server.
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', _CODES_AT_0014)}",
    )
