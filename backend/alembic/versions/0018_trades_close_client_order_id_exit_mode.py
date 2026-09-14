"""`trades` gains five nullable columns — the close's identity, its decided mode, and its measured mark — nothing else.

`T-0144` / `B428b` commit (ii): `PLAN.md` REVISIONS 7 (I-1) and 9 (P-4), and `T-0146` `PLAN.md` REVISIONS 2 (E5), 3 and
4. Five columns, one revision, because all five land with the code that first writes them (`_persist_live_close`, from
the `SettleEvent`):

* **`close_client_order_id`, nullable `String(64)` (I-1).** The client order id of the ENGINE's close order that
  produced this row: `tai-<32 hex>-<leg><2-digit attempt>`, 40 characters (G-1's two digits), so 64 holds it with room
  and never truncates. "Partial taken" (§3.6) is read from this IDENTITY — leg `p` — never inferred from a size. NULL
  for a simulator trade and for an external exit: no engine close id exists, and none is fabricated.
* **`exit_mode`, nullable `String(16)` (E5, REVISIONS 3–4).** The loop's mode WHEN THE EXIT WAS DECIDED — a retried
  settle write never re-reads it. Five values, frozen below as `_EXIT_MODES_AT_0018`. `16`: the longest value,
  `MANAGE_ONLY`, is 11 characters; 16 leaves room for a future value of up to 16 without a type change, while a
  sentence written where a code belongs is still refused (on Postgres; SQLite ignores `VARCHAR` length).
* **`mark_at_detection`, nullable `Numeric(18, 6)` (P-4, R3').** The mark the pass compared with the level when it
  DECIDED the exit, as the `SettleEvent` carried it — never re-read at persist time. A USD price, so the same
  `(18, 6)` as `entry_price`, `exit_price` and `sl` beside it.
* **`mark_source`, nullable `String(32)` (P-4).** Which feed that mark came from. Today's names are `binance_mark`
  (12) and `alpaca_quote_mid` (16), `app.services.execution.reference`; 32 is room, not a vocabulary — no CHECK.
* **`detection_interval_s`, nullable `Numeric(10, 3)` (P-4, R1').** The MEASURED wall time of the pass that detected
  the exit (`_last_pass_s`), not `POLL_INTERVAL`: the real stop-check interval. Millisecond resolution; up to
  9,999,999.999 s.

**WHY THE MARK IS STORED AT ALL.** R3' says the Binance-vs-Alpaca basis is "measured continuously rather than assumed",
and a log line is not queryable next month. So the event's mark, its source and the pass time become durable.

**WHAT IS DERIVED, NOT STORED.** Detection slippage is `mark_at_detection` − the level that triggered (`sl` for a stop
exit, the ruling's case); execution slippage is `exit_price − mark_at_detection`. Both come from columns this table
holds (the leg, and so which level, is in `close_client_order_id`), so storing them would be a second copy that can
disagree with the first. The PAPER label on execution slippage is derived from the run's
`execution_class` (`engine_runs.config`), where it is true for every trade of the run, not copied onto each row.

**ALL FIVE ARE NULL** for a simulator trade (no venue close, no second price feed) and for every row from before
`0018`. None has a server default and none has a CHECK: the `exit_mode` vocabulary is enforced in code
(`app.models.trade.EXIT_MODES`, equal to the frozen tuple by an arm), and a CHECK would be another DDL operation here
and a DROP/CREATE widening for every future value — what each of `0011`–`0017` does for a `decision_records`
vocabulary.

**STRICTLY WIDEN-ONLY. THE UPGRADE TOUCHES NO ROW.** Five `add_column`s, each nullable with no server default, so no
existing row is written and Postgres adds each without a table rewrite. That keeps a rollback of the deploy CODE-ONLY:
the old model simply never reads these columns. No `alter_column`, no `execute`, no CHECK, no backfill — an arm
records every operation and requires exactly these five.

**THE DOWNGRADE DROPS ALL FIVE**, in reverse order. What they held is lost; that is the price of a rollback of the
schema itself, which the code-only rollback above makes unnecessary.

`close_attempt_hint`'s JSON shape changes at (ii) to `{leg: {"n": attempt, "mode": decided mode}}`: no schema change.

**DEPLOY ORDER (`B410`).** The MODEL alone depends on this revision, not only the writer: every ORM read of `Trade`
names every mapped column, so against a database still at `0017` any `select(Trade)` fails (measured on SQLite:
`no such column: trades.close_client_order_id`). It fails loudly, not silently. So this lands in the SAME COMMIT as the
model and the code that writes the columns, as `0013`, `0016` and `0017` did.

**NOT RUN AGAINST A SERVER HERE** (`KILL_SET.md` M18-1): the arms record the operations, render the Postgres DDL
offline and compare the model; precision and scale are only EXECUTED by the scratch Postgres harness, which has not
run this revision in this tree (SQLite ignores `Numeric` scale).

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels = None
depends_on = None

_TABLE = "trades"
_CLOSE_ID_COLUMN = "close_client_order_id"
_EXIT_MODE_COLUMN = "exit_mode"
_MARK_COLUMN = "mark_at_detection"
_MARK_SOURCE_COLUMN = "mark_source"
_INTERVAL_COLUMN = "detection_interval_s"

#: **FROZEN (`B405`/`B416`). THE FIVE EXIT MODES THIS REVISION'S COLUMN CARRIES**, written out rather than
#: imported from `EXIT_MODES` — a migration that reads the live list stops describing its revision.
_EXIT_MODES_AT_0018: tuple[str, ...] = (
    "RUNNING", "MANAGE_ONLY", "STOPPING", "EXTERNAL", "UNRECORDED",
)


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_CLOSE_ID_COLUMN, sa.String(64), nullable=True))
    op.add_column(_TABLE, sa.Column(_EXIT_MODE_COLUMN, sa.String(16), nullable=True))
    op.add_column(_TABLE, sa.Column(_MARK_COLUMN, sa.Numeric(18, 6), nullable=True))
    op.add_column(_TABLE, sa.Column(_MARK_SOURCE_COLUMN, sa.String(32), nullable=True))
    op.add_column(_TABLE, sa.Column(_INTERVAL_COLUMN, sa.Numeric(10, 3), nullable=True))


def downgrade() -> None:
    # Reverse order. All five go; nothing else was created.
    op.drop_column(_TABLE, _INTERVAL_COLUMN)
    op.drop_column(_TABLE, _MARK_SOURCE_COLUMN)
    op.drop_column(_TABLE, _MARK_COLUMN)
    op.drop_column(_TABLE, _EXIT_MODE_COLUMN)
    op.drop_column(_TABLE, _CLOSE_ID_COLUMN)
