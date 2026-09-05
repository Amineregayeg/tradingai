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

import ast
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
    ("0005", "0005_telemetry_records.py", "0004"),
    ("0006", "0006_decision_outcome_abandoned.py", "0005"),
    ("0007", "0007_decision_attribution.py", "0006"),
    ("0008", "0008_decision_outcome_rejected.py", "0007"),
    # `B378`/`B380`. The chain guard fired for this one exactly as designed — a migration on disk
    # that nothing replays is a migration nothing tests, and it caught mine in the full suite.
    ("0009", "0009_compliance_unavailable.py", "0008"),
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
        #: Columns per created table, so a new table is covered the moment it is
        #: created rather than only when someone remembers to assert it.
        self.tables: dict[str, dict[str, sa.Column]] = {}
        self.table_name: str | None = None
        self.columns: dict[str, sa.Column] = {}
        self.checks: dict[str, sa.CheckConstraint] = {}
        self.indexes: list[tuple] = []
        self.other_tables: set[str] = set()

    #: Only decision_records is under assertion here. Migration 0004 also
    #: creates engine_runs, and DDL for other tables is recorded separately so
    #: it neither pollutes the assertions nor fails the replay.
    def create_table(self, name, *cols, **kw):
        self.tables[name] = {c.name: c for c in cols if isinstance(c, sa.Column)}
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

    def alter_column(self, table, name, **kw):
        """Nullability/type changes — `0009` makes four `prop_firm_snapshots` figures nullable.

        **Added because the chain guard caught its own absence.** Every operation here records
        only `decision_records`, which is this file's subject; but a migration touching ANOTHER
        table must still REPLAY, and without this method `_replay_chain` raised `AttributeError`
        and five arms went red for one migration the harness could not run. **The shim was
        narrower than the migrations it replays**, and the guard that says *every migration on
        disk is replayed* is exactly what surfaced it.
        """
        if table != "decision_records":
            return
        col = self.columns.get(name)
        if col is not None and "nullable" in kw:
            col.nullable = kw["nullable"]

    def drop_column(self, table, name, **kw):
        if table == "decision_records":
            self.columns.pop(name, None)

    def create_index(self, name, table, cols, **kw):
        self.indexes.append((name, table, tuple(cols)))

    def drop_index(self, name, table_name=None, **kw):
        self.indexes = [i for i in self.indexes if i[0] != name]

    def drop_table(self, name, **kw):
        self.other_tables.discard(name)

    # A CHECK constraint can be REPLACED after the table exists — migration 0006
    # widens the outcome vocabulary that way. Replaying only create_table would
    # leave the harness asserting the original constraint while production runs
    # the replacement, which is the exact drift this file exists to catch.
    def drop_constraint(self, name, table_name=None, **kw):
        if table_name == "decision_records":
            self.checks.pop(name, None)

    def create_check_constraint(self, name, table_name, condition, **kw):
        if table_name == "decision_records":
            self.checks[name] = sa.CheckConstraint(condition, name=name)

    def execute(self, *_args, **_kw):
        """Data statements change no schema. Recorded as a no-op so a migration
        that repairs rows alongside its DDL still replays."""
        return None

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


def test_the_chain_covers_every_migration_on_disk():
    """_CHAIN is hand-written, so a new migration is invisible to every test here until
    someone remembers to add it.

    That is not hypothetical: 0005 was added and replayed by nothing — the linearity test
    below passed without ever loading it. A migration nobody replays is a migration nobody
    checks against its model.
    """
    on_disk = {p.name for p in _VERSIONS.glob("0*.py")}
    in_chain = {filename for _rev, filename, _down in _CHAIN} | {"0001_initial.py"}
    assert on_disk == in_chain, (
        f"not replayed: {sorted(on_disk - in_chain)}; "
        f"listed but missing: {sorted(in_chain - on_disk)}"
    )


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
        # T-0013. Note what is NOT constrained: `RULE_ENGINE` with a NULL rule id,
        # and `UNSET`. Both are defects and both must be STORABLE — the write
        # sites swallow bookkeeping errors, so a constraint that refused them
        # would drop the row and destroy the evidence of the defect.
        "ck_decision_records_decided_by",
        "ck_decision_records_only_rule_engine_names_a_rule",
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


def test_telemetry_records_migration_matches_model():
    """The same drift check the decision_records table has, for the telemetry store.

    Its shape is fixed by the engine contract and read by the knowledge team's conformance
    suite, so a migration that disagrees with the model would produce records that validate
    in tests and fail to store in production.
    """
    from app.models.telemetry_record import TelemetryRecord

    rec = _replay_chain()
    mig_cols = set(rec.tables.get("telemetry_records", {}))
    model_cols = {c.name for c in TelemetryRecord.__table__.columns}
    assert mig_cols, "0005 did not create telemetry_records during the replay"
    assert mig_cols == model_cols, (
        f"drift: migration-only={mig_cols - model_cols}, model-only={model_cols - mig_cols}"
    )


