"""`MIN_SIZE` joins the rejection vocabulary — the venue's floor, distinct from our arithmetic.

`T-0140` gives `place_order` a body, and the body must **refuse below the venue's published
minimum rather than round to zero**. That refusal needs its own code: `NON_POSITIVE_SIZE` is
`units <= 0`, which is arithmetic on our side (equity against stop width, or a degenerate stop),
while this is a well-formed order that is simply too small for the venue. **Two causes, two
remedies** — collapsing them is part 3's `M-8` one task later.

**THE FLOOR IS NOT A CONSTANT, which is why the code exists at all.** Measured in `T-0139`
(`B409`): BTC `0.000012941`, ETH `0.000397984` — both $1.00 of notional, so the minimum moves with
price while `min_trade_increment` (`1e-9` on both) does not. A pinned constant would refuse valid
orders in one price regime and admit sub-minimum ones in the other, without ever failing.

**DEPLOY ORDER IS LOAD-BEARING AND FAILS SILENTLY IF SPLIT (`B410`).** Production is at `0011`,
whose CHECK closes the vocabulary at seventeen. If code emitting `MIN_SIZE` reached production
before this migration, the insert would violate the constraint — and `_record_rejected_signal`
swallows every exception by design (*"never let bookkeeping kill the loop"*). The order would be
correctly refused and **the row silently lost**: `B403`'s shape produced by deployment order rather
than by code. This migration therefore lands in the SAME COMMIT as the body that writes the code.
Within one deploy the ordering is safe — `compose.vps.yaml`'s api command block begins `set -e` and
runs `deploy_migrate.py` before `exec uvicorn`, so a failed migration stops the container instead of
serving un-migrated. **That `set -e` is load-bearing**: without it a failed migration would fall
through and serve.

Revision ID: 0012
Revises: 0011
"""
from __future__ import annotations

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_decision_records_rejection_code"

#: **FROZEN (`B405`). THE EIGHTEEN CODES THIS MIGRATION CREATES**, written out rather than imported
#: from `REJECTION_CODES`.
#:
#: `0010` and `0011` imported the live list, so their constraints changed meaning every time the
#: vocabulary grew: replaying them on a fresh database produced a different constraint from the one
#: production received, and `0011`'s downgrade rebuilt a "`0010`" permitting codes `0010` never
#: knew. **`T-0140` is what armed that** — adding `MIN_SIZE` to the live list would have leaked it
#: into both earlier constraints. All three are frozen now, each to the list it actually produces.
_CODES_AT_0012: tuple[str, ...] = (
    "NO_REFERENCE_PRICE", "DEGENERATE_STOP", "ENTRY_DRIFT", "THROUGH_STOP",
    "NON_POSITIVE_SIZE", "VENUE_DIRECTION_UNSUPPORTED", "MIN_SIZE",
    "PROP_FIRM_TARGET_REACHED", "PROP_FIRM_HALTED_DAILY_LOSS",
    "PROP_FIRM_HALTED_MAX_DRAWDOWN", "PROP_FIRM_HALTED",
    "PROP_FIRM_WOULD_BREACH_DAILY_LOSS", "PROP_FIRM_WOULD_BREACH_MAX_DRAWDOWN",
    "BROKER_UNAVAILABLE", "VENUE_TRANSPORT", "VENUE_RAISED",
    "UNCODED_LEGACY", "UNCLASSIFIED",
)

#: What `0011` left behind — the target of this migration's downgrade.
_CODES_AT_0011: tuple[str, ...] = tuple(c for c in _CODES_AT_0012 if c != "MIN_SIZE")


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
        f"rejection_code IS NULL OR {_sql_in('rejection_code', _CODES_AT_0012)}",
    )


def downgrade() -> None:
    # Rows carrying MIN_SIZE would violate the narrower constraint and are NOT rewritten: mapping
    # them onto any surviving code would assert a classification no decision site made. A
    # downgrade against such rows fails loudly, which is the correct outcome — the same shape
    # `0011` documents for VENUE_TRANSPORT.
    #
    # **THAT REFUSAL WAS OBSERVED FOR `0011`, ON A REAL SERVER, AND NOT FOR THIS REVISION.**
    # `MIGRATION_TEST.md` covers `0010` and `0011`; `0012` has never been run anywhere but in a
    # unit test that reads these tuples. The shape is expected to match because the code is the
    # same shape — which is an argument, not a measurement, and is exactly the distinction the
    # sentence this replaced blurred.
    op.drop_constraint(_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', _CODES_AT_0011)}",
    )
