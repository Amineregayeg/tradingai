"""T-0068 — `B244`: `shadow_health` neither attested outcome variety nor disclaimed it.

Its scope block exists **precisely to enumerate what it does NOT attest**, and outcome variety
was in none of it. `B243` measured the corpus: **4358 of 4358** `setup_evaluation` rows carry
`decision="STAND_ASIDE"`, because `rec.setup_evaluation(` has exactly ONE call site and it sits
on the `StandAside.unreadable` path.

**Every one of those records is individually CORRECT**, so a corpus of 4358 identical correct
rows is not a correctness problem — and *"correctness of the evaluation"*, the nearest existing
disclaimer, does not reach it. **A reader who did the RIGHT thing — read the scope block instead
of the colour — still did not learn the corpus was single-branch.**

**WHY THE CORPUS IS SINGLE-BRANCH IS NOT THIS TASK.** That is `B243`, and it is correct
behaviour: *a shadow that emitted TAKE would be claiming a trade it cannot substantiate.* **This
task makes the fact visible. It does not change the fact.**
"""
from __future__ import annotations

import ast
import inspect

import pytest

from app.services.monitoring import data_health as dh
from app.services.monitoring.data_health import _branch_variety


# ======================================================================================
# ARM 1 — THE DISCLAIMER, NAMED SPECIFICALLY
# ======================================================================================


def test_arm1_the_scope_block_names_OUTCOME_VARIETY_and_not_a_broader_word():
    """*"Completeness"* or *"coverage"* would absorb it and disclaim nothing in particular.

    The line has to be about MORE THAN ONE OUTCOME, because that is the property `B243`
    measured and the one a reader cannot otherwise learn.
    """
    src = inspect.getsource(dh.shadow_health)
    block = src[src.index('"does_not_attest"'):src.index('"does_not_attest"') + 1800]

    assert "more than one outcome" in block, (
        "the disclaimer must name outcome variety. 'correctness' does not reach it: 4358 "
        "individually correct records are not a correctness problem."
    )


def test_arm1_the_existing_disclaimers_are_KEPT():
    """Additive. The three that were there are each true and each earned."""
    src = inspect.getsource(dh.shadow_health)
    for existing in (
        "correctness of the evaluation",
        "freshness of the correlate panels",
        "whether the grade reflects closed bars",
    ):
        assert existing in src, f"an existing disclaimer was dropped: {existing!r}"


# ======================================================================================
# ARM 2 — THE VALUES MOVE. A field reporting 1 on both corpora is `B243` rebuilt one layer up.
# ======================================================================================


def test_arm2_one_branch_and_several_branches_produce_DIFFERENT_values():
    single = _branch_variety([("STAND_ASIDE", 4358)])
    several = _branch_variety([("STAND_ASIDE", 300), ("TAKE", 80), ("BLOCKED", 20)])

    assert single["distinct_outcomes"] == 1
    assert several["distinct_outcomes"] == 3
    assert single["dominant_share"] == 1.0
    assert several["dominant_share"] < single["dominant_share"], (
        "dominant_share must FALL as variety rises — a value identical on both corpora would "
        "be B243 rebuilt one layer up, in the field written to expose it"
    )


def test_arm2_the_dominant_branch_is_NAMED_not_merely_counted():
    """**`B250`/ARM 6.** `distinct_outcomes == 1` cannot say WHICH branch, and a corpus of only
    `STAND_ASIDE` and one of only `TAKE` mean opposite things."""
    stood_aside = _branch_variety([("STAND_ASIDE", 4358)])
    took = _branch_variety([("TAKE", 4358)])

    assert stood_aside["distinct_outcomes"] == took["distinct_outcomes"] == 1
    assert stood_aside["dominant_branch"] == "STAND_ASIDE"
    assert took["dominant_branch"] == "TAKE"
    assert stood_aside != took, "the count alone cannot tell these apart; the name must"


def test_arm2_a_row_with_NO_decision_is_not_counted_as_a_branch():
    """*"Could not read"* and *"read and stood aside"* are the two states this module exists to
    keep apart, so a `None` decision is reported separately rather than becoming a branch."""
    mixed = _branch_variety([("STAND_ASIDE", 10), (None, 5)])

    assert mixed["distinct_outcomes"] == 1
    assert mixed["dominant_share"] == 1.0, "the share is of rows that HAVE a decision"
    assert mixed["undecided_rows"] == 5

    empty = _branch_variety([(None, 7)])
    assert empty["distinct_outcomes"] == 0 and empty["dominant_branch"] is None
    assert empty["undecided_rows"] == 7