# ======================================================================================
# T-0098 / `B282` — THE CALL SITE, GUARDED STRUCTURALLY
#
# `T-0084` added a must-hit beside the sizing-reconstruction arm: *"assert at least one row
# carries all three columns"*. **It inserted the row it then asserted existed, so it could
# never fail** — `B272`'s shape, inside the arm requested specifically to prevent vacuity,
# and its fourth instance.
#
# **The omission that caused it is the instructive part.** The model cited was
# `test_there_are_adapters_to_check`, and what makes THAT arm work is that its population is
# DERIVED FROM THE TREE. **A population the arm writes itself is not a population.**
#
# Measured by Review before this was written, and reproduced here before it was: set the
# producer's three sizing arguments to `None` and the whole `T-0084` suite reports
# `17 passed`. Nothing notices — and if the call site regresses, reconstruction silently
# becomes impossible again while the arm that exists to keep it possible reports green.
# *That is `B279`'s own failure mode one level up.*
# ======================================================================================

#: The three arguments `size_position` was called with. `signal_sl` is the fourth and was
#: already stored, which is why it is not here.
SIZING_KWARGS = ("sizing_equity", "sizing_risk_pct", "sizing_price")


def _record_signal_decision_call() -> ast.Call:
    """The one call site, located by AST rather than by line number, which would rot."""
    loop_src = (
        _VERSIONS.parents[1] / "app" / "services" / "live" / "crypto_loop.py"
    ).read_text(encoding="utf-8")
    calls = [
        n for n in ast.walk(ast.parse(loop_src))
        if isinstance(n, ast.Call)
        and (getattr(n.func, "attr", None) or getattr(n.func, "id", None))
        == "_record_signal_decision"
    ]
    assert len(calls) == 1, (
        f"expected exactly one call site, found {len(calls)}. A second one is a second place "
        "the sizing inputs can be forgotten, and this arm would only guard the first."
    )
    return calls[0]


def test_the_producer_passes_ALL_THREE_sizing_inputs_at_its_call_site():
    """`B282`. One arm, no database, and it guards the thing the value-level arm could not."""
    call = _record_signal_decision_call()
    passed = {kw.arg for kw in call.keywords if kw.arg}

    missing = set(SIZING_KWARGS) - passed
    assert not missing, (
        f"the call site no longer passes {sorted(missing)}. Every production row would carry "
        "NULL in those columns, `sized_units` would stop being reconstructible, and the "
        "reconstruction arm — scoped to non-null rows — would report green over an empty set."
    )


#: WHAT EACH KEYWORD MUST BE BOUND TO, and the three are NOT the same shape.
#:
#: `B299`: an earlier wording of this rule said all three *"read from the matching key of the
#: execution result"*, which is true of two of them. `sizing_risk_pct` reads `sig.risk_pct` —
#: the value the loop SUPPLIED — because `execute()` does not report the risk it used. So two
#: of the three record what the producer says it USED and the third records what was ASKED,
#: and they coincide only while `execute` passes `sig.risk_pct` through untouched. Pinned as
#: correct-for-now with the asymmetry recorded rather than smoothed over.
EXPECTED_BINDING: dict[str, tuple[str, ...]] = {
    # (kind, name) — "res_key" reads a key of the execution result, "sig_attr" reads the signal
    "sizing_equity": ("res_key", "equity_at_entry"),
    "sizing_price": ("res_key", "sizing_price"),
    "sizing_risk_pct": ("sig_attr", "risk_pct"),
}


def _binding_of(value) -> tuple[str, ...] | None:
    """Classify the expression a keyword is bound to, STRUCTURALLY rather than by its text.

    `ast.unparse` would work and would also fail on a reformat, a renamed local or a differing
    quote style — a call-site pin that breaks on whitespace gets deleted rather than fixed.
    """
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "get"
        and isinstance(value.func.value, ast.Name)
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Constant)
    ):
        return ("res_key", value.args[0].value)
    if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
        return ("sig_attr", value.attr)
    return None


