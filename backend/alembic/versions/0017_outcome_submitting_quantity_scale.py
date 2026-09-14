"""`SUBMITTING` and `SUBMISSION_NOT_FOUND_AFTER_RESTART` join the vocabularies; quantities go to 9 dp.

`T-0144` / `B428b` commit (i), `DESIGN.md` §4.6. Four changes, one revision, because all four land with
the code that needs them:

* **`ck_decision_records_outcome` + `SUBMITTING` (nine).** An entry's `DecisionRecord` is now written
  BEFORE the order is sent (R11'), so the decision id — the position's identity — exists before the venue
  hears of it. The row moves by compare-and-set to `OPEN` / `REJECTED` / `UNSIZED_FILL`, or stays
  `SUBMITTING` while the verdict is unresolved. It never stands as a claim about what the venue did (`B423`).
* **`ck_decision_records_rejection_code` + `SUBMISSION_NOT_FOUND_AFTER_RESTART` (twenty-two).** S4: a
  `SUBMITTING` row left by a crash whose client order id two venue lookups did not find.
* **`decision_records.sized_units` and `trades.lot_size` → `Numeric(21, 9)` (`B458`).** The venue's
  quantity grid is `1e-9`; at 6 dp `0.000058413` was stored as `0.000058`. `fill_price` and every other
  price stay at 6 dp — USD prices, by the manager's ruling. No other quantity column exists on either table.
* **`decision_records.close_attempt_hint`, nullable JSON (ruling G-2).** `{leg: last attempt used}`, a HINT
  for where the close client-id probe starts; written from commit (ii), read by nothing yet.

**THE UPGRADE TOUCHES NO ROW.** Two CHECK swaps, each a strict superset of what it replaces by one value;
two column type changes that raise the scale; one nullable column added. That is what keeps a rollback of
the deploy CODE-ONLY: the old code never writes the new values, the wider CHECKs admit all it does, a 9-dp
column holds every 6-dp value, and the old model simply never reads the new column. An arm asserts the
operations and both supersets.

**STRICTLY WIDEN-ONLY: THE PRECISION GROWS WITH THE SCALE.** `Numeric(18, 6)` keeps 12 integer digits; `(21, 9)`
keeps the same 12 and adds 3 fractional ones, so every value the column holds today fits the new type and the `ALTER`
can neither round nor refuse. (`(18, 9)` would have cut the integer part to 9 digits: a stored `1e9` would make
Postgres refuse the change.) Not run against Postgres here; the scratch harness runs it before any deploy.

**THE DOWNGRADE IS THE DOCUMENTED EXCEPTION.** Narrowing the two columns back to 6 dp ROUNDS any stored
9-dp value — that is data loss, and it is accepted as the price of a rollback of the schema itself, which
the code-only rollback above makes unnecessary. It drops `close_attempt_hint` (hints are rebuildable from
the venue by the probe). Rows carrying `SUBMITTING` or the new code would violate the narrower CHECKs and
are NOT rewritten — mapping them onto a surviving value would assert something no decision site
concluded — so a downgrade against such rows fails loudly, the shape `0013` and `0016` document.

**DEPLOY ORDER IS LOAD-BEARING AND FAILS SILENTLY IF SPLIT (`B410`).** Code writing `SUBMITTING` against a
database still at `0016` would violate the outcome CHECK before the order is sent. So this lands in the
SAME COMMIT as the code that writes both values, as `0013` and `0016` did.

**NOT RUN AGAINST A SERVER HERE** (`KILL_SET.md` M-2): the arms read these tuples and record the
operations; the scratch Postgres harness has not run this revision in this tree.

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels = None
depends_on = None

_OUTCOME_CONSTRAINT = "ck_decision_records_outcome"
_CODE_CONSTRAINT = "ck_decision_records_rejection_code"

#: **FROZEN (`B405`/`B416`). THE NINE OUTCOMES THIS REVISION CREATES**, written out rather than imported
#: from `DECISION_OUTCOMES` — a migration that reads the live list stops describing its revision.
_OUTCOMES_AT_0017: tuple[str, ...] = (
    "WIN", "LOSS", "BE", "OPEN", "ABSTAINED", "ABANDONED", "REJECTED", "UNSIZED_FILL", "SUBMITTING",
)

#: What `0013` left behind (`0014`–`0016` did not touch outcomes) — the DOWNGRADE target, written out rather
#: than derived as "`_OUTCOMES_AT_0017` minus one". That subtraction is the defect `0006` shipped.
_OUTCOMES_AT_0013: tuple[str, ...] = (
    "WIN", "LOSS", "BE", "OPEN", "ABSTAINED", "ABANDONED", "REJECTED", "UNSIZED_FILL",
)

#: **FROZEN. THE TWENTY-TWO CODES THIS REVISION CREATES.**
_CODES_AT_0017: tuple[str, ...] = (
    "NO_REFERENCE_PRICE", "DEGENERATE_STOP", "ENTRY_DRIFT", "THROUGH_STOP",
    "NON_POSITIVE_SIZE", "VENUE_DIRECTION_UNSUPPORTED", "MIN_SIZE",
    "PROTECTION_NOT_ACCEPTED", "VENUE_ENDED_UNFILLED", "KILL_SWITCH_ARMED",
    "PROP_FIRM_TARGET_REACHED", "PROP_FIRM_HALTED_DAILY_LOSS",
    "PROP_FIRM_HALTED_MAX_DRAWDOWN", "PROP_FIRM_HALTED",
    "PROP_FIRM_WOULD_BREACH_DAILY_LOSS", "PROP_FIRM_WOULD_BREACH_MAX_DRAWDOWN",
    "BROKER_UNAVAILABLE", "VENUE_TRANSPORT", "VENUE_RAISED",
    "UNCODED_LEGACY", "UNCLASSIFIED", "SUBMISSION_NOT_FOUND_AFTER_RESTART",
)

#: The DOWNGRADE target: exactly `0016`'s twenty-one, written out (not `_CODES_AT_0017` minus one).
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

#: `(table, column, nullable)` for the two venue-fed QUANTITY columns (`B458`). Prices are not here.
_QUANTITY_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("decision_records", "sized_units", True),
    ("trades", "lot_size", False),
)
_QUANTITY_BEFORE = (18, 6)
_QUANTITY_AFTER = (21, 9)

_HINT_COLUMN = "close_attempt_hint"


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def _swap_checks(outcomes: tuple[str, ...], codes: tuple[str, ...]) -> None:
    # Drop and recreate: a CHECK cannot be widened in place. No `CREATE TYPE`/`ALTER TYPE` (`0009`).
    op.drop_constraint(_OUTCOME_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _OUTCOME_CONSTRAINT, "decision_records",
        f"outcome IS NULL OR {_sql_in('outcome', outcomes)}",
    )
    op.drop_constraint(_CODE_CONSTRAINT, "decision_records", type_="check")
    op.create_check_constraint(
        _CODE_CONSTRAINT, "decision_records",
        f"rejection_code IS NULL OR {_sql_in('rejection_code', codes)}",
    )


def _retype_quantities(before: tuple[int, int], after: tuple[int, int]) -> None:
    for table, column, nullable in _QUANTITY_COLUMNS:
        op.alter_column(
            table, column,
            type_=sa.Numeric(*after),
            existing_type=sa.Numeric(*before),
            existing_nullable=nullable,
        )


def upgrade() -> None:
    _swap_checks(_OUTCOMES_AT_0017, _CODES_AT_0017)
    _retype_quantities(_QUANTITY_BEFORE, _QUANTITY_AFTER)
    op.add_column("decision_records", sa.Column(_HINT_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    # Reverse order. Narrowing ROUNDS stored 9-dp quantities — the documented exception above.
    op.drop_column("decision_records", _HINT_COLUMN)
    _retype_quantities(_QUANTITY_AFTER, _QUANTITY_BEFORE)
    _swap_checks(_OUTCOMES_AT_0013, _CODES_AT_0016)
