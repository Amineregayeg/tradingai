"""Migration 0002 must match the DecisionRecord ORM model exactly.

The SQLite test DB is built from ORM metadata, so a migration that diverges from
the model would never fail those tests — it would only blow up on the real
Postgres deploy. This test drives the migration's ``upgrade()`` through a
recording shim and asserts its columns and CHECK constraints equal the model's,
so drift (an earlier draft shipped an outcome CHECK missing ABSTAINED and no
cohort CHECK) is caught here instead.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.models.decision_record import DecisionRecord

_MIG = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "0002_decision_records.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("m0002", _MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _RecordingOp:
    """Captures create_table so we can inspect the migration's DDL intent."""

    def __init__(self):
        self.table = None
        self.indexes = []

    def create_table(self, name, *cols):
        self.table = (name, cols)

    def create_index(self, name, table, cols):
        self.indexes.append((name, table, tuple(cols)))


def _captured_upgrade():
    mod = _load_migration()
    rec = _RecordingOp()
    orig = mod.op
    mod.op = rec
    try:
        mod.upgrade()
    finally:
        mod.op = orig
    return rec


def test_revision_chain():
    mod = _load_migration()
    assert mod.revision == "0002"
    assert mod.down_revision == "0001"


def test_migration_columns_match_model():
    rec = _captured_upgrade()
    assert rec.table is not None and rec.table[0] == "decision_records"
    mig_cols = {c.name for c in rec.table[1] if isinstance(c, sa.Column)}
    model_cols = {c.name for c in DecisionRecord.__table__.columns}
    assert mig_cols == model_cols, f"drift: migration-only={mig_cols - model_cols}, model-only={model_cols - mig_cols}"


def test_migration_check_constraints_match_model():
    rec = _captured_upgrade()
    mig_checks = {
        c.name for c in rec.table[1] if isinstance(c, sa.CheckConstraint)
    }
    model_checks = {
        c.name
        for c in DecisionRecord.__table__.constraints
        if isinstance(c, sa.CheckConstraint)
    }
    assert mig_checks == model_checks
    # the three enum-like columns must all be guarded
    assert mig_checks == {
        "ck_decision_records_signal_dir",
        "ck_decision_records_outcome",
        "ck_decision_records_cohort",
    }


def test_outcome_vocab_includes_abstained():
    # ABSTAINED is the whole reason this table exists (it records no-trade
    # decisions too) — guard against a future edit dropping it.
    rec = _captured_upgrade()
    outcome_check = next(
        c for c in rec.table[1]
        if isinstance(c, sa.CheckConstraint) and c.name == "ck_decision_records_outcome"
    )
    assert "ABSTAINED" in str(outcome_check.sqltext)
