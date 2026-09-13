"""`PROTECTION_NOT_ACCEPTED` joins the rejection vocabulary — the venue would not take the stop.

`B429`. `AlpacaAdapter.place_order` received `request.sl` and `request.tp` and **discarded both**:
a plain `MarketOrderRequest`, no bracket, nothing sent to the venue. And the only SL/TP enforcement
in this codebase is `PaperBroker.on_tick` and `cft_sim.on_tick`, both simulators — `AlpacaAdapter`
has no `on_tick` at all (`B428`). So a live position there had **no stop at the venue and no stop
in process**, while `execution/service.py:174` sized that position FROM the stop and `:166` refused
to trade when price was already through it. The risk model was computed from a stop nothing placed.

The fix attaches the protection and then reads the response back. Three outcomes:

    venue refuses the attachment   -> raises, no position, loud            (already safe)
    venue accepts it               -> the stop exists at the venue         (the happy path)
    venue accepts the ORDER and
    ignores the ATTACHMENT         -> cancel the entry, close any position, OBSERVE flat;
                                      only on observed flat does THIS CODE go on the row —
                                      anything short of observed flat halts instead

**WHY ITS OWN CODE, and not `VENUE_TRANSPORT` or `VENUE_DIRECTION_UNSUPPORTED`.** `MIN_SIZE`'s
argument one migration along: transport says *transient, it will clear*; direction-unsupported
names a different capability. This is a venue that will refuse the same order every time until the
protection is placeable, and telling an operator which of those three worlds they are in is the
entire value of the column (`B375`).

**DEPLOY ORDER IS LOAD-BEARING AND FAILS SILENTLY IF SPLIT (`B410`).** Production's CHECK closes the
vocabulary at eighteen values without this one. If code emitting `PROTECTION_NOT_ACCEPTED` reached
production before this migration, the insert would violate the constraint — and
`_record_rejected_signal` swallows every exception by design (*"never let bookkeeping kill the
loop"*). The order would be correctly refused and **the row silently lost**. This migration
therefore lands in the SAME COMMIT as the code that writes it, exactly as `0012` did.

**WHAT IS NOT CLAIMED HERE.** Whether Alpaca accepts a bracket on CRYPTO is unestablished. The SDK
imposes no asset-class restriction, so the answer lives on the server and nothing in this
repository can reach it. This code exists so that the unknown fails LOUDLY and with a name, not
because the third outcome above has been observed.
"""
from __future__ import annotations

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_decision_records_rejection_code"

#: **FROZEN (`B405`). THE NINETEEN CODES THIS MIGRATION CREATES**, written out rather than imported
#: from `REJECTION_CODES`.
#:
#: `0010` and `0011` imported the live list, so their constraints changed meaning every time the
#: vocabulary grew — replaying them on a fresh database produced a different constraint from the
#: one production received. Every migration since is frozen to the list it actually produces, and
#: this one adding a code is exactly the event that would have leaked into all of them.
_CODES_AT_0014: tuple[str, ...] = (
    "NO_REFERENCE_PRICE", "DEGENERATE_STOP", "ENTRY_DRIFT", "THROUGH_STOP",
    "NON_POSITIVE_SIZE", "VENUE_DIRECTION_UNSUPPORTED", "MIN_SIZE",
    "PROTECTION_NOT_ACCEPTED",
    "PROP_FIRM_TARGET_REACHED", "PROP_FIRM_HALTED_DAILY_LOSS",
    "PROP_FIRM_HALTED_MAX_DRAWDOWN", "PROP_FIRM_HALTED",
    "PROP_FIRM_WOULD_BREACH_DAILY_LOSS", "PROP_FIRM_WOULD_BREACH_MAX_DRAWDOWN",
    "BROKER_UNAVAILABLE", "VENUE_TRANSPORT", "VENUE_RAISED",
    "UNCODED_LEGACY", "UNCLASSIFIED",
)

#: What `0012` left behind — the target of this migration's downgrade. `0013` widened the OUTCOME
#: vocabulary and left this column untouched, so the predecessor here is `0012`'s eighteen.
_CODES_AT_0012: tuple[str, ...] = tuple(
    c for c in _CODES_AT_0014 if c != "PROTECTION_NOT_ACCEPTED"
)


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    # Drop and recreate: a CHECK constraint cannot be widened in place. No `CREATE TYPE` and no
    # `ALTER TYPE` — `0009` took production down doing that inside a transaction, and the
    # String + CheckConstraint arrangement is why that cannot recur on this column.
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', _CODES_AT_0014)}",
    )


def downgrade() -> None:
    # Rows carrying PROTECTION_NOT_ACCEPTED would violate the narrower constraint and are NOT
    # rewritten: mapping them onto any surviving code would assert a classification no decision
    # site made. A downgrade against such rows fails loudly, which is the correct outcome — the
    # same shape `0011` documents for VENUE_TRANSPORT and `0012` for MIN_SIZE.
    #
    # **OBSERVED FOR `0011` ON A REAL SERVER, NOT FOR THIS REVISION.** `MIGRATION_TEST.md` covers
    # `0010` and `0011`; this one has been run only against a unit test that reads these tuples.
    # The shape is expected to match because the code is the same shape — an argument, not a
    # measurement, and the distinction is the point of saying so.
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', _CODES_AT_0012)}",
    )