def test_each_sizing_keyword_is_bound_to_THE_RIGHT_SOURCE():
    """**A structural arm over a call site can check THREE things, and the two above check two.**

    That general form belongs here because this is the third time the project has needed it:

        1. the keyword is PRESENT              `test_the_producer_passes_ALL_THREE...`
        2. it is not obviously EMPTY           `test_none_of_the_three_is_bound_to_a_LITERAL_None`
        3. it holds the RIGHT VALUE            this arm

    **The first two are satisfied by a keyword bound to the wrong source**, and the wrong source
    is the whole reason the third column exists. Measured before this was written, and measured
    over every test that names these columns rather than over one file:

        sizing_price=res.get("sizing_price")  ->  res.get("fill")     34 passed -> 34 passed

    `size_position` divides by the SIZING price and never by the fill — `B280`, measured at
    4.76% out at fifty ticks of slippage — so that mutation reintroduces the exact defect the
    column was added to make impossible, and **nothing notices.**

    **AND THE RECONSTRUCTION ARM STRUCTURALLY CANNOT CATCH IT.** It builds its own row with
    internally consistent values, so it can never observe a PRODUCER binding the wrong source.
    A real row would be internally INCONSISTENT — `sized_units` computed from one price while
    `sizing_price` holds another — and no arm reconstructs from a row the producer wrote.
    """
    call = _record_signal_decision_call()
    bound = {kw.arg: kw.value for kw in call.keywords if kw.arg in EXPECTED_BINDING}

    wrong = []
    for name, expected in EXPECTED_BINDING.items():
        value = bound.get(name)
        if value is None:
            continue          # absence is the FIRST arm's subject, and it fails there by name
        actual = _binding_of(value)
        if actual != expected:
            wrong.append(f"{name} is bound to `{ast.unparse(value)}` and must read {expected}")

    assert not wrong, (
        "the producer records a value it did not size with: " + "; ".join(wrong) + ". The "
        "keyword is present and non-None, so both other arms stay green while the stored "
        "column no longer describes the call that produced the row."
    )


def test_none_of_the_three_is_bound_to_a_LITERAL_None():
    """**The half a keyword-presence check would miss, and it is the mutation Review ran.**

    Review's probe KEPT the keywords and changed their values to `None`. An arm asserting
    only that the argument is *passed* is satisfied by `sizing_equity=None` — so it would
    have reported green over exactly the regression it was written to catch.
    """
    call = _record_signal_decision_call()
    nulled = [
        kw.arg for kw in call.keywords
        if kw.arg in SIZING_KWARGS
        and isinstance(kw.value, ast.Constant) and kw.value.value is None
    ]
    assert not nulled, (
        f"{sorted(nulled)} is passed as a literal None. The keyword is present and the value "
        "is absent — the column exists, the row is NULL, and the reconstruction is impossible "
        "while every arm stays green."
    )


def test_no_migration_USES_an_enum_value_it_ADDS_in_the_same_transaction():
    """The arm for the class that took production down, and it is not the arm this needs.

    **WHAT HAPPENED.** `0009` ran `ALTER TYPE compliance_t ADD VALUE 'UNAVAILABLE'` and then, in
    the same transaction, created a `CheckConstraint` whose predicate NAMES that value. PostgreSQL
    refuses: `UnsafeNewEnumValueUsageError`. The api crash-looped and the site returned 502. The
    database was untouched — the transaction rolled back atomically — but the deploy was dead.

    **`env.py` DOES `with context.begin_transaction(): context.run_migrations()` — ONE transaction
    for ALL migrations** — so splitting the ALTER and the constraint into two revisions does not
    help. Only a `COMMIT` between them does.

    **WHY THIS ARM IS HONEST ABOUT ITS OWN WEAKNESS.** The real acceptance is *the migration RUNS
    against PostgreSQL*, and nothing in this suite executes alembic against a real server — there
    is no Postgres and no Docker on this machine, which is exactly why a file that passed every
    local check failed in production. This is a STRUCTURAL guard over the source: it catches this
    class and it is not a substitute for running the thing. **Recorded so the next reader does not
    mistake a green here for a migration that has been executed.**
    """
    import ast
    import re

    for path in sorted(_VERSIONS.glob("0*.py")):
        source = path.read_text(encoding="utf-8")
        # SCOPED TO upgrade(), AND ANCHORED ON THE ALTER ITSELF. The first version split on the
        # first occurrence of the quoted value, which is a PROSE mention in the docstring — so it
        # measured the comments and fired on the fixed file. `downgrade()` is excluded because it
        # runs in its own transaction and does not add the value.
        tree = ast.parse(source)
        upgrade = next(
            (n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name == "upgrade"), None,
        )
        if upgrade is None:
            continue
        body = ast.get_source_segment(source, upgrade) or ""

        for match in re.finditer(r"ADD VALUE(?:\s+IF NOT EXISTS)?\s+'([A-Z_]+)'", body):
            value = match.group(1)
            after = body[match.end():]
            # A COMMIT between the ALTER and any later use makes the value durable first.
            window = after.split('"COMMIT"')[0] if '"COMMIT"' in after else after
            assert f"'{value}'" not in window, (
                f"{path.name}: upgrade() uses the enum value {value!r} after adding it and BEFORE "
                f"any COMMIT. PostgreSQL raises UnsafeNewEnumValueUsageError, and env.py runs "
                f"every migration in ONE transaction, so splitting revisions does NOT help."
            )