# ======================================================================================
# ARM 3 — STATUS IS UNAFFECTED. This is the arm that protects Malek's ruling.
# ======================================================================================


@pytest.fixture
async def bound(engine, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.db.session as dbsession

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(dbsession, "async_session_maker", maker)
    monkeypatch.setattr(dbsession, "AsyncSessionLocal", maker)
    return maker


async def _seed_shadow_corpus(maker, decisions: list[str]) -> None:
    """A run and one `setup_evaluation` row per decision, through the REAL tables.

    **NOT a monkeypatched `shadow_health`.** My first version of the arm below stubbed the
    producer and asserted the stub's own status — so it passed under a mutation that made
    variety drive the status, because the mutated code never ran. *That is `B265` exactly, the
    defect T-0080 closed, reproduced by me one task later in the arm written to prevent it.*
    """
    from datetime import datetime, timedelta, timezone

    from app.models.engine_run import EngineRun
    from app.models.telemetry_record import TelemetryRecord

    now = datetime.now(tz=timezone.utc)
    async with maker() as db:
        db.add(EngineRun(started_at=now - timedelta(minutes=30)))
        for i, decision in enumerate(decisions):
            db.add(
                TelemetryRecord(
                    record_type="setup_evaluation",
                    record_id=f"ev-{i}-{decision}",
                    instrument="BTC/USD",
                    decision=decision,
                    created_at=now - timedelta(seconds=30 + i),
                    payload={"record_type": "setup_evaluation"},
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_arm3_low_variety_does_NOT_change_the_REAL_producers_status(bound):
    """**A non-healthy status here would flip `ok` for a component doing its job** — `B229`
    arriving from the other side, one day after Malek ruled on that boolean.

    The shadow is not broken when the corpus is single-branch: it is recording the only thing
    it CAN record. Driven through the REAL `shadow_health` so the status expression actually
    runs — a stubbed producer cannot fail for the reason this arm exists.
    """
    await _seed_shadow_corpus(bound, ["STAND_ASIDE"] * 12)

    health = await dh.shadow_health()

    assert health["distinct_outcomes"] == 1 and health["dominant_branch"] == "STAND_ASIDE"
    assert health["dominant_share"] == 1.0
    assert health["status"] == "healthy", (
        f"a single-branch corpus made the shadow {health['status']!r}. It is doing its job: "
        "one call site on the StandAside.unreadable path is the only branch it CAN record, "
        "and a non-healthy status here flips `ok` for a working component."
    )


@pytest.mark.asyncio
async def test_arm3_a_VARIED_corpus_reports_the_same_status_as_a_single_branch_one(bound):
    """The control pair. If variety changed the status in EITHER direction it would be a
    signal about the corpus wearing a signal about the shadow's health."""
    await _seed_shadow_corpus(bound, ["STAND_ASIDE"] * 8 + ["TAKE"] * 3 + ["BLOCKED"])

    health = await dh.shadow_health()

    assert health["distinct_outcomes"] == 3
    assert health["dominant_branch"] == "STAND_ASIDE"
    assert health["dominant_share"] < 1.0
    assert health["status"] == "healthy", "status must be independent of variety BOTH ways"


def test_arm3_the_variety_fields_are_NOT_read_by_any_status_expression():
    """Mutating the code to make low variety set a non-healthy status must turn this red.

    Asserted structurally, because the behavioural arm above pins today's data and this pins
    the SHAPE: no status decision may mention the variety fields at all.
    """
    src = inspect.getsource(dh.shadow_health)
    tree = ast.parse(src.lstrip())

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.Compare)):
            text = ast.unparse(node)
            if any(f in text for f in ("distinct_outcomes", "dominant_share", "dominant_branch")):
                offenders.append(text[:90])
    assert not offenders, (
        f"a variety field is being used in a decision: {offenders}. These are VALUES. A status "
        "computed from them would flip `ok` for a component that is working."
    )


# ======================================================================================
# ARM 4 — NO THRESHOLD EXISTS
# ======================================================================================


def test_arm4_no_constant_is_compared_against_the_variety_anywhere_in_the_module():
    """*"Fewer than N distinct outcomes is an alarm"* is unanswerable — **a legitimately quiet
    regime produces one branch too** — and picking N is `B93`'s tuned number.

    A constant introduced later must fail this.
    """
    tree = ast.parse(inspect.getsource(dh))
    offenders = [
        ast.unparse(node)[:90]
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and "distinct_outcomes" in ast.unparse(node)
        and any(isinstance(c, ast.Constant) for c in node.comparators)
    ]
    assert not offenders, f"a threshold on outcome variety has appeared: {offenders}"
