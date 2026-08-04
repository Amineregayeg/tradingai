"""The migration CHAIN must produce exactly the DecisionRecord ORM model.

The SQLite test DB is built from ORM metadata, so a migration that diverges from
the model would never fail those tests — it would only blow up on the real
Postgres deploy, at container boot, with the API down.

This drives each migration's ``upgrade()`` through a recording shim and replays
their DDL intent in order, then asserts the resulting columns and CHECK
constraints equal the model's. Drift is caught here instead (an earlier draft
shipped an outcome CHECK missing ABSTAINED and no cohort CHECK).

It walks the whole chain rather than a single revision on purpose: when 0003
added ``fill_price``, a version of this test that only inspected 0002 failed —
correctly, but for the wrong reason. It would have been "fixed" by pinning it to
the newest migration, which quietly narrows the guard to one file and lets any
column added by an *earlier* revision drift unnoticed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.models.decision_record import DecisionRecord

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"

#: Every migration touching decision_records, in apply order.
_CHAIN = [
    ("0002", "0002_decision_records.py", "0001"),
    ("0003", "0003_decision_fill_price.py", "0002"),
    ("0004", "0004_engine_runs.py", "0003"),
]


def _load(filename: str):
    path = _VERSIONS / filename
    spec = importlib.util.spec_from_file_location(f"mig_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _RecordingOp:
    """Captures DDL intent instead of executing it."""

    def __init__(self):
        self.table_name: str | None = None
        self.columns: dict[str, sa.Column] = {}
        self.checks: dict[str, sa.CheckConstraint] = {}
        self.indexes: list[tuple] = []
        self.other_tables: set[str] = set()

    #: Only decision_records is under assertion here. Migration 0004 also
    #: creates engine_runs, and DDL for other tables is recorded separately so
    #: it neither pollutes the assertions nor fails the replay.
    def create_table(self, name, *cols, **kw):
        if name != "decision_records":
            self.other_tables.add(name)
            return
        self.table_name = name
        for c in cols:
            if isinstance(c, sa.Column):
                self.columns[c.name] = c
            elif isinstance(c, sa.CheckConstraint):
                self.checks[c.name] = c

    def add_column(self, table, col, **kw):
        if table != "decision_records":
            return
        self.columns[col.name] = col

    def drop_column(self, table, name, **kw):
        if table == "decision_records":
            self.columns.pop(name, None)

    def create_index(self, name, table, cols, **kw):
        self.indexes.append((name, table, tuple(cols)))

    def drop_index(self, name, table_name=None, **kw):
        self.indexes = [i for i in self.indexes if i[0] != name]

    def drop_table(self, name, **kw):
        self.other_tables.discard(name)

    def get_bind(self):
        """A bind that swallows data statements.

        Migrations may run DML as well as DDL — 0004 backfills run_id onto
        existing rows. This test asserts DDL INTENT against an in-memory
        recorder, so data statements have nothing to act on and are discarded.
        Raising here instead (the earlier behaviour) made the suite fail the
        moment any migration touched data, which is a normal thing to do.
        """

        class _NullResult:
            def scalar(self):
                return 0

            def fetchall(self):
                return []

        class _NullBind:
            def execute(self, *_a, **_kw):
                return _NullResult()

        return _NullBind()


def _replay_chain() -> _RecordingOp:
    """Apply every migration's upgrade() in order against the shim."""
    rec = _RecordingOp()
    for _rev, filename, _down in _CHAIN:
        mod = _load(filename)
        orig_op = mod.op
        mod.op = rec
        # Migrations added after 0002 guard themselves with a live-schema check
        # (`_has_column`) so a bootstrapped DB can be upgraded safely. That needs
        # a real connection; here we assert the DDL INTENT, so force the guard to
        # report "not present yet" and let the DDL through.
        # Migrations guard themselves against an already-migrated schema by
        # probing the live database (_has_column / _cols / _tables). Those need
        # a real connection; here we assert DDL INTENT, so make every probe
        # report "nothing exists yet" and let the DDL through.
        # The right stub semantics are "the tables from earlier migrations
        # exist, but this migration's new columns do not yet" — which is the
        # state a migration is written to expect. Returning an empty table set
        # instead made 0004 skip its add_column entirely and the drift check
        # then reported a column the migration does add.
        class _AnyTable(set):
            def __contains__(self, item):  # every table is present
                return True

        probes = {}
        for name, stub in (
            ("_has_column", lambda: False),
            ("_cols", lambda _t=None: set()),
            ("_tables", lambda: _AnyTable()),
        ):
            if hasattr(mod, name):
                probes[name] = getattr(mod, name)
                setattr(mod, name, stub)
        try:
            mod.upgrade()
        finally:
            mod.op = orig_op
            for name, original in probes.items():
                setattr(mod, name, original)
    return rec


def test_revision_chain_is_linear_and_complete():
    for rev, filename, down in _CHAIN:
        mod = _load(filename)
        assert mod.revision == rev, f"{filename} declares revision {mod.revision}"
        assert mod.down_revision == down, f"{filename} declares down_revision {mod.down_revision}"


def test_migration_columns_match_model():
    rec = _replay_chain()
    assert rec.table_name == "decision_records"
    model_cols = {c.name for c in DecisionRecord.__table__.columns}
    mig_cols = set(rec.columns)
    assert mig_cols == model_cols, (
        f"drift: migration-only={mig_cols - model_cols}, model-only={model_cols - mig_cols}"
    )


def test_fill_price_is_in_the_chain():
    """Explicit, because this column is what makes R measurable against reality.

    Without it, realized_r is computed against `signal_entry` — the price the
    strategy asked for rather than the one it paid — and the feedback loop's
    slippage rule has nothing to read.
    """
    rec = _replay_chain()
    assert "fill_price" in rec.columns
    assert rec.columns["fill_price"].nullable is True, (
        "fill_price must be nullable: rows written before it existed have no "
        "recoverable fill, and backfilling one would fabricate zero slippage"
    )


def test_migration_check_constraints_match_model():
    rec = _replay_chain()
    model_checks = {
        c.name
        for c in DecisionRecord.__table__.constraints
        if isinstance(c, sa.CheckConstraint)
    }
    assert set(rec.checks) == model_checks
    assert set(rec.checks) == {
        "ck_decision_records_signal_dir",
        "ck_decision_records_outcome",
        "ck_decision_records_cohort",
    }


def test_outcome_vocab_includes_abstained():
    # ABSTAINED is the whole reason this table exists (it records no-trade
    # decisions too) — guard against a future edit dropping it.
    rec = _replay_chain()
    assert "ABSTAINED" in str(rec.checks["ck_decision_records_outcome"].sqltext)


def test_fill_price_migration_is_idempotent():
    """upgrade() must no-op when the column already exists.

    deploy_migrate.py can bootstrap a fresh DB from offline SQL and then run
    `alembic upgrade head` over it, so a migration can meet a schema that already
    contains its target. Adding it twice aborts the upgrade and takes the API
    container down on boot.
    """
    mod = _load("0003_decision_fill_price.py")
    rec = _RecordingOp()
    rec.table_name = "decision_records"
    orig_op, orig_has = mod.op, mod._has_column
    mod.op = rec
    mod._has_column = lambda: True          # pretend it is already there
    try:
        mod.upgrade()
    finally:
        mod.op, mod._has_column = orig_op, orig_has
    assert "fill_price" not in rec.columns, "upgrade() re-added an existing column"
