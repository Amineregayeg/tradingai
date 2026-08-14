"""An unattributed decision must not be storable as an attributed one (T-0013, B31).

WHY THIS FILE IS MOSTLY ONE TEST
Criterion 6 of T-0013 makes success look like failure: after this lands the ICT path
still decides every trade, so every new row is `decided_by='ICT'` with a NULL rule id
and **no rule ids appear anywhere**. That is the correct outcome, which means nothing
observable in production distinguishes this task working from it never having been
deployed. The mutation below is the only real proof, so it is written as a QUERY over a
table containing all four states rather than as an assertion about one object.

THE STATE SPACE THIS DEFENDS

    decided_by     deciding_rule_id     meaning
    ICT            NULL                 ICT decided. Every row until the cutover.
    RULE_ENGINE    NULL                 PLUMBING DEFECT — the decider was lost.
    RULE_ENGINE    NO_RULE_DECIDED      Rule engine ran, nothing owned the verdict.
    RULE_ENGINE    GATE-017             Attributed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.decision_record import (
    COHORT_PAPER,
    DECIDED_BY_ICT,
    DECIDED_BY_RULE_ENGINE,
    DECIDED_BY_UNSET,
    NO_RULE_DECIDED,
    OUTCOME_ABSTAINED,
    Attribution,
    DecisionRecord,
)

_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "app/services/telemetry/contract/RULE_REGISTRY.json"
)


def _row(**kw) -> DecisionRecord:
    base = dict(
        symbol="BTC/USD",
        timeframe="5m",
        inputs_hash="h",
        code_path_hash="c",
        abstained=True,
        outcome=OUTCOME_ABSTAINED,
        cohort=COHORT_PAPER,
    )
    base.update(kw)
    return DecisionRecord(**base)


class _Evaluation:
    """Stands in for the rules evaluator, which exposes `deciding_rule_id`."""

    def __init__(self, decider: str | None):
        self.deciding_rule_id = decider


# ---------------------------------------------------------------------------
# Criterion 2 — THE MUTATION. The three states must be separable BY QUERY.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_query_returns_exactly_the_plumbing_defect_rows(db_session):
    """Given all four states, ONE statement must return only the lost-decider rows.

    This is the test the plan asks for, and it is a query rather than an assertion
    because the claim being defended is about the corpus, not about an object: an
    auditor with SQL and no access to engine internals must be able to find decisions
    the rule engine made but could not account for.

    If this returns the ICT rows too, NULL has gone back to meaning two things and
    B31 has been reproduced in a second table.
    """
    ict = _row(**Attribution.ict().as_columns())
    attributed = _row(
        **Attribution.from_rule_evaluation(_Evaluation("GATE-017")).as_columns()
    )
    honest_none = _row(
        **Attribution.from_rule_evaluation(_Evaluation(None)).as_columns()
    )
    # Case 2 is only reachable by BYPASSING Attribution — which is the point. This
    # is what a plumbing defect looks like from the table's side.
    lost = _row(decided_by=DECIDED_BY_RULE_ENGINE, deciding_rule_id=None)

    db_session.add_all([ict, attributed, honest_none, lost])
    await db_session.commit()

    defects = (
        await db_session.execute(
            select(DecisionRecord).where(
                DecisionRecord.decided_by == DECIDED_BY_RULE_ENGINE,
                DecisionRecord.deciding_rule_id.is_(None),
            )
        )
    ).scalars().all()

    assert [r.id for r in defects] == [lost.id], (
        "the defect query did not isolate the lost-decider row — it returned "
        f"{len(defects)} rows. NULL now means more than one thing."
    )

    # And the other three must NOT be reported as defects, individually, so a
    # future change that collapses any one of them into NULL goes red here.
    assert ict.deciding_rule_id is None and ict.decided_by == DECIDED_BY_ICT
    assert honest_none.deciding_rule_id == NO_RULE_DECIDED
    assert attributed.deciding_rule_id == "GATE-017"


@pytest.mark.asyncio
async def test_an_ict_row_may_not_carry_a_rule_id(db_session):
    """The contradiction case is refused at the database, not merely discouraged.

    An ICT decision naming a registry rule would corrupt every
    `GROUP BY deciding_rule_id` audit with attributions no rule produced.
    """
    from sqlalchemy.exc import IntegrityError

    db_session.add(_row(decided_by=DECIDED_BY_ICT, deciding_rule_id="GATE-017"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_the_defect_state_is_storable_because_losing_it_would_hide_it(db_session):
    """`RULE_ENGINE` + NULL must INSERT cleanly. This is deliberate, not an oversight.

    Both write sites in `crypto_loop.py` swallow bookkeeping exceptions rather than
    kill the trading loop. A constraint forbidding this state would make the insert
    raise, the handler would swallow it, and the row would be DROPPED — so the corpus
    would lose precisely the evidence that the plumbing failed. Storing it and finding
    it by query beats refusing it and losing it.
    """
    db_session.add(_row(decided_by=DECIDED_BY_RULE_ENGINE, deciding_rule_id=None))
    await db_session.commit()  # must not raise


# ---------------------------------------------------------------------------
# The default. Found by Review before the migration shipped.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_write_that_forgets_the_attribution_does_not_claim_ICT(db_session):
    """THE REVIEW MUTATION. Omitting `decided_by` must not produce a real attribution.

    If the column defaulted to ICT, a write path that forgot it would emit a row
    asserting the ICT path decided. Before the cutover that happens to be true; after
    it, it is FALSE and undetectable — the defect query looks for
    `RULE_ENGINE + NULL` and this row claims ICT, so a rule-engine decision would sit
    in the evidence base attributed to the wrong engine.

    That is B31's shape — a claim satisfied by a default — in the columns added to
    prevent B31.
    """
    forgotten = _row()  # no attribution supplied at all
    db_session.add(forgotten)
    await db_session.commit()

    assert forgotten.decided_by == DECIDED_BY_UNSET, (
        "a row written without an attribution claims to know who decided it"
    )
    assert forgotten.decided_by != DECIDED_BY_ICT
    assert forgotten.deciding_rule_id is None


@pytest.mark.asyncio
async def test_the_unset_rows_are_found_by_one_query(db_session):
    """UNSET must be countable, which is the whole reason it is stored not refused."""
    db_session.add_all([_row(), _row(**Attribution.ict().as_columns())])
    await db_session.commit()

    unset = (
        await db_session.execute(
            select(DecisionRecord).where(
                DecisionRecord.decided_by == DECIDED_BY_UNSET
            )
        )
    ).scalars().all()
    assert len(unset) == 1


@pytest.mark.asyncio
async def test_an_unset_row_may_not_carry_a_rule_id(db_session):
    """Only the rule engine may name a rule — UNSET has nobody standing behind it."""
    from sqlalchemy.exc import IntegrityError

    db_session.add(_row(decided_by=DECIDED_BY_UNSET, deciding_rule_id="GATE-017"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# Criterion 4 — first-fail semantics survive the write
# ---------------------------------------------------------------------------

def test_a_hand_supplied_decider_is_rejected_rather_than_stored():
    """THE CRITERION-4 MUTATION. A caller may not assert an attribution it did not compute.

    `evaluator.py:25`: `deciding_rule_id` is the FIRST rule that failed, so evaluation
    ORDER decides which rule gets the blame — the value is a property of a completed
    evaluation. `gate_036_stand_aside.py:35` is explicit that nothing may pass a decider
    in by hand. A classmethod accepting `str` would allow exactly that.
    """
    with pytest.raises(TypeError, match="not a decider value"):
        Attribution.from_rule_evaluation("GATE-017")

    with pytest.raises(TypeError):
        Attribution.from_rule_evaluation(None)


def test_the_decider_is_read_from_the_evaluation_not_defaulted():
    assert Attribution.from_rule_evaluation(_Evaluation("GRADE-029")) == Attribution(
        decided_by=DECIDED_BY_RULE_ENGINE, deciding_rule_id="GRADE-029"
    )


def test_a_missing_decider_becomes_the_sentinel_never_none():
    """The B31 shape, inverted. An absence must be SAID, not left to look like a loss."""
    got = Attribution.from_rule_evaluation(_Evaluation(None))
    assert got.deciding_rule_id == NO_RULE_DECIDED
    assert got.deciding_rule_id is not None, (
        "a missing decider became NULL, which is how a LOST decider presents — the "
        "honest-none case and the plumbing defect are now indistinguishable"
    )
    # And the empty string, which `or` would also swallow.
    assert Attribution.from_rule_evaluation(_Evaluation("")).deciding_rule_id == (
        NO_RULE_DECIDED
    )


# ---------------------------------------------------------------------------
# Criterion 3 — decided_by is not inferable from the rule id
# ---------------------------------------------------------------------------

def test_decided_by_is_independent_of_whether_a_rule_id_was_captured():
    """If `decided_by` were derived from the id's presence, a plumbing failure in the
    rule path would silently re-label the row as ICT-decided — deleting the evidence
    of itself and shrinking the corpus that proves the defect."""
    lost = Attribution.from_rule_evaluation(_Evaluation(None))
    assert lost.decided_by == DECIDED_BY_RULE_ENGINE, (
        "an evaluation that named no rule was labelled ICT — the rule engine ran and "
        "the record now denies it"
    )
    assert Attribution.ict().decided_by == DECIDED_BY_ICT


# ---------------------------------------------------------------------------
# The sentinel's safety, checked against the real registry
# ---------------------------------------------------------------------------

def test_the_sentinel_cannot_collide_with_any_registry_id():
    """Asserted against the real 117-entry registry, not against a comment.

    If a future rule were ever named `NO_RULE_DECIDED`, case 3 and an attributed
    decision would become the same value and the state space would silently lose a
    member.
    """
    data = json.loads(_REGISTRY.read_text())
    rules = data.get("rules", data)
    ids = {r["id"] for r in (rules if isinstance(rules, list) else rules.values())}
    assert ids, "registry read produced no ids — this guard would pass vacuously"
    assert NO_RULE_DECIDED not in ids
    assert DECIDED_BY_ICT not in ids and DECIDED_BY_RULE_ENGINE not in ids
